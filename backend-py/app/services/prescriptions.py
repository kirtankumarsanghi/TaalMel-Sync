"""Prescription intake and OCR processing.

Upload: validate type and size, dedupe by SHA-256 per household member, store the file,
record the Prescription (PENDING), emit PrescriptionUploaded, then enqueue OCR.

OCR job: runs against the real prescription id. Events are keyed to the prescription,
never to a medication. Failures are recorded on the row and as a PrescriptionOcrFailed
event, then re-raised so the worker surfaces them. Nothing is swallowed.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlmodel import Session, select

from app.audit import service as audit
from app.consent.service import authorize_member
from app.db.models import Prescription, PrescriptionItem
from app.events import store as events
from app.events.payloads import (
    MedicationExtractedPayload,
    PrescriptionOcrCompletedPayload,
    PrescriptionOcrFailedPayload,
    PrescriptionUploadedPayload,
    PrescriptionVerifiedPayload,
)
from app.events.types import EventType, Source
from app.ocr.base import OcrProvider, status_for
from app.services import medications
from app.services.medications import MedicationOutcome
from app.services.storage import StorageService

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class PrescriptionError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DuplicatePrescription(PrescriptionError):
    def __init__(self) -> None:
        super().__init__(
            "This prescription file has already been uploaded for this patient.", status_code=409
        )


class JobQueue(Protocol):
    def enqueue_ocr(self, prescription_id: str) -> None: ...


def _now() -> datetime:
    return datetime.now(UTC)


def validate_upload(data: bytes, mime_type: str, filename: str) -> None:
    if not filename or len(filename) > 255:
        raise PrescriptionError("Filename must be 1-255 characters.")
    if mime_type not in ALLOWED_MIME_TYPES:
        raise PrescriptionError("Invalid file type. Only JPEG, PNG, and PDF are allowed.")
    if len(data) == 0:
        raise PrescriptionError("Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PrescriptionError("File exceeds the 10 MB limit.", status_code=413)


def upload_prescription(
    session: Session,
    *,
    storage: StorageService,
    queue: JobQueue,
    user_id: str,
    household_member_id: str,
    data: bytes,
    mime_type: str,
    filename: str,
) -> Prescription:
    validate_upload(data, mime_type, filename)
    authorize_member(session, user_id, household_member_id)

    file_hash = hashlib.sha256(data).hexdigest()
    duplicate = session.exec(
        select(Prescription).where(
            Prescription.household_member_id == household_member_id,
            Prescription.file_hash == file_hash,
        )
    ).first()
    if duplicate is not None:
        raise DuplicatePrescription()

    storage_key = f"prescriptions/{household_member_id}/{file_hash}-{_safe_name(filename)}"
    storage.upload(storage_key, data)

    prescription = Prescription(
        household_member_id=household_member_id,
        file_storage_key=storage_key,
        original_filename=filename,
        mime_type=mime_type,
        file_size_bytes=len(data),
        file_hash=file_hash,
        uploaded_by_user_id=user_id,
        ocr_status="PENDING",
    )
    session.add(prescription)
    session.flush()

    events.append_event(
        session,
        event_type=EventType.PRESCRIPTION_UPLOADED,
        payload=PrescriptionUploadedPayload(
            prescription_id=prescription.id, file_storage_key=storage_key
        ),
        source=Source.CAREGIVER,
        household_member_id=household_member_id,
        source_user_id=user_id,
        created_by=user_id,
    )
    audit.log(
        session,
        audit.AuditAction.PRESCRIPTION_UPLOADED,
        user_id=user_id,
        details={"prescription_id": prescription.id, "household_member_id": household_member_id},
    )
    session.commit()

    queue.enqueue_ocr(prescription.id)
    return prescription


def run_ocr_job(
    session: Session,
    *,
    storage: StorageService,
    provider: OcrProvider,
    prescription_id: str,
) -> Prescription:
    prescription = session.get(Prescription, prescription_id)
    if prescription is None:
        raise PrescriptionError("Prescription not found", status_code=404)

    prescription.ocr_status = "PROCESSING"
    prescription.updated_at = _now()
    session.add(prescription)
    session.commit()

    try:
        data = storage.download(prescription.file_storage_key)
        result = provider.extract(data, prescription.mime_type)
    except Exception as exc:
        prescription.ocr_status = "FAILED"
        prescription.ocr_error = str(exc)[:500]
        prescription.updated_at = _now()
        session.add(prescription)
        events.append_event(
            session,
            event_type=EventType.PRESCRIPTION_OCR_FAILED,
            payload=PrescriptionOcrFailedPayload(
                prescription_id=prescription.id, error=str(exc)[:500] or "unknown error"
            ),
            source=Source.OCR,
            household_member_id=prescription.household_member_id,
        )
        session.commit()
        raise

    status = status_for(result.candidates)
    now = _now()
    prescription.ocr_status = status
    prescription.ocr_raw_text = result.raw_text
    prescription.ocr_completed_at = now
    prescription.ocr_error = None
    prescription.updated_at = now
    session.add(prescription)

    for candidate in result.candidates:
        item = PrescriptionItem(
            prescription_id=prescription.id,
            medication_name=candidate.medication_name,
            dosage=candidate.dosage,
            frequency=candidate.frequency,
            instructions=candidate.instructions,
            confidence=candidate.confidence,
            ocr_raw_value=candidate.medication_name,
            verified=False,
        )
        session.add(item)
        session.flush()
        events.append_event(
            session,
            event_type=EventType.MEDICATION_EXTRACTED,
            payload=MedicationExtractedPayload(
                prescription_item_id=item.id,
                name_raw=candidate.medication_name,
                dosage=candidate.dosage,
                frequency=candidate.frequency,
                instructions=candidate.instructions,
                confidence=candidate.confidence,
            ),
            source=Source.OCR,
            household_member_id=prescription.household_member_id,
        )

    events.append_event(
        session,
        event_type=EventType.PRESCRIPTION_OCR_COMPLETED,
        payload=PrescriptionOcrCompletedPayload(
            prescription_id=prescription.id, item_count=len(result.candidates)
        ),
        source=Source.OCR,
        household_member_id=prescription.household_member_id,
    )
    session.commit()
    return prescription


@dataclass(frozen=True)
class VerifiedItemInput:
    item_id: str
    medication_name: str
    dosage: str | None = None
    frequency: str | None = None
    instructions: str | None = None


def verify_prescription(
    session: Session,
    *,
    user_id: str,
    prescription_id: str,
    items: list[VerifiedItemInput],
) -> list[MedicationOutcome]:
    """A caregiver confirms the OCR items. Each item becomes (or merges into) a Medication.

    Everything happens in one transaction: if any item is invalid, nothing is saved.
    """
    prescription = session.get(Prescription, prescription_id)
    if prescription is None:
        raise PrescriptionError("Prescription not found", status_code=404)
    authorize_member(session, user_id, prescription.household_member_id)

    existing_items = {
        i.id: i
        for i in session.exec(
            select(PrescriptionItem).where(PrescriptionItem.prescription_id == prescription_id)
        ).all()
    }
    for requested in items:
        if requested.item_id not in existing_items:
            raise PrescriptionError(
                f"Item {requested.item_id} not found on this prescription", status_code=400
            )

    now = _now()
    outcomes: list[MedicationOutcome] = []
    try:
        for requested in items:
            item = existing_items[requested.item_id]
            item.medication_name = requested.medication_name
            item.dosage = requested.dosage
            item.frequency = requested.frequency
            item.instructions = requested.instructions
            item.verified = True
            item.verified_at = now
            item.verified_by_user_id = user_id
            session.add(item)
            session.flush()
            outcomes.append(
                medications.create_or_merge_from_item(
                    session,
                    user_id=user_id,
                    item=item,
                    household_member_id=prescription.household_member_id,
                )
            )

        prescription.verified = True
        prescription.verified_at = now
        prescription.verified_by_user_id = user_id
        prescription.updated_at = now
        session.add(prescription)

        events.append_event(
            session,
            event_type=EventType.PRESCRIPTION_VERIFIED,
            payload=PrescriptionVerifiedPayload(
                prescription_id=prescription.id, verified_item_count=len(items)
            ),
            source=Source.CAREGIVER,
            household_member_id=prescription.household_member_id,
            source_user_id=user_id,
            created_by=user_id,
        )
        audit.log(
            session,
            audit.AuditAction.PRESCRIPTION_VERIFIED,
            user_id=user_id,
            details={"prescription_id": prescription.id, "item_count": len(items)},
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return outcomes


def _safe_name(filename: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in filename)
    return keep[:120] or "upload"
