"""Evidence capture: a caregiver or patient records what they observed about a medication.

Each function:
  1. resolves the medication and checks the caller may act on its household member,
  2. appends one typed event (validated by the event store),
  3. returns the event for the route to hand back.

No function here decides whether something is a conflict. That is the reconciliation
engine's job (step 7), which reads the events written here.
"""

from datetime import datetime
from typing import Literal

from sqlmodel import Session

from app.audit import service as audit
from app.consent.service import authorize_member
from app.db.models import Event, Medication
from app.events import store as events
from app.events.payloads import (
    AvailabilityObservedPayload,
    DoseChangedPayload,
    MedicationConfirmedPayload,
    MedicationReportedPayload,
)
from app.events.types import EventType, ReasonCode, Source


class EvidenceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _load_medication(session: Session, user_id: str, medication_id: str) -> Medication:
    med = session.get(Medication, medication_id)
    if med is None:
        raise EvidenceError("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)
    return med


def _source_for(role: str) -> Source:
    # Source reflects who is speaking. The role comes from the authenticated user, never the request body.
    return Source.PATIENT if role == "patient" else Source.CAREGIVER


def _run_triggers(session: Session, event: Event) -> None:
    """Evaluate trigger rules after an evidence write. Imported here to avoid a cycle
    (triggers import the reconciliation service, which imports evidence errors)."""
    from app.services.triggers import notify_for_event

    notify_for_event(session, event)


def report_taking(
    session: Session,
    *,
    user_id: str,
    role: str,
    medication_id: str,
    taking: bool,
    reason: ReasonCode | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
    voice: bool = False,
) -> Event:
    med = _load_medication(session, user_id, medication_id)
    event = events.append_event(
        session,
        event_type=EventType.MEDICATION_REPORTED,
        payload=MedicationReportedPayload(
            medication_id=med.id, taking=taking, reason=reason, note=note
        ),
        source=Source.VOICE if voice else _source_for(role),
        medication_id=med.id,
        source_user_id=user_id,
        created_by=user_id,
        idempotency_key=idempotency_key,
    )
    audit.log(
        session,
        audit.AuditAction.EVIDENCE_REPORTED,
        user_id=user_id,
        details={"medication_id": med.id, "taking": taking, "source": "voice" if voice else _source_for(role).value},
    )
    session.commit()
    _run_triggers(session, event)
    return event


def record_availability(
    session: Session,
    *,
    user_id: str,
    medication_id: str,
    present: bool,
    quantity_note: Literal["ok", "low", "nearly empty"] | None = None,
    expiry_date: datetime | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> Event:
    med = _load_medication(session, user_id, medication_id)
    event = events.append_event(
        session,
        event_type=EventType.AVAILABILITY_OBSERVED,
        payload=AvailabilityObservedPayload(
            medication_id=med.id,
            present=present,
            quantity_note=quantity_note,
            expiry_date=expiry_date,
            note=note,
        ),
        source=Source.CAREGIVER,
        medication_id=med.id,
        source_user_id=user_id,
        created_by=user_id,
        idempotency_key=idempotency_key,
    )
    audit.log(
        session,
        audit.AuditAction.EVIDENCE_AVAILABILITY_RECORDED,
        user_id=user_id,
        details={"medication_id": med.id, "present": present},
    )
    session.commit()
    _run_triggers(session, event)
    return event


def confirm_status(
    session: Session,
    *,
    user_id: str,
    role: str,
    medication_id: str,
    status: Literal["CONFIRMED", "DISCONTINUED", "UNCERTAIN"],
    confirmation_method: str,
    idempotency_key: str | None = None,
) -> Event:
    med = _load_medication(session, user_id, medication_id)
    event = events.append_event(
        session,
        event_type=EventType.MEDICATION_CONFIRMED,
        payload=MedicationConfirmedPayload(
            medication_id=med.id, status=status, confirmation_method=confirmation_method
        ),
        source=_source_for(role),
        medication_id=med.id,
        source_user_id=user_id,
        created_by=user_id,
        idempotency_key=idempotency_key,
    )
    audit.log(
        session,
        audit.AuditAction.EVIDENCE_STATUS_CONFIRMED,
        user_id=user_id,
        details={"medication_id": med.id, "status": status},
    )
    session.commit()
    _run_triggers(session, event)
    return event


def record_dose_change(
    session: Session,
    *,
    user_id: str,
    role: str,
    medication_id: str,
    new_dose: str,
    changed_by: str,
    previous_dose: str | None = None,
) -> Event:
    """Record a dose change. Reconciliation then re-runs, since a new dose can invalidate
    an earlier 'taking' report."""
    med = _load_medication(session, user_id, medication_id)
    event = events.append_event(
        session,
        event_type=EventType.DOSE_CHANGED,
        payload=DoseChangedPayload(
            medication_id=med.id,
            new_dose=new_dose,
            previous_dose=previous_dose,
            changed_by=changed_by,
        ),
        source=_source_for(role),
        medication_id=med.id,
        source_user_id=user_id,
        created_by=user_id,
    )
    audit.log(
        session,
        audit.AuditAction.DOSE_CHANGED,
        user_id=user_id,
        details={"medication_id": med.id, "new_dose": new_dose, "changed_by": changed_by},
    )
    session.commit()
    _run_triggers(session, event)
    return event


def history(session: Session, *, user_id: str, medication_id: str) -> list[Event]:
    med = _load_medication(session, user_id, medication_id)
    return list(events.events_for_medication(session, med.id))


def medicines_for_member(session: Session, *, user_id: str, household_member_id: str) -> list[Medication]:
    """The patient's medicines, for anything that must match against them.

    Voice reports use this: a transcript is matched to a real medicine rather than to
    free text, so the recorded report always points at one record.
    """
    from sqlmodel import select

    authorize_member(session, user_id, household_member_id)
    return list(
        session.exec(
            select(Medication).where(Medication.household_member_id == household_member_id)
        ).all()
    )
