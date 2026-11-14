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
from app.ocr.base import OcrResult
from app.ocr.stub import StubOcrProvider
from app.services.photo_verification import OcrPhotoMatcher
from app.services.storage import LocalStorageService
from app.services.triggers import run_all_periodic_checks


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


def _register(client: TestClient, phone: str, name: str = "Asha") -> tuple[str, dict[str, str]]:
    r = client.post(
        "/api/auth/register",
        json={"name": name, "phone": phone, "password": "correct-horse-battery", "role": "caregiver"},
    )
    assert r.status_code == 201
    body = r.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def test_household_detail_and_temporary_access_routes(client: TestClient) -> None:
    _, owner_h = _register(client, "9600000001", "Owner")
    guest_id, guest_h = _register(client, "9600000002", "Guest")

    created = client.post(
        "/api/households",
        headers=owner_h,
        json={"household_name": "Home", "patient_display_name": "Dadi", "consent_recorded": True},
    ).json()
    hh_id = created["household"]["id"]
    member_id = created["patient"]["household_member_id"]

    # Owner can fetch household detail
    res = client.get(f"/api/households/{hh_id}", headers=owner_h)
    assert res.status_code == 200
    assert res.json()["members"][0]["household_member_id"] == member_id

    # Stranger cannot
    assert client.get(f"/api/households/{hh_id}", headers=guest_h).status_code == 403

    # Grant temporary access, record consent, verify access, then revoke via DELETE
    expires = (datetime.now(UTC) + timedelta(hours=4)).isoformat()
    grant = client.post(
        f"/api/households/{hh_id}/temporary-access",
        headers=owner_h,
        json={"caregiver_user_id": guest_id, "household_member_id": member_id, "expires_at": expires},
    )
    assert grant.status_code == 201
    access_id = grant.json()["id"]

    client.post(f"/api/access/{access_id}/consent", headers=guest_h, json={})
    assert client.get(f"/api/households/{hh_id}", headers=guest_h).status_code == 200

    revoked = client.delete(f"/api/households/{hh_id}/temporary-access/{access_id}", headers=owner_h)
    assert revoked.status_code == 204
    assert client.get(f"/api/households/{hh_id}", headers=guest_h).status_code == 403


def test_patient_list_routes_and_expiry_alerts_and_plain_explanation(
    client: TestClient, engine
) -> None:
    _, headers = _register(client, "9600000003")
    created = client.post(
        "/api/households",
        headers=headers,
        json={"household_name": "Home", "patient_display_name": "Amma", "consent_recorded": True},
    ).json()
    patient_id = created["patient"]["patient_id"]
    member_id = created["patient"]["household_member_id"]

    # Upload & verify prescription
    rx = client.post(
        "/api/prescriptions/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": ("rx.jpg", b"scan-rx", "image/jpeg")},
    ).json()
    verify = client.post(
        f"/api/prescriptions/{rx['id']}/verify",
        headers=headers,
        json={"items": [{"item_id": rx["items"][0]["id"], "medication_name": "Metformin 500mg", "instructions": "After dinner"}]},
    ).json()
    med_id = verify["medication_results"][0]["medication_id"]

    # List patient prescriptions
    rx_list = client.get(f"/api/patients/{patient_id}/prescriptions", headers=headers)
    assert rx_list.status_code == 200
    assert len(rx_list.json()) == 1

    # List patient lab reports (empty initially)
    lab_list = client.get(f"/api/patients/{patient_id}/lab-reports", headers=headers)
    assert lab_list.status_code == 200
    assert lab_list.json() == []

    # Plain-language explanation appears alongside verbatim doctor instruction
    today_res = client.get(f"/api/households/{member_id}/today", headers=headers).json()
    assert today_res[0]["instruction"] == "After dinner"
    assert "blood sugar" in (today_res[0]["plain_explanation"] or "").lower()

    # Log near-expiry date -> appears in expiry-alerts and daily sweep
    soon = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    client.post(
        f"/api/medications/{med_id}/availability",
        headers=headers,
        json={"present": True, "expiry_date": soon},
    )
    alerts = client.get(f"/api/patients/{patient_id}/expiry-alerts", headers=headers)
    assert alerts.status_code == 200
    assert len(alerts.json()) == 1
    assert alerts.json()[0]["expired"] is False

    with Session(engine) as s:
        count = run_all_periodic_checks(s)
        assert count >= 1


def test_ocr_photo_matcher_scores_real_text() -> None:
    class _FakeOcr:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract(self, data: bytes, mime_type: str) -> OcrResult:
            return OcrResult(raw_text=self._text, candidates=[])

    match = OcrPhotoMatcher(_FakeOcr("Glycomet 500mg Strip")).compare(b"img", "image/png", "Metformin")
    assert match.outcome == "MATCH"

    mismatch = OcrPhotoMatcher(_FakeOcr("Dolo 650mg")).compare(b"img", "image/png", "Metformin")
    assert mismatch.outcome == "NO_MATCH"

    empty = OcrPhotoMatcher(_FakeOcr("")).compare(b"img", "image/png", "Metformin")
    assert empty.outcome == "NOT_CHECKED"
