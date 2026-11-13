"""Turn trigger rules into Notification rows, choosing recipients by escalation level.

- INFO / ACTION  -> the primary caregiver (the household creator)
- CRITICAL       -> the primary caregiver plus any EmergencyContact for this member

Dedupe: each notification carries a dedupe_key of (rule, medication, subject). A
repeated run on the same evidence will not create a second row, so an hourly job
cannot spam the caregiver.

Sending is a stub: rows are stored, not delivered. The delivery layer is a later phase.
"""

from sqlmodel import Session, select

from app.db.models import Case, Conflict, EmergencyContact, Event, Household, HouseholdMember, Medication, Notification
from app.consent.service import authorize_member
from app.engines.state import compute_state
from app.engines.triggers import (
    Escalation,
    Trigger,
    check_expiry,
    check_refill,
    conflict_trigger,
    expired_stock_trigger,
    triggers_for_event,
)
from app.events import store as events
from app.services.reconciliation import CaseError, detect_and_open_cases
from app.services.reasons import detect_repeated_reasons


def _primary_caregiver(session: Session, household_member_id: str) -> str | None:
    member = session.get(HouseholdMember, household_member_id)
    if member is None:
        return None
    household = session.get(Household, member.household_id)
    return household.created_by if household else None


def _recipients(session: Session, household_member_id: str, level: Escalation) -> set[str]:
    recipients: set[str] = set()
    primary = _primary_caregiver(session, household_member_id)
    if primary:
        recipients.add(primary)
    if level == Escalation.CRITICAL:
        contacts = session.exec(
            select(EmergencyContact).where(
                EmergencyContact.household_member_id == household_member_id
            )
        ).all()
        recipients.update(c.user_id for c in contacts)
    return recipients


def _write(
    session: Session,
    *,
    household_member_id: str,
    level: Escalation,
    trigger: Trigger,
    dedupe_subject: str,
) -> list[Notification]:
    created: list[Notification] = []
    for user_id in _recipients(session, household_member_id, level):
        dedupe_key = f"{trigger.rule}:{household_member_id}:{dedupe_subject}:{user_id}"
        existing = session.exec(
            select(Notification).where(Notification.dedupe_key == dedupe_key)
        ).first()
        if existing is not None:
            continue
        note = Notification(
            user_id=user_id,
            title=f"[{level.name}] {trigger.rule.replace('_', ' ').title()}",
            body=trigger.message,
            rule=trigger.rule,
            dedupe_key=dedupe_key,
        )
        session.add(note)
        created.append(note)
    return created


def notify_for_event(session: Session, event: Event) -> list[Notification]:
    """Event-driven notifications. For evidence events this also re-runs reconciliation."""
    med = session.get(Medication, event.medication_id) if event.medication_id else None
    member_id = event.household_member_id
    created: list[Notification] = []

    for trigger in triggers_for_event(event.event_type):
        created += _write(
            session,
            household_member_id=member_id,
            level=trigger.level,
            trigger=trigger,
            dedupe_subject=event.event_type,
        )

    if med is None:
        session.commit()
        return created

    if event.event_type in ("MedicationReported", "AvailabilityObserved", "MedicationConfirmed"):
        # Reconciliation opens any new cases; each new case is worth telling the caregiver about.
        user_id = event.created_by or _primary_caregiver(session, member_id) or ""
        if user_id:
            opened = detect_and_open_cases(session, user_id=user_id, medication_id=med.id)

            for case in opened:
                trigger_event = session.get(Event, case.trigger_event_id)
                payload = events.decode_payload(trigger_event) if trigger_event else {}
                if payload.get("conflict_type") == "EXPIRED_STOCK":
                    # Expired stock is CRITICAL, so it escalates beyond the primary
                    # caregiver and uses its own rule name rather than the generic notice.
                    expiry = check_expiry(
                        compute_state(med.id, list(events.events_for_medication(session, med.id)))
                    )
                    if expiry is not None:
                        created += _write(
                            session,
                            household_member_id=member_id,
                            level=Escalation.CRITICAL,
                            trigger=expired_stock_trigger(
                                med.name_generic or med.name_raw, expiry.expiry_date
                            ),
                            dedupe_subject=expiry.expiry_date.isoformat(),
                        )
                    continue

                created += _write(
                    session,
                    household_member_id=member_id,
                    level=Escalation.ACTION,
                    trigger=conflict_trigger(
                        med.name_generic or med.name_raw,
                        payload.get("conflict_type", "EVIDENCE_CONFLICT"),
                        payload.get("description", "Evidence conflict detected"),
                    ),
                    dedupe_subject=case.id,
                )

    if event.event_type == "ReasonRecorded":
        user_id = event.created_by or _primary_caregiver(session, member_id) or ""
        if user_id:
            for repeated in detect_repeated_reasons(session, user_id=user_id, medication_id=med.id):
                created += _write(
                    session,
                    household_member_id=member_id,
                    level=Escalation.ACTION,
                    trigger=Trigger(
                        rule="REPEATED_REASON_PATTERN",
                        message=repeated.message,
                        level=Escalation.ACTION,
                    ),
                    dedupe_subject=repeated.reason_code.value,
                )

    session.commit()
    return created


