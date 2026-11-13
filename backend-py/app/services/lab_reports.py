"""Lab report intake and correlation.

Correlation, not interpretation. The system stores values exactly as printed and places
them on the same timeline as reported adherence. It never decides whether a value is
good or bad — that is the doctor's job.

Adherence here is derived only from MedicationReported events, and is always labelled
"reported", never "actual".
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.audit import service as audit
from app.consent.service import authorize_member
from app.db.models import Event, LabReport, LabValue, Medication
from app.events import store as events
from app.events.types import EventType
from app.ocr.base import LabOcrProvider
from app.services.prescriptions import (
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_BYTES,
    PrescriptionError,
    _safe_name,
)
from app.services.storage import StorageService

CORRELATION_WINDOW_DAYS = 90


@dataclass(frozen=True)
class AdherenceWindow:
    medication_name: str
    days_covered: int
    taking_reports: int
    not_taking_reports: int
    reported_adhered_percent: int | None
    basis: str


@dataclass(frozen=True)
class LabFinding:
    test_name: str
    value: str
    unit: str | None
    reference_range_raw: str | None
    captured_on: str | None
    adherence_before: list[AdherenceWindow]


def upload_lab_report(
    session: Session,
    *,
    storage: StorageService,
    user_id: str,
    household_member_id: str,
    data: bytes,
    mime_type: str,
    filename: str,
) -> LabReport:
    if mime_type not in ALLOWED_MIME_TYPES:
        raise PrescriptionError("Invalid file type. Only JPEG, PNG, and PDF are allowed.")
    if not data:
        raise PrescriptionError("Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PrescriptionError("File exceeds the 10 MB limit.", status_code=413)
    authorize_member(session, user_id, household_member_id)

    file_hash = hashlib.sha256(data).hexdigest()
    duplicate = session.exec(
        select(LabReport).where(
            LabReport.household_member_id == household_member_id,
            LabReport.file_hash == file_hash,
        )
    ).first()
    if duplicate is not None:
        raise PrescriptionError("This lab report has already been uploaded for this patient.", status_code=409)

    storage_key = f"lab_reports/{household_member_id}/{file_hash}-{_safe_name(filename)}"
    storage.upload(storage_key, data)

    report = LabReport(
        household_member_id=household_member_id,
        file_storage_key=storage_key,
        original_filename=filename,
        mime_type=mime_type,
        file_size_bytes=len(data),
        file_hash=file_hash,
        uploaded_by_user_id=user_id,
    )
    session.add(report)
    session.flush()
    audit.log(
        session,
        audit.AuditAction.LAB_REPORT_UPLOADED,
        user_id=user_id,
        details={"lab_report_id": report.id, "household_member_id": household_member_id},
    )
    session.commit()
    return report


def process_lab_report(
    session: Session, *, storage: StorageService, provider: LabOcrProvider, lab_report_id: str
) -> LabReport:
    report = session.get(LabReport, lab_report_id)
    if report is None:
        raise PrescriptionError("Lab report not found", status_code=404)

    try:
        data = storage.download(report.file_storage_key)
        result = provider.extract_lab(data, report.mime_type)
    except Exception as exc:
        report.ocr_status = "FAILED"
        report.ocr_error = str(exc)[:500]
        report.updated_at = datetime.now(UTC)
        session.add(report)
        session.commit()
        raise

    # No readable values is NEEDS_REVIEW, not an empty success and not a guess.
    report.ocr_status = "COMPLETED" if result.values else "NEEDS_REVIEW"
    report.ocr_raw_text = result.raw_text
    report.captured_on = result.captured_on
    report.lab_name = result.lab_name
    report.ocr_error = None
    report.updated_at = datetime.now(UTC)
    session.add(report)

    for value in result.values:
        session.add(
            LabValue(
                lab_report_id=report.id,
                test_name=value.test_name,
                value=value.value,
                unit=value.unit,
                reference_range_raw=value.reference_range_raw,
            )
        )
    session.commit()
    return report


def _adherence_before(
    session: Session, medication: Medication, until: datetime, days: int = CORRELATION_WINDOW_DAYS
) -> AdherenceWindow:
    since = until - timedelta(days=days)
    reports = [
        e
        for e in events.events_for_medication(session, medication.id)
        if e.event_type == EventType.MEDICATION_REPORTED and since <= _aware(e.occurred_at) <= until
    ]
    taking = sum(1 for e in reports if json.loads(e.payload).get("taking"))
    not_taking = len(reports) - taking
    percent = round(taking * 100 / len(reports)) if reports else None
    return AdherenceWindow(
        medication_name=medication.name_generic or medication.name_raw,
        days_covered=days,
        taking_reports=taking,
        not_taking_reports=not_taking,
        reported_adhered_percent=percent,
        basis=(
            f"From {len(reports)} recorded patient self-reports in the {days} days before the test."
            if reports
            else "No patient self-reports were recorded in this window."
        ),
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def correlate(session: Session, *, user_id: str, household_member_id: str) -> list[LabFinding]:
    """Each stored lab value, with reported adherence in the window before its report date."""
    authorize_member(session, user_id, household_member_id)
    return assemble_findings(session, household_member_id)


def assemble_findings(session: Session, household_member_id: str) -> list[LabFinding]:
    """The correlation itself, with no access check. Callers must have established access."""
    reports = session.exec(
        select(LabReport).where(
            LabReport.household_member_id == household_member_id,
            LabReport.ocr_status.in_(["COMPLETED", "NEEDS_REVIEW"]),  # type: ignore[attr-defined]
        )
    ).all()
    medications = session.exec(
        select(Medication).where(Medication.household_member_id == household_member_id)
    ).all()

    findings: list[LabFinding] = []
    for report in reports:
        captured = (
            datetime.fromisoformat(report.captured_on).replace(tzinfo=UTC)
            if report.captured_on
            else _aware(report.created_at)
        )
        windows = [_adherence_before(session, med, captured) for med in medications]
        for value in session.exec(select(LabValue).where(LabValue.lab_report_id == report.id)).all():
            findings.append(
                LabFinding(
                    test_name=value.test_name,
                    value=value.value,
                    unit=value.unit,
                    reference_range_raw=value.reference_range_raw,
                    captured_on=report.captured_on,
                    adherence_before=windows,
                )
            )
    return findings


def assemble_lab_findings(session: Session, household_member_id: str) -> list[dict]:
    """Same correlation as `assemble_findings`, shaped as plain dicts for the export."""
    return [asdict(f) for f in assemble_findings(session, household_member_id)]


def timeline(session: Session, *, user_id: str, household_member_id: str) -> list[Event]:
    authorize_member(session, user_id, household_member_id)
    return list(events.events_for_member(session, household_member_id))
