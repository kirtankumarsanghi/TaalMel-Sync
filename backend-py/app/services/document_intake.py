"""Unified clinical document intake.

A patient or caregiver can upload a prescription, a lab report, a discharge summary,
a doctor's note, or an unreadable page. The document is always stored and classified;
structured rows are created when a parser understands it. Nothing is interpreted and
nothing is auto-verified.

Classification is deliberately conservative. If the text does not look like a
prescription or a lab report, it is kept as a MedicalDocument rather than forced into a
wrong type.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.audit import service as audit
from app.consent.service import authorize_member
from app.db.models import (
    LabReport,
    LabValue,
    MedicalDocument,
    Prescription,
    PrescriptionItem,
)
from app.events import store as events
from app.events.payloads import (
    MedicationExtractedPayload,
    PrescriptionOcrCompletedPayload,
    PrescriptionUploadedPayload,
)
from app.events.types import EventType, Source
from app.ocr.base import OcrProvider, status_for
from app.ocr.handwriting import fallback_candidates_from_text
from app.ocr.lab_parsing import values_from_text
from app.ocr.parsing import candidates_from_text, looks_like_prescription
from app.services.prescriptions import (
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_BYTES,
    PrescriptionError,
    _safe_name,
)
from app.services.storage import StorageService

DOCUMENT_MIME_TYPES = ALLOWED_MIME_TYPES | {"image/webp", "image/tiff"}

LAB_MARKERS = (
    "hba1c",
    "haemoglobin",
    "hemoglobin",
    "creatinine",
    "cholesterol",
    "triglyceride",
    "bilirubin",
    "platelet",
    "leucocyte",
    "erythrocyte",
    "reference range",
    "lipid profile",
    "thyroid",
    "laboratory",
    "diagnostics",
)
DISCHARGE_MARKERS = (
    "discharge summary",
    "admitted",
    "admission date",
    "condition at discharge",
    "diagnosis",
    "advice",
    "follow up",
)
INVOICE_MARKERS = ("invoice", "gstin", "total amount", "qty", "rate", "subtotal", "bill")


@dataclass(frozen=True)
class DocumentResult:
    document_id: str
    document_type: str
    ocr_status: str
    raw_text: str
    prescription_id: str | None = None
    lab_report_id: str | None = None
    item_count: int = 0
    value_count: int = 0
    message: str = ""


def classify_document(raw_text: str, candidate_count: int, lab_value_count: int) -> str:
    lowered = raw_text.lower()
    lab_hits = sum(1 for marker in LAB_MARKERS if marker in lowered)
    discharge_hits = sum(1 for marker in DISCHARGE_MARKERS if marker in lowered)
    invoice_hits = sum(1 for marker in INVOICE_MARKERS if marker in lowered)

    if lab_hits >= 2 and lab_hits > discharge_hits:
        return "LAB_REPORT"
    if invoice_hits >= 2 and invoice_hits > discharge_hits:
        return "INVOICE"
    if discharge_hits >= 2:
        return "DISCHARGE_SUMMARY"
    if candidate_count > 0 or looks_like_prescription(raw_text):
        return "PRESCRIPTION"
    if lab_value_count > 0:
        return "LAB_REPORT"
    return "OTHER"


def _validate(data: bytes, mime_type: str, filename: str) -> None:
    if not filename or len(filename) > 255:
        raise PrescriptionError("Filename must be 1-255 characters.")
    if mime_type not in DOCUMENT_MIME_TYPES:
        raise PrescriptionError(
            "Invalid file type. Use JPEG, PNG, WEBP, TIFF, or PDF."
        )
    if not data:
        raise PrescriptionError("Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PrescriptionError("File exceeds the 10 MB limit.", status_code=413)


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime | None) -> datetime | None:
    """Date-only input arrives naive; the column requires an aware UTC value."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _existing_document(
    session: Session, member_id: str, file_hash: str
) -> MedicalDocument | None:
    return session.exec(
        select(MedicalDocument).where(
            MedicalDocument.household_member_id == member_id,
            MedicalDocument.file_hash == file_hash,
        )
    ).first()


