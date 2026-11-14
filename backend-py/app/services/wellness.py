"""Patient wellness timeline.

This is a read-only, patient-facing view of what happened, in order. It is not a
health score and it does not interpret anything: each row is an event or a report with
its source and date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.consent.service import authorize_patient
from app.db.models import LabReport, LabValue, Medication, SymptomReport
from app.events import store as events


@dataclass(frozen=True)
class TimelineRow:
    date: datetime
    kind: str
    title: str
    detail: str | None
    source: str | None


_LABELS = {
    "MedicationNormalized": "Medicine added",
    "MedicationReported": "Self-report",
    "AvailabilityObserved": "Stock check",
    "MedicationConfirmed": "Status confirmed",
    "DoseChanged": "Dose changed",
    "ConflictDetected": "Discrepancy detected",
    "ReasonRecorded": "Reason recorded",
    "CaseResolved": "Case resolved",
}


def patient_timeline(
    session: Session, *, user_id: str, patient_id: str, limit: int = 200
) -> list[TimelineRow]:
    patient = authorize_patient(session, user_id, patient_id)
    member_id = patient.household_member_id

    rows: list[TimelineRow] = []
    medications = {
        med.id: med.name_generic or med.name_raw
        for med in session.exec(
            select(Medication).where(Medication.household_member_id == member_id)
        ).all()
    }

    for event in events.events_for_member(session, member_id):
        label = _LABELS.get(event.event_type)
        if label is None:
            continue
        payload = events.decode_payload(event)
        name = medications.get(event.medication_id or "", "")
        detail = None
        if event.event_type == "MedicationReported":
            detail = "taking" if payload.get("taking") else "not taking"
        elif event.event_type == "DoseChanged":
            detail = f"new dose {payload.get('new_dose')}"
        elif event.event_type == "AvailabilityObserved":
            detail = "present" if payload.get("present") else "not found"
        elif event.event_type in ("ConflictDetected", "ReasonRecorded"):
            detail = payload.get("description") or str(payload.get("reason_code") or "")
        rows.append(
            TimelineRow(
                date=event.occurred_at,
                kind=event.event_type,
                title=f"{label}{f': {name}' if name else ''}",
                detail=detail,
                source=event.source,
            )
        )

    for report in session.exec(
        select(LabReport).where(LabReport.household_member_id == member_id)
    ).all():
        values = session.exec(
            select(LabValue).where(LabValue.lab_report_id == report.id)
        ).all()
        detail = ", ".join(f"{v.test_name} {v.value}{v.unit or ''}" for v in values) or None
        rows.append(
            TimelineRow(
                date=report.created_at,
                kind="LabReport",
                title=f"Lab report: {report.lab_name or report.original_filename}",
                detail=detail,
                source="lab",
            )
        )

    for symptom in session.exec(
        select(SymptomReport).where(SymptomReport.household_member_id == member_id)
    ).all():
        rows.append(
            TimelineRow(
                date=symptom.created_at,
                kind="SymptomReport",
                title=f"Symptom reported ({symptom.severity.lower()})",
                detail=symptom.symptom_text,
                source="patient",
            )
        )

    for row in rows:
        if row.date.tzinfo is None:
            object.__setattr__(row, "date", row.date.replace(tzinfo=UTC))

    return sorted(rows, key=lambda row: row.date, reverse=True)[:limit]