def run_periodic_checks(session: Session, *, user_id: str, medication_id: str) -> list[Notification]:
    """Refill-window and expiry checks. Safe to run repeatedly; duplicates are suppressed."""
    med = session.get(Medication, medication_id)
    if med is None:
        raise CaseError("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)

    state = compute_state(med.id, list(events.events_for_medication(session, med.id)))
    member_id = med.household_member_id
    name = med.name_generic or med.name_raw
    created: list[Notification] = []

    refill = check_refill(state)
    if refill is not None:
        created += _write(
            session,
            household_member_id=member_id,
            level=refill.level,
            trigger=Trigger(rule=refill.rule, message=f"{name}: {refill.message}", level=refill.level),
            dedupe_subject=refill.last_verified.isoformat() if refill.last_verified else "unknown",
        )

    expiry = check_expiry(state)
    if expiry is not None and not expiry.expired:
        # A medicine nearing expiry is a heads-up, not a tracked problem.
        created += _write(
            session,
            household_member_id=member_id,
            level=expiry.level,
            trigger=Trigger(rule=expiry.rule, message=f"{name}: {expiry.message}", level=expiry.level),
            dedupe_subject=expiry.expiry_date.isoformat(),
        )

    if expiry is not None and expiry.expired:
        # Expired stock is a tracked case, not just a notification. Open it if it is not
        # already open, then notify only when no case exists — checked against the
        # database, not against what this call happened to open, so a case opened
        # earlier (for example by the availability write) is not announced twice.
        detect_and_open_cases(session, user_id=user_id, medication_id=med.id)
        if not _has_open_expiry_case(session, med.id):
            created += _write(
                session,
                household_member_id=member_id,
                level=expiry.level,
                trigger=expired_stock_trigger(name, expiry.expiry_date),
                dedupe_subject=expiry.expiry_date.isoformat(),
            )

    session.commit()
    return created


def _has_open_expiry_case(session: Session, medication_id: str) -> bool:
    """True when an unresolved EXPIRED_STOCK case already exists for this medication."""
    rows = session.exec(
        select(Conflict).where(
            Conflict.medication_id == medication_id,
            Conflict.type == "EXPIRED_STOCK",
            Conflict.status == "OPEN",
        )
    ).all()
    for conflict in rows:
        case = session.exec(
            select(Case).where(Case.trigger_event_id == conflict.trigger_event_id)
        ).first()
        if case is not None and case.status in ("OPEN", "AWAITING_INFO"):
            return True
    return False


def list_notifications(session: Session, *, user_id: str) -> list[Notification]:
    return list(
        session.exec(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())  # type: ignore[union-attr]
        ).all()
    )


def mark_read(session: Session, *, user_id: str, notification_id: str) -> Notification:
    note = session.get(Notification, notification_id)
    if note is None or note.user_id != user_id:
        raise CaseError("Notification not found", status_code=404)
    note.is_read = True
    session.add(note)
    session.commit()
    return note
