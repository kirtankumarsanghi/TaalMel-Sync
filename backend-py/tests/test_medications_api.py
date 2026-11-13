from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.db.models import Medication, NormalizationLog, PrescriptionItem
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


def _setup(client: TestClient, phone: str) -> tuple[str, dict[str, str]]:
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
    return created["patient"]["household_member_id"], headers


def _upload_and_get_item(client: TestClient, headers: dict, member_id: str, data: bytes) -> tuple[str, str]:
    rx = client.post(
        "/api/prescriptions/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": ("rx.jpg", data, "image/jpeg")},
    ).json()
    return rx["id"], rx["items"][0]["id"]


def _verify_body(item_id: str, name: str, dosage: str | None = None, frequency: str | None = None) -> dict:
    return {
        "items": [
            {"item_id": item_id, "medication_name": name, "dosage": dosage, "frequency": frequency}
        ]
    }


def test_verify_creates_normalized_medication(client: TestClient, engine) -> None:
    member_id, headers = _setup(client, "9200000001")
    rx_id, item_id = _upload_and_get_item(client, headers, member_id, b"verify-create")

    r = client.post(
        f"/api/prescriptions/{rx_id}/verify",
        headers=headers,
        json=_verify_body(item_id, "Glucophage 500mg", dosage="500mg", frequency="bd"),
    )
    assert r.status_code == 200, r.text
    result = r.json()["medication_results"][0]
    assert result["action"] == "CREATED"
    assert result["name_generic"] == "Metformin"
    assert result["normalization_status"] == "NORMALIZED"

    with Session(engine) as s:
        med = s.get(Medication, result["medication_id"])
        assert med.name_raw == "Glucophage 500mg"
        assert med.frequency == "twice daily"
        assert med.identity_confirmed is True
        logs = s.exec(select(NormalizationLog).where(NormalizationLog.medication_id == med.id)).all()
        assert len(logs) == 1


def test_same_generic_and_strength_merges_instead_of_duplicating(client: TestClient, engine) -> None:
    member_id, headers = _setup(client, "9200000002")
    rx1, item1 = _upload_and_get_item(client, headers, member_id, b"merge-one")
    rx2, item2 = _upload_and_get_item(client, headers, member_id, b"merge-two")

    first = client.post(f"/api/prescriptions/{rx1}/verify", headers=headers,
                        json=_verify_body(item1, "Glucophage 500mg")).json()["medication_results"][0]
    second = client.post(f"/api/prescriptions/{rx2}/verify", headers=headers,
                         json=_verify_body(item2, "Glycomet 500mg")).json()["medication_results"][0]

    assert second["action"] == "MERGED"
    assert second["medication_id"] == first["medication_id"]
    with Session(engine) as s:
        assert len(s.exec(select(Medication).where(Medication.household_member_id == member_id)).all()) == 1


def test_same_generic_different_strength_creates_new_record(client: TestClient) -> None:
    member_id, headers = _setup(client, "9200000003")
    rx1, item1 = _upload_and_get_item(client, headers, member_id, b"strength-one")
    rx2, item2 = _upload_and_get_item(client, headers, member_id, b"strength-two")

    client.post(f"/api/prescriptions/{rx1}/verify", headers=headers,
                json=_verify_body(item1, "Metformin 500mg"))
    second = client.post(f"/api/prescriptions/{rx2}/verify", headers=headers,
                         json=_verify_body(item2, "Metformin 1000mg")).json()["medication_results"][0]
    assert second["action"] == "CREATED"


def test_unknown_medication_lands_in_review_queue(client: TestClient) -> None:
    member_id, headers = _setup(client, "9200000004")
    rx_id, item_id = _upload_and_get_item(client, headers, member_id, b"review-queue")
    result = client.post(f"/api/prescriptions/{rx_id}/verify", headers=headers,
                         json=_verify_body(item_id, "SomeUnknownMedicine 50mg")).json()["medication_results"][0]
    assert result["normalization_status"] == "NEEDS_REVIEW"

    queue = client.get("/api/medications/needs-review",
                       headers=headers, params={"household_member_id": member_id})
    assert queue.status_code == 200
    assert any(m["id"] == result["medication_id"] for m in queue.json())


def test_manual_verification_overrides_and_clears_queue(client: TestClient) -> None:
    member_id, headers = _setup(client, "9200000005")
    rx_id, item_id = _upload_and_get_item(client, headers, member_id, b"manual-verify")
    med_id = client.post(f"/api/prescriptions/{rx_id}/verify", headers=headers,
                         json=_verify_body(item_id, "Mystery 50mg")).json()["medication_results"][0]["medication_id"]

    r = client.post(f"/api/medications/{med_id}/verify-normalization", headers=headers,
                    json={"name_generic": "Losartan", "strength": "50mg", "dosage_form": "tablet"})
    assert r.status_code == 200
    body = r.json()
    assert body["name_generic"] == "Losartan"
    assert body["normalization_status"] == "MANUALLY_VERIFIED"
    assert body["normalization_confidence"] == 1.0
    assert body["identity_confirmed"] is True

    queue = client.get("/api/medications/needs-review", headers=headers,
                       params={"household_member_id": member_id}).json()
    assert all(m["id"] != med_id for m in queue)


def test_bad_item_id_rolls_back_whole_verification(client: TestClient, engine) -> None:
    member_id, headers = _setup(client, "9200000006")
    rx_id, item_id = _upload_and_get_item(client, headers, member_id, b"rollback")

    body = {
        "items": [
            {"item_id": item_id, "medication_name": "Glucophage 500mg"},
            {"item_id": "not-on-this-prescription", "medication_name": "Aspirin 75mg"},
        ]
    }
    r = client.post(f"/api/prescriptions/{rx_id}/verify", headers=headers, json=body)
    assert r.status_code == 400

    with Session(engine) as s:
        assert s.exec(select(Medication)).all() == []
        item = s.get(PrescriptionItem, item_id)
        assert item.verified is False


def test_verify_requires_access(client: TestClient) -> None:
    member_id, headers = _setup(client, "9200000007")
    rx_id, item_id = _upload_and_get_item(client, headers, member_id, b"private-verify")
    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9200000008", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    r = client.post(f"/api/prescriptions/{rx_id}/verify",
                    headers={"Authorization": f"Bearer {stranger['access_token']}"},
                    json=_verify_body(item_id, "Glucophage 500mg"))
    assert r.status_code == 403


def test_normalize_preview_does_not_save(client: TestClient, engine) -> None:
    _, headers = _setup(client, "9200000009")
    r = client.post("/api/medications/normalize-preview", headers=headers,
                    json={"name_raw": "Crocin 650mg", "frequency": "tid"})
    assert r.status_code == 200
    body = r.json()
    assert body["name_generic"] == "Paracetamol"
    assert body["strength"] == "650mg"
    assert body["frequency"] == "three times daily"
    assert body["status"] == "NORMALIZED"

    with Session(engine) as s:
        assert s.exec(select(Medication)).all() == []


def test_normalize_preview_rejects_empty_name(client: TestClient) -> None:
    _, headers = _setup(client, "9200000010")
    r = client.post("/api/medications/normalize-preview", headers=headers, json={"name_raw": ""})
    assert r.status_code == 422
