"""Record a reason against a case and carry out its policy.

record_reason:
  1. checks the case and the caller's access,
  2. appends a ReasonRecorded event and stores the code on the case,
  3. executes the policy action:
       OPEN_CASE_NOTIFY_CAREGIVER      -> a Notification row for the caregiver
       INCREASE_REMINDERS              -> a ReminderRequested event (reminder work reads it later)
       MARK_DISCONTINUED_CONFIRMED     -> a MedicationConfirmed(DISCONTINUED) event
       other actions                   -> returned to the caller; recorded on the event, no state change
  4. closes the case only where the policy says so and the effect has happened.

detect_repeated_reasons: flags a reason that appears REPEAT_THRESHOLD or more times for one medication.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.audit import service as audit
from app.consent.service import authorize_member, has_active_consent
from app.db.models import Case, CaregiverAccess, Medication, Notification
from app.engines.reasons import REPEAT_THRESHOLD, ReasonAction, ReasonPolicy, policy_for
from app.events import store as events
from app.events.payloads import ActionAssignedPayload, MedicationConfirmedPayload, ReasonRecordedPayload
from app.events.types import CaseStatus, EventType, ReasonCode, Source
from app.services.reconciliation import CaseError


@dataclass(frozen=True)
class RepeatedReason:
    reason_code: ReasonCode
    occurrences: int
    message: str


def _load_case(session: Session, user_id: str, case_id: str) -> tuple[Case, Medication]:
    case = session.get(Case, case_id)
    if case is None:
        raise CaseError("Case not found", status_code=404)
    med = session.get(Medication, case.medication_id)
    if med is None:
        raise CaseError("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)
    return case, med


def _notify_caregivers(session: Session, med: Medication, case: Case, reason: ReasonCode) -> None:
    """Notify every caregiver whose consent is currently active for this member."""
    accesses = session.exec(
        select(CaregiverAccess).where(CaregiverAccess.household_member_id == med.household_member_id)
    ).all()
    for access in accesses:
        if not has_active_consent(session, access):
            continue
        session.add(
            Notification(
                user_id=access.caregiver_user_id,
                title=f"Medicine follow-up: {med.name_generic or med.name_raw}",
                body=f"Reason recorded: {reason.value.replace('_', ' ').lower()}. Case {case.id} needs attention.",
            )
        )


def _execute(
    session: Session,
    *,
    user_id: str,
    med: Medication,
    case: Case,
    reason: ReasonCode,
    policy: ReasonPolicy,
) -> None:
    if policy.action == ReasonAction.OPEN_CASE_NOTIFY_CAREGIVER:
        _notify_caregivers(session, med, case, reason)
    elif policy.action == ReasonAction.INCREASE_REMINDERS:
        events.append_event(
            session,
            event_type=EventType.ACTION_ASSIGNED,
            payload=ActionAssignedPayload(
                medication_id=med.id,
                case_id=case.id,
                action_description="Increase reminders and share them with the caregiver",
            ),
            source=Source.SYSTEM,
            medication_id=med.id,
            source_user_id=user_id,
        )
    elif policy.action == ReasonAction.MARK_DISCONTINUED_CONFIRMED:
        events.append_event(
            session,
            event_type=EventType.MEDICATION_CONFIRMED,
            payload=MedicationConfirmedPayload(
                medication_id=med.id,
                status="DISCONTINUED",
                confirmation_method="reason recorded: doctor told patient to stop",
            ),
            source=Source.CAREGIVER,
            medication_id=med.id,
            source_user_id=user_id,
            created_by=user_id,
        )


def record_reason(
    session: Session,
    *,
    user_id: str,
    case_id: str,
    reason: ReasonCode,
    note: str | None = None,
) -> tuple[Case, ReasonPolicy]:
    case, med = _load_case(session, user_id, case_id)
    if CaseStatus(case.status) == CaseStatus.RESOLVED:
        raise CaseError("A resolved case cannot take a new reason.", status_code=409)

    policy = policy_for(reason)

    events.append_event(
        session,
        event_type=EventType.REASON_RECORDED,
        payload=ReasonRecordedPayload(
            medication_id=med.id, case_id=case.id, reason_code=reason, note=note
        ),
        source=Source.CAREGIVER,
        medication_id=med.id,
        source_user_id=user_id,
        created_by=user_id,
    )
    case.reason_code = reason.value
    _execute(session, user_id=user_id, med=med, case=case, reason=reason, policy=policy)

    if policy.closes_case:
        case.status = CaseStatus.RESOLVED.value
        case.resolution_note = f"Closed by reason {reason.value}"
        case.resolved_at = datetime.now(UTC)

    session.add(case)
    audit.log(
        session,
        audit.AuditAction.REASON_RECORDED,
        user_id=user_id,
        details={"case_id": case.id, "reason": reason.value, "action": policy.action.value},
    )
    session.commit()
    return case, policy


def detect_repeated_reasons(
    session: Session, *, user_id: str, medication_id: str, threshold: int = REPEAT_THRESHOLD
) -> list[RepeatedReason]:
    med = session.get(Medication, medication_id)
    if med is None:
        raise CaseError("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)

    cases = session.exec(
        select(Case).where(Case.medication_id == medication_id, Case.reason_code.is_not(None))  # type: ignore[union-attr]
    ).all()
    counts = Counter(ReasonCode(c.reason_code) for c in cases if c.reason_code)

    return [
        RepeatedReason(
            reason_code=code,
            occurrences=n,
            message=f"Repeated {code.value.replace('_', ' ').lower()} - follow-up recommended.",
        )
        for code, n in counts.items()
        if n >= threshold
    ]
