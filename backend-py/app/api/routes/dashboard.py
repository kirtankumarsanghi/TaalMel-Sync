from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import CurrentUserDep, SessionDep
from app.consent.service import authorize_member
from app.db.models import Medication
from app.services import dashboard as service
from app.services import safety

router = APIRouter()


class SummaryOut(BaseModel):
    medicines_total: int
    confirmed: int
    needs_checking: int
    open_cases: int
    near_expiry: int
    expired: int


class ExplanationOut(BaseModel):
    what: str
    why: str
    source: str
    status: str
    action: str
    reason_recorded: str | None
    taalmel_does_not: str


class CompletenessOut(BaseModel):
    medicines_total: int
    with_prescription: int
    with_availability_check: int
    with_self_report: int
    stale_items: int
    score_percent: int


class PairOut(BaseModel):
    a: str
    b: str
    result: str
    detail: str | None
    source: str | None


class SafetyOut(BaseModel):
    normalized_names: list[str]
    pairs: list[PairOut]
    uncovered: list[str]
    disclaimer: str


@router.get("/households/{household_member_id}/summary", response_model=SummaryOut)
def summary(
    household_member_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> SummaryOut:
    return SummaryOut(**vars(service.summarize(session, user_id=user_id, household_member_id=household_member_id)))


@router.get("/cases/{case_id}/explain", response_model=ExplanationOut)
def explain(case_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep) -> ExplanationOut:
    return ExplanationOut(**vars(service.explain_case(session, user_id=user_id, case_id=case_id)))


@router.get("/households/{household_member_id}/completeness", response_model=CompletenessOut)
def completeness(
    household_member_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> CompletenessOut:
    return CompletenessOut(
        **vars(service.record_completeness(session, user_id=user_id, household_member_id=household_member_id))
    )


@router.get("/households/{household_member_id}/safety-check", response_model=SafetyOut)
def safety_check(
    household_member_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> SafetyOut:
    authorize_member(session, user_id, household_member_id)
    meds = session.exec(
        select(Medication).where(Medication.household_member_id == household_member_id)
    ).all()
    names = [m.name_generic or m.name_raw for m in meds]
    result = safety.check_interactions(names)
    return SafetyOut(
        normalized_names=list(result.normalized_names),
        pairs=[
            PairOut(a=p.a, b=p.b, result=p.result, detail=p.detail, source=p.source)
            for p in result.pairs
        ],
        uncovered=list(result.uncovered),
        disclaimer=result.disclaimer,
    )