def intake_document(
    session: Session,
    *,
    storage: StorageService,
    provider: OcrProvider,
    user_id: str,
    household_member_id: str,
    data: bytes,
    mime_type: str,
    filename: str,
    prescribed_by: str | None = None,
    prescribed_on: datetime | None = None,
) -> DocumentResult:
    _validate(data, mime_type, filename)
    authorize_member(session, user_id, household_member_id)

    file_hash = hashlib.sha256(data).hexdigest()
    existing = _existing_document(session, household_member_id, file_hash)
    if existing is not None:
        linked_prescription = session.exec(
            select(Prescription).where(
                Prescription.household_member_id == household_member_id,
                Prescription.file_hash == file_hash,
            )
        ).first()
        linked_lab = session.exec(
            select(LabReport).where(
                LabReport.household_member_id == household_member_id,
                LabReport.file_hash == file_hash,
            )
        ).first()
        return DocumentResult(
            document_id=existing.id,
            document_type=existing.document_type,
            ocr_status=existing.ocr_status,
            raw_text=existing.raw_text or "",
            prescription_id=linked_prescription.id if linked_prescription else None,
            lab_report_id=linked_lab.id if linked_lab else None,
            message="This document was already uploaded for this patient.",
        )

    storage_key = f"documents/{household_member_id}/{file_hash}-{_safe_name(filename)}"
    storage.upload(storage_key, data)

    ocr_error: str | None = None
    try:
        extraction = provider.extract(data, mime_type)
        raw_text = extraction.raw_text or ""
        candidates = extraction.candidates
    except Exception as exc:
        raw_text = ""
        candidates = []
        ocr_error = str(exc)[:500]

    lab_result = None
    if hasattr(provider, "extract_lab"):
        try:
            lab_result = provider.extract_lab(data, mime_type)  # type: ignore[attr-defined]
        except Exception:
            lab_result = None
    if lab_result is None and raw_text:
        lab_result = values_from_text(raw_text)

    lab_values = lab_result.values if lab_result is not None else []
    doc_type = classify_document(raw_text, len(candidates), len(lab_values))
    now = _now()

    document = MedicalDocument(
        household_member_id=household_member_id,
        document_type=doc_type,
        original_filename=filename,
        mime_type=mime_type,
        file_size_bytes=len(data),
        file_hash=file_hash,
        file_storage_key=storage_key,
        ocr_status="PROCESSING",
        ocr_error=ocr_error,
        raw_text=raw_text,
        captured_on=(
            lab_result.captured_on
            if (lab_result is not None and lab_result.captured_on is not None)
            else _utc(prescribed_on)
        ),
        uploaded_by_user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    session.flush()

    prescription_id: str | None = None
    lab_report_id: str | None = None
    item_count = 0
    value_count = 0
    message = ""
    uploaded_event = None

    try:
        if doc_type == "PRESCRIPTION":
            prescription = Prescription(
                household_member_id=household_member_id,
                prescribed_by=prescribed_by,
                prescribed_on=_utc(prescribed_on),
                file_storage_key=storage_key,
                original_filename=filename,
                mime_type=mime_type,
                file_size_bytes=len(data),
                file_hash=file_hash,
                uploaded_by_user_id=user_id,
                ocr_status=status_for(candidates),
                ocr_raw_text=raw_text,
                ocr_completed_at=now,
                ocr_error=ocr_error,
            )
            session.add(prescription)
            session.flush()
            prescription_id = prescription.id
            uploaded_event = events.append_event(
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
            for candidate in candidates:
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
                item_count += 1
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
                    household_member_id=household_member_id,
                )
            from app.services.conditions import sync_conditions_from_text

            sync_conditions_from_text(
                session,
                household_member_id=household_member_id,
                raw_text=raw_text,
                prescription_id=prescription.id,
                document_id=document.id,
            )
            events.append_event(
                session,
                event_type=EventType.PRESCRIPTION_OCR_COMPLETED,
                payload=PrescriptionOcrCompletedPayload(
                    prescription_id=prescription.id, item_count=item_count
                ),
                source=Source.OCR,
                household_member_id=household_member_id,
            )
            document.ocr_status = prescription.ocr_status
            message = (
                "Prescription read. Review the medicine lines before confirming."
                if item_count
                else "Prescription stored, but no medicine lines were readable. Add them by hand."
            )

        elif doc_type == "LAB_REPORT":
            report = LabReport(
                household_member_id=household_member_id,
                file_storage_key=storage_key,
                original_filename=filename,
                mime_type=mime_type,
                file_size_bytes=len(data),
                file_hash=file_hash,
                captured_on=(
            lab_result.captured_on
            if (lab_result is not None and lab_result.captured_on is not None)
            else _utc(prescribed_on)
        ),
                lab_name=lab_result.lab_name if lab_result is not None else None,
                ocr_status="COMPLETED" if lab_values else "NEEDS_REVIEW",
                ocr_raw_text=raw_text,
                ocr_error=ocr_error,
                uploaded_by_user_id=user_id,
            )
            session.add(report)
            session.flush()
            lab_report_id = report.id
            for value in lab_values:
                session.add(
                    LabValue(
                        lab_report_id=report.id,
                        test_name=value.test_name,
                        value=value.value,
                        unit=value.unit,
                        reference_range_raw=value.reference_range_raw,
                    )
                )
                value_count += 1
            document.ocr_status = report.ocr_status
            message = (
                f"Lab report stored with {value_count} value(s). Values are shown as printed."
                if value_count
                else "Lab report stored, but no values were readable."
            )
        else:
            document.ocr_status = "COMPLETED" if raw_text.strip() else ("FAILED" if ocr_error else "NEEDS_REVIEW")
            document.extracted_json = json.dumps(
                {"document_type": doc_type, "raw_text_length": len(raw_text)}
            )
            message = (
                "Document stored and text extracted. No structured parser applies to this type."
                if raw_text.strip()
                else "Document stored, but no text was readable."
            )

        document.updated_at = _now()
        session.add(document)
        audit.log(
            session,
            audit.AuditAction.DOCUMENT_UPLOADED,
            user_id=user_id,
            details={
                "document_id": document.id,
                "document_type": doc_type,
                "prescription_id": prescription_id,
                "lab_report_id": lab_report_id,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    if uploaded_event is not None:
        from app.services.triggers import notify_for_event

        notify_for_event(session, uploaded_event)

    return DocumentResult(
        document_id=document.id,
        document_type=doc_type,
        ocr_status=document.ocr_status,
        raw_text=raw_text,
        prescription_id=prescription_id,
        lab_report_id=lab_report_id,
        item_count=item_count,
        value_count=value_count,
        message=message,
    )


def reclassify_as_prescription(
    session: Session, *, user_id: str, document_id: str
) -> str:
    """Open an uploaded document as a prescription review.

    This is the handwriting safety net: even if OCR produced nothing usable or the
    classifier chose OTHER, the caregiver can still open the prescription screen and
    enter the lines by hand. Nothing is auto-verified.
    """
    document = session.get(MedicalDocument, document_id)
    if document is None:
        raise PrescriptionError("Document not found", status_code=404)
    authorize_member(session, user_id, document.household_member_id)

    existing = session.exec(
        select(Prescription).where(
            Prescription.household_member_id == document.household_member_id,
            Prescription.file_hash == document.file_hash,
        )
    ).first()
    if existing is not None:
        document.document_type = "PRESCRIPTION"
        session.add(document)
        session.commit()
        return existing.id

    raw_text = document.raw_text or ""
    candidates = candidates_from_text(raw_text) or fallback_candidates_from_text(raw_text)
    now = _now()
    prescription = Prescription(
        household_member_id=document.household_member_id,
        file_storage_key=document.file_storage_key,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        file_size_bytes=document.file_size_bytes,
        file_hash=document.file_hash,
        uploaded_by_user_id=user_id,
        ocr_status=status_for(candidates),
        ocr_raw_text=raw_text,
        ocr_completed_at=now,
    )
    session.add(prescription)
    session.flush()

    upload_event = events.append_event(
        session,
        event_type=EventType.PRESCRIPTION_UPLOADED,
        payload=PrescriptionUploadedPayload(
            prescription_id=prescription.id, file_storage_key=document.file_storage_key
        ),
        source=Source.CAREGIVER,
        household_member_id=document.household_member_id,
        source_user_id=user_id,
        created_by=user_id,
    )
    for candidate in candidates:
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
            household_member_id=document.household_member_id,
        )

    document.document_type = "PRESCRIPTION"
    document.ocr_status = prescription.ocr_status
    document.updated_at = now
    session.add(document)
    audit.log(
        session,
        audit.AuditAction.PRESCRIPTION_UPDATED,
        user_id=user_id,
        details={"document_id": document.id, "prescription_id": prescription.id, "via": "reclassify"},
    )
    session.commit()
    from app.services.triggers import notify_for_event

    notify_for_event(session, upload_event)
    return prescription.id


def list_documents(
    session: Session, *, user_id: str, patient_id: str
) -> list[MedicalDocument]:
    from app.consent.service import authorize_patient

    patient = authorize_patient(session, user_id, patient_id)
    return list(
        session.exec(
            select(MedicalDocument)
            .where(MedicalDocument.household_member_id == patient.household_member_id)
            .order_by(MedicalDocument.created_at.desc())  # type: ignore[union-attr]
        ).all()
    )
