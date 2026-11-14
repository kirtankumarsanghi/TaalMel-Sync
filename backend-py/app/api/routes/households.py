from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.api.deps import CurrentUserDep, SessionDep
from app.consent import service as consent
from app.db.models import Household, HouseholdMember, Patient
from app.households import service as households
from app.services import emergency_contacts

router = APIRouter()


class CreateHouseholdIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    household_name: str = Field(min_length=1, max_length=120)
    patient_display_name: str = Field(min_length=1, max_length=120)
    relationship: str | None = Field(default=None, max_length=60)
    consent_recorded: bool = False


class AddPatientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=120)
    relationship: str | None = Field(default=None, max_length=60)


class UpdatePatientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    relationship: str | None = Field(default=None, max_length=60)


class GrantAccessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caregiver_user_id: str
    household_member_id: str
    # Temporary handoff: access stops working at this time with no manual revoke.
    expires_at: datetime | None = None


class RecordConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent_type: str = Field(default="data_access", max_length=40)
    consent_method: str = Field(default="in_app", max_length=40)


class EmergencyContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    relationship: str | None = Field(default=None, max_length=60)


class EmergencyContactOut(BaseModel):
    id: str
    user_id: str
    relationship: str | None


class HouseholdOut(BaseModel):
    id: str
    name: str


class PatientOut(BaseModel):
    patient_id: str
    household_member_id: str
    household_id: str
    display_name: str
    relationship: str | None


class CreatedHouseholdOut(BaseModel):
    household: HouseholdOut
    patient: PatientOut


class IdOut(BaseModel):
    id: str


def _patient_out(patient: Patient, member: HouseholdMember) -> PatientOut:
    return PatientOut(
        patient_id=patient.id,
        household_member_id=member.id,
        household_id=member.household_id,
        display_name=member.display_name,
        relationship=member.relationship,
    )


