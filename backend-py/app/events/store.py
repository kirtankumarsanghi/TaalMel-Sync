"""Append-only event log.

Rules enforced here:
- Payloads are validated against the typed model for their event type before write.
- Unknown event types are rejected.
- A repeated idempotency_key returns the original event; the new payload is ignored.
- There are no update or delete functions. Corrections are new events.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import Event, Medication
from app.events.payloads import PAYLOAD_MODELS
from app.events.types import EventType, Source


class UnknownEventTypeError(ValueError):
    pass


class EventNotFoundError(LookupError):
    pass


def _validate(event_type: str, payload: BaseModel | dict[str, Any]) -> dict[str, Any]:
    model = PAYLOAD_MODELS.get(event_type)
    if model is None:
        raise UnknownEventTypeError(f"Unknown event type: {event_type}")
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    validated = model.model_validate(payload)
    return validated.model_dump(mode="json")


def _resolve_household_member_id(
    session: Session, household_member_id: str | None, medication_id: str | None
) -> str:
    if household_member_id:
        return household_member_id
    if medication_id:
        medication = session.get(Medication, medication_id)
        if medication is None:
            raise EventNotFoundError("Medication not found for event logging.")
        return medication.household_member_id
    raise ValueError("household_member_id is required when no medication_id is given.")


def append_event(
    session: Session,
    *,
    event_type: EventType | str,
    payload: BaseModel | dict[str, Any],
    source: Source | str,
    household_member_id: str | None = None,
    medication_id: str | None = None,
    source_user_id: str | None = None,
    created_by: str | None = None,
    idempotency_key: str | None = None,
    occurred_at: datetime | None = None,
) -> Event:
    event_type_str = str(event_type)
    clean_payload = _validate(event_type_str, payload)

    if idempotency_key:
        existing = session.exec(
            select(Event).where(Event.idempotency_key == idempotency_key)
        ).first()
        if existing is not None:
            return existing

    member_id = _resolve_household_member_id(session, household_member_id, medication_id)
    now = datetime.now(UTC)

    event = Event(
        household_member_id=member_id,
        medication_id=medication_id,
        event_type=event_type_str,
        payload=json.dumps(clean_payload),
        source=str(source),
        source_user_id=source_user_id,
        created_by=created_by,
        idempotency_key=idempotency_key,
        occurred_at=occurred_at or now,
        created_at=now,
    )
    session.add(event)
    try:
        session.flush()
    except IntegrityError:
        # Lost a race on the idempotency key: roll back and return the winner.
        session.rollback()
        if idempotency_key:
            winner = session.exec(
                select(Event).where(Event.idempotency_key == idempotency_key)
            ).first()
            if winner is not None:
                return winner
        raise
    return event


def get_event(session: Session, event_id: str) -> Event:
    event = session.get(Event, event_id)
    if event is None:
        raise EventNotFoundError(f"Event not found: {event_id}")
    return event


def events_for_medication(session: Session, medication_id: str) -> Sequence[Event]:
    return session.exec(
        select(Event)
        .where(Event.medication_id == medication_id)
        .order_by(Event.occurred_at, Event.created_at)
    ).all()


def events_for_member(session: Session, household_member_id: str) -> Sequence[Event]:
    return session.exec(
        select(Event)
        .where(Event.household_member_id == household_member_id)
        .order_by(Event.occurred_at, Event.created_at)
    ).all()


def decode_payload(event: Event) -> dict[str, Any]:
    return json.loads(event.payload)
