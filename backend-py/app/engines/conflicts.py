"""Conflict detection: compare the four evidence dimensions and name any disagreement.

Pure rules over a MedicationState (no database here). Persistence lives in
app/services/reconciliation.py.

Rules (ported from conflictDetection.ts):
  PRESCRIPTION_VS_REPORT    prescription ACTIVE, patient reported STOPPED, not confirmed DISCONTINUED
  REPORT_VS_AVAILABILITY    patient reported TAKING, medicine recorded ABSENT
  STOPPED_BUT_UNEXPLAINED   patient reported STOPPED, medicine still PRESENT, not confirmed DISCONTINUED

Safety rule added in this port: a dimension older than the stale threshold does not
participate in a conflict. Comparing an old report against fresh evidence would
produce false alarms, so the caregiver is asked to re-check instead (see
`stale_dimensions` on the result).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from app.engines.state import DimensionState, MedicationState
from app.events.types import Dimension

ConflictType = Literal[
    "PRESCRIPTION_VS_REPORT",
    "REPORT_VS_AVAILABILITY",
    "STOPPED_BUT_UNEXPLAINED",
    "EXPIRED_STOCK",
]


@dataclass(frozen=True)
class DetectedConflict:
    conflict_type: ConflictType
    description: str
    dimensions_involved: tuple[Dimension, ...]
    suggested_question: str


@dataclass(frozen=True)
class DetectionResult:
    conflicts: tuple[DetectedConflict, ...]
    stale_dimensions: tuple[Dimension, ...]


def _fresh(dim: DimensionState) -> bool:
    return not dim.stale


def detect(state: MedicationState, today: date | None = None) -> DetectionResult:
    today = today or datetime.now(UTC).date()
    prescribed = state.prescribed
    reported = state.reported_taking
    available = state.available
    confirmed = state.confirmed_status

    stale: list[Dimension] = []
    for dim_enum, dim in (
        (Dimension.PRESCRIBED, prescribed),
        (Dimension.AVAILABLE, available),
        (Dimension.REPORTED_TAKING, reported),
        (Dimension.CONFIRMED_STATUS, confirmed),
    ):
        if dim.stale:
            stale.append(dim_enum)

    discontinued = confirmed.status == "DISCONTINUED" and _fresh(confirmed)
    found: list[DetectedConflict] = []

    if (
        prescribed.status == "ACTIVE"
        and reported.status == "STOPPED"
        and _fresh(prescribed)
        and _fresh(reported)
        and not discontinued
    ):
        found.append(
            DetectedConflict(
                conflict_type="PRESCRIPTION_VS_REPORT",
                description="Prescription says Active; patient reported Stopped",
                dimensions_involved=(Dimension.PRESCRIBED, Dimension.REPORTED_TAKING),
                suggested_question="Who told you to stop, and when?",
            )
        )

    if reported.status == "TAKING" and available.status == "ABSENT" and _fresh(reported) and _fresh(available):
        found.append(
            DetectedConflict(
                conflict_type="REPORT_VS_AVAILABILITY",
                description="Patient reports taking it; none was found available",
                dimensions_involved=(Dimension.REPORTED_TAKING, Dimension.AVAILABLE),
                suggested_question="Is there a new strip that hasn't been recorded yet, or has this run out?",
            )
        )

    if (
        reported.status == "STOPPED"
        and available.status == "PRESENT"
        and _fresh(reported)
        and _fresh(available)
        and not discontinued
    ):
        found.append(
            DetectedConflict(
                conflict_type="STOPPED_BUT_UNEXPLAINED",
                description="Patient reported stopping; medicine is still available; no confirmed discontinuation",
                dimensions_involved=(Dimension.REPORTED_TAKING, Dimension.CONFIRMED_STATUS),
                suggested_question="Why did you stop taking this?",
            )
        )

    # Expired stock is a genuine evidence disagreement: the medicine is physically there,
    # but the label says it is past its date. Unlike the other rules this is not gated on
    # freshness — the expiry date is a durable fact, and "remove or replace it" is safe to
    # ask whether or not the availability check was recent.
    if available.status == "PRESENT":
        expiry = _parse_date(available.details.get("expiry_date"))
        if expiry is not None and expiry < today:
            found.append(
                DetectedConflict(
                    conflict_type="EXPIRED_STOCK",
                    description=f"Medicine is present but expired on {expiry.isoformat()}",
                    dimensions_involved=(Dimension.AVAILABLE,),
                    suggested_question=(
                        "This medicine is past its expiry date. When can it be replaced, "
                        "and has anyone taken any since the date passed?"
                    ),
                )
            )

    return DetectionResult(conflicts=tuple(found), stale_dimensions=tuple(stale))


def _parse_date(raw: object) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None