@router.post("/households", response_model=CreatedHouseholdOut, status_code=201)
def create_household(
    body: CreateHouseholdIn, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> CreatedHouseholdOut:
    household, member, patient = households.create_household_with_patient(
        session,
        user_id=user_id,
        household_name=body.household_name,
        patient_display_name=body.patient_display_name,
        relationship=body.relationship,
        consent_recorded=body.consent_recorded,
    )
    return CreatedHouseholdOut(
        household=HouseholdOut(id=household.id, name=household.name),
        patient=_patient_out(patient, member),
    )


@router.post("/households/{household_id}/patients", response_model=PatientOut, status_code=201)
def add_patient(
    household_id: str,
    body: AddPatientIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> PatientOut:
    member, patient = households.add_patient(
        session,
        user_id=user_id,
        household_id=household_id,
        display_name=body.display_name,
        relationship=body.relationship,
    )
    return _patient_out(patient, member)


@router.post("/households/{household_id}/members", response_model=PatientOut, status_code=201)
def add_member(
    household_id: str,
    body: AddPatientIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> PatientOut:
    """Compatibility alias for POST /households/{id}/patients."""
    return add_patient(household_id, body, user_id, session)


@router.post("/households/{household_id}/access", response_model=IdOut, status_code=201)
def grant_household_access(
    household_id: str,
    body: GrantAccessIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> IdOut:
    member = session.get(HouseholdMember, body.household_member_id)
    if member is None or member.household_id != household_id:
        raise consent.AccessDenied("Household member not found in this household", status_code=404)
    return grant_access(body, user_id, session)


@router.post(
    "/households/{household_id}/access/{caregiver_access_id}/consent",
    response_model=IdOut,
    status_code=201,
)
def record_household_consent(
    household_id: str,
    caregiver_access_id: str,
    body: RecordConsentIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> IdOut:
    return record_consent(caregiver_access_id, body, user_id, session)


@router.get("/patients/{patient_id}", response_model=PatientOut)
def get_patient(
    patient_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> PatientOut:
    patient = consent.authorize_patient(session, user_id, patient_id)
    member = session.get(HouseholdMember, patient.household_member_id)
    return _patient_out(patient, member)


@router.patch("/patients/{patient_id}", response_model=PatientOut)
def update_patient(
    patient_id: str,
    body: UpdatePatientIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> PatientOut:
    member = households.update_patient(
        session,
        user_id=user_id,
        patient_id=patient_id,
        display_name=body.display_name,
        relationship=body.relationship,
    )
    patient = consent.authorize_patient(session, user_id, patient_id)
    return _patient_out(patient, member)


@router.post("/access", response_model=IdOut, status_code=201)
def grant_access(
    body: GrantAccessIn, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> IdOut:
    access = consent.grant_access(
        session,
        granting_user_id=user_id,
        caregiver_user_id=body.caregiver_user_id,
        household_member_id=body.household_member_id,
        expires_at=body.expires_at,
    )
    return IdOut(id=access.id)


@router.post("/access/{caregiver_access_id}/consent", response_model=IdOut, status_code=201)
def record_consent(
    caregiver_access_id: str,
    body: RecordConsentIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> IdOut:
    record = consent.record_consent_as_caregiver(
        session,
        acting_user_id=user_id,
        caregiver_access_id=caregiver_access_id,
        consent_type=body.consent_type,
        consent_method=body.consent_method,
    )
    return IdOut(id=record.id)


@router.post("/access/{caregiver_access_id}/revoke", status_code=204)
def revoke_consent(
    caregiver_access_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> None:
    consent.revoke_consent_as_actor(
        session, acting_user_id=user_id, caregiver_access_id=caregiver_access_id
    )


class HouseholdDetailOut(BaseModel):
    id: str
    name: str
    members: list[PatientOut]


@router.get("/households/{household_id}", response_model=HouseholdDetailOut)
def get_household(
    household_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> HouseholdDetailOut:
    household = session.get(Household, household_id)
    if household is None:
        raise consent.AccessDenied("Household not found", status_code=404)

    members = session.exec(
        select(HouseholdMember).where(HouseholdMember.household_id == household_id)
    ).all()
    visible: list[PatientOut] = []
    for member in members:
        try:
            consent.authorize_member(session, user_id, member.id)
        except consent.AccessDenied:
            continue
        patient = session.exec(
            select(Patient).where(Patient.household_member_id == member.id)
        ).first()
        if patient is not None:
            visible.append(_patient_out(patient, member))

    if household.created_by != user_id and not visible:
        raise consent.AccessDenied("Not authorized for this household")
    return HouseholdDetailOut(id=household.id, name=household.name, members=visible)


@router.post("/households/{household_id}/temporary-access", response_model=IdOut, status_code=201)
def grant_temporary_access(
    household_id: str,
    body: GrantAccessIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> IdOut:
    if body.expires_at is None:
        raise consent.AccessDenied("expires_at is required for temporary access", status_code=400)
    member = session.get(HouseholdMember, body.household_member_id)
    if member is None or member.household_id != household_id:
        raise consent.AccessDenied("Household member not found in this household", status_code=404)
    access = consent.grant_access(
        session,
        granting_user_id=user_id,
        caregiver_user_id=body.caregiver_user_id,
        household_member_id=body.household_member_id,
        expires_at=body.expires_at,
    )
    return IdOut(id=access.id)


@router.delete("/households/{household_id}/temporary-access/{access_id}", status_code=204)
def revoke_temporary_access(
    household_id: str,
    access_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> None:
    consent.revoke_consent_as_actor(
        session, acting_user_id=user_id, caregiver_access_id=access_id
    )


@router.post(
    "/households/{household_member_id}/emergency-contacts",
    response_model=EmergencyContactOut,
    status_code=201,
)
def add_emergency_contact(
    household_member_id: str,
    body: EmergencyContactIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> EmergencyContactOut:
    contact = emergency_contacts.add_contact(
        session,
        user_id=user_id,
        household_member_id=household_member_id,
        contact_user_id=body.user_id,
        relationship=body.relationship,
    )
    return EmergencyContactOut(id=contact.id, user_id=contact.user_id, relationship=contact.relationship)


@router.get(
    "/households/{household_member_id}/emergency-contacts",
    response_model=list[EmergencyContactOut],
)
def list_emergency_contacts(
    household_member_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[EmergencyContactOut]:
    return [
        EmergencyContactOut(id=c.id, user_id=c.user_id, relationship=c.relationship)
        for c in emergency_contacts.list_contacts(
            session, user_id=user_id, household_member_id=household_member_id
        )
    ]


@router.delete(
    "/households/{household_member_id}/emergency-contacts/{contact_id}",
    status_code=204,
)
def remove_emergency_contact(
    household_member_id: str,
    contact_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> None:
    emergency_contacts.remove_contact(
        session,
        user_id=user_id,
        household_member_id=household_member_id,
        contact_id=contact_id,
    )
