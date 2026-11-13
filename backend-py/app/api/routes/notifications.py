from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.db.models import Notification
from app.services import triggers as service

router = APIRouter()


class NotificationOut(BaseModel):
    id: str
    title: str
    body: str
    rule: str | None
    is_read: bool
    created_at: datetime


def _out(note: Notification) -> NotificationOut:
    return NotificationOut(
        id=note.id,
        title=note.title,
        body=note.body,
        rule=note.rule,
        is_read=note.is_read,
        created_at=note.created_at,
    )


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(user_id: str = CurrentUserDep, session: Session = SessionDep) -> list[NotificationOut]:
    return [_out(n) for n in service.list_notifications(session, user_id=user_id)]


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> NotificationOut:
    return _out(service.mark_read(session, user_id=user_id, notification_id=notification_id))


@router.post("/medications/{medication_id}/checks", response_model=list[NotificationOut])
def run_checks(
    medication_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[NotificationOut]:
    """Refill-window and expiry checks for one medication. Safe to call repeatedly."""
    created = service.run_periodic_checks(session, user_id=user_id, medication_id=medication_id)
    return [_out(n) for n in created]
