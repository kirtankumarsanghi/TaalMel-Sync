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
    channel: str | None = None
    delivered_at: datetime | None = None
    delivery_error: str | None = None
    created_at: datetime


def _out(note: Notification) -> NotificationOut:
    return NotificationOut(
        id=note.id,
        title=note.title,
        body=note.body,
        rule=note.rule,
        is_read=note.is_read,
        channel=note.channel,
        delivered_at=note.delivered_at,
        delivery_error=note.delivery_error,
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


class ExpiryAlertOut(BaseModel):
    medication_id: str
    medication_name: str
    expiry_date: str
    days_remaining: int
    expired: bool
    message: str


@router.get("/patients/{patient_id}/expiry-alerts", response_model=list[ExpiryAlertOut])
def expiry_alerts(
    patient_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[ExpiryAlertOut]:
    from sqlmodel import select

    from app.consent.service import authorize_member
    from app.db.models import Medication, Patient
    from app.engines.state import compute_state
    from app.engines.triggers import check_expiry
    from app.events import store as events

    patient = session.get(Patient, patient_id)
    member_id = patient.household_member_id if patient is not None else patient_id
    authorize_member(session, user_id, member_id)
    meds = session.exec(
        select(Medication).where(Medication.household_member_id == member_id)
    ).all()
    alerts: list[ExpiryAlertOut] = []
    for med in meds:
        state = compute_state(med.id, list(events.events_for_medication(session, med.id)))
        expiry = check_expiry(state)
        if expiry is not None:
            alerts.append(
                ExpiryAlertOut(
                    medication_id=med.id,
                    medication_name=med.name_generic or med.name_raw,
                    expiry_date=expiry.expiry_date.isoformat(),
                    days_remaining=expiry.days_remaining,
                    expired=expiry.expired,
                    message=expiry.message,
                )
            )
    return alerts
