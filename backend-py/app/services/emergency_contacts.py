"""Emergency contacts: the people notified when something is CRITICAL.

Only the household creator may add or remove a contact. A contact must be a registered
user. Adding one does not grant access to the patient record: it only means they are
notified when a CRITICAL event happens.
"""

from sqlmodel import Session, select

from app.audit import service as audit
from app.db.models import EmergencyContact, Household, HouseholdMember, User
from app.services.reconciliation import CaseError


def _require_creator(session: Session, user_id: str, household_member_id: str) -> HouseholdMember:
    member = session.get(HouseholdMember, household_member_id)
    if member is None:
        raise CaseError("Household member not found", status_code=404)
    household = session.get(Household, member.household_id)
    if household is None or household.created_by != user_id:
        raise CaseError("Only the household creator can manage emergency contacts", status_code=403)
    return member


def add_contact(
    session: Session, *, user_id: str, household_member_id: str, contact_user_id: str, relationship: str | None
) -> EmergencyContact:
    _require_creator(session, user_id, household_member_id)

    contact_user = session.get(User, contact_user_id)
    if contact_user is None:
        raise CaseError("Contact must be a registered user", status_code=404)

    existing = session.exec(
        select(EmergencyContact).where(
            EmergencyContact.household_member_id == household_member_id,
            EmergencyContact.user_id == contact_user_id,
        )
    ).first()
    if existing is not None:
        return existing

    contact = EmergencyContact(
        household_member_id=household_member_id,
        user_id=contact_user_id,
        relationship=relationship,
    )
    session.add(contact)
    audit.log(
        session,
        audit.AuditAction.EMERGENCY_CONTACT_ADDED,
        user_id=user_id,
        details={"household_member_id": household_member_id, "contact_user_id": contact_user_id},
    )
    session.commit()
    return contact


def list_contacts(session: Session, *, user_id: str, household_member_id: str) -> list[EmergencyContact]:
    _require_creator(session, user_id, household_member_id)
    return list(
        session.exec(
            select(EmergencyContact).where(EmergencyContact.household_member_id == household_member_id)
        ).all()
    )


def remove_contact(session: Session, *, user_id: str, household_member_id: str, contact_id: str) -> None:
    _require_creator(session, user_id, household_member_id)
    contact = session.get(EmergencyContact, contact_id)
    if contact is None or contact.household_member_id != household_member_id:
        raise CaseError("Emergency contact not found", status_code=404)

    audit.log(
        session,
        audit.AuditAction.EMERGENCY_CONTACT_REMOVED,
        user_id=user_id,
        details={"household_member_id": household_member_id, "contact_user_id": contact.user_id},
    )
    session.delete(contact)
    session.commit()
