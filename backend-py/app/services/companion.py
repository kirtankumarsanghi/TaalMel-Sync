"""Daily companion: read-only views over the reconciliation record.

These give the caregiver a reason to open the app on an ordinary day, not only when
something is wrong. Nothing here writes medical content, and the app never answers a
clinical question — questions are collected for the doctor instead.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.consent.service import authorize_member
from app.db.models import DoctorQuestion, Medication
from app.engines.state import compute_state
from app.engines.triggers import check_refill
from app.events import store as events
from app.events.types import EventType
from app.services.reconciliation import CaseError


@dataclass(frozen=True)
class TodayItem:
    medication_id: str
    name: str
    dose: str | None
    confirmed_status: str
    reported_taking: str
    instruction: str | None


@dataclass(frozen=True)
class ChangeEntry:
    date: datetime
    event_type: str
    summary: str
    source: str


@dataclass(frozen=True)
class RefillItem:
    medication_id: str
    name: str
    dose: str | None
    reason: str
    basis: str


def today(session: Session, *, user_id: str, household_member_id: str) -> list[TodayItem]:
    authorize_member(session, user_id, household_member_id)
    items: list[TodayItem] = []
    for med in _medications(session, household_member_id):
        state = compute_state(med.id, list(events.events_for_medication(session, med.id)))
        items.append(
            TodayItem(
                medication_id=med.id,
                name=med.name_generic or med.name_raw,
                dose=state.current_dose or med.strength,
                confirmed_status=state.confirmed_status.status,
                reported_taking=state.reported_taking.status,
                # The doctor's own instruction, shown verbatim. Never replaced.
                instruction=med.instructions_raw,
            )
        )
    return items


def changes(
    session: Session, *, user_id: str, household_member_id: str, since_days: int = 90
) -> list[ChangeEntry]:
    authorize_member(session, user_id, household_member_id)
    since = datetime.now(UTC) - timedelta(days=since_days)
    relevant = {
        EventType.DOSE_CHANGED,
        EventType.MEDICATION_REPORTED,
        EventType.MEDICATION_CONFIRMED,
        EventType.CASE_RESOLVED,
        EventType.CONFLICT_DETECTED,
    }
    entries: list[ChangeEntry] = []
    for med in _medications(session, household_member_id):
        for event in events.events_for_medication(session, med.id):
            occurred = event.occurred_at if event.occurred_at.tzinfo else event.occurred_at.replace(tzinfo=UTC)
            if event.event_type not in relevant or occurred < since:
                continue
            entries.append(
                ChangeEntry(
                    date=occurred,
                    event_type=event.event_type,
                    summary=_summarize(event.event_type, events.decode_payload(event), med),
                    source=event.source,
                )
            )
    return sorted(entries, key=lambda e: e.date, reverse=True)


def add_question(
    session: Session,
    *,
    user_id: str,
    household_member_id: str,
    question_text: str,
    raised_by: str,
    medication_id: str | None = None,
) -> DoctorQuestion:
    authorize_member(session, user_id, household_member_id)
    question = DoctorQuestion(
        household_member_id=household_member_id,
        medication_id=medication_id,
        question_text=question_text,
        raised_by=raised_by,
    )
    session.add(question)
    session.commit()
    return question


def list_questions(
    session: Session, *, user_id: str, household_member_id: str, status: str = "PENDING"
) -> list[DoctorQuestion]:
    authorize_member(session, user_id, household_member_id)
    return list(
        session.exec(
            select(DoctorQuestion).where(
                DoctorQuestion.household_member_id == household_member_id,
                DoctorQuestion.status == status,
            )
        ).all()
    )


def mark_discussed(session: Session, *, user_id: str, question_id: str) -> DoctorQuestion:
    question = session.get(DoctorQuestion, question_id)
    if question is None:
        raise CaseError("Question not found", status_code=404)
    authorize_member(session, user_id, question.household_member_id)
    question.status = "DISCUSSED"
    question.discussed_at = datetime.now(UTC)
    question.updated_at = datetime.now(UTC)
    session.add(question)
    session.commit()
    return question


def refill_list(session: Session, *, user_id: str, household_member_id: str) -> list[RefillItem]:
    """A shopping list of medicines that may need refilling.

    Ordering is deliberately not offered; the list is to hand to any pharmacy.
    """
    authorize_member(session, user_id, household_member_id)
    items: list[RefillItem] = []
    for med in _medications(session, household_member_id):
        state = compute_state(med.id, list(events.events_for_medication(session, med.id)))
        refill = check_refill(state)
        if refill is None:
            continue
        items.append(
            RefillItem(
                medication_id=med.id,
                name=med.name_generic or med.name_raw,
                dose=med.strength,
                reason=refill.message,
                basis=(
                    "Based on the recorded availability snapshot, not a predicted "
                    "consumption rate."
                ),
            )
        )
    return items


def _medications(session: Session, household_member_id: str) -> list[Medication]:
    return list(
        session.exec(
            select(Medication).where(Medication.household_member_id == household_member_id)
        ).all()
    )


def _summarize(event_type: str, payload: dict, med: Medication) -> str:
    name = med.name_generic or med.name_raw
    if event_type == EventType.DOSE_CHANGED:
        return f"{name}: dose changed to {payload.get('new_dose')}"
    if event_type == EventType.MEDICATION_REPORTED:
        return f"{name}: patient reported " + ("taking" if payload.get("taking") else "stopped")
    if event_type == EventType.MEDICATION_CONFIRMED:
        return f"{name}: status confirmed as {str(payload.get('status')).lower()}"
    if event_type == EventType.CASE_RESOLVED:
        return f"{name}: case resolved"
    return f"{name}: discrepancy detected"
