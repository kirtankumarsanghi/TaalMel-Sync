"""Medication state: fold a medication's event history into four evidence dimensions.

Rules (ported from medicationStateEngine.ts, with its inconsistencies removed):
- Each dimension keeps its most recent event (last event wins, by occurred_at then created_at).
- Dimensions are PRESCRIBED, AVAILABLE, REPORTED_TAKING, CONFIRMED_STATUS.
- Each dimension has its own freshness window: a prescription stays valid for months, a
  cabinet check goes stale in days. Stale evidence is never silently treated as current.
- A dimension with no evidence reports status UNKNOWN, never a guessed value.

The freshness numbers are engineering defaults, not clinical thresholds. They must be
reviewed by a qualified professional before real use.

Pure function: takes the events, returns the state. No database access.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.db.models import Event
from app.events.types import Dimension, EventType

# Default windows, in days, per evidence dimension. Overridable via settings.
FRESHNESS_DAYS: dict[Dimension, int] = {
    Dimension.PRESCRIBED: 180,       # a prescription remains valid for months
    Dimension.CONFIRMED_STATUS: 90,  # a status confirmation holds for a while
    Dimension.AVAILABLE: 7,          # "it is in the cabinet" is a snapshot
    Dimension.REPORTED_TAKING: 3,    # a self-report is about the last few days
}

# Retained for callers that only need the most permissive window (e.g. reporting).
STALE_THRESHOLD_DAYS = max(FRESHNESS_DAYS.values())


@dataclass(frozen=True)
class DimensionState:
    status: str
    last_verified: datetime | None
    age_days: int | None
    stale: bool
    source_event_id: str | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DoseChange:
    dose: str
    changed_at: datetime
    event_id: str


@dataclass(frozen=True)
class MedicationState:
    medication_id: str
    prescribed: DimensionState
    available: DimensionState
    reported_taking: DimensionState
    confirmed_status: DimensionState
    current_dose: str | None
    dose_history: list[DoseChange]
    event_count: int


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _unknown() -> DimensionState:
    return DimensionState(
        status="UNKNOWN",
        last_verified=None,
        age_days=None,
        stale=False,
        source_event_id=None,
    )


def _evidence(
    dimension: Dimension,
    status: str,
    event: Event,
    now: datetime,
    details: dict[str, Any] | None = None,
    freshness_days: dict[Dimension, int] | None = None,
) -> DimensionState:
    occurred = _aware(event.occurred_at)
    age = (now - occurred).days
    window = (freshness_days or FRESHNESS_DAYS)[dimension]
    return DimensionState(
        status=status,
        last_verified=occurred,
        age_days=age,
        stale=age > window,
        source_event_id=event.id,
        details=details or {},
    )


def compute_state(
    medication_id: str,
    events: list[Event],
    now: datetime | None = None,
    freshness_days: dict[Dimension, int] | None = None,
) -> MedicationState:
    now = _aware(now or datetime.now(UTC))
    windows = freshness_days or FRESHNESS_DAYS

    prescribed: DimensionState | None = None
    available: DimensionState | None = None
    reported: DimensionState | None = None
    confirmed: DimensionState | None = None
    current_dose: str | None = None
    dose_history: list[DoseChange] = []

    ordered = sorted(events, key=lambda e: (_aware(e.occurred_at), _aware(e.created_at)))
    for event in ordered:
        payload = json.loads(event.payload)
        kind = event.event_type

        if kind in (EventType.MEDICATION_NORMALIZED, EventType.MEDICATION_NORMALIZATION_REVIEW):
            # A medication exists only once a prescription item has been verified into it,
            # so this is the point at which the prescription is established as evidence.
            prescribed = _evidence(Dimension.PRESCRIBED, "ACTIVE", event, now, freshness_days=windows)
        elif kind == EventType.DOSE_CHANGED:
            new_dose = payload["new_dose"]
            dose_history.append(DoseChange(dose=new_dose, changed_at=_aware(event.occurred_at), event_id=event.id))
            current_dose = new_dose
        elif kind == EventType.AVAILABILITY_OBSERVED:
            status = "PRESENT" if payload["present"] else "ABSENT"
            available = _evidence(
                Dimension.AVAILABLE,
                status,
                event,
                now,
                {"quantity_note": payload.get("quantity_note"), "expiry_date": payload.get("expiry_date")},
                freshness_days=windows,
            )
        elif kind == EventType.MEDICATION_REPORTED:
            status = "TAKING" if payload["taking"] else "STOPPED"
            reported = _evidence(
                Dimension.REPORTED_TAKING, status, event, now,
                {"reason": payload.get("reason")}, freshness_days=windows,
            )
        elif kind == EventType.MEDICATION_CONFIRMED:
            confirmed = _evidence(
                Dimension.CONFIRMED_STATUS, payload["status"], event, now,
                {"confirmed_by": event.source}, freshness_days=windows,
            )

    return MedicationState(
        medication_id=medication_id,
        prescribed=prescribed or _unknown(),
        available=available or _unknown(),
        reported_taking=reported or _unknown(),
        confirmed_status=confirmed or _unknown(),
        current_dose=current_dose,
        dose_history=dose_history,
        event_count=len(events),
    )
