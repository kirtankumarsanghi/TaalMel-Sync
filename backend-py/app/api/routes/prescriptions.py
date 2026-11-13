from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.api.deps import CurrentUserDep, SessionDep
from app.consent.service import authorize_member
from app.db.models import Prescription, PrescriptionItem
from app.db.session import get_engine
from app.jobs.queue import InlineQueue
from app.ocr.base import OcrProvider
from app.ocr.provider import get_ocr_provider
from app.services import prescriptions as service
from app.services.prescriptions import JobQueue
from app.services.storage import StorageService, get_storage

router = APIRouter()


class PrescriptionItemOut(BaseModel):
    id: str
    medication_name: str
    dosage: str | None
    frequency: str | None
    instructions: str | None
    confidence: float
    verified: bool


class PrescriptionOut(BaseModel):
    id: str
    household_member_id: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    ocr_status: str
    ocr_error: str | None
    verified: bool
    items: list[PrescriptionItemOut]


def engine_dep() -> Engine:
    return get_engine()


def storage_dep() -> StorageService:
    return get_storage()


def ocr_provider_dep() -> OcrProvider:
    return get_ocr_provider()


def queue_dep(
    engine: Engine = Depends(engine_dep),
    storage: StorageService = Depends(storage_dep),
    provider: OcrProvider = Depends(ocr_provider_dep),
) -> JobQueue:
    return InlineQueue(
        session_factory=lambda: Session(engine),
        storage=storage,
        provider=provider,
    )


def _to_out(session: Session, prescription: Prescription) -> PrescriptionOut:
    items = session.exec(
        select(PrescriptionItem).where(PrescriptionItem.prescription_id == prescription.id)
    ).all()
    return PrescriptionOut(
        id=prescription.id,
        household_member_id=prescription.household_member_id,
        original_filename=prescription.original_filename,
        mime_type=prescription.mime_type,
        file_size_bytes=prescription.file_size_bytes,
        ocr_status=prescription.ocr_status,
        ocr_error=prescription.ocr_error,
        verified=prescription.verified,
        items=[
            PrescriptionItemOut(
                id=i.id,
                medication_name=i.medication_name,
                dosage=i.dosage,
                frequency=i.frequency,
                instructions=i.instructions,
                confidence=i.confidence,
                verified=i.verified,
            )
            for i in items
        ],
    )


@router.post("/prescriptions/upload", response_model=PrescriptionOut, status_code=201)
async def upload_prescription(
    household_member_id: str,
    file: UploadFile = File(...),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
    storage: StorageService = Depends(storage_dep),
    queue: JobQueue = Depends(queue_dep),
) -> PrescriptionOut:
    # Read one byte past the limit so the service can reject oversize files without loading more.
    data = await file.read(service.MAX_UPLOAD_BYTES + 1)
    prescription = service.upload_prescription(
        session,
        storage=storage,
        queue=queue,
        user_id=user_id,
        household_member_id=household_member_id,
        data=data,
        mime_type=file.content_type or "",
        filename=file.filename or "",
    )
    session.refresh(prescription)
    return _to_out(session, prescription)


@router.get("/prescriptions/{prescription_id}", response_model=PrescriptionOut)
def get_prescription(
    prescription_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> PrescriptionOut:
    prescription = session.get(Prescription, prescription_id)
    if prescription is None:
        raise service.PrescriptionError("Prescription not found", status_code=404)
    authorize_member(session, user_id, prescription.household_member_id)
    return _to_out(session, prescription)
