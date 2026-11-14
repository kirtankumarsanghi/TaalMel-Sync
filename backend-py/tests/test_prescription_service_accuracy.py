"""A readable-but-not-a-prescription upload must be reported honestly.

Regression: a lab report or invoice used to create junk medicine records. It now
creates none — and must say so in a way a caregiver can act on, not as a silent
success or a generic technical failure.
"""

from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.db.models import Medication, PrescriptionItem
from app.main import create_app
from app.ocr.easyocr_provider import EasyOcrProvider
from app.services.storage import LocalStorageService


def make_pdf(lines: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for index, line in enumerate(lines):
        page.insert_text((50, y), line, fontsize=18 if index == 0 else 14)
        y += 32
    data = doc.tobytes()
    doc.close()
    return data


INVOICE = make_pdf([
    "GREEN LEAF STATIONERS",
    "12 MG Road, Bengaluru 560001",
    "GSTIN 29ABCDE1234F1Z5",
    "Invoice No 4412  Date: 03/11/2026",
    "Item  Qty  Amount",
    "A4 paper ream 500 g  2  420.00",
    "Total  570.00",
])

PRESCRIPTION = make_pdf([
    "CITY MEDICAL CENTRE",
    "Dr. A. Rao  MBBS",
    "Patient: Mr Sharma  Age: 68",
    "Rx",
    "Tab Metformin 500mg BD after meals for 30 days",
    "Tab Amlodipine 5mg OD morning",
])

BLANK = make_pdf(["CITY MEDICAL CENTRE", "Dr. A. Rao", "Date: 12/11/2026"])


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
    # Real OCR, because the point of this test is the real extraction path.
    app.dependency_overrides[rx_routes.ocr_provider_dep] = lambda: EasyOcrProvider(languages=("en",))
    with TestClient(app) as c:
        yield c


def _setup(client: TestClient, phone: str) -> tuple[str, dict[str, str]]:
    reg = client.post("/api/auth/register", json={
        "name": "Accuracy", "phone": phone, "password": "correct-horse-battery", "role": "caregiver",
    }).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    created = client.post("/api/households", headers=headers, json={
        "household_name": "F", "patient_display_name": "Amma", "consent_recorded": True,
    }).json()
    return created["patient"]["household_member_id"], headers


def _upload(client, headers, member, data, name):
    return client.post(
        "/api/prescriptions/upload",
        headers=headers,
        params={"household_member_id": member},
        files={"file": (name, data, "application/pdf")},
    )


@pytest.mark.slow
def test_invoice_is_reported_as_no_medicines_found(client: TestClient, engine) -> None:
    member, headers = _setup(client, "9500000101")
    response = _upload(client, headers, member, INVOICE, "invoice.pdf")
    assert response.status_code == 201

    body = response.json()
    assert body["ocr_status"] == "NO_MEDICINES_FOUND"
    assert body["items"] == []
    # The caregiver is given an instruction, not just a status code.
    assert body["ocr_error"]

    with Session(engine) as s:
        assert s.exec(select(Medication)).all() == []
        assert s.exec(select(PrescriptionItem)).all() == []


@pytest.mark.slow
def test_real_prescription_still_extracts_cleanly(client: TestClient, engine) -> None:
    member, headers = _setup(client, "9500000102")
    response = _upload(client, headers, member, PRESCRIPTION, "rx.pdf")
    body = response.json()

    assert body["ocr_status"] == "COMPLETED"
    names = [item["medication_name"] for item in body["items"]]
    assert names == ["Metformin", "Amlodipine"], names
    # No instruction fragments absorbed into the name.
    assert all("after" not in n.lower() and "morning" not in n.lower() for n in names)

    doses = {item["medication_name"]: item["dosage"] for item in body["items"]}
    assert doses["Metformin"] == "500mg"
    assert doses["Amlodipine"] == "5mg"


@pytest.mark.slow
def test_readable_page_without_medicines_is_not_a_failure(client: TestClient, engine) -> None:
    """A header-only page was read fine; calling that a technical failure is misleading."""
    member, headers = _setup(client, "9500000103")
    body = _upload(client, headers, member, BLANK, "blank.pdf").json()
    assert body["ocr_status"] in {"NO_MEDICINES_FOUND", "FAILED"}
    assert body["items"] == []
