"""Households and patients. Creating either writes an audit record in the same transaction."""

from sqlmodel import Session, select

from app.audit import service as audit
from app.consent.service import AccessDenied, authorize_patient, record_consent
from app.db.models import CaregiverAccess, Household, HouseholdMember, Patient


def create_household_with_patient(
    session: Session,
    *,
    user_id: str,
    household_name: str,
    patient_display_name: str,
    relationship: str | None,
    consent_recorded: bool,
) -> tuple[Household, HouseholdMember, Patient]:
    household = Household(name=household_name, created_by=user_id)
    session.add(household)
    session.flush()

    member = HouseholdMember(
        household_id=household.id,
        display_name=patient_display_name,
        relationship=relationship,
        is_patient=True,
    )
    session.add(member)
    session.flush()

    patient = Patient(household_member_id=member.id)
    session.add(patient)

    access = CaregiverAccess(
        caregiver_user_id=user_id,
        household_member_id=member.id,
        consent_recorded=False,
    )
    session.add(access)
    session.flush()

    if consent_recorded:
        record_consent(session, caregiver_access_id=access.id, consent_method="in_app")

    audit.log(
        session,
        audit.AuditAction.HOUSEHOLD_CREATED,
        user_id=user_id,
        details={"household_id": household.id, "member_id": member.id},
    )
    session.commit()
    return household, member, patient


def add_patient(
    session: Session,
    *,
    user_id: str,
    household_id: str,
    display_name: str,
    relationship: str | None,
) -> tuple[HouseholdMember, Patient]:
    household = session.get(Household, household_id)
    if household is None:
        raise AccessDenied("Household not found", status_code=404)

    is_member = session.exec(
        select(HouseholdMember).where(
            HouseholdMember.household_id == household_id,
            HouseholdMember.user_id == user_id,
        )
    ).first()
    if is_member is None and household.created_by != user_id:
        raise AccessDenied("Not a member of this household")

    member = HouseholdMember(
        household_id=household_id,
        display_name=display_name,
        relationship=relationship,
        is_patient=True,
    )
    session.add(member)
    session.flush()

    patient = Patient(household_member_id=member.id)
    session.add(patient)

    # The creator of the patient gets an access row, but consent is still
    # recorded separately, never assumed.
    session.add(
        CaregiverAccess(
            caregiver_user_id=user_id,
            household_member_id=member.id,
            consent_recorded=False,
        )
    )
    audit.log(
        session,
        audit.AuditAction.PATIENT_CREATED,
        user_id=user_id,
        details={"member_id": member.id, "household_id": household_id},
    )
    session.commit()
    return member, patient


def update_patient(
    session: Session,
    *,
    user_id: str,
    patient_id: str,
    display_name: str | None = None,
    relationship: str | None = None,
) -> HouseholdMember:
    patient = authorize_patient(session, user_id, patient_id)
    member = session.get(HouseholdMember, patient.household_member_id)
    if member is None:
        raise AccessDenied("Patient not found", status_code=404)
    if display_name is not None:
        member.display_name = display_name
    if relationship is not None:
        member.relationship = relationship
    session.add(member)
    session.commit()
    return member
