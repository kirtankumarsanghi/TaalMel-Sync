"""Trigger rules: decide which notifications an event should produce.

Pure rules over the event type and state. Persistence (writing Notification rows and
choosing recipients by escalation level) lives in app/services/triggers.py.

Escalation levels:
  INFO      ordinary awareness; the primary caregiver
  ACTION    something the caregiver must do; the primary caregiver
  CRITICAL  cannot wait; the primary caregiver plus designated emergency contacts
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import IntEnum

from app.engines.state import MedicationState
from app.events.types import EventType

REFILL_WINDOW_DAYS = 30
EXPIRY_WARNING_DAYS = 30


class Escalation(IntEnum):
    INFO = 0
    ACTION = 1
    CRITICAL = 2


@dataclass(frozen=True)
class Trigger:
    rule: str
    message: str
    level: Escalation


@dataclass(frozen=True)
class RefillCheck:
    rule: str
    message: str
    level: Escalation
    last_verified: datetime | None
    age_days: int | None


@dataclass(frozen=True)
class ExpiryCheck:
    rule: str
    message: str
    level: Escalation
    expiry_date: date
    days_remaining: int
    expired: bool


EVIDENCE_EVENTS = frozenset(
    {
        EventType.MEDICATION_REPORTED,
        EventType.AVAILABILITY_OBSERVED,
        EventType.MEDICATION_CONFIRMED,
    }
)


def triggers_for_event(event_type: str) -> list[Trigger]:
    """Event-driven notifications that do not depend on state."""
    if event_type in (EventType.PRESCRIPTION_UPLOADED, EventType.MEDICATION_EXTRACTED):
        return [
            Trigger(
                rule="NEW_PRESCRIPTION_UPLOADED",
                message="New prescription uploaded - checking whether it changes the current medication list.",
                level=Escalation.INFO,
            )
        ]
    if event_type == EventType.PRESCRIPTION_OCR_COMPLETED:
        return [
            Trigger(
                rule="PRESCRIPTION_READ",
                message="A prescription has been read and is waiting for a person to confirm the medicines.",
                level=Escalation.ACTION,
            )
        ]
    if event_type == EventType.PRESCRIPTION_VERIFIED:
        return [
            Trigger(
                rule="PRESCRIPTION_CONFIRMED",
                message="A person confirmed the prescription; the medication list has been updated.",
                level=Escalation.INFO,
            )
        ]
    if event_type in EVIDENCE_EVENTS:
        return [
            Trigger(
                rule="EVIDENCE_CHANGED",
                message="New evidence recorded; reconciliation should be re-run.",
                level=Escalation.INFO,
            )
        ]
    if event_type == EventType.REASON_RECORDED:
        return [
            Trigger(
                rule="REASON_RECORDED",
                message="A reason was recorded for an open case.",
                level=Escalation.INFO,
            )
        ]
    return []


def conflict_trigger(medication_name: str, conflict_type: str, question: str) -> Trigger:
    return Trigger(
        rule="EVIDENCE_CONFLICT",
        message=f"{medication_name}: {question}",
        level=Escalation.ACTION,
    )


def repeated_reason_trigger(message: str) -> Trigger:
    return Trigger(rule="REPEATED_REASON_PATTERN", message=message, level=Escalation.ACTION)


def expired_stock_trigger(medication_name: str, expiry: date) -> Trigger:
    return Trigger(
        rule="MEDICINE_EXPIRED",
        message=f"{medication_name} expired on {expiry.isoformat()}. Do not continue taking it.",
        level=Escalation.CRITICAL,
    )


def check_refill(state: MedicationState, refill_window_days: int = REFILL_WINDOW_DAYS) -> RefillCheck | None:
    available = state.available
    if available.last_verified is None:
        return None

    quantity = available.details.get("quantity_note")
    # The caregiver can record "low" as well as "nearly empty"; both are an explicit
    # statement that stock is running out, so both must reach the refill list.
    low_stock = quantity in ("low", "nearly empty")
    window_elapsed = (available.age_days or 0) >= refill_window_days
    if not (low_stock or window_elapsed):
        return None

    rule = "REFILL_WINDOW_ELAPSED" if window_elapsed else "REFILL_LIKELY_NEEDED_SOON"
    message = (
        "Expected refill window has passed with no confirmation - please check availability."
        if window_elapsed
        else "Refill may be needed soon."
    )
    return RefillCheck(
        rule=rule,
        message=message,
        level=Escalation.ACTION,
        last_verified=available.last_verified,
        age_days=available.age_days,
    )


# How many days of reported doses are needed before a consumption estimate is trusted.
MIN_DAYS_FOR_ESTIMATE = 7


@dataclass(frozen=True)
class ConsumptionEstimate:
    """How fast the medicine is actually being taken, from reported doses.

    This is an estimate from *self-reports*, not from pharmacy dispensing, so it is
    labelled as such wherever it is shown. When there is not enough evidence the
    estimate is None and the caller falls back to the time window.
    """

    doses_per_day: float
    days_of_evidence: int
    reported_doses: int
    basis: str


def estimate_consumption(
    reported_doses_by_day: dict[str, int] | None, min_days: int = MIN_DAYS_FOR_ESTIMATE
) -> ConsumptionEstimate | None:
    """Average reported doses per day across the days that actually have reports.

    Counting only days with a report avoids the trap of dividing by calendar days and
    understating consumption whenever the patient is simply quiet.
    """
    if not reported_doses_by_day:
        return None

    active_days = {day: count for day, count in reported_doses_by_day.items() if count > 0}
    if len(active_days) < min_days:
        return None

    total = sum(active_days.values())
    per_day = total / len(active_days)
    return ConsumptionEstimate(
        doses_per_day=round(per_day, 2),
        days_of_evidence=len(active_days),
        reported_doses=total,
        basis=(
            f"Estimated from {total} reported doses across {len(active_days)} days. "
            f"Self-reported, not a pharmacy record."
        ),
    )


def check_expiry(state: MedicationState, today: date | None = None) -> ExpiryCheck | None:
    """Warn EXPIRY_WARNING_DAYS before the recorded expiry date, and after it passes."""
    today = today or datetime.now(UTC).date()
    raw = state.available.details.get("expiry_date")
    if not raw:
        return None
    try:
        expiry = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None

    days_remaining = (expiry - today).days
    if days_remaining > EXPIRY_WARNING_DAYS:
        return None
    expired = days_remaining < 0
    return ExpiryCheck(
        rule="MEDICINE_EXPIRED" if expired else "MEDICINE_EXPIRING_SOON",
        message=(
            f"Medicine expired on {expiry.isoformat()}."
            if expired
            else f"Medicine expires in {days_remaining} day(s) on {expiry.isoformat()}."
        ),
        level=Escalation.CRITICAL if expired else Escalation.ACTION,
        expiry_date=expiry,
        days_remaining=days_remaining,
        expired=expired,
    )
