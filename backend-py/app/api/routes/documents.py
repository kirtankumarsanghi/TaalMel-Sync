"""Unified document intake endpoints."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.consent.service import authorize_patient
from app.ocr.base import OcrProvider
from app.ocr.provider import get_ocr_provider
from app.services import document_intake
from app.services.prescriptions import PrescriptionError
from app.services.storage import StorageService, get_storage

router = APIRouter()


class DocumentUploadOut(BaseModel):
    document_id: str
    document_type: str
    ocr_status: str
    prescription_id: str | None = None
    lab_report_id: str | None = None
    item_count: int = 0
    value_count: int = 0
    message: str
    raw_text_preview: str


class DocumentOut(BaseModel):
    id: str
    document_type: str
    original_filename: str
    ocr_status: str
    ocr_error: str | None
    captured_on: str | None
    created_at: datetime
    raw_text_preview: str


class BulkItemOut(BaseModel):
    filename: str
    ok: bool
    document_id: str | None = None
    document_type: str | None = None
    prescription_id: str | None = None
    item_count: int = 0
    message: str = ""
    error: str | None = None


class BulkImportOut(BaseModel):
    imported: int
    failed: int
    items: list[BulkItemOut]


def ocr_provider_dep() -> OcrProvider:
    return get_ocr_provider()


@router.post("/documents/upload", response_model=DocumentUploadOut, status_code=201)
async def upload_document(
    household_member_id: str,
    file: UploadFile = File(...),
    prescribed_by: str | None = Query(default=None),
    prescribed_on: datetime | None = Query(default=None),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
    storage: StorageService = Depends(get_storage),
    provider: OcrProvider = Depends(ocr_provider_dep),
) -> DocumentUploadOut:
    data = await file.read(document_intake.MAX_UPLOAD_BYTES + 1)
    result = document_intake.intake_document(
        session,
        storage=storage,
        provider=provider,
        user_id=user_id,
        household_member_id=household_member_id,
        data=data,
        mime_type=file.content_type or "",
        filename=file.filename or "",
        prescribed_by=prescribed_by,
        prescribed_on=prescribed_on,
    )
    return DocumentUploadOut(
        document_id=result.document_id,
        document_type=result.document_type,
        ocr_status=result.ocr_status,
        prescription_id=result.prescription_id,
        lab_report_id=result.lab_report_id,
        item_count=result.item_count,
        value_count=result.value_count,
        message=result.message,
        raw_text_preview=result.raw_text[:2000],
    )


@router.post(
    "/patients/{patient_id}/documents/bulk", response_model=BulkImportOut, status_code=201
)
async def bulk_upload(
    patient_id: str,
    files: list[UploadFile] = File(...),
    visit_dates: str = Form(...),
    prescribed_by: str | None = Form(default=None),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
    storage: StorageService = Depends(get_storage),
    provider: OcrProvider = Depends(ocr_provider_dep),
) -> BulkImportOut:
    """Import a stack of past records, one visit date per file.

    A date is required for every file: the whole point of an archive is a year-by-year
    view, and an undated stack cannot provide one. One bad file never aborts the batch.
    """
    patient = authorize_patient(session, user_id, patient_id)

    try:
        raw_dates = json.loads(visit_dates)
    except json.JSONDecodeError as exc:
        raise PrescriptionError(
            "visit_dates must be a JSON array of ISO dates.", status_code=400
        ) from exc
    if not isinstance(raw_dates, list) or len(raw_dates) != len(files):
        raise PrescriptionError(
            "visit_dates must contain exactly one date per uploaded file.", status_code=400
        )
    if not files:
        raise PrescriptionError("No files were uploaded.", status_code=400)

    dates: list[datetime] = []
    for value in raw_dates:
        if not isinstance(value, str) or not value.strip():
            raise PrescriptionError(
                "Every file needs a visit date. Use YYYY-MM-DD.", status_code=400
            )
        try:
            dates.append(datetime.fromisoformat(value))
        except ValueError as exc:
            raise PrescriptionError(
                f"Invalid visit date {value!r}. Use YYYY-MM-DD.", status_code=400
            ) from exc

    items: list[BulkItemOut] = []
    for upload, visit_date in zip(files, dates):
        filename = upload.filename or "unnamed"
        try:
            data = await upload.read(document_intake.MAX_UPLOAD_BYTES + 1)
            result = document_intake.intake_document(
                session,
                storage=storage,
                provider=provider,
                user_id=user_id,
                household_member_id=patient.household_member_id,
                data=data,
                mime_type=upload.content_type or "",
                filename=filename,
                prescribed_by=prescribed_by,
                prescribed_on=visit_date,
            )
            items.append(
                BulkItemOut(
                    filename=filename,
                    ok=True,
                    document_id=result.document_id,
                    document_type=result.document_type,
                    prescription_id=result.prescription_id,
                    item_count=result.item_count,
                    message=result.message,
                )
            )
        except Exception as exc:  # one bad file must not lose the rest of the batch
            items.append(
                BulkItemOut(filename=filename, ok=False, error=str(exc)[:300])
            )

    return BulkImportOut(
        imported=sum(1 for item in items if item.ok),
        failed=sum(1 for item in items if not item.ok),
        items=items,
    )


@router.post("/documents/{document_id}/as-prescription", response_model=dict)
def document_as_prescription(
    document_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> dict:
    prescription_id = document_intake.reclassify_as_prescription(
        session, user_id=user_id, document_id=document_id
    )
    return {"prescription_id": prescription_id}


@router.get("/patients/{patient_id}/documents", response_model=list[DocumentOut])
def list_documents(
    patient_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[DocumentOut]:
    rows = document_intake.list_documents(
        session, user_id=user_id, patient_id=patient_id
    )
    return [
        DocumentOut(
            id=row.id,
            document_type=row.document_type,
            original_filename=row.original_filename,
            ocr_status=row.ocr_status,
            ocr_error=row.ocr_error,
            captured_on=row.captured_on,
            created_at=row.created_at,
            raw_text_preview=(row.raw_text or "")[:1000],
        )
        for row in rows
    ]
