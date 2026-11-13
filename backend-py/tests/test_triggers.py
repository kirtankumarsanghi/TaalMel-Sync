from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.db.models import EmergencyContact, Medication, Notification
from app.engines.state import DimensionState, MedicationState
from app.engines.triggers import (
    Escalation,
    check_expiry,
    check_refill,
    triggers_for_event,
)
from app.events.types import EventType
from app.main import create_app
from app.ocr.stub import StubOcrProvider
from app.services.storage import LocalStorageService


# ── Refill rules (pure) ─────────────────────────────────────────────

def _state_with_available(status: str, age_days: int, quantity: str | None = None, expiry: str | None = None) -> MedicationState:
    details = {}
    if quantity:
        details["quantity_note"] = quantity
    if expiry:
        details["expiry_date"] = expiry
    available = DimensionState(
        status=status,
        last_verified=datetime(2026, 11, 1, tzinfo=UTC),
        age_days=age_days,
        stale=age_days > 30,
        source_event_id="e",
        details=details,
    )
    unknown = DimensionState(status="UNKNOWN", last_verified=None, age_days=None, stale=False, source_event_id=None)
    return MedicationState("m", unknown, available, unknown, unknown, None, [], 0)


def test_refill_not_triggered_inside_window() -> None:
    assert check_refill(_state_with_available("PRESENT", age_days=10)) is None


def test_refill_window_elapsed_triggers() -> None:
    result = check_refill(_state_with_available("PRESENT", age_days=31))
    assert result is not None
    assert result.rule == "REFILL_WINDOW_ELAPSED"
    assert result.level == Escalation.ACTION


def test_nearly_empty_triggers_before_window() -> None:
    result = check_refill(_state_with_available("PRESENT", age_days=5, quantity="nearly empty"))
    assert result is not None
    assert result.rule == "REFILL_LIKELY_NEEDED_SOON"


def test_no_availability_evidence_means_no_refill_trigger() -> None:
    unknown = DimensionState(status="UNKNOWN", last_verified=None, age_days=None, stale=False, source_event_id=None)
    state = MedicationState("m", unknown, unknown, unknown, unknown, None, [], 0)
    assert check_refill(state) is None


# ── Expiry rules (pure) ─────────────────────────────────────────────

TODAY = date(2026, 11, 13)


def test_expiry_far_away_is_quiet() -> None:
    state = _state_with_available("PRESENT", 1, expiry="2027-06-30")
    assert check_expiry(state, today=TODAY) is None


def test_expiry_within_30_days_warns() -> None:
    state = _state_with_available("PRESENT", 1, expiry="2026-12-01")
    result = check_expiry(state, today=TODAY)
    assert result is not None
    assert result.rule == "MEDICINE_EXPIRING_SOON"
    assert result.expired is False
    assert result.level == Escalation.ACTION


def test_expired_stock_is_critical() -> None:
    state = _state_with_available("PRESENT", 1, expiry="2026-10-01")
    result = check_expiry(state, today=TODAY)
    assert result is not None
    assert result.expired is True
    assert result.level == Escalation.CRITICAL


def test_missing_expiry_does_not_guess() -> None:
    assert check_expiry(_state_with_available("PRESENT", 1), today=TODAY) is None


def test_evidence_events_have_a_trigger() -> None:
    for event_type in (EventType.MEDICATION_REPORTED, EventType.AVAILABILITY_OBSERVED, EventType.MEDICATION_CONFIRMED):
        assert triggers_for_event(event_type)


# ── HTTP ────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine, tmp_path: Path) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    app = create_app()
    app.dependency_overrides[db_session] = override_session
    app.dependency_overrides[rx_routes.engine_dep] = lambda: engine
    app.dependency_overrides[rx_routes.storage_dep] = lambda: LocalStorageService(tmp_path / "up")
    app.dependency_overrides[rx_routes.ocr_provider_dep] = lambda: StubOcrProvider()
    with TestClient(app) as c:
        yield c


