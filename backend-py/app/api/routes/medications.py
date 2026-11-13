from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.db.models import Medication
from app.services import medications as med_service
from app.services import prescriptions as rx_service
from app.services.normalization import NormalizationInput, normalize_medication

router = APIRouter()


class MedicationOut(BaseModel):
    id: str
    household_member_id: str
    name_raw: str
    name_generic: str | None
    name_brand: str | None
    strength: str | None
    dosage_form: str | None
    frequency: str | None
    normalization_status: str
    normalization_method: str | None
    normalization_confidence: float | None
    identity_confirmed: bool


class VerifiedItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    medication_name: str = Field(min_length=1, max_length=200)
    dosage: str | None = Field(default=None, max_length=60)
    frequency: str | None = Field(default=None, max_length=60)
    instructions: str | None = Field(default=None, max_length=500)


class VerifyPrescriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[VerifiedItemIn] = Field(min_length=1, max_length=50)


class MedicationResultOut(BaseModel):
    item_id: str
    medication_id: str
    action: str
    normalization_status: str
    name_generic: str | None


class VerifyPrescriptionOut(BaseModel):
    prescription_id: str
    medication_results: list[MedicationResultOut]


class VerifyNormalizationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_generic: str = Field(min_length=1, max_length=120)
    name_brand: str | None = Field(default=None, max_length=120)
    strength: str | None = Field(default=None, max_length=40)
    dosage_form: str | None = Field(default=None, max_length=60)


class NormalizePreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_raw: str = Field(min_length=1, max_length=200)
    dosage: str | None = Field(default=None, max_length=60)
    frequency: str | None = Field(default=None, max_length=60)


class NormalizationOut(BaseModel):
    name_generic: str | None
    name_brand: str | None
    strength: str | None
    dosage_form: str | None
    frequency: str | None
    method: str
    confidence: float
    status: str


def _med_out(m: Medication) -> MedicationOut:
    return MedicationOut(
        id=m.id,
        household_member_id=m.household_member_id,
        name_raw=m.name_raw,
        name_generic=m.name_generic,
        name_brand=m.name_brand,
        strength=m.strength,
        dosage_form=m.dosage_form,
        frequency=m.frequency,
        normalization_status=m.normalization_status,
        normalization_method=m.normalization_method,
        normalization_confidence=m.normalization_confidence,
        identity_confirmed=m.identity_confirmed,
    )


@router.post(
    "/prescriptions/{prescription_id}/verify",
    response_model=VerifyPrescriptionOut,
)
def verify_prescription(
    prescription_id: str,
    body: VerifyPrescriptionIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> VerifyPrescriptionOut:
    outcomes = rx_service.verify_prescription(
        session,
        user_id=user_id,
        prescription_id=prescription_id,
        items=[
            rx_service.VerifiedItemInput(
                item_id=i.item_id,
                medication_name=i.medication_name,
                dosage=i.dosage,
                frequency=i.frequency,
                instructions=i.instructions,
            )
            for i in body.items
        ],
    )
    return VerifyPrescriptionOut(
        prescription_id=prescription_id,
        medication_results=[
            MedicationResultOut(
                item_id=body.items[idx].item_id,
                medication_id=o.medication.id,
                action=o.action,
                normalization_status=o.normalization.status,
                name_generic=o.normalization.name_generic,
            )
            for idx, o in enumerate(outcomes)
        ],
    )


@router.get("/medications", response_model=list[MedicationOut])
def list_medications(
    household_member_id: str = Query(...),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[MedicationOut]:
    meds = med_service.list_for_member(
        session, user_id=user_id, household_member_id=household_member_id
    )
    return [_med_out(m) for m in meds]


@router.get("/medications/needs-review", response_model=list[MedicationOut])
def needs_review(
    household_member_id: str = Query(...),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[MedicationOut]:
    meds = med_service.list_needing_review(
        session, user_id=user_id, household_member_id=household_member_id
    )
    return [_med_out(m) for m in meds]


@router.post("/medications/{medication_id}/verify-normalization", response_model=MedicationOut)
def verify_normalization(
    medication_id: str,
    body: VerifyNormalizationIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> MedicationOut:
    med = med_service.verify_normalization(
        session,
        user_id=user_id,
        medication_id=medication_id,
        name_generic=body.name_generic,
        name_brand=body.name_brand,
        strength=body.strength,
        dosage_form=body.dosage_form,
    )
    return _med_out(med)


@router.post("/medications/normalize-preview", response_model=NormalizationOut)
def normalize_preview(
    body: NormalizePreviewIn,
    user_id: str = CurrentUserDep,
) -> NormalizationOut:
    """Returns what normalization would produce, without saving anything."""
    result = normalize_medication(
        NormalizationInput(name_raw=body.name_raw, dosage=body.dosage, frequency=body.frequency)
    )
    return NormalizationOut(
        name_generic=result.name_generic,
        name_brand=result.name_brand,
        strength=result.strength,
        dosage_form=result.dosage_form,
        frequency=result.frequency,
        method=result.method,
        confidence=result.confidence,
        status=result.status,
    )
