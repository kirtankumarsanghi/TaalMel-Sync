"""Unified document intake endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.ocr.base import OcrProvider
from app.ocr.provider import get_ocr_provider
from app.services import document_intake
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


def ocr_provider_dep() -> OcrProvider:
    return get_ocr_provider()


@router.post("/documents/upload", response_model=DocumentUploadOut, status_code=201)
async def upload_document(
    household_member_id: str,
    file: UploadFile = File(...),
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
