"""Dosage tapering tracker.

Applies to medicines that must be reduced gradually — steroids, certain antidepressants,
benzodiazepines. Stopping or jumping a step can be harmful, so the system tracks the
schedule the *doctor* wrote and flags deviations.

It never suggests a taper. A taper schedule exists only because a prescription said so.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlmodel import Session, select

from app.consent.service import authorize_member
from app.db.models import Medication, TaperSchedule
from app.engines.state import compute_state
from app.events import store as events
from app.events.types import EventType
from app.services.reconciliation import CaseError

MEDICINE_ERROR = CaseError

# Medicines where tapering is clinically common. Presence here is not a recommendation;
# it only means the app knows to look for a taper schedule on the prescription.
TAPER_PRONE = frozenset(
    {
        "prednisolone", "prednisone", "dexamethasone", "methylprednisolone",
        "hydrocortisone", "betamethasone",
        "diazepam", "clonazepam", "lorazepam", "alprazolam", "chlordiazepoxide",
        "paroxetine", "sertraline", "venlafaxine", "escitalopram", "fluoxetine",
        "gabapentin", "pregabalin", "baclofen", "tramadol",
    }
)


@dataclass(frozen=True)
class TaperStep:
    step: int
    dose: str
    duration_days: int


@dataclass(frozen=True)
class TaperStatus:
    medication_id: str
    medicine: str
    schedule: list[TaperStep]
    current_step: int | None
    expected_dose: str | None
    reported_dose: str | None
    finding: Literal[
        "ON_TRACK", "STEP_SKIPPED", "DOSE_ABOVE_SCHEDULE", "NO_SCHEDULE", "UNREADABLE"
    ]
    detail: str


def is_taper_prone(name: str | None, generic: str | None) -> bool:
    for candidate in (generic, name):
        if candidate and candidate.strip().lower() in TAPER_PRONE:
            return True
    return False


def parse_schedule(raw: str) -> list[TaperStep] | None:
    """Parse a schedule the doctor wrote, e.g. "20mg x7d, 10mg x7d, 5mg x7d".

    Returns None when the text cannot be read with confidence — the caller then reports
    UNREADABLE rather than inventing a taper.
    """
    if not raw or not raw.strip():
        return None

    steps: list[TaperStep] = []
    for index, chunk in enumerate(part.strip() for part in raw.split(",")):
        if not chunk:
            continue
        dose_match = None
        days_match = None
        import re

        dose_match = re.match(r"(\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml))", chunk, re.IGNORECASE)
        days_match = re.search(r"(?:x|\*|for\s+)?\s*(\d+)\s*(?:d|day|days)", chunk, re.IGNORECASE)
        if not dose_match or not days_match:
            return None
        steps.append(
            TaperStep(
                step=len(steps) + 1,
                dose=dose_match.group(1).replace(" ", "").lower(),
                duration_days=int(days_match.group(1)),
            )
        )
    return steps or None


def set_schedule(
    session: Session,
    *,
    user_id: str,
    medication_id: str,
    schedule_text: str,
    prescribed_by: str | None = None,
) -> TaperSchedule:
    med = session.get(Medication, medication_id)
    if med is None:
        raise MEDICINE_ERROR("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)

    steps = parse_schedule(schedule_text)
    if steps is None:
        raise MEDICINE_ERROR(
            "That schedule could not be read. Use a form like '20mg x7d, 10mg x7d, 5mg x7d'.",
            status_code=400,
        )

    existing = session.exec(
        select(TaperSchedule).where(TaperSchedule.medication_id == medication_id)
    ).first()
    if existing is not None:
        session.delete(existing)
        session.flush()

    row = TaperSchedule(
        medication_id=medication_id,
        schedule_text=schedule_text.strip(),
        steps=str(len(steps)),
        prescribed_by=prescribed_by,
        started_on=datetime.now(UTC),
        active=True,
    )
    session.add(row)
    session.flush()
    session.commit()
    return row


def _reported_dose(session: Session, medication_id: str) -> str | None:
    """The most recent dose the record knows about: a change, or the prescription."""
    for event in reversed(list(events.events_for_medication(session, medication_id))):
        if event.event_type == EventType.DOSE_CHANGED:
            payload = events.decode_payload(event)
            return str(payload.get("new_dose") or "") or None
    med = session.get(Medication, medication_id)
    if med is None:
        return None
    return med.strength


def check(
    session: Session, *, user_id: str, medication_id: str, today_day: int | None = None
) -> TaperStatus:
    """Compare progress against the schedule.

    `today_day` is days since the schedule started; None means "not tracked yet", in
    which case the status is ON_TRACK rather than a guess.
    """
    med = session.get(Medication, medication_id)
    if med is None:
        raise MEDICINE_ERROR("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)

    name = med.name_generic or med.name_raw
    row = session.exec(
        select(TaperSchedule).where(TaperSchedule.medication_id == medication_id)
    ).first()

    if row is None:
        return TaperStatus(
            medication_id=medication_id,
            medicine=name,
            schedule=[],
            current_step=None,
            expected_dose=None,
            reported_dose=_reported_dose(session, medication_id),
            finding="NO_SCHEDULE",
            detail=(
                "No tapering schedule is recorded. This medicine is often reduced "
                "gradually, so ask the prescriber and record the plan here."
                if is_taper_prone(med.name_generic, med.name_raw)
                else "No tapering schedule is recorded."
            ),
        )

    steps = parse_schedule(row.schedule_text)
    if steps is None:
        return TaperStatus(
            medication_id=medication_id,
            medicine=name,
            schedule=[],
            current_step=None,
            expected_dose=None,
            reported_dose=_reported_dose(session, medication_id),
            finding="UNREADABLE",
            detail="The recorded schedule could not be read. It is shown exactly as entered.",
        )

    reported = _reported_dose(session, medication_id)

    if today_day is None:
        started = row.started_on or row.created_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        today_day = max(0, (datetime.now(UTC) - started).days)

    # Which step should the patient be on today?
    elapsed = 0
    expected: TaperStep | None = None
    for step in steps:
        elapsed += step.duration_days
        if today_day <= elapsed:
            expected = step
            break
    if expected is None:
        expected = steps[-1]

    def normalise(value: str | None) -> str | None:
        return value.replace(" ", "").lower() if value else None

    expected_dose = normalise(expected.dose)
    actual = normalise(reported)

    if actual is None:
        return TaperStatus(
            medication_id=medication_id,
            medicine=name,
            schedule=steps,
            current_step=expected.step,
            expected_dose=expected.dose,
            reported_dose=None,
            finding="ON_TRACK",
            detail=f"Expected to be on {expected.dose} today. No dose has been reported yet.",
        )

    if actual == expected_dose:
        return TaperStatus(
            medication_id=medication_id,
            medicine=name,
            schedule=steps,
            current_step=expected.step,
            expected_dose=expected.dose,
            reported_dose=reported,
            finding="ON_TRACK",
            detail=f"On schedule: step {expected.step} of {len(steps)}, {expected.dose}.",
        )

    # A dose higher than expected means a reduction was skipped or reversed — the
    # dangerous direction, and therefore a tracked case.
    try:
        actual_value = float(actual.rstrip("abcdefghijklmnopqrstuvwxyz"))
        expected_value = float(expected_dose.rstrip("abcdefghijklmnopqrstuvwxyz"))
    except (ValueError, AttributeError):
        return TaperStatus(
            medication_id=medication_id,
            medicine=name,
            schedule=steps,
            current_step=expected.step,
            expected_dose=expected.dose,
            reported_dose=reported,
            finding="UNREADABLE",
            detail="Reported dose could not be compared with the schedule.",
        )

    if actual_value > expected_value:
        return TaperStatus(
            medication_id=medication_id,
            medicine=name,
            schedule=steps,
            current_step=expected.step,
            expected_dose=expected.dose,
            reported_dose=reported,
            finding="DOSE_ABOVE_SCHEDULE",
            detail=(
                f"Recorded dose {reported} is higher than the scheduled {expected.dose} "
                f"for step {expected.step}. Confirm with the prescriber before continuing."
            ),
        )

    return TaperStatus(
        medication_id=medication_id,
        medicine=name,
        schedule=steps,
        current_step=expected.step,
        expected_dose=expected.dose,
        reported_dose=reported,
        finding="STEP_SKIPPED",
        detail=(
            f"Recorded dose {reported} is below the scheduled {expected.dose} for step "
            f"{expected.step}. A reduction may have happened earlier than planned."
        ),
    )
