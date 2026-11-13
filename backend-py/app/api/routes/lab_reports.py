from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import CurrentUserDep, SessionDep
from app.db.models import LabValue
from app.ocr.base import LabOcrProvider
from app.ocr.provider import get_lab_ocr_provider
from app.services import lab_reports as service
from app.services.storage import StorageService, get_storage

router = APIRouter()


class LabValueOut(BaseModel):
    test_name: str
    value: str
    unit: str | None
    reference_range_raw: str | None


class LabReportOut(BaseModel):
    id: str
    household_member_id: str
    original_filename: str
    ocr_status: str
    ocr_error: str | None
    captured_on: str | None
    lab_name: str | None
    values: list[LabValueOut]


class AdherenceWindowOut(BaseModel):
    medication_name: str
    days_covered: int
    taking_reports: int
    not_taking_reports: int
    reported_adhered_percent: int | None
    basis: str


class LabFindingOut(BaseModel):
    test_name: str
    value: str
    unit: str | None
    reference_range_raw: str | None
    captured_on: str | None
    adherence_before: list[AdherenceWindowOut]


def storage_dep() -> StorageService:
    return get_storage()


def lab_provider_dep() -> LabOcrProvider:
    return get_lab_ocr_provider()


@router.post("/lab-reports/upload", response_model=LabReportOut, status_code=201)
async def upload(
    household_member_id: str,
    file: UploadFile = File(...),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
    storage: StorageService = Depends(storage_dep),
    provider: LabOcrProvider = Depends(lab_provider_dep),
) -> LabReportOut:
    data = await file.read(service.MAX_UPLOAD_BYTES + 1)
    report = service.upload_lab_report(
        session,
        storage=storage,
        user_id=user_id,
        household_member_id=household_member_id,
        data=data,
        mime_type=file.content_type or "",
        filename=file.filename or "",
    )
    # Inline processing, matching the prescription path in dev/test.
    report = service.process_lab_report(
        session, storage=storage, provider=provider, lab_report_id=report.id
    )
    values = session.exec(select(LabValue).where(LabValue.lab_report_id == report.id)).all()
    return LabReportOut(
        id=report.id,
        household_member_id=report.household_member_id,
        original_filename=report.original_filename,
        ocr_status=report.ocr_status,
        ocr_error=report.ocr_error,
        captured_on=report.captured_on,
        lab_name=report.lab_name,
        values=[
            LabValueOut(
                test_name=v.test_name,
                value=v.value,
                unit=v.unit,
                reference_range_raw=v.reference_range_raw,
            )
            for v in values
        ],
    )


@router.get("/households/{household_member_id}/lab-correlation", response_model=list[LabFindingOut])
def correlation(
    household_member_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[LabFindingOut]:
    findings = service.correlate(session, user_id=user_id, household_member_id=household_member_id)
    return [
        LabFindingOut(
            test_name=f.test_name,
            value=f.value,
            unit=f.unit,
            reference_range_raw=f.reference_range_raw,
            captured_on=f.captured_on,
            adherence_before=[
                AdherenceWindowOut(
                    medication_name=w.medication_name,
                    days_covered=w.days_covered,
                    taking_reports=w.taking_reports,
                    not_taking_reports=w.not_taking_reports,
                    reported_adhered_percent=w.reported_adhered_percent,
                    basis=w.basis,
                )
                for w in f.adherence_before
            ],
        )
        for f in findings
    ]
