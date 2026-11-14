"""Reconciliation: detect conflicts for a medication and track the cases they open.

detect_and_open_cases:
  - folds the medication's events into state,
  - runs the conflict rules,
  - for each conflict type not already open, writes a Conflict row, a ConflictDetected
    event, and an OPEN case linked to that event.
  Running it twice on the same evidence opens nothing new (no duplicate cases).

assign_action / resolve_case move an existing case through its lifecycle, writing an
event for each change. Invalid transitions are rejected with a clear error.
"""

from datetime import UTC, datetime

from sqlmodel import Session, select

from app.audit import service as audit
from app.consent.service import authorize_member
from app.db.models import Case, Conflict, Event, Medication
from app.engines.cases import OPEN_STATUSES, InvalidTransition, require_transition
from app.engines.conflicts import DetectedConflict, DetectionResult, detect
from app.engines.state import compute_state
from app.events import store as events
from app.events.payloads import (
    ActionAssignedPayload,
    CaseResolvedPayload,
    ConflictDetectedPayload,
)
from app.events.types import CaseStatus, EventType, Source


class CaseError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _load_medication(session: Session, user_id: str, medication_id: str) -> Medication:
    med = session.get(Medication, medication_id)
    if med is None:
        raise CaseError("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)
    return med


def _open_conflict_types(session: Session, medication_id: str) -> set[str]:
    rows = session.exec(
        select(Case).where(
            Case.medication_id == medication_id,
            Case.status.in_([s.value for s in OPEN_STATUSES]),  # type: ignore[attr-defined]
        )
    ).all()
    open_types: set[str] = set()
    for case in rows:
        if case.trigger_event_id is None:
            continue
        trigger = session.get(Event, case.trigger_event_id)
        if trigger is not None and trigger.event_type == EventType.CONFLICT_DETECTED:
            open_types.add(events.decode_payload(trigger)["conflict_type"])
    return open_types


def detect_and_open_cases(session: Session, *, user_id: str, medication_id: str) -> list[Case]:
    med = _load_medication(session, user_id, medication_id)
    state = compute_state(med.id, list(events.events_for_medication(session, med.id)))
    result = detect(state)
    return _open_new_cases(session, med, result, user_id)


def _open_new_cases(
    session: Session,
    med: Medication,
    result: DetectionResult,
    user_id: str | None,
) -> list[Case]:
    already_open = _open_conflict_types(session, med.id)
    opened: list[Case] = []
    for conflict in result.conflicts:
        if conflict.conflict_type in already_open:
            continue
        opened.append(_open_case_for(session, med.id, conflict, user_id))

    if opened:
        audit.log(
            session,
            audit.AuditAction.CONFLICT_DETECTED,
            user_id=user_id,
            details={"medication_id": med.id, "opened": len(opened)},
        )
    session.commit()
    return opened


def _open_case_for(
    session: Session, medication_id: str, conflict: DetectedConflict, user_id: str | None
) -> Case:
    description = conflict.description
    event = events.append_event(
        session,
        event_type=EventType.CONFLICT_DETECTED,
        payload=ConflictDetectedPayload(
            medication_id=medication_id,
            conflict_type=conflict.conflict_type,
            description=description,
            dimensions_involved=list(conflict.dimensions_involved),
        ),
        source=Source.SYSTEM,
        medication_id=medication_id,
        source_user_id=user_id,
    )
    session.add(
        Conflict(
            medication_id=medication_id,
            trigger_event_id=event.id,
            type=conflict.conflict_type,
            description=description,
            dimensions_involved=",".join(d.value for d in conflict.dimensions_involved),
            suggested_question=conflict.suggested_question,
            status="OPEN",
        )
    )
    case = Case(
        medication_id=medication_id,
        trigger_event_id=event.id,
        status=CaseStatus.OPEN.value,
    )
    session.add(case)
    session.flush()
    return case


def _load_case(session: Session, user_id: str, case_id: str) -> tuple[Case, Medication]:
    case = session.get(Case, case_id)
    if case is None:
        raise CaseError("Case not found", status_code=404)
    med = _load_medication(session, user_id, case.medication_id)
    return case, med


def assign_action(
    session: Session,
    *,
    user_id: str,
    case_id: str,
    action_description: str,
    assigned_to_user_id: str | None = None,
) -> Case:
    case, med = _load_case(session, user_id, case_id)
    current = CaseStatus(case.status)
    if current == CaseStatus.RESOLVED:
        raise CaseError("A resolved case cannot take new actions.", status_code=409)

    events.append_event(
        session,
        event_type=EventType.ACTION_ASSIGNED,
        payload=ActionAssignedPayload(
            medication_id=med.id,
            case_id=case.id,
            action_description=action_description,
            assigned_to_user_id=assigned_to_user_id,
        ),
        source=Source.CAREGIVER,
        medication_id=med.id,
        source_user_id=user_id,
        created_by=user_id,
    )
    case.action_taken = action_description
    if current == CaseStatus.OPEN:
        case.status = CaseStatus.AWAITING_INFO.value
    session.add(case)
    session.commit()
    return case


def resolve_case(
    session: Session,
    *,
    user_id: str,
    case_id: str,
    outcome: CaseStatus,
    resolution_note: str | None = None,
) -> Case:
    if outcome not in (CaseStatus.RESOLVED, CaseStatus.STILL_UNCERTAIN):
        raise CaseError("Outcome must be RESOLVED or STILL_UNCERTAIN.")

    case, med = _load_case(session, user_id, case_id)
    try:
        require_transition(case.status, outcome)
    except InvalidTransition as exc:
        raise CaseError(str(exc), status_code=409) from exc

    events.append_event(
        session,
        event_type=EventType.CASE_RESOLVED,
        payload=CaseResolvedPayload(
            medication_id=med.id,
            case_id=case.id,
            resolution_note=resolution_note,
        ),
        source=Source.CAREGIVER,
        medication_id=med.id,
        source_user_id=user_id,
        created_by=user_id,
    )
    now = datetime.now(UTC)
    case.status = outcome.value
    case.resolution_note = resolution_note
    if outcome == CaseStatus.RESOLVED:
        case.resolved_at = now
        _close_triggering_conflict(session, case, now)
    session.add(case)
    audit.log(
        session,
        audit.AuditAction.CASE_RESOLVED,
        user_id=user_id,
        details={"case_id": case.id, "outcome": outcome.value},
    )
    session.commit()
    return case


def _close_triggering_conflict(session: Session, case: Case, now: datetime) -> None:
    """Mark the exact Conflict row that opened this case as resolved.

    Matching is by the triggering event, not by conflict type: a medication can have
    several conflicts of the same type over its lifetime, and resolving one must not
    close the others. A STILL_UNCERTAIN case deliberately leaves its conflict open.
    """
    if case.trigger_event_id is None:
        return

    row = session.exec(
        select(Conflict).where(Conflict.trigger_event_id == case.trigger_event_id)
    ).first()
    if row is None:
        return

    row.status = "RESOLVED"
    row.updated_at = now
    session.add(row)


def close_conflict_for_case(session: Session, case: Case, now: datetime | None = None) -> None:
    """Public wrapper used when a case is closed outside resolve_case (e.g. a reason)."""
    _close_triggering_conflict(session, case, now or datetime.now(UTC))


def open_cases_for_member(
    session: Session, *, user_id: str, household_member_id: str
) -> list[tuple[Case, str, str | None]]:
    """Open cases with the medicine name and a one-line issue, so a list is readable."""
    authorize_member(session, user_id, household_member_id)
    rows = session.exec(
        select(Case)
        .join(Medication, Case.medication_id == Medication.id)  # type: ignore[arg-type]
        .where(
            Medication.household_member_id == household_member_id,
            Case.status.in_([s.value for s in OPEN_STATUSES]),  # type: ignore[attr-defined]
        )
        .order_by(Case.opened_at.desc())  # type: ignore[union-attr]
    ).all()

    named: list[tuple[Case, str, str | None]] = []
    for case in rows:
        med = session.get(Medication, case.medication_id)
        label = (med.name_generic or med.name_raw) if med else "Unknown medicine"
        issue: str | None = None
        if case.trigger_event_id:
            trigger = session.get(Event, case.trigger_event_id)
            if trigger is not None:
                issue = events.decode_payload(trigger).get("description")
        named.append((case, label, issue))
    return named




