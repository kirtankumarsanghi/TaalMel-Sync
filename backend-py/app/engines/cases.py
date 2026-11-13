"""Case lifecycle: a tracked problem stays visible until someone resolves it.

Transitions (from caseLifecycle.ts):
  OPEN            -> AWAITING_INFO | RESOLVED | STILL_UNCERTAIN
  AWAITING_INFO   -> RESOLVED | STILL_UNCERTAIN | OPEN
  STILL_UNCERTAIN -> OPEN | AWAITING_INFO
  RESOLVED        -> (terminal)

Resolving is the only way a case leaves the open list. Nothing disappears on its own.
"""

from app.db.models import Case
from app.events.types import CaseStatus

VALID_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.OPEN: frozenset({CaseStatus.AWAITING_INFO, CaseStatus.RESOLVED, CaseStatus.STILL_UNCERTAIN}),
    CaseStatus.AWAITING_INFO: frozenset({CaseStatus.RESOLVED, CaseStatus.STILL_UNCERTAIN, CaseStatus.OPEN}),
    CaseStatus.STILL_UNCERTAIN: frozenset({CaseStatus.OPEN, CaseStatus.AWAITING_INFO}),
    CaseStatus.RESOLVED: frozenset(),
}

OPEN_STATUSES = frozenset({CaseStatus.OPEN, CaseStatus.AWAITING_INFO})


class InvalidTransition(Exception):
    pass


def is_open(case: Case) -> bool:
    return CaseStatus(case.status) in OPEN_STATUSES


def can_transition(current: str, target: CaseStatus) -> bool:
    try:
        source = CaseStatus(current)
    except ValueError:
        return False
    return target in VALID_TRANSITIONS[source]


def require_transition(current: str, target: CaseStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(f"Cannot transition case from {current} to {target}")
