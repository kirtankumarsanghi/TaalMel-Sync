from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.main import create_app
from app.ocr.stub import StubOcrProvider
from app.services.safety import check_interactions
from app.services.storage import LocalStorageService


# ── Safety rules (pure) ─────────────────────────────────────────────

def test_known_pair_with_interaction_is_flagged() -> None:
    result = check_interactions(["Warfarin", "Aspirin"])
    assert any(p.result == "INTERACTION_FLAGGED" for p in result.pairs)
    flagged = next(p for p in result.pairs if p.result == "INTERACTION_FLAGGED")
    assert flagged.detail and flagged.source


def test_brand_names_are_normalized_before_checking() -> None:
    result = check_interactions(["Ecosprin", "Warf"])
    assert "Aspirin" in result.normalized_names
    assert "Warfarin" in result.normalized_names
    assert any(p.result == "INTERACTION_FLAGGED" for p in result.pairs)


def test_unknown_medicine_is_not_covered_never_safe() -> None:
    result = check_interactions(["UnknownDrug", "Aspirin"])
    assert any(p.result == "NOT_COVERED" for p in result.pairs)
    assert "UnknownDrug" in result.uncovered


def test_known_but_unlisted_pair_is_no_known_issue() -> None:
    result = check_interactions(["Metformin", "Amlodipine"])
    assert result.pairs[0].result == "NO_KNOWN_ISSUE_IN_DATASET"


def test_duplicate_ingredient_group_is_flagged() -> None:
    result = check_interactions(["Paracetamol", "Crocin"])
    # Crocin normalizes to Paracetamol, so this pair is a duplicate ingredient.
    assert "Paracetamol" in result.normalized_names
    assert any(p.result == "DUPLICATE_INGREDIENT_FLAGGED" for p in result.pairs)


def test_disclaimer_is_always_present() -> None:
    assert "not" in check_interactions([]).disclaimer.lower()


# ── HTTP ────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine, tmp_path: Path) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    app = create_app()
    app.dependency_overrides[db_session] = override_session
    app.dependency_overrides[rx_routes.engine_dep] = lambda: engine
    app.dependency_overrides[rx_routes.storage_dep] = lambda: LocalStorageService(tmp_path / "up")
    app.dependency_overrides[rx_routes.ocr_provider_dep] = lambda: StubOcrProvider()
    with TestClient(app) as c:
        yield c


def _setup(client: TestClient, phone: str, medicine: str = "Glucophage 500mg") -> tuple[str, str, dict[str, str]]:
    reg = client.post(
        "/api/auth/register",
        json={"name": "Asha", "phone": phone, "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    created = client.post(
        "/api/households", headers=headers,
        json={"household_name": "F", "patient_display_name": "Amma", "consent_recorded": True},
    ).json()
    member_id = created["patient"]["household_member_id"]
    rx = client.post(
        "/api/prescriptions/upload", headers=headers, params={"household_member_id": member_id},
        files={"file": (f"{phone}.jpg", f"scan-{phone}".encode(), "image/jpeg")},
    ).json()
    verify = client.post(
        f"/api/prescriptions/{rx['id']}/verify", headers=headers,
        json={"items": [{"item_id": rx["items"][0]["id"], "medication_name": medicine}]},
    ).json()
    return verify["medication_results"][0]["medication_id"], member_id, headers


def test_summary_counts_open_cases_and_needs_checking(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9700000001")
    summary = client.get(f"/api/households/{member_id}/summary", headers=headers).json()
    assert summary["medicines_total"] == 1
    assert summary["needs_checking"] == 1  # no availability check and no self-report yet

    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})

    after = client.get(f"/api/households/{member_id}/summary", headers=headers).json()
    assert after["open_cases"] == 2
    assert after["needs_checking"] == 0


def test_case_explanation_has_what_why_source_status_action(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9700000002")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False, "reason": "FORGOT"})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    case_id = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()[0]["id"]

    body = client.get(f"/api/cases/{case_id}/explain", headers=headers).json()
    assert body["what"]
    assert body["why"]
    assert "Event recorded" in body["source"]
    assert body["status"] == "OPEN"
    assert body["action"]
    assert "change or stop any medication" in body["taalmel_does_not"]


def test_completeness_rewards_fresh_evidence(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9700000003")
    before = client.get(f"/api/households/{member_id}/completeness", headers=headers).json()
    assert before["medicines_total"] == 1
    assert before["score_percent"] == 33  # only the prescription point

    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": True})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    after = client.get(f"/api/households/{member_id}/completeness", headers=headers).json()
    assert after["score_percent"] == 100
    assert after["stale_items"] == 0


def test_safety_check_endpoint_reports_uncovered(client: TestClient, engine) -> None:
    _med, member_id, headers = _setup(client, "9700000004", medicine="SomeUnlistedBrand 10mg")
    body = client.get(f"/api/households/{member_id}/safety-check", headers=headers).json()
    assert body["uncovered"]
    assert "not" in body["disclaimer"].lower()


def test_dashboard_endpoints_require_access(client: TestClient, engine) -> None:
    _, member_id, _headers = _setup(client, "9700000005")
    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9700000006", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    s_headers = {"Authorization": f"Bearer {stranger['access_token']}"}
    for path in ("summary", "completeness", "safety-check"):
        assert client.get(f"/api/households/{member_id}/{path}", headers=s_headers).status_code == 403
