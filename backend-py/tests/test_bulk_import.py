from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import documents as document_routes
from app.db.models import MedicalDocument, Prescription
from app.main import create_app
from app.ocr.stub import StubOcrProvider
from app.services.storage import LocalStorageService, get_storage


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine, tmp_path: Path) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    app = create_app()
    app.dependency_overrides[db_session] = override_session
    app.dependency_overrides[document_routes.ocr_provider_dep] = lambda: StubOcrProvider()
    app.dependency_overrides[get_storage] = lambda: LocalStorageService(tmp_path / "up")
    with TestClient(app) as c:
        c.engine = engine  # type: ignore[attr-defined]
        yield c


def _setup(client: TestClient, phone: str) -> tuple[str, str, dict[str, str]]:
    reg = client.post(
        "/api/auth/register",
        json={"name": "Asha", "phone": phone, "password": "correct-horse-battery",
              "role": "caregiver"},
    ).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    created = client.post(
        "/api/households",
        headers=headers,
        json={"household_name": "Family", "patient_display_name": "Amma",
              "consent_recorded": True},
    ).json()
    return created["patient"]["patient_id"], created["patient"]["household_member_id"], headers


def test_bulk_import_records_a_date_per_file(client: TestClient) -> None:
    patient_id, member_id, headers = _setup(client, "9700000001")

    response = client.post(
        f"/api/patients/{patient_id}/documents/bulk",
        headers=headers,
        data={"visit_dates": '["2020-02-01", "2023-06-15"]', "prescribed_by": "Dr Rao"},
        files=[
            ("files", ("one.png", b"first record", "image/png")),
            ("files", ("two.png", b"second record", "image/png")),
        ],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["imported"] == 2, [item.get("error") for item in body["items"]]
    assert body["failed"] == 0
    assert all(item["ok"] for item in body["items"])

    with Session(client.engine) as session:  # type: ignore[attr-defined]
        prescriptions = session.exec(
            select(Prescription).where(Prescription.household_member_id == member_id)
        ).all()
        documents = session.exec(select(MedicalDocument)).all()
    assert len(documents) == 2
    dates = sorted(p.prescribed_on.date().isoformat() for p in prescriptions)
    assert dates == ["2020-02-01", "2023-06-15"]


def test_bulk_import_requires_a_date_for_every_file(client: TestClient) -> None:
    patient_id, _, headers = _setup(client, "9700000002")

    mismatched = client.post(
        f"/api/patients/{patient_id}/documents/bulk",
        headers=headers,
        data={"visit_dates": '["2020-02-01"]'},
        files=[
            ("files", ("one.png", b"a", "image/png")),
            ("files", ("two.png", b"b", "image/png")),
        ],
    )
    assert mismatched.status_code == 400

    blank = client.post(
        f"/api/patients/{patient_id}/documents/bulk",
        headers=headers,
        data={"visit_dates": '[""]'},
        files=[("files", ("one.png", b"a", "image/png"))],
    )
    assert blank.status_code == 400
    assert "visit date" in blank.json()["error"].lower()


def test_one_bad_file_does_not_lose_the_batch(client: TestClient) -> None:
    patient_id, _, headers = _setup(client, "9700000003")

    response = client.post(
        f"/api/patients/{patient_id}/documents/bulk",
        headers=headers,
        data={"visit_dates": '["2021-01-01", "2022-01-01"]'},
        files=[
            ("files", ("ok.png", b"readable", "image/png")),
            ("files", ("bad.txt", b"not an image", "text/plain")),
        ],
    )
    assert response.status_code == 201
    body = response.json()
    assert body["imported"] == 1
    assert body["failed"] == 1
    bad = next(item for item in body["items"] if not item["ok"])
    assert bad["filename"] == "bad.txt"
    assert "Invalid file type" in (bad["error"] or "")


def test_bulk_import_is_scoped_to_the_patient(client: TestClient) -> None:
    _, _, headers = _setup(client, "9700000004")
    patient_id, _, _ = _setup(client, "9700000005")

    response = client.post(
        f"/api/patients/{patient_id}/documents/bulk",
        headers=headers,
        data={"visit_dates": '["2020-02-01"]'},
        files=[("files", ("one.png", b"a", "image/png"))],
    )
    assert response.status_code == 403


def test_stub_dates_are_parsed_not_guessed(client: TestClient) -> None:
    """The stored date is the one supplied, never the upload time."""
    patient_id, member_id, headers = _setup(client, "9700000006")
    client.post(
        f"/api/patients/{patient_id}/documents/bulk",
        headers=headers,
        data={"visit_dates": '["2015-11-30"]'},
        files=[("files", ("old.png", b"old record", "image/png"))],
    )
    with Session(client.engine) as session:  # type: ignore[attr-defined]
        prescription = session.exec(
            select(Prescription).where(Prescription.household_member_id == member_id)
        ).first()
    assert prescription is not None
    assert prescription.prescribed_on.date().isoformat() == "2015-11-30"
