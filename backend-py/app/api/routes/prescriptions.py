from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.api.deps import CurrentUserDep, SessionDep
from app.consent.service import authorize_member
from app.db.models import Prescription, PrescriptionItem
from app.config import get_settings
from app.db.session import get_engine
from app.jobs.queue import ArqQueue, InlineQueue
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
    prescribed_by: str | None = None
    prescribed_on: datetime | None = None
    ocr_status: str
    ocr_error: str | None
    ocr_raw_text: str | None = None
    verified: bool
    items: list[PrescriptionItemOut]


class PrescriptionDetailsIn(BaseModel):
    prescribed_by: str | None = None
    prescribed_on: datetime | None = None


class ManualItemIn(BaseModel):
    medication_name: str
    dosage: str | None = None
    frequency: str | None = None
    instructions: str | None = None


class ParseTextIn(BaseModel):
    text: str


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
    settings = get_settings()
    if settings.job_queue == "arq" or not settings.ocr_inline:
        return ArqQueue(settings.redis_url)
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
        prescribed_by=prescription.prescribed_by,
        prescribed_on=prescription.prescribed_on,
        ocr_status=prescription.ocr_status,
        ocr_error=prescription.ocr_error,
        ocr_raw_text=prescription.ocr_raw_text,
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
    prescribed_by: str | None = Form(default=None),
    prescribed_on: datetime | None = Form(default=None),
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
        prescribed_by=prescribed_by,
        prescribed_on=prescribed_on,
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


@router.post(
    "/prescriptions/{prescription_id}/items",
    response_model=PrescriptionItemOut,
    status_code=201,
)
def add_manual_item(
    prescription_id: str,
    body: ManualItemIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> PrescriptionItemOut:
    item = service.add_manual_item(
        session,
        user_id=user_id,
        prescription_id=prescription_id,
        medication_name=body.medication_name,
        dosage=body.dosage,
        frequency=body.frequency,
        instructions=body.instructions,
    )
    return PrescriptionItemOut(
        id=item.id,
        medication_name=item.medication_name,
        dosage=item.dosage,
        frequency=item.frequency,
        instructions=item.instructions,
        confidence=item.confidence,
        verified=item.verified,
    )


@router.post(
    "/prescriptions/{prescription_id}/parse-text",
    response_model=list[PrescriptionItemOut],
    status_code=201,
)
def parse_prescription_text(
    prescription_id: str,
    body: ParseTextIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[PrescriptionItemOut]:
    items = service.add_items_from_text(
        session,
        user_id=user_id,
        prescription_id=prescription_id,
        text=body.text,
    )
    return [
        PrescriptionItemOut(
            id=item.id,
            medication_name=item.medication_name,
            dosage=item.dosage,
            frequency=item.frequency,
            instructions=item.instructions,
            confidence=item.confidence,
            verified=item.verified,
        )
        for item in items
    ]


@router.patch("/prescriptions/{prescription_id}", response_model=PrescriptionOut)
def update_prescription(
    prescription_id: str,
    body: PrescriptionDetailsIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> PrescriptionOut:
    prescription = service.update_prescription_details(
        session,
        user_id=user_id,
        prescription_id=prescription_id,
        prescribed_by=body.prescribed_by,
        prescribed_on=body.prescribed_on,
    )
    return _to_out(session, prescription)


@router.get("/patients/{patient_id}/prescriptions", response_model=list[PrescriptionOut])
def list_patient_prescriptions(
    patient_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[PrescriptionOut]:
    from app.db.models import Patient

    patient = session.get(Patient, patient_id)
    member_id = patient.household_member_id if patient is not None else patient_id
    authorize_member(session, user_id, member_id)
    rows = session.exec(
        select(Prescription)
        .where(Prescription.household_member_id == member_id)
        .order_by(Prescription.created_at.desc())  # type: ignore[union-attr]
    ).all()
    return [_to_out(session, row) for row in rows]
