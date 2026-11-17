"""The multi-year dossier: one document a new doctor can read in ten minutes.

It composes what is already derived elsewhere — the medication timeline, the condition
list, and the lab comparison — and adds the records that could not be read. Nothing is
re-interpreted here, and every medicine row still points at its source document.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from app.consent.service import authorize_patient
from app.db.models import HouseholdMember, MedicalDocument, Prescription
from app.services import lab_comparison, timeline

UNREADABLE_STATUSES = ("FAILED", "NO_MEDICINES_FOUND")


def assemble_dossier(session: Session, *, user_id: str, patient_id: str) -> dict:
    patient = authorize_patient(session, user_id, patient_id)
    member_id = patient.household_member_id
    member = session.get(HouseholdMember, member_id)

    history = timeline.medication_timeline(session, user_id=user_id, patient_id=patient_id)
    labs = lab_comparison.lab_comparison(session, user_id=user_id, patient_id=patient_id)

    prescriptions = session.exec(
        select(Prescription)
        .where(Prescription.household_member_id == member_id)
        .order_by(Prescription.prescribed_on)
    ).all()
    documents = session.exec(
        select(MedicalDocument).where(MedicalDocument.household_member_id == member_id)
    ).all()

    unreadable = [
        {
            "filename": prescription.original_filename,
            "date": prescription.prescribed_on.date().isoformat()
            if prescription.prescribed_on
            else None,
            "status": prescription.ocr_status,
            "reason": prescription.ocr_error,
        }
        for prescription in prescriptions
        if prescription.ocr_status in UNREADABLE_STATUSES
    ]
    unreadable += [
        {
            "filename": document.original_filename,
            "date": document.captured_on,
            "status": document.ocr_status,
            "reason": document.ocr_error,
        }
        for document in documents
        if document.ocr_status in UNREADABLE_STATUSES
    ]

    sources = [
        {
            "filename": prescription.original_filename,
            "date": prescription.prescribed_on.date().isoformat()
            if prescription.prescribed_on
            else None,
            "prescriber": prescription.prescribed_by,
            "verified": prescription.verified,
            "ocr_status": prescription.ocr_status,
        }
        for prescription in prescriptions
    ]

    confirmed_conditions = [c for c in history["conditions"] if c["confirmed"]]
    years = [row["year"] for row in history["years"] if row["year"].isdigit()]
    period = f"{years[0]} - {years[-1]}" if years else "no dated records"

    return {
        "patient_id": patient_id,
        "patient_name": member.display_name if member else "Patient",
        "generated_at": datetime.now(UTC),
        "period": period,
        "conditions": confirmed_conditions,
        "condition_links": history["condition_links"],
        "years": history["years"],
        "medications": history["medications"],
        "labs": labs["tests"],
        "lab_summary": labs["summary"],
        "sources": sources,
        "unreadable": unreadable,
        "counts": {
            "prescriptions": len(prescriptions),
            "medicines": len(history["medications"]),
            "lab_tests": len(labs["tests"]),
            "confirmed_conditions": len(confirmed_conditions),
            "unreadable": len(unreadable),
        },
    }
