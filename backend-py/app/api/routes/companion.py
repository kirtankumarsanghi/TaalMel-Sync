from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import CurrentRoleDep, CurrentUserDep, SessionDep
from app.services import companion as service

router = APIRouter()


class TodayOut(BaseModel):
    medication_id: str
    name: str
    dose: str | None
    confirmed_status: str
    reported_taking: str
    instruction: str | None


class ChangeOut(BaseModel):
    date: datetime
    event_type: str
    summary: str
    source: str


class QuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_text: str = Field(min_length=1, max_length=500)
    medication_id: str | None = None


class QuestionOut(BaseModel):
    id: str
    medication_id: str | None
    question_text: str
    raised_by: str
    status: str
    created_at: datetime
    discussed_at: datetime | None
    note: str = "Saved to your Ask My Doctor list. Taalmel does not answer clinical questions."


class RefillOut(BaseModel):
    medication_id: str
    name: str
    dose: str | None
    reason: str
    basis: str


@router.get("/households/{household_member_id}/today", response_model=list[TodayOut])
def today(
    household_member_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[TodayOut]:
    return [
        TodayOut(
            medication_id=i.medication_id,
            name=i.name,
            dose=i.dose,
            confirmed_status=i.confirmed_status,
            reported_taking=i.reported_taking,
            instruction=i.instruction,
        )
        for i in service.today(session, user_id=user_id, household_member_id=household_member_id)
    ]


@router.get("/households/{household_member_id}/changes", response_model=list[ChangeOut])
def changes(
    household_member_id: str,
    since_days: int = Query(default=90, ge=1, le=3650),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[ChangeOut]:
    return [
        ChangeOut(date=c.date, event_type=c.event_type, summary=c.summary, source=c.source)
        for c in service.changes(
            session, user_id=user_id, household_member_id=household_member_id, since_days=since_days
        )
    ]


@router.post("/households/{household_member_id}/questions", response_model=QuestionOut, status_code=201)
def add_question(
    household_member_id: str,
    body: QuestionIn,
    user_id: str = CurrentUserDep,
    role: str = CurrentRoleDep,
    session: Session = SessionDep,
) -> QuestionOut:
    q = service.add_question(
        session,
        user_id=user_id,
        household_member_id=household_member_id,
        question_text=body.question_text,
        raised_by=role or "caregiver",
        medication_id=body.medication_id,
    )
    return _question_out(q)


@router.get("/households/{household_member_id}/questions", response_model=list[QuestionOut])
def list_questions(
    household_member_id: str,
    status: str = Query(default="PENDING"),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[QuestionOut]:
    return [
        _question_out(q)
        for q in service.list_questions(
            session, user_id=user_id, household_member_id=household_member_id, status=status
        )
    ]


@router.post("/questions/{question_id}/discussed", response_model=QuestionOut)
def mark_discussed(
    question_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> QuestionOut:
    return _question_out(service.mark_discussed(session, user_id=user_id, question_id=question_id))


@router.get("/households/{household_member_id}/refill-list", response_model=list[RefillOut])
def refill_list(
    household_member_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[RefillOut]:
    return [
        RefillOut(medication_id=i.medication_id, name=i.name, dose=i.dose, reason=i.reason, basis=i.basis)
        for i in service.refill_list(
            session, user_id=user_id, household_member_id=household_member_id
        )
    ]


def _question_out(q) -> QuestionOut:
    return QuestionOut(
        id=q.id,
        medication_id=q.medication_id,
        question_text=q.question_text,
        raised_by=q.raised_by,
        status=q.status,
        created_at=q.created_at,
        discussed_at=q.discussed_at,
    )
