"""Part 1 correctness fixes: per-dimension freshness, expired stock as a case,
emergency contacts via API, dose changes, conflict rows closing."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.db.models import Case, Conflict, EmergencyContact, Event, Notification
from app.engines.conflicts import detect
from app.engines.state import FRESHNESS_DAYS, DimensionState, MedicationState, compute_state
from app.events.types import Dimension
from app.main import create_app
from app.ocr.stub import StubOcrProvider
from app.services.storage import LocalStorageService


# ── 1.1 Per-dimension freshness ─────────────────────────────────────

def _event(event_type: str, occurred_at: datetime, payload: str) -> Event:
    return Event(
        household_member_id="hm", medication_id="m", event_type=event_type,
        payload=payload, source="caregiver", occurred_at=occurred_at, created_at=occurred_at,
    )


def test_availability_goes_stale_in_days_but_prescription_does_not() -> None:
    now = datetime(2026, 11, 13, tzinfo=UTC)
    ten_days_ago = now - timedelta(days=10)
    events = [
        _event("MedicationNormalized", ten_days_ago,
               '{"medication_id":"m","name_generic":"Metformin","method":"EXACT_GENERIC_MATCH","confidence":1.0,"status":"NORMALIZED"}'),
        _event("AvailabilityObserved", ten_days_ago, '{"medication_id":"m","present":true}'),
    ]
    state = compute_state("m", events, now=now)
    assert state.available.stale is True       # 7-day window
    assert state.prescribed.stale is False     # 180-day window


def test_self_report_goes_stale_after_three_days() -> None:
    now = datetime(2026, 11, 13, tzinfo=UTC)
    four_days_ago = now - timedelta(days=4)
    events = [_event("MedicationReported", four_days_ago, '{"medication_id":"m","taking":true}')]
    assert compute_state("m", events, now=now).reported_taking.stale is True

    two_days_ago = now - timedelta(days=2)
    events = [_event("MedicationReported", two_days_ago, '{"medication_id":"m","taking":true}')]
    assert compute_state("m", events, now=now).reported_taking.stale is False


def test_freshness_windows_can_be_overridden() -> None:
    now = datetime(2026, 11, 13, tzinfo=UTC)
    events = [_event("AvailabilityObserved", now - timedelta(days=10), '{"medication_id":"m","present":true}')]
    state = compute_state("m", events, now=now, freshness_days={**FRESHNESS_DAYS, Dimension.AVAILABLE: 30})
    assert state.available.stale is False


# ── 1.2 Expired stock as a tracked case ─────────────────────────────

TODAY = datetime(2026, 11, 13, tzinfo=UTC)


def _state_with(available_status: str, expiry: str | None, stale: bool = False) -> MedicationState:
    details = {"expiry_date": expiry} if expiry else {}
    available = DimensionState(
        status=available_status, last_verified=TODAY, age_days=1, stale=stale,
        source_event_id="e", details=details,
    )
    unknown = DimensionState(status="UNKNOWN", last_verified=None, age_days=None, stale=False, source_event_id=None)
    return MedicationState("m", unknown, available, unknown, unknown, None, [], 0)


def test_expired_present_stock_is_a_conflict() -> None:
    result = detect(_state_with("PRESENT", "2026-10-01"), today=TODAY.date())
    assert [c.conflict_type for c in result.conflicts] == ["EXPIRED_STOCK"]


def test_unexpired_present_stock_is_not_a_conflict() -> None:
    assert detect(_state_with("PRESENT", "2027-06-30"), today=TODAY.date()).conflicts == ()


def test_absent_stock_is_never_an_expiry_conflict() -> None:
    assert detect(_state_with("ABSENT", "2020-01-01"), today=TODAY.date()).conflicts == ()


def test_expired_stock_conflict_is_not_suppressed_by_staleness() -> None:
    """Expiry is a durable fact: an old availability check still proves the strip is expired."""
    result = detect(_state_with("PRESENT", "2020-01-01", stale=True), today=TODAY.date())
    assert [c.conflict_type for c in result.conflicts] == ["EXPIRED_STOCK"]


# ── HTTP fixtures ───────────────────────────────────────────────────

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


def _setup(client: TestClient, phone: str) -> tuple[str, str, dict[str, str]]:
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
    return verify["medication_results"][0]["medication_id"], member_id, headers


def test_expired_stock_opens_a_case_that_can_be_resolved(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9900000001")
    client.post(f"/api/medications/{med_id}/availability", headers=headers,
                json={"present": True, "expiry_date": "2020-01-01T00:00:00+00:00"})

    cases = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    types = []
    with Session(engine) as s:
        for c in cases:
            trigger = s.get(Event, c["trigger_event_id"])
            types.append(__import__("json").loads(trigger.payload)["conflict_type"])
    assert "EXPIRED_STOCK" in types

    cases = client.post(f"/api/medications/{med_id}/detect", headers=headers).json()
    assert cases == []  # already open, no duplicate

    expired_case = next(
        c for c in client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
        if c["status"] == "OPEN"
    )
    resolved = client.post(f"/api/cases/{expired_case['id']}/resolve", headers=headers,
                           json={"outcome": "RESOLVED", "resolution_note": "Replaced at pharmacy"})
    assert resolved.status_code == 200


def test_expiry_warning_creates_notification_but_no_case(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9900000002")
    soon = (datetime.now(UTC).date() + timedelta(days=20)).isoformat()
    client.post(f"/api/medications/{med_id}/availability", headers=headers,
                json={"present": True, "expiry_date": soon})

    created = client.post(f"/api/medications/{med_id}/checks", headers=headers).json()
    assert any(n["rule"] == "MEDICINE_EXPIRING_SOON" for n in created)

    with Session(engine) as s:
        types = []
        for case in s.exec(select(Case)).all():
            trigger = s.get(Event, case.trigger_event_id) if case.trigger_event_id else None
            if trigger is not None:
                types.append(__import__("json").loads(trigger.payload).get("conflict_type"))
    assert "EXPIRED_STOCK" not in types


# ── 1.3 Emergency contacts ──────────────────────────────────────────

def test_creator_can_add_and_remove_emergency_contact(client: TestClient, engine) -> None:
    _, member_id, headers = _setup(client, "9900000003")
    contact = client.post(
        "/api/auth/register",
        json={"name": "Uncle", "phone": "9900000004", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()

    created = client.post(
        f"/api/households/{member_id}/emergency-contacts", headers=headers,
        json={"user_id": contact["user"]["id"], "relationship": "brother"},
    )
    assert created.status_code == 201, created.text

    listed = client.get(f"/api/households/{member_id}/emergency-contacts", headers=headers).json()
    assert [c["user_id"] for c in listed] == [contact["user"]["id"]]

    deleted = client.delete(
        f"/api/households/{member_id}/emergency-contacts/{created.json()['id']}", headers=headers
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/households/{member_id}/emergency-contacts", headers=headers).json() == []


def test_non_creator_cannot_manage_emergency_contacts(client: TestClient, engine) -> None:
    _, member_id, _ = _setup(client, "9900000005")
    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9900000006", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    r = client.post(
        f"/api/households/{member_id}/emergency-contacts",
        headers={"Authorization": f"Bearer {stranger['access_token']}"},
        json={"user_id": stranger["user"]["id"]},
    )
    assert r.status_code == 403


def test_contact_must_be_a_registered_user(client: TestClient, engine) -> None:
    _, member_id, headers = _setup(client, "9900000007")
    r = client.post(
        f"/api/households/{member_id}/emergency-contacts", headers=headers,
        json={"user_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 404


def test_emergency_contact_receives_critical_notification(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9900000008")
    contact = client.post(
        "/api/auth/register",
        json={"name": "Uncle", "phone": "9900000009", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    client.post(f"/api/households/{member_id}/emergency-contacts", headers=headers,
                json={"user_id": contact["user"]["id"]})

    client.post(f"/api/medications/{med_id}/availability", headers=headers,
                json={"present": True, "expiry_date": "2020-01-01T00:00:00+00:00"})
    client.post(f"/api/medications/{med_id}/checks", headers=headers)

    with Session(engine) as s:
        recipients = {
            n.user_id for n in s.exec(select(Notification).where(Notification.rule == "MEDICINE_EXPIRED")).all()
        }
    assert contact["user"]["id"] in recipients


# ── 1.4 Dose changes ────────────────────────────────────────────────

def test_dose_change_builds_history_and_sets_current_dose(client: TestClient, engine) -> None:
    med_id, _, headers = _setup(client, "9900000010")
    first = client.post(f"/api/medications/{med_id}/dose-change", headers=headers,
                        json={"new_dose": "500mg", "changed_by": "Dr Rao"})
    assert first.status_code == 201, first.text
    second = client.post(f"/api/medications/{med_id}/dose-change", headers=headers,
                         json={"new_dose": "1000mg", "changed_by": "Dr Rao", "previous_dose": "500mg"})
    assert second.status_code == 201

    state = client.get(f"/api/medications/{med_id}/state", headers=headers).json()
    assert state["current_dose"] == "1000mg"
    assert [c["dose"] for c in state["dose_history"]] == ["500mg", "1000mg"]


def test_dose_change_requires_access_and_valid_body(client: TestClient, engine) -> None:
    med_id, _, headers = _setup(client, "9900000011")
    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9900000012", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    denied = client.post(f"/api/medications/{med_id}/dose-change",
                         headers={"Authorization": f"Bearer {stranger['access_token']}"},
                         json={"new_dose": "1g", "changed_by": "x"})
    assert denied.status_code == 403
    bad = client.post(f"/api/medications/{med_id}/dose-change", headers=headers, json={"new_dose": ""})
    assert bad.status_code == 422


# ── 1.5 Conflict rows close on resolution ───────────────────────────

def test_resolving_a_case_closes_its_conflict_row(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9900000013")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})

    with Session(engine) as s:
        assert len(s.exec(select(Conflict).where(Conflict.status == "OPEN")).all()) == 2

    case_id = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()[0]["id"]
    client.post(f"/api/cases/{case_id}/resolve", headers=headers, json={"outcome": "RESOLVED"})

    with Session(engine) as s:
        assert len(s.exec(select(Conflict).where(Conflict.status == "OPEN")).all()) == 1


def test_still_uncertain_does_not_close_the_conflict(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9900000014")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    case_id = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()[0]["id"]

    client.post(f"/api/cases/{case_id}/resolve", headers=headers, json={"outcome": "STILL_UNCERTAIN"})

    with Session(engine) as s:
        assert len(s.exec(select(Conflict).where(Conflict.status == "OPEN")).all()) == 2


# ── 1.6 Affordability resources ─────────────────────────────────────

def test_could_not_afford_returns_named_resources(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9900000015")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    case_id = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()[0]["id"]

    body = client.post(f"/api/cases/{case_id}/reason", headers=headers,
                       json={"reason": "COULD_NOT_AFFORD"}).json()
    assert body["action"] == "SHOW_AFFORDABILITY_RESOURCES"
    assert body["resources"]
    assert all("url" in r and "name" in r for r in body["resources"])


def test_other_reasons_return_no_resources(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9900000016")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    case_id = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()[0]["id"]

    body = client.post(f"/api/cases/{case_id}/reason", headers=headers, json={"reason": "RAN_OUT"}).json()
    assert body["resources"] is None
