from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.db.models import Case
from app.events.types import CaseStatus, ReasonCode
from app.services import affordability
from app.services import reasons as reason_service
from app.services import reconciliation as service

router = APIRouter()


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: ReasonCode
    note: str | None = Field(default=None, max_length=500)


class RepeatedReasonOut(BaseModel):
    reason_code: str
    occurrences: int
    message: str


class CaseOut(BaseModel):
    id: str
    medication_id: str
    medication_name: str | None = None
    # One line describing what disagreed, so a list of cases is readable at a glance.
    issue: str | None = None
    trigger_event_id: str | None
    status: str
    action_taken: str | None
    reason_code: str | None
    opened_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


class ReasonOut(BaseModel):
    case: CaseOut
    action: str
    action_description: str
    closes_case: bool
    # Populated only for COULD_NOT_AFFORD: named public resources, never a generated
    # "cheaper alternative". The app still prompts a conversation with a professional.
    resources: list[dict[str, str]] | None = None


class AssignActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_description: str = Field(min_length=1, max_length=500)
    assigned_to_user_id: str | None = None


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: CaseStatus
    resolution_note: str | None = Field(default=None, max_length=500)


def _out(case: Case, medication_name: str | None = None, issue: str | None = None) -> CaseOut:
    return CaseOut(
        id=case.id,
        medication_id=case.medication_id,
        medication_name=medication_name,
        issue=issue,
        trigger_event_id=case.trigger_event_id,
        status=case.status,
        action_taken=case.action_taken,
        reason_code=case.reason_code,
        opened_at=case.opened_at,
        resolved_at=case.resolved_at,
        resolution_note=case.resolution_note,
    )


@router.post("/medications/{medication_id}/detect", response_model=list[CaseOut])
def detect(
    medication_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[CaseOut]:
    cases = service.detect_and_open_cases(session, user_id=user_id, medication_id=medication_id)
    return [_out(c) for c in cases]


@router.get("/households/{household_member_id}/open-cases", response_model=list[CaseOut])
def open_cases(
    household_member_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[CaseOut]:
    cases = service.open_cases_for_member(
        session, user_id=user_id, household_member_id=household_member_id
    )
    return [_out(case, name, issue) for case, name, issue in cases]


@router.post("/cases/{case_id}/action", response_model=CaseOut)
def assign_action(
    case_id: str,
    body: AssignActionIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> CaseOut:
    case = service.assign_action(
        session,
        user_id=user_id,
        case_id=case_id,
        action_description=body.action_description,
        assigned_to_user_id=body.assigned_to_user_id,
    )
    return _out(case)


@router.post("/cases/{case_id}/reason", response_model=ReasonOut)
def record_reason(
    case_id: str,
    body: ReasonIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> ReasonOut:
    case, policy = reason_service.record_reason(
        session, user_id=user_id, case_id=case_id, reason=body.reason, note=body.note
    )
    resources = (
        affordability.affordability_resources()
        if policy.action.value == "SHOW_AFFORDABILITY_RESOURCES"
        else None
    )
    return ReasonOut(
        case=_out(case),
        action=policy.action.value,
        action_description=policy.description,
        closes_case=policy.closes_case,
        resources=resources,
    )


@router.get("/medications/{medication_id}/repeated-reasons", response_model=list[RepeatedReasonOut])
def repeated_reasons(
    medication_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[RepeatedReasonOut]:
    items = reason_service.detect_repeated_reasons(
        session, user_id=user_id, medication_id=medication_id
    )
    return [
        RepeatedReasonOut(reason_code=i.reason_code.value, occurrences=i.occurrences, message=i.message)
        for i in items
    ]


@router.post("/cases/{case_id}/resolve", response_model=CaseOut)
def resolve(
    case_id: str,
    body: ResolveIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> CaseOut:
    case = service.resolve_case(
        session,
        user_id=user_id,
        case_id=case_id,
        outcome=body.outcome,
        resolution_note=body.resolution_note,
    )
    return _out(case)
