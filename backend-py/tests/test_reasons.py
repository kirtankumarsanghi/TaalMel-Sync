from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.db.models import Case, Event, Notification
from app.engines.reasons import POLICY, REPEAT_THRESHOLD, ReasonAction
from app.events.types import ReasonCode
from app.main import create_app
from app.ocr.stub import StubOcrProvider
from app.services.storage import LocalStorageService


# ── Policy table (pure) ─────────────────────────────────────────────

def test_every_reason_code_has_a_policy() -> None:
    assert set(POLICY) == set(ReasonCode)


def test_side_effect_is_routed_not_interpreted() -> None:
    policy = POLICY[ReasonCode.SIDE_EFFECT]
    assert policy.action == ReasonAction.ROUTE_TO_PROFESSIONAL_FOLLOWUP
    assert policy.closes_case is False
    assert "no symptom interpretation" in policy.description.lower()


def test_affordability_never_ends_at_a_cheaper_option() -> None:
    policy = POLICY[ReasonCode.COULD_NOT_AFFORD]
    assert policy.action == ReasonAction.SHOW_AFFORDABILITY_RESOURCES
    assert policy.closes_case is False
    assert "never end" in policy.description.lower()


def test_patient_declined_is_never_overridden() -> None:
    policy = POLICY[ReasonCode.PATIENT_DECLINED]
    assert policy.action == ReasonAction.ROUTE_FOR_AWARENESS_NO_OVERRIDE
    assert policy.closes_case is False


def test_only_doctor_stop_and_forgot_close_the_case() -> None:
    closing = {code for code, p in POLICY.items() if p.closes_case}
    assert closing == {ReasonCode.FORGOT, ReasonCode.DOCTOR_TOLD_TO_STOP}


def test_expired_stays_open() -> None:
    assert POLICY[ReasonCode.EXPIRED].closes_case is False


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


def _setup(client: TestClient, phone: str) -> tuple[str, str, dict[str, str]]:
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
        json={"items": [{"item_id": rx["items"][0]["id"], "medication_name": "Glucophage 500mg"}]},
    ).json()
    return verify["medication_results"][0]["medication_id"], member_id, headers


def _open_stopped_case(client: TestClient, med_id: str, member_id: str, headers: dict) -> str:
    """Stopped + stock present opens conflict cases automatically (triggers run on evidence write)."""
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    cases = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    assert cases, "expected reconciliation to open at least one case"
    return cases[0]["id"]


def test_ran_out_keeps_case_open_and_notifies_caregiver(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9500000001")
    case_id = _open_stopped_case(client, med_id, member_id, headers)

    r = client.post(f"/api/cases/{case_id}/reason", headers=headers, json={"reason": "RAN_OUT"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "OPEN_CASE_NOTIFY_CAREGIVER"
    assert body["closes_case"] is False
    assert body["case"]["status"] == "OPEN"
    assert body["case"]["reason_code"] == "RAN_OUT"

    with Session(engine) as s:
        followups = [n for n in s.exec(select(Notification)).all() if "ran out" in n.body]
        # Evidence writes also emit EVIDENCE_CHANGED info rows; only the reason follow-up mentions the reason.
        assert len(followups) == 1
        assert followups[0].rule is None


def test_forgot_increases_reminders_and_closes_case(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9500000002")
    case_id = _open_stopped_case(client, med_id, member_id, headers)

    r = client.post(f"/api/cases/{case_id}/reason", headers=headers, json={"reason": "FORGOT"})
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "INCREASE_REMINDERS"
    assert r.json()["case"]["status"] == "RESOLVED"

    with Session(engine) as s:
        actions = [e.event_type for e in s.exec(select(Event)).all()]
        assert "ActionAssigned" in actions
        assert "ReasonRecorded" in actions


def test_doctor_told_to_stop_confirms_discontinuation_and_closes(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9500000003")
    case_id = _open_stopped_case(client, med_id, member_id, headers)

    r = client.post(f"/api/cases/{case_id}/reason", headers=headers,
                    json={"reason": "DOCTOR_TOLD_TO_STOP"})
    assert r.status_code == 200, r.text
    assert r.json()["case"]["status"] == "RESOLVED"

    state = client.get(f"/api/medications/{med_id}/state", headers=headers).json()
    assert state["confirmed_status"]["status"] == "DISCONTINUED"


def test_side_effect_is_recorded_without_closing(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9500000004")
    case_id = _open_stopped_case(client, med_id, member_id, headers)
    r = client.post(f"/api/cases/{case_id}/reason", headers=headers,
                    json={"reason": "SIDE_EFFECT", "note": "reported by patient"})
    assert r.status_code == 200
    assert r.json()["action"] == "ROUTE_TO_PROFESSIONAL_FOLLOWUP"
    assert r.json()["case"]["status"] == "OPEN"


def test_expired_reason_is_accepted_and_stays_open(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9500000005")
    case_id = _open_stopped_case(client, med_id, member_id, headers)
    r = client.post(f"/api/cases/{case_id}/reason", headers=headers, json={"reason": "EXPIRED"})
    assert r.status_code == 200
    assert r.json()["case"]["status"] == "OPEN"


def test_unknown_reason_code_is_rejected(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9500000006")
    case_id = _open_stopped_case(client, med_id, member_id, headers)
    r = client.post(f"/api/cases/{case_id}/reason", headers=headers, json={"reason": "BORED"})
    assert r.status_code == 422


def test_reason_on_resolved_case_is_409(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9500000007")
    case_id = _open_stopped_case(client, med_id, member_id, headers)
    client.post(f"/api/cases/{case_id}/resolve", headers=headers, json={"outcome": "RESOLVED"})
    r = client.post(f"/api/cases/{case_id}/reason", headers=headers, json={"reason": "RAN_OUT"})
    assert r.status_code == 409


def test_repeated_reason_flagged_at_threshold(client: TestClient, engine) -> None:
    """Three RAN_OUT reasons on three different cases for one medication are flagged."""
    med_id, member_id, headers = _setup(client, "9500000008")

    # Seed REPEAT_THRESHOLD cases carrying the same reason. Detection normally opens one
    # case per conflict type, so additional cases are written directly for this check.
    with Session(engine) as s:
        for _ in range(REPEAT_THRESHOLD):
            s.add(Case(medication_id=med_id, status="RESOLVED", reason_code="RAN_OUT"))
        s.commit()

    r = client.get(f"/api/medications/{med_id}/repeated-reasons", headers=headers)
    assert r.status_code == 200
    flagged = {item["reason_code"]: item["occurrences"] for item in r.json()}
    assert flagged.get("RAN_OUT") == REPEAT_THRESHOLD


def test_repeated_reason_not_flagged_below_threshold(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9500000009")
    with Session(engine) as s:
        for _ in range(REPEAT_THRESHOLD - 1):
            s.add(Case(medication_id=med_id, status="RESOLVED", reason_code="FORGOT"))
        s.commit()

    r = client.get(f"/api/medications/{med_id}/repeated-reasons", headers=headers)
    assert r.json() == []


def test_stranger_cannot_record_reason(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9500000010")
    case_id = _open_stopped_case(client, med_id, member_id, headers)
    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9500000011", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    r = client.post(f"/api/cases/{case_id}/reason",
                    headers={"Authorization": f"Bearer {stranger['access_token']}"},
                    json={"reason": "RAN_OUT"})
    assert r.status_code == 403
