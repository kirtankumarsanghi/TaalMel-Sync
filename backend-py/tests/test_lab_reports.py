from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import lab_reports as lab_routes
from app.api.routes import prescriptions as rx_routes
from app.db.models import AuditRecord, LabValue
from app.main import create_app
from app.ocr.lab_stub import StubLabOcrProvider
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
    app.dependency_overrides[lab_routes.storage_dep] = lambda: LocalStorageService(tmp_path / "up")
    # Pin the deterministic lab stub. Without this the suite would use whatever the
    # configured engine is, which makes tests slow and dependent on a vision model.
    app.dependency_overrides[lab_routes.lab_provider_dep] = lambda: StubLabOcrProvider()
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


def _upload_lab(client: TestClient, headers: dict, member_id: str, data: bytes, name: str = "lab.jpg"):
    return client.post(
        "/api/lab-reports/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": (name, data, "image/jpeg")},
    )


def test_lab_upload_stores_values_as_printed(client: TestClient, engine) -> None:
    _, member_id, headers = _setup(client, "9960000001")
    r = _upload_lab(client, headers, member_id, b"clean-lab")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ocr_status"] == "COMPLETED"
    assert body["captured_on"] == "2026-09-14"
    names = {v["test_name"]: v for v in body["values"]}
    assert names["HbA1c"]["value"] == "8.2"
    assert names["HbA1c"]["unit"] == "%"
    assert names["HbA1c"]["reference_range_raw"] == "4.0 - 5.6"


def test_unreadable_lab_is_needs_review_not_a_guess(client: TestClient) -> None:
    _, member_id, headers = _setup(client, "9960000002")
    r = _upload_lab(client, headers, member_id, b"UNREADABLE_LAB")
    assert r.status_code == 201
    assert r.json()["ocr_status"] == "NEEDS_REVIEW"
    assert r.json()["values"] == []


def test_duplicate_lab_is_rejected(client: TestClient) -> None:
    _, member_id, headers = _setup(client, "9960000003")
    assert _upload_lab(client, headers, member_id, b"same-lab").status_code == 201
    assert _upload_lab(client, headers, member_id, b"same-lab").status_code == 409


def test_lab_upload_requires_access(client: TestClient) -> None:
    _, member_id, _ = _setup(client, "9960000004")
    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9960000005", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    r = _upload_lab(client, {"Authorization": f"Bearer {stranger['access_token']}"}, member_id, b"x")
    assert r.status_code == 403


def _add_report_in_window(engine, med_id: str, member_id: str, taking: bool, days_before_capture: int) -> None:
    """Write a MedicationReported event dated inside the stub report's 90-day window.

    The stub report is captured on 2026-09-14, so reports are placed before that date.
    Writing directly keeps the test about correlation, not about the clock.
    """
    import json
    from datetime import UTC, datetime, timedelta

    from app.db.models import Event

    captured = datetime.fromisoformat("2026-09-14").replace(tzinfo=UTC)
    when = captured - timedelta(days=days_before_capture)
    with Session(engine) as s:
        s.add(Event(
            household_member_id=member_id,
            medication_id=med_id,
            event_type="MedicationReported",
            payload=json.dumps({"medication_id": med_id, "taking": taking}),
            source="patient",
            occurred_at=when,
            created_at=when,
        ))
        s.commit()


def test_correlation_pairs_test_with_reported_adherence(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9960000006")
    # Two taking reports and one stopped inside the window: 2 of 3 = 67%.
    _add_report_in_window(engine, med_id, member_id, True, 10)
    _add_report_in_window(engine, med_id, member_id, True, 20)
    _add_report_in_window(engine, med_id, member_id, False, 30)
    _upload_lab(client, headers, member_id, b"adherence-lab")

    findings = client.get(f"/api/households/{member_id}/lab-correlation", headers=headers).json()
    assert findings
    window = findings[0]["adherence_before"][0]
    assert window["taking_reports"] == 2
    assert window["not_taking_reports"] == 1
    assert window["reported_adhered_percent"] == 67
    assert "self-reports" in window["basis"]


def test_correlation_block_appears_in_the_doctor_export(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9960000007")
    _add_report_in_window(engine, med_id, member_id, True, 5)
    _upload_lab(client, headers, member_id, b"export-lab")

    body = client.get(f"/api/households/{member_id}/doctor-export", headers=headers).json()
    assert body["lab_findings"]
    finding = body["lab_findings"][0]
    assert finding["test_name"] in {"HbA1c", "Creatinine"}
    assert finding["adherence_before"][0]["reported_adhered_percent"] == 100


def test_no_reports_means_null_percentage_not_zero(client: TestClient, engine) -> None:
    """Absence of evidence must not be reported as 0% adherence."""
    _, member_id, headers = _setup(client, "9960000008")
    _upload_lab(client, headers, member_id, b"no-reports-lab")

    findings = client.get(f"/api/households/{member_id}/lab-correlation", headers=headers).json()
    window = findings[0]["adherence_before"][0]
    assert window["taking_reports"] == 0
    assert window["reported_adhered_percent"] is None
    assert "No patient self-reports" in window["basis"]


def test_lab_upload_is_audited(client: TestClient, engine) -> None:
    _, member_id, headers = _setup(client, "9960000009")
    _upload_lab(client, headers, member_id, b"audited-lab")
    with Session(engine) as s:
        assert "LAB_REPORT_UPLOADED" in {a.action for a in s.exec(select(AuditRecord)).all()}


def test_stored_values_are_not_interpreted(client: TestClient, engine) -> None:
    """No field in the response says high/low/normal — only the printed value and range."""
    _, member_id, headers = _setup(client, "9960000010")
    _upload_lab(client, headers, member_id, b"interpret-check")

    with Session(engine) as s:
        for value in s.exec(select(LabValue)).all():
            fields = set(value.model_dump().keys())
            assert not {"flag", "status", "abnormal", "interpretation"} & fields
