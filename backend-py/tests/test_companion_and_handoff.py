from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
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
        json={"items": [{"item_id": rx["items"][0]["id"], "medication_name": "Glucophage 500mg",
                         "instructions": "Take after breakfast"}]},
    ).json()
    return verify["medication_results"][0]["medication_id"], member_id, headers


# ── Companion ───────────────────────────────────────────────────────

def test_today_shows_doctor_instruction_verbatim(client: TestClient, engine) -> None:
    _, member_id, headers = _setup(client, "9970000001")
    items = client.get(f"/api/households/{member_id}/today", headers=headers).json()
    assert len(items) == 1
    # The doctor's own instruction is present, alongside — not replaced by — anything else.
    assert items[0]["instruction"] == "Take after breakfast"
    assert items[0]["confirmed_status"] == "UNKNOWN"


def test_changes_lists_recent_events_with_sources(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9970000002")
    client.post(f"/api/medications/{med_id}/dose-change", headers=headers,
                json={"new_dose": "1000mg", "changed_by": "Dr Rao"})
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": True})

    changes = client.get(f"/api/households/{member_id}/changes", headers=headers).json()
    types = {c["event_type"] for c in changes}
    assert "DoseChanged" in types
    assert "MedicationReported" in types
    assert all(c["source"] for c in changes)


def test_changes_respects_since_window(client: TestClient, engine) -> None:
    _, member_id, headers = _setup(client, "9970000003")
    changes = client.get(f"/api/households/{member_id}/changes?sinceDays=1", headers=headers).json()
    for change in changes:
        assert change["date"] >= (datetime.now(UTC) - timedelta(days=1)).isoformat()[:10]


def test_questions_are_stored_and_never_answered(client: TestClient, engine) -> None:
    _, member_id, headers = _setup(client, "9970000004")
    created = client.post(
        f"/api/households/{member_id}/questions", headers=headers,
        json={"question_text": "Can this be taken before breakfast?"},
    )
    assert created.status_code == 201
    body = created.json()
    assert "does not answer" in body["note"]

    listed = client.get(f"/api/households/{member_id}/questions", headers=headers).json()
    assert [q["question_text"] for q in listed] == ["Can this be taken before breakfast?"]

    discussed = client.post(f"/api/questions/{body['id']}/discussed", headers=headers).json()
    assert discussed["status"] == "DISCUSSED"


def test_question_requires_access(client: TestClient, engine) -> None:
    _, member_id, _ = _setup(client, "9970000005")
    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9970000006", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    r = client.post(
        f"/api/households/{member_id}/questions",
        headers={"Authorization": f"Bearer {stranger['access_token']}"},
        json={"question_text": "anything?"},
    )
    assert r.status_code == 403


def test_refill_list_appears_when_stock_is_low(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9970000007")
    assert client.get(f"/api/households/{member_id}/refill-list", headers=headers).json() == []

    client.post(f"/api/medications/{med_id}/availability", headers=headers,
                json={"present": True, "quantity_note": "nearly empty"})
    items = client.get(f"/api/households/{member_id}/refill-list", headers=headers).json()
    assert len(items) == 1
    assert items[0]["name"] == "Metformin"
    # The basis must say how the conclusion was reached, not just assert it.
    assert "availability snapshot" in items[0]["basis"]


# ── Temporary access handoff ────────────────────────────────────────

def _grant(client, headers, member_id, caregiver_user_id, expires_at=None):
    payload = {"caregiver_user_id": caregiver_user_id, "household_member_id": member_id}
    if expires_at:
        payload["expires_at"] = expires_at
    return client.post("/api/access", headers=headers, json=payload)


def test_temporary_access_works_then_expires(client: TestClient, engine) -> None:
    owner = client.post(
        "/api/auth/register",
        json={"name": "Asha", "phone": "9970000008", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    created = client.post(
        "/api/households", headers=headers,
        json={"household_name": "F", "patient_display_name": "Amma", "consent_recorded": True},
    ).json()
    member_id = created["patient"]["household_member_id"]

    sister = client.post(
        "/api/auth/register",
        json={"name": "Meera", "phone": "9970000009", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    s_headers = {"Authorization": f"Bearer {sister['access_token']}"}

    future = (datetime.now(UTC) + timedelta(days=10)).isoformat()
    access_id = _grant(client, headers, member_id, sister["user"]["id"], future).json()["id"]
    client.post(f"/api/access/{access_id}/consent", headers=s_headers, json={})

    # Active while the window is open.
    assert client.get(f"/api/households/{member_id}/today", headers=s_headers).status_code == 200

    # Expire the window and confirm access stops without any revoke call.
    from app.db.models import CaregiverAccess

    with Session(engine) as s:
        row = s.get(CaregiverAccess, access_id)
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        s.add(row)
        s.commit()

    assert client.get(f"/api/households/{member_id}/today", headers=s_headers).status_code == 403


def test_permanent_access_has_no_expiry(client: TestClient, engine) -> None:
    owner = client.post(
        "/api/auth/register",
        json={"name": "Asha", "phone": "9970000010", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    created = client.post(
        "/api/households", headers=headers,
        json={"household_name": "F", "patient_display_name": "Amma", "consent_recorded": True},
    ).json()
    member_id = created["patient"]["household_member_id"]

    sister = client.post(
        "/api/auth/register",
        json={"name": "Meera", "phone": "9970000011", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    s_headers = {"Authorization": f"Bearer {sister['access_token']}"}
    access_id = _grant(client, headers, member_id, sister["user"]["id"]).json()["id"]
    client.post(f"/api/access/{access_id}/consent", headers=s_headers, json={})

    assert client.get(f"/api/households/{member_id}/today", headers=s_headers).status_code == 200
