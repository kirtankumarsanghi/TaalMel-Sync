"""Caregiver access and consent.

Rules:
- A user may act on a household member only if they are (a) the member's own
  linked user, (b) the household creator, or (c) a caregiver with a
  CaregiverAccess row.
- Caregiver (c) additionally needs an active (non-revoked) Consent record.
  Consent is never assumed. Revoking consent blocks access immediately.
- Self-access (a) does not need consent.
"""

from datetime import UTC, datetime

from sqlmodel import Session, select

from app.audit import service as audit
from app.db.models import CaregiverAccess, Consent, Household, HouseholdMember, Patient


class AccessDenied(Exception):
    def __init__(self, message: str, status_code: int = 403) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(UTC)


def get_access_row(session: Session, user_id: str, household_member_id: str) -> CaregiverAccess | None:
    return session.exec(
        select(CaregiverAccess).where(
            CaregiverAccess.caregiver_user_id == user_id,
            CaregiverAccess.household_member_id == household_member_id,
        )
    ).first()


def has_active_consent(session: Session, access: CaregiverAccess) -> bool:
    if access.expires_at is not None and _as_utc(access.expires_at) <= _now():
        # Temporary access has ended. It grants nothing, and nothing needs revoking.
        return False
    if not access.consent_recorded:
        return False
    consent = session.exec(
        select(Consent).where(Consent.caregiver_access_id == access.id)
    ).first()
    return consent is not None and consent.revoked_at is None


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def authorize_member(session: Session, user_id: str, household_member_id: str) -> HouseholdMember:
    """Return the member if the user may act on it, else raise AccessDenied."""
    member = session.get(HouseholdMember, household_member_id)
    if member is None:
        raise AccessDenied("Household member not found", status_code=404)

    if member.user_id == user_id:
        return member

    access = get_access_row(session, user_id, household_member_id)
    if access is None:
        raise AccessDenied("Not authorized for this patient")
    if not has_active_consent(session, access):
        raise AccessDenied("Consent not recorded or has been revoked")
    return member


def authorize_patient(session: Session, user_id: str, patient_id: str) -> Patient:
    patient = session.get(Patient, patient_id)
    if patient is None:
        raise AccessDenied("Patient not found", status_code=404)
    authorize_member(session, user_id, patient.household_member_id)
    return patient


def grant_access(
    session: Session,
    *,
    granting_user_id: str,
    caregiver_user_id: str,
    household_member_id: str,
    expires_at: datetime | None = None,
) -> CaregiverAccess:
    """Create a CaregiverAccess row (consent still starts unrecorded).

    `expires_at` supports temporary handoff: the visiting caregiver gets access for a
    defined period, and it stops working when that period ends, with no manual step.
    Only the household creator may grant.
    """
    member = session.get(HouseholdMember, household_member_id)
    if member is None:
        raise AccessDenied("Household member not found", status_code=404)
    household = session.get(Household, member.household_id)
    if household is None or household.created_by != granting_user_id:
        raise AccessDenied("Only the household creator can grant access")

    existing = get_access_row(session, caregiver_user_id, household_member_id)
    if existing is not None:
        return existing

    access = CaregiverAccess(
        caregiver_user_id=caregiver_user_id,
        household_member_id=household_member_id,
        consent_recorded=False,
        granted_at=_now(),
        expires_at=expires_at,
        updated_at=_now(),
    )
    session.add(access)
    session.flush()
    audit.log(
        session,
        audit.AuditAction.ACCESS_GRANTED,
        user_id=granting_user_id,
        details={"caregiver_user_id": caregiver_user_id, "household_member_id": household_member_id},
    )
    session.commit()
    return access


def record_consent_as_caregiver(
    session: Session,
    *,
    acting_user_id: str,
    caregiver_access_id: str,
    consent_type: str = "data_access",
    consent_method: str = "in_app",
) -> Consent:
    """Only the caregiver a consent applies to may record it. Consent is never recorded on their behalf."""
    access = session.get(CaregiverAccess, caregiver_access_id)
    if access is None:
        raise AccessDenied("Caregiver access record not found", status_code=404)
    if access.caregiver_user_id != acting_user_id:
        raise AccessDenied("Consent can only be recorded by the caregiver it applies to")

    record = record_consent(
        session,
        caregiver_access_id=caregiver_access_id,
        consent_type=consent_type,
        consent_method=consent_method,
    )
    audit.log(
        session,
        audit.AuditAction.CONSENT_RECORDED,
        user_id=acting_user_id,
        details={"caregiver_access_id": caregiver_access_id},
    )
    session.commit()
    return record


def revoke_consent_as_actor(
    session: Session, *, acting_user_id: str, caregiver_access_id: str
) -> None:
    """The caregiver or the household creator may revoke consent."""
    access = session.get(CaregiverAccess, caregiver_access_id)
    if access is None:
        raise AccessDenied("Caregiver access record not found", status_code=404)
    member = session.get(HouseholdMember, access.household_member_id)
    household = session.get(Household, member.household_id) if member else None
    allowed = {access.caregiver_user_id}
    if household is not None:
        allowed.add(household.created_by)
    if acting_user_id not in allowed:
        raise AccessDenied("Only the caregiver or household creator can revoke consent")

    revoke_consent(session, caregiver_access_id=caregiver_access_id)
    audit.log(
        session,
        audit.AuditAction.CONSENT_REVOKED,
        user_id=acting_user_id,
        details={"caregiver_access_id": caregiver_access_id},
    )
    session.commit()


def record_consent(
    session: Session,
    *,
    caregiver_access_id: str,
    consent_type: str = "data_access",
    consent_method: str = "in_app",
) -> Consent:
    access = session.get(CaregiverAccess, caregiver_access_id)
    if access is None:
        raise AccessDenied("Caregiver access record not found", status_code=404)

    now = _now()
    consent = session.exec(
        select(Consent).where(Consent.caregiver_access_id == caregiver_access_id)
    ).first()
    if consent is None:
        consent = Consent(
            caregiver_access_id=caregiver_access_id,
            consent_type=consent_type,
            consent_method=consent_method,
            recorded_at=now,
            updated_at=now,
        )
    else:
        consent.consent_type = consent_type
        consent.consent_method = consent_method
        consent.recorded_at = now
        consent.revoked_at = None
        consent.updated_at = now
    session.add(consent)

    access.consent_recorded = True
    access.updated_at = now
    session.add(access)
    session.flush()
    return consent


def revoke_consent(session: Session, *, caregiver_access_id: str) -> None:
    consent = session.exec(
        select(Consent).where(Consent.caregiver_access_id == caregiver_access_id)
    ).first()
    if consent is None:
        raise AccessDenied("Consent record not found", status_code=404)

    now = _now()
    consent.revoked_at = now
    consent.updated_at = now
    session.add(consent)

    access = session.get(CaregiverAccess, caregiver_access_id)
    if access is not None:
        access.consent_recorded = False
        access.updated_at = now
        session.add(access)
    session.flush()
