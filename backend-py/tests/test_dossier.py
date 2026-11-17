from datetime import UTC, datetime

from sqlmodel import Session

from app.db import models
from app.services import dossier, dossier_pdf


def _seed(session: Session) -> tuple[models.User, models.Patient]:
    user = models.User(role="caregiver", name="Asha", password_hash="x")
    session.add(user)
    session.flush()
    household = models.Household(name="Family", created_by=user.id)
    session.add(household)
    session.flush()
    member = models.HouseholdMember(
        household_id=household.id, display_name="Amma", user_id=user.id
    )
    session.add(member)
    session.flush()
    patient = models.Patient(household_member_id=member.id)
    session.add(patient)
    session.commit()
    return user, patient


def _prescription(session: Session, member_id: str, date: datetime, items: list[tuple[str, str | None]]) -> models.Prescription:
    prescription = models.Prescription(
        household_member_id=member_id,
        prescribed_by="Dr A",
        prescribed_on=date,
        file_storage_key="k",
        original_filename="rx.png",
        mime_type="image/png",
        file_size_bytes=1,
        file_hash=str(date),
        uploaded_by_user_id="u",
        verified=True,
        ocr_status="COMPLETED",
    )
    session.add(prescription)
    session.flush()
    for name, dose in items:
        session.add(
            models.PrescriptionItem(
                prescription_id=prescription.id,
                medication_name=name,
                dosage=dose,
                frequency="once daily",
                verified=True,
            )
        )
    session.commit()
    return prescription


def test_dossier_assembles_every_section(session: Session) -> None:
    user, patient = _seed(session)
    member_id = patient.household_member_id
    first = _prescription(
        session, member_id, datetime(2023, 5, 10, tzinfo=UTC),
        [("Sotret NF", "10mg")],
    )
    _prescription(
        session, member_id, datetime(2025, 1, 15, tzinfo=UTC),
        [("Sotret NF", "20mg")],
    )
    session.add(
        models.Condition(
            household_member_id=member_id,
            name="Acne grade III",
            source_prescription_id=first.id,
            confirmed=True,
        )
    )
    failed = models.Prescription(
        household_member_id=member_id,
        file_storage_key="k2",
        original_filename="blurred.jpg",
        mime_type="image/jpeg",
        file_size_bytes=1,
        file_hash="failed",
        uploaded_by_user_id="u",
        ocr_status="FAILED",
        ocr_error="cloud OCR unavailable",
    )
    session.add(failed)
    session.commit()

    assembled = dossier.assemble_dossier(session, user_id=user.id, patient_id=patient.id)

    assert assembled["patient_name"] == "Amma"
    assert assembled["period"] == "2023 - 2025"
    assert assembled["counts"]["medicines"] == 1
    assert assembled["counts"]["confirmed_conditions"] == 1
    assert any(item["filename"] == "blurred.jpg" for item in assembled["unreadable"])
    changes = [
        episode
        for medicine in assembled["medications"]
        for episode in medicine["episodes"]
        if episode["dose_changed"]
    ]
    assert changes and changes[0]["previous_dose"] == "10mg"
    assert assembled["condition_links"][0]["condition"]["name"] == "Acne grade III"


def test_dossier_pdf_is_a_real_document(session: Session) -> None:
    user, patient = _seed(session)
    _prescription(
        session, patient.household_member_id, datetime(2024, 3, 3, tzinfo=UTC),
        [("Metformin", "500mg")],
    )
    assembled = dossier.assemble_dossier(session, user_id=user.id, patient_id=patient.id)
    pdf = dossier_pdf.render_dossier(assembled)

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_empty_patient_still_renders(session: Session) -> None:
    user, patient = _seed(session)
    assembled = dossier.assemble_dossier(session, user_id=user.id, patient_id=patient.id)
    pdf = dossier_pdf.render_dossier(assembled)

    assert pdf.startswith(b"%PDF")
    assert assembled["period"] == "no dated records"
