from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlmodel import Session, select

from app.db.models import Event
from app.events import store
from app.events.payloads import MedicationReportedPayload
from app.events.types import EventType, ReasonCode, Source


def test_appends_and_reads_back_valid_event(session: Session, member_and_medication) -> None:
    member_id, medication_id = member_and_medication

    event = store.append_event(
        session,
        event_type=EventType.MEDICATION_REPORTED,
        payload=MedicationReportedPayload(medication_id=medication_id, taking=True),
        source=Source.PATIENT,
        medication_id=medication_id,
    )
    session.commit()

    fetched = store.get_event(session, event.id)
    assert fetched.event_type == "MedicationReported"
    assert fetched.household_member_id == member_id
    assert store.decode_payload(fetched)["taking"] is True
    assert [e.id for e in store.events_for_medication(session, medication_id)] == [event.id]
    assert [e.id for e in store.events_for_member(session, member_id)] == [event.id]


def test_rejects_unknown_event_type(session: Session, member_and_medication) -> None:
    member_id, _ = member_and_medication
    with pytest.raises(store.UnknownEventTypeError, match="NON_EXISTENT"):
        store.append_event(
            session,
            event_type="NON_EXISTENT",
            payload={},
            source=Source.SYSTEM,
            household_member_id=member_id,
        )


def test_rejects_payload_with_wrong_types(session: Session, member_and_medication) -> None:
    member_id, medication_id = member_and_medication
    with pytest.raises(ValidationError):
        store.append_event(
            session,
            event_type=EventType.PRESCRIPTION_UPLOADED,
            payload={"prescription_id": "not-a-uuid", "file_storage_key": 123},
            source=Source.SYSTEM,
            household_member_id=member_id,
        )


def test_rejects_unknown_payload_fields(session: Session, member_and_medication) -> None:
    """The old TS code let typos through silently. Extra fields must fail now."""
    member_id, medication_id = member_and_medication
    with pytest.raises(ValidationError, match="extra"):
        store.append_event(
            session,
            event_type=EventType.MEDICATION_REPORTED,
            payload={"medication_id": medication_id, "taking": True, "reportType": "TAKING"},
            source=Source.PATIENT,
            household_member_id=member_id,
        )


def test_rejects_invalid_reason_code(session: Session, member_and_medication) -> None:
    _, medication_id = member_and_medication
    with pytest.raises(ValidationError):
        MedicationReportedPayload(
            medication_id=medication_id, taking=False, reason="BORED"  # type: ignore[arg-type]
        )


def test_valid_reason_code_is_accepted(session: Session, member_and_medication) -> None:
    _, medication_id = member_and_medication
    payload = MedicationReportedPayload(
        medication_id=medication_id, taking=False, reason=ReasonCode.RAN_OUT
    )
    assert payload.reason == ReasonCode.RAN_OUT


def test_idempotency_key_returns_original_event(session: Session, member_and_medication) -> None:
    member_id, medication_id = member_and_medication
    key = str(uuid4())

    first = store.append_event(
        session,
        event_type=EventType.MEDICATION_REPORTED,
        payload={"medication_id": medication_id, "taking": True},
        source=Source.PATIENT,
        medication_id=medication_id,
        idempotency_key=key,
    )
    session.commit()

    second = store.append_event(
        session,
        event_type=EventType.MEDICATION_REPORTED,
        payload={"medication_id": medication_id, "taking": False},
        source=Source.PATIENT,
        medication_id=medication_id,
        idempotency_key=key,
    )
    session.commit()

    assert second.id == first.id
    assert store.decode_payload(second)["taking"] is True
    assert len(session.exec(select(Event)).all()) == 1


def test_different_idempotency_keys_create_separate_events(
    session: Session, member_and_medication
) -> None:
    _, medication_id = member_and_medication
    payload = {"medication_id": medication_id, "taking": True}

    a = store.append_event(
        session, event_type=EventType.MEDICATION_REPORTED, payload=payload,
        source=Source.PATIENT, medication_id=medication_id, idempotency_key=str(uuid4()),
    )
    b = store.append_event(
        session, event_type=EventType.MEDICATION_REPORTED, payload=payload,
        source=Source.PATIENT, medication_id=medication_id, idempotency_key=str(uuid4()),
    )
    session.commit()
    assert a.id != b.id


def test_medication_id_resolves_household_member(session: Session, member_and_medication) -> None:
    member_id, medication_id = member_and_medication
    event = store.append_event(
        session,
        event_type=EventType.MEDICATION_REPORTED,
        payload={"medication_id": medication_id, "taking": True},
        source=Source.PATIENT,
        medication_id=medication_id,
    )
    assert event.household_member_id == member_id


def test_unknown_medication_is_rejected(session: Session, member_and_medication) -> None:
    with pytest.raises(store.EventNotFoundError):
        store.append_event(
            session,
            event_type=EventType.MEDICATION_REPORTED,
            payload={"medication_id": str(uuid4()), "taking": True},
            source=Source.PATIENT,
            medication_id=str(uuid4()),
        )


def test_store_exposes_no_update_or_delete_functions() -> None:
    """Append-only is a rule of the design, so guard it structurally."""
    public = {name for name in dir(store) if not name.startswith("_")}
    forbidden = {name for name in public if name.startswith(("update", "delete", "remove", "edit"))}
    assert forbidden == set()
