import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import CurrentRoleDep, CurrentUserDep, SessionDep
from app.db.models import Event
from app.engines.state import DimensionState, MedicationState, compute_state
from app.events.types import ReasonCode
from app.services import evidence as service

router = APIRouter()


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    taking: bool
    reason: ReasonCode | None = None
    note: str | None = Field(default=None, max_length=500)


class AvailabilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    present: bool
    quantity_note: Literal["ok", "low", "nearly empty"] | None = None
    expiry_date: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["CONFIRMED", "DISCONTINUED", "UNCERTAIN"]
    confirmation_method: str = Field(min_length=1, max_length=120)


class DoseChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_dose: str = Field(min_length=1, max_length=60)
    changed_by: str = Field(min_length=1, max_length=120)
    previous_dose: str | None = Field(default=None, max_length=60)


class EventOut(BaseModel):
    id: str
    medication_id: str | None
    event_type: str
    source: str
    occurred_at: datetime
    payload: dict


class DimensionOut(BaseModel):
    status: str
    last_verified: datetime | None
    age_days: int | None
    stale: bool
    source_event_id: str | None
    details: dict


class DoseChangeOut(BaseModel):
    dose: str
    changed_at: datetime
    event_id: str


class StateOut(BaseModel):
    medication_id: str
    prescribed: DimensionOut
    available: DimensionOut
    reported_taking: DimensionOut
    confirmed_status: DimensionOut
    current_dose: str | None
    dose_history: list[DoseChangeOut]
    event_count: int


def _event_out(event: Event) -> EventOut:
    return EventOut(
        id=event.id,
        medication_id=event.medication_id,
        event_type=event.event_type,
        source=event.source,
        occurred_at=event.occurred_at,
        payload=json.loads(event.payload),
    )


def _dim_out(d: DimensionState) -> DimensionOut:
    return DimensionOut(
        status=d.status,
        last_verified=d.last_verified,
        age_days=d.age_days,
        stale=d.stale,
        source_event_id=d.source_event_id,
        details=d.details,
    )


def _state_out(state: MedicationState) -> StateOut:
    return StateOut(
        medication_id=state.medication_id,
        prescribed=_dim_out(state.prescribed),
        available=_dim_out(state.available),
        reported_taking=_dim_out(state.reported_taking),
        confirmed_status=_dim_out(state.confirmed_status),
        current_dose=state.current_dose,
        dose_history=[
            DoseChangeOut(dose=c.dose, changed_at=c.changed_at, event_id=c.event_id)
            for c in state.dose_history
        ],
        event_count=state.event_count,
    )


@router.post("/medications/{medication_id}/report", response_model=EventOut, status_code=201)
def report(
    medication_id: str,
    body: ReportIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: str = CurrentUserDep,
    role: str = CurrentRoleDep,
    session: Session = SessionDep,
) -> EventOut:
    event = service.report_taking(
        session,
        user_id=user_id,
        role=role,
        medication_id=medication_id,
        taking=body.taking,
        reason=body.reason,
        note=body.note,
        idempotency_key=idempotency_key,
    )
    return _event_out(event)


@router.post("/medications/{medication_id}/availability", response_model=EventOut, status_code=201)
def availability(
    medication_id: str,
    body: AvailabilityIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> EventOut:
    event = service.record_availability(
        session,
        user_id=user_id,
        medication_id=medication_id,
        present=body.present,
        quantity_note=body.quantity_note,
        expiry_date=body.expiry_date,
        note=body.note,
        idempotency_key=idempotency_key,
    )
    return _event_out(event)


@router.post("/medications/{medication_id}/confirm", response_model=EventOut, status_code=201)
def confirm(
    medication_id: str,
    body: ConfirmIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: str = CurrentUserDep,
    role: str = CurrentRoleDep,
    session: Session = SessionDep,
) -> EventOut:
    event = service.confirm_status(
        session,
        user_id=user_id,
        role=role,
        medication_id=medication_id,
        status=body.status,
        confirmation_method=body.confirmation_method,
        idempotency_key=idempotency_key,
    )
    return _event_out(event)


@router.post("/medications/{medication_id}/dose-change", response_model=EventOut, status_code=201)
def dose_change(
    medication_id: str,
    body: DoseChangeIn,
    user_id: str = CurrentUserDep,
    role: str = CurrentRoleDep,
    session: Session = SessionDep,
) -> EventOut:
    event = service.record_dose_change(
        session,
        user_id=user_id,
        role=role,
        medication_id=medication_id,
        new_dose=body.new_dose,
        changed_by=body.changed_by,
        previous_dose=body.previous_dose,
    )
    return _event_out(event)


@router.get("/medications/{medication_id}/history", response_model=list[EventOut])
def history(
    medication_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[EventOut]:
    events = service.history(session, user_id=user_id, medication_id=medication_id)
    return [_event_out(e) for e in events]


@router.get("/medications/{medication_id}/state", response_model=StateOut)
def state(
    medication_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> StateOut:
    events = service.history(session, user_id=user_id, medication_id=medication_id)
    return _state_out(compute_state(medication_id, list(events)))
