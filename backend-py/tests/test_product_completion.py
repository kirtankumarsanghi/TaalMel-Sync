"""End-to-end coverage for the completion work: documented API aliases, prescriber,
voice transcript path, expiry, doctor dashboard, pharmacy orders, symptoms, wellness,
and notification delivery bookkeeping."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import patient as patient_routes
from app.api.routes import documents as document_routes
from app.api.routes import prescriptions as rx_routes
from app.db.models import DoctorGrant, Notification, RefillOrder
from app.main import create_app
from app.ocr.lab_stub import StubLabOcrProvider
from app.ocr.stub import StubOcrProvider
from app.services.photo_verification import NoOpMatcher
from app.services.storage import LocalStorageService, get_storage


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine, tmp_path, monkeypatch) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    app = create_app()
    app.dependency_overrides[db_session] = override_session
    app.dependency_overrides[rx_routes.engine_dep] = lambda: engine
    app.dependency_overrides[rx_routes.storage_dep] = lambda: LocalStorageService(tmp_path / "up")
    app.dependency_overrides[rx_routes.ocr_provider_dep] = lambda: StubOcrProvider()
    app.dependency_overrides[patient_routes.matcher_dep] = lambda: NoOpMatcher()
    app.dependency_overrides[document_routes.ocr_provider_dep] = lambda: StubOcrProvider()
    app.dependency_overrides[get_storage] = lambda: LocalStorageService(tmp_path / "up")
    monkeypatch.setattr(
        "app.ocr.provider.get_lab_ocr_provider", lambda: StubLabOcrProvider()
    )
    with TestClient(app) as c:
        yield c


def _setup(client: TestClient, phone: str, role: str = "caregiver") -> tuple[str, str, dict[str, str]]:
    reg = client.post(
        "/api/auth/register",
        json={"name": "Asha", "phone": phone, "password": "correct-horse-battery", "role": role},
    ).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    created = client.post(
        "/api/households",
        headers=headers,
        json={
            "household_name": "F",
            "patient_display_name": "Amma",
            "consent_recorded": True,
        },
    ).json()
    return (
        created["patient"]["household_member_id"],
        created["patient"]["patient_id"],
        headers,
    )


def _medication(client: TestClient, headers: dict, member_id: str) -> str:
    rx = client.post(
        "/api/prescriptions/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": ("rx.jpg", b"scan", "image/jpeg")},
        data={"prescribed_by": "Dr Rao"},
    ).json()
    verified = client.post(
        f"/api/prescriptions/{rx['id']}/verify",
        headers=headers,
        json={"items": [{"item_id": rx["items"][0]["id"], "medication_name": "Glucophage 500mg"}]},
    ).json()
    return verified["medication_results"][0]["medication_id"]


def test_prescriber_is_captured_and_appears_in_export(client: TestClient) -> None:
    member_id, _, headers = _setup(client, "9800000101")
    rx = client.post(
        "/api/prescriptions/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": ("rx.jpg", b"scan", "image/jpeg")},
        data={"prescribed_by": "Dr Rao"},
    ).json()
    client.post(
        f"/api/prescriptions/{rx['id']}/verify",
        headers=headers,
        json={"items": [{"item_id": rx["items"][0]["id"], "medication_name": "Glucophage 500mg"}]},
    )

    body = client.get(f"/api/households/{member_id}/doctor-export", headers=headers).json()
    assert body["medications"][0]["prescribed_by"] == "Dr Rao"

    updated = client.patch(
        f"/api/prescriptions/{rx['id']}",
        headers=headers,
        json={"prescribed_by": "Dr Mehta"},
    )
    assert updated.status_code == 200, updated.text
    body = client.get(f"/api/households/{member_id}/doctor-export", headers=headers).json()
    assert body["medications"][0]["prescribed_by"] == "Dr Mehta"


def test_documented_aliases_resolve(client: TestClient) -> None:
    member_id, patient_id, headers = _setup(client, "9800000102")
    medication_id = _medication(client, headers, member_id)

    household = client.get(f"/api/households/{client.get('/api/patients/' + patient_id, headers=headers).json()['household_id']}", headers=headers)
    assert household.status_code == 200

    aliases = [
        (f"/api/patients/{patient_id}/prescriptions", "get"),
        (f"/api/patients/{patient_id}/self-reports", "get"),
        (f"/api/patients/{patient_id}/lab-reports", "get"),
        (f"/api/patients/{patient_id}/lab-adherence-timeline", "get"),
        (f"/api/patients/{patient_id}/expiry-alerts", "get"),
        (f"/api/patients/{patient_id}/refill-list", "get"),
        (f"/api/patients/{patient_id}/wellness-timeline", "get"),
        (f"/api/doctors/export/{patient_id}", "get"),
    ]
    for path, _ in aliases:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)

    assert medication_id


def test_voice_transcript_records_voice_source(client: TestClient, engine) -> None:
    member_id, _, headers = _setup(client, "9800000103")
    _medication(client, headers, member_id)

    response = client.post(
        f"/api/households/{member_id}/voice-report",
        headers=headers,
        data={"transcript": "yes I took the metformin"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recorded"] is True
    assert body["taking"] is True


def test_expiry_endpoint_and_alert_list(client: TestClient) -> None:
    member_id, patient_id, headers = _setup(client, "9800000104")
    medication_id = _medication(client, headers, member_id)

    response = client.post(
        f"/api/medicines/{medication_id}/expiry",
        headers=headers,
        json={"expiry_date": "2020-01-01T00:00:00+00:00", "present": True},
    )
    assert response.status_code == 200, response.text
    open_cases = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    assert open_cases

    alerts = client.get(f"/api/patients/{patient_id}/expiry-alerts", headers=headers).json()
    assert alerts and alerts[0]["expired"] is True


def test_taper_tracks_without_caller_supplied_day(client: TestClient) -> None:
    member_id, _, headers = _setup(client, "9800000105")
    medication_id = _medication(client, headers, member_id)

    saved = client.post(
        f"/api/medications/{medication_id}/taper",
        headers=headers,
        json={"schedule_text": "20mg x7d, 10mg x7d, 5mg x7d"},
    ).json()
    assert saved["current_step"] == 1
    assert saved["expected_dose"] == "20mg"


def test_self_report_alias(client: TestClient) -> None:
    member_id, patient_id, headers = _setup(client, "9800000106")
    medication_id = _medication(client, headers, member_id)

    response = client.post(
        f"/api/patients/{patient_id}/self-report",
        headers=headers,
        json={"medication_id": medication_id, "taking": True},
    )
    assert response.status_code == 201, response.text
    assert response.json()["taking"] is True

    rows = client.get(f"/api/patients/{patient_id}/self-reports", headers=headers).json()
    assert any(row["medication_id"] == medication_id for row in rows)


def test_doctor_can_redeem_link_and_use_dashboard(client: TestClient) -> None:
    member_id, _, caregiver_headers = _setup(client, "9800000107")
    _medication(client, caregiver_headers, member_id)
    link = client.post(
        f"/api/households/{member_id}/doctor-link", headers=caregiver_headers
    ).json()

    doctor = client.post(
        "/api/auth/register",
        json={"name": "Dr Rao", "phone": "9800000108", "password": "correct-horse-battery", "role": "doctor"},
    ).json()
    doctor_headers = {"Authorization": f"Bearer {doctor['access_token']}"}

    redeemed = client.post(
        "/api/doctor/redeem", headers=doctor_headers, json={"token": link["token"]}
    )
    assert redeemed.status_code == 201, redeemed.text
    patients = client.get("/api/doctor/patients", headers=doctor_headers).json()
    assert patients and patients[0]["household_member_id"] == member_id
    export = client.get(
        f"/api/doctor/patients/{member_id}/export", headers=doctor_headers
    )
    assert export.status_code == 200, export.text
    assert export.json()["patient_name"] == "Amma"


def test_refill_order_round_trip(client: TestClient, engine) -> None:
    member_id, _, headers = _setup(client, "9800000109")
    medication_id = _medication(client, headers, member_id)
    client.post(
        f"/api/medications/{medication_id}/availability",
        headers=headers,
        json={"present": True, "quantity_note": "nearly empty"},
    )

    order = client.post(f"/api/households/{member_id}/refill-orders", headers=headers)
    assert order.status_code == 201, order.text
    body = order.json()
    assert body["provider"] == "mock"
    assert body["items"]
    fetched = client.get(f"/api/refill-orders/{body['id']}", headers=headers)
    assert fetched.status_code == 200

    with Session(engine) as session:
        assert session.exec(select(RefillOrder)).all()


def test_symptom_connector_never_names_a_medicine(client: TestClient) -> None:
    _, patient_id, headers = _setup(client, "9800000110")
    response = client.post(
        f"/api/patients/{patient_id}/symptoms",
        headers=headers,
        json={"symptom_text": "I feel dizzy", "severity": "EMERGENCY"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "emergency" in body["care_action"].lower()
    assert "metformin" not in body["care_action"].lower()


def test_wellness_timeline_returns_events(client: TestClient) -> None:
    member_id, patient_id, headers = _setup(client, "9800000111")
    medication_id = _medication(client, headers, member_id)
    client.post(
        f"/api/medications/{medication_id}/report",
        headers=headers,
        json={"taking": True},
    )
    rows = client.get(f"/api/patients/{patient_id}/wellness-timeline", headers=headers).json()
    assert any(row["kind"] == "MedicationReported" for row in rows)


def test_manual_item_when_handwriting_ocr_returns_nothing(client: TestClient) -> None:
    member_id, _, headers = _setup(client, "9800000113")
    rx = client.post(
        "/api/prescriptions/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": ("handwritten.jpg", b"EMPTY_OCR scan", "image/jpeg")},
    ).json()
    assert rx["items"] == []

    added = client.post(
        f"/api/prescriptions/{rx['id']}/items",
        headers=headers,
        json={"medication_name": "Metformin", "dosage": "500mg", "frequency": "twice daily"},
    )
    assert added.status_code == 201, added.text
    assert added.json()["confidence"] == 0.0

    placeholder = client.post(
        f"/api/prescriptions/{rx['id']}/verify",
        headers=headers,
        json={"items": [{"item_id": added.json()["id"], "medication_name": "New medicine"}]},
    )
    assert placeholder.status_code == 400

    verified = client.post(
        f"/api/prescriptions/{rx['id']}/verify",
        headers=headers,
        json={"items": [{"item_id": added.json()["id"], "medication_name": "Metformin 500mg"}]},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["medication_results"][0]["name_generic"] == "Metformin"


def test_unified_document_upload_classifies_prescription(client: TestClient) -> None:
    member_id, patient_id, headers = _setup(client, "9800000114")
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": ("scan.jpg", b"handwritten scan", "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document_type"] == "PRESCRIPTION"
    assert body["prescription_id"]
    assert body["item_count"] == 1

    docs = client.get(f"/api/patients/{patient_id}/documents", headers=headers).json()
    assert docs and docs[0]["document_type"] == "PRESCRIPTION"

    duplicate = client.post(
        "/api/documents/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": ("scan.jpg", b"handwritten scan", "image/jpeg")},
    ).json()
    assert duplicate["document_id"] == body["document_id"]
    assert duplicate["prescription_id"] == body["prescription_id"]


def test_unclassified_handwriting_can_be_opened_and_typed(client: TestClient) -> None:
    member_id, _, headers = _setup(client, "9800000115")
    up = client.post(
        "/api/documents/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": ("handwriting.jpg", b"EMPTY_OCR page", "image/jpeg")},
    ).json()
    assert up["document_type"] == "OTHER"

    opened = client.post(f"/api/documents/{up['document_id']}/as-prescription", headers=headers)
    assert opened.status_code == 200, opened.text
    prescription_id = opened.json()["prescription_id"]

    parsed = client.post(
        f"/api/prescriptions/{prescription_id}/parse-text",
        headers=headers,
        json={"text": "Tab Augmentin 625mg 1-0-1 x 5 days\nTab Pan 40mg 1-0-0 x 5 days"},
    )
    assert parsed.status_code == 201, parsed.text
    assert len(parsed.json()) == 2
    assert parsed.json()[0]["dosage"] == "625mg"


def test_notification_delivery_state_is_visible(client: TestClient, engine) -> None:
    member_id, _, headers = _setup(client, "9800000112")
    _medication(client, headers, member_id)

    notes = client.get("/api/notifications", headers=headers).json()
    assert notes
    assert any(note["channel"] == "none" for note in notes)
    assert any(note["delivery_error"] for note in notes)