def _setup(client: TestClient, phone: str) -> tuple[str, str, str, dict[str, str]]:
    reg = client.post(
        "/api/auth/register",
        json={"name": "Asha", "phone": phone, "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    created = client.post(
        "/api/households", headers=headers,
        json={"household_name": "F", "patient_display_name": "Amma", "consent_recorded": True},
    ).json()
    member_id = created["patient"]["household_member_id"]
    rx = client.post(
        "/api/prescriptions/upload", headers=headers, params={"household_member_id": member_id},
        files={"file": (f"{phone}.jpg", f"scan-{phone}".encode(), "image/jpeg")},
    ).json()
    verify = client.post(
        f"/api/prescriptions/{rx['id']}/verify", headers=headers,
        json={"items": [{"item_id": rx["items"][0]["id"], "medication_name": "Glucophage 500mg"}]},
    ).json()
    return verify["medication_results"][0]["medication_id"], member_id, reg["user"]["id"], headers


def test_evidence_write_creates_conflict_notification(client: TestClient, engine) -> None:
    med_id, _, _, headers = _setup(client, "9600000001")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})

    notes = client.get("/api/notifications", headers=headers).json()
    conflicts = [n for n in notes if n["rule"] == "EVIDENCE_CONFLICT"]
    assert conflicts, [n["rule"] for n in notes]


def test_expired_stock_notifies_emergency_contact_too(client: TestClient, engine) -> None:
    med_id, member_id, owner_id, headers = _setup(client, "9600000002")

    # Add an emergency contact (a second registered user).
    contact = client.post(
        "/api/auth/register",
        json={"name": "Uncle", "phone": "9600000003", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    with Session(engine) as s:
        s.add(EmergencyContact(household_member_id=member_id, user_id=contact["user"]["id"], relationship="brother"))
        s.commit()

    # Recording expired stock notifies immediately, at CRITICAL, so it escalates.
    client.post(f"/api/medications/{med_id}/availability", headers=headers,
                json={"present": True, "expiry_date": "2020-01-01T00:00:00+00:00"})

    notes = client.get("/api/notifications", headers=headers).json()
    expired = [n for n in notes if n["rule"] == "MEDICINE_EXPIRED"]
    assert expired, [n["rule"] for n in notes]
    assert expired[0]["title"].startswith("[CRITICAL]")

    with Session(engine) as s:
        recipients = {n.user_id for n in s.exec(select(Notification).where(Notification.rule == "MEDICINE_EXPIRED")).all()}
    assert owner_id in recipients
    assert contact["user"]["id"] in recipients


def test_expired_stock_is_announced_once_not_twice(client: TestClient, engine) -> None:
    """Regression: the availability write and /checks both announced the same expiry."""
    med_id, _, _, headers = _setup(client, "9600000007")
    client.post(f"/api/medications/{med_id}/availability", headers=headers,
                json={"present": True, "expiry_date": "2020-01-01T00:00:00+00:00"})

    # Repeated checks must not add a second announcement of the same expiry.
    client.post(f"/api/medications/{med_id}/checks", headers=headers)
    client.post(f"/api/medications/{med_id}/checks", headers=headers)

    with Session(engine) as s:
        expiry_notes = s.exec(select(Notification).where(Notification.rule == "MEDICINE_EXPIRED")).all()
    assert len(expiry_notes) == 1


def test_repeat_checks_do_not_duplicate_notifications(client: TestClient, engine) -> None:
    med_id, _, _, headers = _setup(client, "9600000004")
    client.post(f"/api/medications/{med_id}/availability", headers=headers,
                json={"present": True, "quantity_note": "nearly empty"})

    first = client.post(f"/api/medications/{med_id}/checks", headers=headers).json()
    second = client.post(f"/api/medications/{med_id}/checks", headers=headers).json()
    assert first
    assert second == []

    with Session(engine) as s:
        refill = s.exec(select(Notification).where(Notification.rule == "REFILL_LIKELY_NEEDED_SOON")).all()
        assert len(refill) == 1


def test_notifications_are_per_user_and_markable_read(client: TestClient, engine) -> None:
    med_id, _, _, headers = _setup(client, "9600000005")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})

    mine = client.get("/api/notifications", headers=headers).json()
    assert mine
    note_id = mine[0]["id"]
    marked = client.post(f"/api/notifications/{note_id}/read", headers=headers)
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True

    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9600000006", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    s_headers = {"Authorization": f"Bearer {stranger['access_token']}"}
    assert client.get("/api/notifications", headers=s_headers).json() == []
    assert client.post(f"/api/notifications/{note_id}/read", headers=s_headers).status_code == 404
