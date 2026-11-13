from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import prescriptions as prescription_routes
from app.db.models import AuditRecord, Event, Prescription, PrescriptionItem
from app.main import create_app
from app.ocr.stub import OcrExtractionError, StubOcrProvider
from app.services import prescriptions as service
from app.services.storage import LocalStorageService


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    return tmp_path / "uploads"


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine, storage_dir: Path) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    app = create_app()
    app.dependency_overrides[db_session] = override_session
    app.dependency_overrides[prescription_routes.engine_dep] = lambda: engine
    app.dependency_overrides[prescription_routes.storage_dep] = lambda: LocalStorageService(storage_dir)
    app.dependency_overrides[prescription_routes.ocr_provider_dep] = lambda: StubOcrProvider()
    with TestClient(app) as c:
        yield c


def _setup_patient(client: TestClient, phone: str) -> tuple[str, str, dict[str, str]]:
    """Creates a caregiver with a household. Returns (member_id, user_id, auth headers)."""
    reg = client.post(
        "/api/auth/register",
        json={"name": "Asha", "phone": phone, "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    created = client.post(
        "/api/households",
        headers=headers,
        json={"household_name": "Family", "patient_display_name": "Amma", "consent_recorded": True},
    ).json()
    return created["patient"]["household_member_id"], reg["user"]["id"], headers


def _upload(client: TestClient, headers: dict, member_id: str, data: bytes,
            filename: str = "rx.jpg", mime: str = "image/jpeg"):
    return client.post(
        "/api/prescriptions/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": (filename, data, mime)},
    )


# ── Validation ──────────────────────────────────────────────────────

def test_rejects_disallowed_mime_type(client: TestClient) -> None:
    member_id, _, headers = _setup_patient(client, "9100000001")
    r = _upload(client, headers, member_id, b"hello", filename="notes.txt", mime="text/plain")
    assert r.status_code == 400
    assert "Invalid file type" in r.json()["error"]


def test_rejects_empty_file(client: TestClient) -> None:
    member_id, _, headers = _setup_patient(client, "9100000002")
    r = _upload(client, headers, member_id, b"")
    assert r.status_code == 400
    assert "empty" in r.json()["error"]


def test_rejects_file_over_10mb(client: TestClient) -> None:
    member_id, _, headers = _setup_patient(client, "9100000003")
    big = b"x" * (service.MAX_UPLOAD_BYTES + 1)
    r = _upload(client, headers, member_id, big)
    assert r.status_code == 413


def test_validate_upload_allows_exact_limit() -> None:
    service.validate_upload(b"x" * service.MAX_UPLOAD_BYTES, "image/png", "rx.png")


# ── Access ──────────────────────────────────────────────────────────

def test_upload_without_access_is_403(client: TestClient) -> None:
    member_id, _, _ = _setup_patient(client, "9100000004")
    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9100000005", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    headers = {"Authorization": f"Bearer {stranger['access_token']}"}
    r = _upload(client, headers, member_id, b"rx-bytes")
    assert r.status_code == 403


# ── Dedup ───────────────────────────────────────────────────────────

def test_same_file_twice_for_same_member_is_409(client: TestClient) -> None:
    member_id, _, headers = _setup_patient(client, "9100000006")
    first = _upload(client, headers, member_id, b"same-bytes")
    assert first.status_code == 201
    second = _upload(client, headers, member_id, b"same-bytes")
    assert second.status_code == 409


def test_same_file_for_different_member_is_allowed(client: TestClient, engine) -> None:
    member_a, _, headers = _setup_patient(client, "9100000007")
    member_b, _, _ = _setup_patient(client, "9100000008")
    # Same caregiver owns both households in this test: create a second household for them.
    second_household = client.post(
        "/api/households",
        headers=headers,
        json={"household_name": "Second", "patient_display_name": "Papa", "consent_recorded": True},
    ).json()
    member_b = second_household["patient"]["household_member_id"]

    assert _upload(client, headers, member_a, b"shared-scan").status_code == 201
    assert _upload(client, headers, member_b, b"shared-scan").status_code == 201


# ── OCR outcomes ────────────────────────────────────────────────────

def test_successful_ocr_completes_and_stores_items_with_events(client: TestClient, engine) -> None:
    member_id, _, headers = _setup_patient(client, "9100000009")
    r = _upload(client, headers, member_id, b"clear-scan")
    assert r.status_code == 201
    body = r.json()
    assert body["ocr_status"] == "COMPLETED"
    assert len(body["items"]) == 1
    assert body["items"][0]["medication_name"] == "Lisinopril"
    assert body["items"][0]["verified"] is False

    with Session(engine) as s:
        types = [e.event_type for e in s.exec(select(Event)).all()]
    assert {"PrescriptionUploaded", "MedicationExtracted", "PrescriptionOcrCompleted"} <= set(types)


