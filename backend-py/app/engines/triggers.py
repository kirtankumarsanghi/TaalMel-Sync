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
    nearly_empty = quantity == "nearly empty"
    window_elapsed = (available.age_days or 0) >= refill_window_days
    if not (nearly_empty or window_elapsed):
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
