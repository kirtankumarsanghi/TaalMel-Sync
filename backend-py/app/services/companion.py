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
from app.engines.triggers import check_refill, estimate_consumption
from app.events import store as events
from app.events.types import EventType
from app.services.reconciliation import CaseError


# Static, source-attributed plain-language descriptions (shown alongside, never replacing,
# the doctor's instruction). Medicines not in this reviewed table return None.
PLAIN_EXPLANATIONS: dict[str, tuple[str, str]] = {
    "metformin": ("Helps keep blood sugar levels steady.", "WHO Essential Medicines"),
    "amlodipine": ("Helps lower high blood pressure.", "WHO Essential Medicines"),
    "atorvastatin": ("Helps lower cholesterol.", "WHO Essential Medicines"),
    "aspirin": ("Used in low doses to help prevent blood clots.", "WHO Essential Medicines"),
    "lisinopril": ("Helps relax blood vessels to lower blood pressure.", "WHO Essential Medicines"),
    "telmisartan": ("Helps lower high blood pressure.", "WHO Essential Medicines"),
    "omeprazole": ("Reduces stomach acid.", "WHO Essential Medicines"),
    "pantoprazole": ("Reduces stomach acid.", "WHO Essential Medicines"),
    "paracetamol": ("Helps relieve mild pain or fever.", "WHO Essential Medicines"),
    "insulin": ("Helps control blood sugar levels.", "WHO Essential Medicines"),
    "levothyroxine": ("Replaces thyroid hormone.", "WHO Essential Medicines"),
}


def plain_explanation_for(name: str | None) -> tuple[str | None, str | None]:
    if not name:
        return None, None
    key = name.strip().lower().split()[0]
    hit = PLAIN_EXPLANATIONS.get(key)
    return (hit[0], hit[1]) if hit else (None, None)


@dataclass(frozen=True)
class TodayItem:
    medication_id: str
    name: str
    dose: str | None
    confirmed_status: str
    reported_taking: str
    instruction: str | None
    plain_explanation: str | None = None
    explanation_source: str | None = None


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
        med_name = med.name_generic or med.name_raw
        plain, plain_src = plain_explanation_for(med.name_generic or med.name_raw)
        items.append(
            TodayItem(
                medication_id=med.id,
                name=med_name,
                dose=state.current_dose or med.strength,
                confirmed_status=state.confirmed_status.status,
                reported_taking=state.reported_taking.status,
                # The doctor's own instruction, shown verbatim. Never replaced.
                instruction=med.instructions_raw,
                plain_explanation=plain,
                explanation_source=plain_src,
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

    Two signals, in order of strength: how fast the patient is actually reporting taking
    it, and the time since the last availability check. If there is enough evidence to
    estimate consumption, that estimate drives the basis text so the caregiver knows how
    the conclusion was reached. Ordering is deliberately not offered.
    """
    authorize_member(session, user_id, household_member_id)
    items: list[RefillItem] = []

    for med in _medications(session, household_member_id):
        med_events = list(events.events_for_medication(session, med.id))
        state = compute_state(med.id, med_events)

        reported_by_day: dict[str, int] = {}
        for event in med_events:
            if event.event_type != EventType.MEDICATION_REPORTED:
                continue
            payload = events.decode_payload(event)
            if not payload.get("taking"):
                continue
            occurred = event.occurred_at if event.occurred_at.tzinfo else event.occurred_at.replace(tzinfo=UTC)
            reported_by_day[occurred.date().isoformat()] = (
                reported_by_day.get(occurred.date().isoformat(), 0) + 1
            )

        estimate = estimate_consumption(reported_by_day)
        refill = check_refill(state)
        # Only medicines that are actually due are listed; a consumption estimate alone
        # is not a reason to buy more.
        if refill is None:
            continue

        if estimate is not None:
            basis = (
                f"{estimate.basis} About {estimate.doses_per_day} dose(s) per day, so a "
                f"30-dose strip lasts roughly "
                f"{max(1, round(30 / max(estimate.doses_per_day, 0.1)))} days. "
                f"Confirmed by the last availability check."
            )
        else:
            basis = (
                "Based on the recorded availability snapshot only. Not enough reported "
                "doses yet to estimate how fast it is being used."
            )

        items.append(
            RefillItem(
                medication_id=med.id,
                name=med.name_generic or med.name_raw,
                dose=med.strength,
                reason=refill.message,
                basis=basis,
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