def test_events_reference_real_prescription_not_a_medication(client: TestClient, engine) -> None:
    """Regression for the TS bug where the OCR job passed prescriptionId as medicationId."""
    member_id, _, headers = _setup_patient(client, "9100000010")
    rx_id = _upload(client, headers, member_id, b"clear-scan-2").json()["id"]

    with Session(engine) as s:
        events = s.exec(select(Event).where(Event.event_type == "PrescriptionOcrCompleted")).all()
        assert len(events) == 1
        assert events[0].medication_id is None
        assert f'"prescription_id": "{rx_id}"' in events[0].payload


def test_low_confidence_needs_review(client: TestClient) -> None:
    member_id, _, headers = _setup_patient(client, "9100000011")
    r = _upload(client, headers, member_id, b"LOW_CONFIDENCE scan")
    assert r.json()["ocr_status"] == "NEEDS_REVIEW"


def test_empty_ocr_result_is_failed(client: TestClient) -> None:
    member_id, _, headers = _setup_patient(client, "9100000012")
    r = _upload(client, headers, member_id, b"EMPTY_OCR scan")
    assert r.json()["ocr_status"] == "FAILED"
    assert r.json()["items"] == []


def test_ocr_exception_is_recorded_and_not_swallowed(engine, storage_dir: Path) -> None:
    """The old TS worker swallowed errors. Here the failure must be stored on the row,
    emitted as an event, and re-raised so the caller sees it."""
    storage = LocalStorageService(storage_dir)
    with Session(engine) as s:
        from app.db import models

        user = models.User(role="caregiver", name="A", password_hash="x")
        s.add(user)
        s.flush()
        household = models.Household(name="H", created_by=user.id)
        s.add(household)
        s.flush()
        member = models.HouseholdMember(household_id=household.id, display_name="P")
        s.add(member)
        s.flush()
        s.add(models.CaregiverAccess(caregiver_user_id=user.id, household_member_id=member.id, consent_recorded=True))
        s.commit()
        member_id = member.id
        user_id = user.id

    data = b"FAIL_OCR scan"
    storage.upload("prescriptions/x/bad.jpg", data)
    with Session(engine) as s:
        rx = Prescription(
            household_member_id=member_id,
            file_storage_key="prescriptions/x/bad.jpg",
            original_filename="bad.jpg",
            mime_type="image/jpeg",
            file_size_bytes=len(data),
            file_hash="abc",
            uploaded_by_user_id=user_id,
        )
        s.add(rx)
        s.commit()
        rx_id = rx.id

    with Session(engine) as s:
        with pytest.raises(OcrExtractionError):
            service.run_ocr_job(s, storage=storage, provider=StubOcrProvider(), prescription_id=rx_id)

    with Session(engine) as s:
        row = s.get(Prescription, rx_id)
        assert row.ocr_status == "FAILED"
        assert "forced failure" in (row.ocr_error or "")
        failed = s.exec(select(Event).where(Event.event_type == "PrescriptionOcrFailed")).all()
        assert len(failed) == 1


def test_get_prescription_returns_items_for_authorized_caregiver(client: TestClient) -> None:
    member_id, _, headers = _setup_patient(client, "9100000013")
    rx_id = _upload(client, headers, member_id, b"readable").json()["id"]
    r = client.get(f"/api/prescriptions/{rx_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["items"][0]["medication_name"] == "Lisinopril"


def test_get_prescription_is_403_for_stranger(client: TestClient) -> None:
    member_id, _, headers = _setup_patient(client, "9100000014")
    rx_id = _upload(client, headers, member_id, b"private").json()["id"]
    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9100000015", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    r = client.get(f"/api/prescriptions/{rx_id}", headers={"Authorization": f"Bearer {stranger['access_token']}"})
    assert r.status_code == 403


def test_upload_is_audited(client: TestClient, engine) -> None:
    member_id, _, headers = _setup_patient(client, "9100000016")
    _upload(client, headers, member_id, b"audited")
    with Session(engine) as s:
        actions = {a.action for a in s.exec(select(AuditRecord)).all()}
    assert "PRESCRIPTION_UPLOADED" in actions


def test_storage_refuses_path_traversal(storage_dir: Path) -> None:
    storage = LocalStorageService(storage_dir)
    with pytest.raises(ValueError, match="escapes"):
        storage.upload("../../evil.txt", b"x")
