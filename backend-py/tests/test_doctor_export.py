from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.config import get_settings
from app.db.models import AuditRecord, DoctorQuestion, HouseholdMember, Prescription
from app.main import create_app
from app.ocr.stub import StubOcrProvider
from app.services.storage import LocalStorageService


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


def _setup(client: TestClient, engine, phone: str) -> tuple[str, str, str, dict[str, str]]:
    """Returns (medication_id, member_id, patient_id, headers)."""
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
    patient_id = created["patient"]["patient_id"]

    rx = client.post(
        "/api/prescriptions/upload", headers=headers, params={"household_member_id": member_id},
        files={"file": (f"{phone}.jpg", f"scan-{phone}".encode(), "image/jpeg")},
    ).json()
    with Session(engine) as s:
        row = s.get(Prescription, rx["id"])
        row.prescribed_by = "Dr Rao"
        s.add(row)
        s.commit()

    verify = client.post(
        f"/api/prescriptions/{rx['id']}/verify", headers=headers,
        json={"items": [{"item_id": rx["items"][0]["id"], "medication_name": "Glucophage 500mg"}]},
    ).json()
    return verify["medication_results"][0]["medication_id"], member_id, patient_id, headers


# ── Export content ──────────────────────────────────────────────────

def test_export_names_prescriber_and_carries_a_note(client: TestClient, engine) -> None:
    med_id, member_id, _, headers = _setup(client, engine, "9950000001")
    client.post(f"/api/medications/{med_id}/dose-change", headers=headers,
                json={"new_dose": "500mg", "changed_by": "Dr Rao"})

    body = client.get(f"/api/households/{member_id}/doctor-export", headers=headers).json()
    med = body["medications"][0]
    assert med["prescribed_by"] == "Dr Rao"
    assert med["prescribed_on"] is not None
    assert "not a diagnosis" in body["note"].lower()


def test_export_timeline_is_dated_and_sourced(client: TestClient, engine) -> None:
    med_id, member_id, _, headers = _setup(client, engine, "9950000002")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": True})

    med = client.get(f"/api/households/{member_id}/doctor-export", headers=headers).json()["medications"][0]
    timeline = med["timeline"]
    assert timeline
    assert all(entry["source"] for entry in timeline)
    assert all(entry["date"] for entry in timeline)
    assert any(entry["label"] == "Patient reported" for entry in timeline)


def test_export_reports_unknown_rather_than_inventing(client: TestClient, engine) -> None:
    _, member_id, _, headers = _setup(client, engine, "9950000003")
    med = client.get(f"/api/households/{member_id}/doctor-export", headers=headers).json()["medications"][0]
    # Nothing has been observed yet.
    assert med["dimensions"]["reported_taking"]["status"] == "UNKNOWN"
    assert "No evidence recorded yet" in med["evidence_basis"] or "recorded evidence" in med["evidence_basis"]


def test_export_includes_pending_doctor_questions(client: TestClient, engine) -> None:
    _, member_id, _, headers = _setup(client, engine, "9950000004")
    with Session(engine) as s:
        s.add(DoctorQuestion(
            household_member_id=member_id,
            question_text="Can this be taken before breakfast?",
            raised_by="caregiver",
        ))
        s.commit()

    body = client.get(f"/api/households/{member_id}/doctor-export", headers=headers).json()
    assert "Can this be taken before breakfast?" in body["questions_to_discuss"]


def test_export_counts_open_cases(client: TestClient, engine) -> None:
    med_id, member_id, _, headers = _setup(client, engine, "9950000005")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})

    body = client.get(f"/api/households/{member_id}/doctor-export", headers=headers).json()
    assert body["unresolved_case_count"] == 2


def test_info_card_is_shorter_than_the_export(client: TestClient, engine) -> None:
    _, member_id, _, headers = _setup(client, engine, "9950000006")
    card = client.get(f"/api/households/{member_id}/info-card", headers=headers).json()
    assert "current_medications" in card
    assert "timeline" not in card
    assert "triage" in card["note"].lower()


def test_export_requires_access(client: TestClient, engine) -> None:
    _, member_id, _, _ = _setup(client, engine, "9950000007")
    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9950000008", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    headers = {"Authorization": f"Bearer {stranger['access_token']}"}
    assert client.get(f"/api/households/{member_id}/doctor-export", headers=headers).status_code == 403
    assert client.post(f"/api/households/{member_id}/doctor-link", headers=headers).status_code == 403


# ── Public link security ────────────────────────────────────────────

def test_issued_link_works_without_auth(client: TestClient, engine) -> None:
    _, member_id, _, headers = _setup(client, engine, "9950000009")
    link = client.post(f"/api/households/{member_id}/doctor-link", headers=headers).json()

    r = client.get(link["url_path"])  # no Authorization header
    assert r.status_code == 200, r.text
    assert r.json()["patient_name"] == "Amma"
    assert r.json()["medications"]


def test_expired_link_is_rejected(client: TestClient, engine) -> None:
    _, member_id, _, headers = _setup(client, engine, "9950000010")
    settings = get_settings()
    expired = jwt.encode(
        {
            "typ": "doctor_export",
            "sub": member_id,
            "jti": "x",
            "iat": datetime.now(UTC) - timedelta(hours=4),
            "exp": datetime.now(UTC) - timedelta(hours=2),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    r = client.get(f"/api/public/doctor-export/{expired}")
    assert r.status_code == 401


def test_normal_access_token_cannot_open_the_public_route(client: TestClient, engine) -> None:
    """The export token and an access token must not be interchangeable."""
    _, member_id, _, headers = _setup(client, engine, "9950000011")
    access_token = headers["Authorization"].removeprefix("Bearer ")

    r = client.get(f"/api/public/doctor-export/{access_token}")
    assert r.status_code == 401


def test_doctor_link_token_is_rejected_by_authenticated_routes(client: TestClient, engine) -> None:
    """The reverse direction: a doctor link must not act as a login."""
    _, member_id, _, headers = _setup(client, engine, "9950000012")
    link = client.post(f"/api/households/{member_id}/doctor-link", headers=headers).json()

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {link['token']}"})
    assert r.status_code == 401


def test_tampered_token_is_rejected(client: TestClient, engine) -> None:
    _, member_id, _, headers = _setup(client, engine, "9950000013")
    link = client.post(f"/api/households/{member_id}/doctor-link", headers=headers).json()
    tampered = link["token"][:-4] + "AAAA"
    assert client.get(f"/api/public/doctor-export/{tampered}").status_code == 401


def test_token_for_one_patient_does_not_expose_another(client: TestClient, engine) -> None:
    _, member_a, _, headers = _setup(client, engine, "9950000014")
    _, member_b, _, _ = _setup(client, engine, "9950000015")

    link_a = client.post(f"/api/households/{member_a}/doctor-link", headers=headers).json()
    body = client.get(link_a["url_path"]).json()
    assert body["patient_id"] == member_a
    assert body["patient_id"] != member_b


def test_issuing_and_viewing_are_audited(client: TestClient, engine) -> None:
    _, member_id, _, headers = _setup(client, engine, "9950000016")
    link = client.post(f"/api/households/{member_id}/doctor-link", headers=headers).json()
    client.get(link["url_path"])

    with Session(engine) as s:
        actions = {a.action for a in s.exec(select(AuditRecord)).all()}
    assert {"DOCTOR_LINK_ISSUED", "DOCTOR_EXPORT_VIEWED"}.issubset(actions)
