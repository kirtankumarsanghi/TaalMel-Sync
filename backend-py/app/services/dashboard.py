"""Read-only summaries for the caregiver.

dashboard:      counts of medicines confirmed, needing checking, open cases, near expiry.
case_explain:   what / why / source / status / action, plus the explicit non-action.
completeness:   how complete and current the record is (data quality, not a health score).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.consent.service import authorize_member
from app.db.models import Case, Medication
from app.engines.cases import OPEN_STATUSES
from app.engines.state import compute_state
from app.engines.triggers import check_expiry
from app.events import store as events
from app.services.reconciliation import CaseError


@dataclass(frozen=True)
class DashboardSummary:
    medicines_total: int
    confirmed: int
    needs_checking: int
    open_cases: int
    near_expiry: int
    expired: int


def summarize(session: Session, *, user_id: str, household_member_id: str) -> DashboardSummary:
    authorize_member(session, user_id, household_member_id)
    meds = session.exec(
        select(Medication).where(Medication.household_member_id == household_member_id)
    ).all()

    open_case_count = len(
        session.exec(
            select(Case)
            .join(Medication, Case.medication_id == Medication.id)  # type: ignore[arg-type]
            .where(
                Medication.household_member_id == household_member_id,
                Case.status.in_([s.value for s in OPEN_STATUSES]),  # type: ignore[attr-defined]
            )
        ).all()
    )

    today = datetime.now(UTC).date()
    confirmed = needs_checking = near_expiry = expired = 0
    for med in meds:
        state = compute_state(med.id, list(events.events_for_medication(session, med.id)))
        if state.confirmed_status.status == "CONFIRMED":
            confirmed += 1
        if (
            state.available.last_verified is None
            or state.available.stale
            or state.reported_taking.last_verified is None
        ):
            needs_checking += 1
        expiry = check_expiry(state, today=today)
        if expiry is not None and expiry.expired:
            expired += 1
        elif expiry is not None:
            near_expiry += 1

    return DashboardSummary(
        medicines_total=len(meds),
        confirmed=confirmed,
        needs_checking=needs_checking,
        open_cases=open_case_count,
        near_expiry=near_expiry,
        expired=expired,
    )


@dataclass(frozen=True)
class CaseExplanation:
    what: str
    why: str
    source: str
    status: str
    action: str
    reason_recorded: str | None
    taalmel_does_not: str


def explain_case(session: Session, *, user_id: str, case_id: str) -> CaseExplanation:
    case = session.get(Case, case_id)
    if case is None:
        raise CaseError("Case not found", status_code=404)
    med = session.get(Medication, case.medication_id)
    if med is None:
        raise CaseError("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)

    trigger = session.get(events.Event, case.trigger_event_id) if case.trigger_event_id else None
    payload = events.decode_payload(trigger) if trigger is not None else {}
    occurred = trigger.occurred_at.isoformat() if trigger is not None else "unknown time"

    return CaseExplanation(
        what="Potential medication discrepancy",
        why=str(payload.get("description", "Evidence gap detected")),
        source=(
            f"Event recorded {occurred} ({trigger.source})" if trigger is not None else "Unknown"
        ),
        status=case.status,
        action=case.action_taken or "Confirm the underlying facts before proceeding",
        reason_recorded=case.reason_code,
        taalmel_does_not=f"change or stop any medication ({med.name_generic or med.name_raw})",
    )


@dataclass(frozen=True)
class Completeness:
    medicines_total: int
    with_prescription: int
    with_availability_check: int
    with_self_report: int
    stale_items: int
    score_percent: int


def record_completeness(session: Session, *, user_id: str, household_member_id: str) -> Completeness:
    """A data-quality measure, not a health score.

    Each medicine earns up to three points: prescribed (it exists), a fresh availability
    check, and a fresh self-report. The percentage is the fraction of points earned.
    """
    authorize_member(session, user_id, household_member_id)
    meds = session.exec(
        select(Medication).where(Medication.household_member_id == household_member_id)
    ).all()

    with_prescription = with_availability = with_report = stale = 0
    earned = 0
    for med in meds:
        state = compute_state(med.id, list(events.events_for_medication(session, med.id)))
        earned += 1  # the medication exists, so it came from a verified prescription
        with_prescription += 1
        if state.available.last_verified is not None and not state.available.stale:
            with_availability += 1
            earned += 1
        if state.reported_taking.last_verified is not None and not state.reported_taking.stale:
            with_report += 1
            earned += 1
        stale += int(state.available.stale) + int(state.reported_taking.stale)

    possible = len(meds) * 3
    return Completeness(
        medicines_total=len(meds),
        with_prescription=with_prescription,
        with_availability_check=with_availability,
        with_self_report=with_report,
        stale_items=stale,
        score_percent=round(earned * 100 / possible) if possible else 0,
    )
