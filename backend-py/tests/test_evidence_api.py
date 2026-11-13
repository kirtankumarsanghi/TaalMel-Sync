from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.db.models import Event, Medication
from app.engines.state import STALE_THRESHOLD_DAYS, compute_state
from app.main import create_app
from app.ocr.stub import StubOcrProvider
from app.services.storage import LocalStorageService


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


def _register(client: TestClient, phone: str, name: str, role: str = "caregiver") -> dict:
    r = client.post(
        "/api/auth/register",
        json={"name": name, "phone": phone, "password": "correct-horse-battery", "role": role},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user_id": body["user"]["id"]}


def _setup_medication(client: TestClient, engine, phone: str) -> tuple[str, dict[str, str]]:
    """Caregiver with a household, plus one normalized medication (Metformin 500mg)."""
    caregiver = _register(client, phone, "Asha")
    headers = caregiver["headers"]
    created = client.post(
        "/api/households",
        headers=headers,
        json={"household_name": "Family", "patient_display_name": "Amma", "consent_recorded": True},
    ).json()
    member_id = created["patient"]["household_member_id"]

    rx = client.post(
        "/api/prescriptions/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": (f"rx-{phone}.jpg", f"scan-{phone}".encode(), "image/jpeg")},
    ).json()
    item_id = rx["items"][0]["id"]
    verify = client.post(
        f"/api/prescriptions/{rx['id']}/verify",
        headers=headers,
        json={"items": [{"item_id": item_id, "medication_name": "Glucophage 500mg", "frequency": "bd"}]},
    )
    assert verify.status_code == 200, verify.text
    medication_id = verify.json()["medication_results"][0]["medication_id"]
    return medication_id, headers


# ── Each evidence endpoint writes an event that the state engine reads ──

def test_report_taking_is_recorded_and_reflected_in_state(client: TestClient, engine) -> None:
    med_id, headers = _setup_medication(client, engine, "9300000001")

    r = client.post(f"/api/medications/{med_id}/report", headers=headers,
                    json={"taking": True})
    assert r.status_code == 201, r.text
    assert r.json()["event_type"] == "MedicationReported"
    assert r.json()["source"] == "caregiver"

    state = client.get(f"/api/medications/{med_id}/state", headers=headers).json()
    assert state["reported_taking"]["status"] == "TAKING"
    assert state["reported_taking"]["source_event_id"] == r.json()["id"]


def test_report_stopped_with_reason_round_trips(client: TestClient, engine) -> None:
    med_id, headers = _setup_medication(client, engine, "9300000002")
    client.post(f"/api/medications/{med_id}/report", headers=headers,
                json={"taking": False, "reason": "RAN_OUT"})

    state = client.get(f"/api/medications/{med_id}/state", headers=headers).json()
    assert state["reported_taking"]["status"] == "STOPPED"
    assert state["reported_taking"]["details"]["reason"] == "RAN_OUT"


def test_availability_is_recorded_and_reflected_in_state(client: TestClient, engine) -> None:
    med_id, headers = _setup_medication(client, engine, "9300000003")
    expiry = "2027-06-30T00:00:00+00:00"

    r = client.post(f"/api/medications/{med_id}/availability", headers=headers,
                    json={"present": True, "quantity_note": "low", "expiry_date": expiry})
    assert r.status_code == 201, r.text

    state = client.get(f"/api/medications/{med_id}/state", headers=headers).json()
    assert state["available"]["status"] == "PRESENT"
    assert state["available"]["details"]["quantity_note"] == "low"
    assert state["available"]["details"]["expiry_date"].startswith("2027-06-30")


def test_confirm_is_recorded_and_reflected_in_state(client: TestClient, engine) -> None:
    med_id, headers = _setup_medication(client, engine, "9300000004")
    r = client.post(f"/api/medications/{med_id}/confirm", headers=headers,
                    json={"status": "DISCONTINUED", "confirmation_method": "doctor phone call"})
    assert r.status_code == 201, r.text

    state = client.get(f"/api/medications/{med_id}/state", headers=headers).json()
    assert state["confirmed_status"]["status"] == "DISCONTINUED"
    assert state["confirmed_status"]["details"]["confirmed_by"] == "caregiver"


def test_prescribed_dimension_is_populated_after_verification(client: TestClient, engine) -> None:
    med_id, headers = _setup_medication(client, engine, "9300000005")
    state = client.get(f"/api/medications/{med_id}/state", headers=headers).json()
    assert state["prescribed"]["status"] == "ACTIVE"
    assert state["prescribed"]["source_event_id"] is not None


def test_history_lists_events_in_order(client: TestClient, engine) -> None:
    med_id, headers = _setup_medication(client, engine, "9300000006")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": True})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})

    hist = client.get(f"/api/medications/{med_id}/history", headers=headers).json()
    types = [e["event_type"] for e in hist]
    assert types.index("MedicationNormalized") < types.index("MedicationReported") < types.index("AvailabilityObserved")


# ── Idempotency ─────────────────────────────────────────────────────

def test_idempotency_key_returns_original_event(client: TestClient, engine) -> None:
    med_id, headers = _setup_medication(client, engine, "9300000007")
    key = {"Idempotency-Key": "report-once-abc"}

    first = client.post(f"/api/medications/{med_id}/report", headers={**headers, **key},
                        json={"taking": True}).json()
    second = client.post(f"/api/medications/{med_id}/report", headers={**headers, **key},
                         json={"taking": False}).json()

    assert second["id"] == first["id"]
    assert second["payload"]["taking"] is True

    with Session(engine) as s:
        reports = s.exec(select(Event).where(Event.event_type == "MedicationReported")).all()
        assert len(reports) == 1


# ── Validation ──────────────────────────────────────────────────────

def test_report_rejects_unknown_reason_code(client: TestClient, engine) -> None:
    med_id, headers = _setup_medication(client, engine, "9300000008")
    r = client.post(f"/api/medications/{med_id}/report", headers=headers,
                    json={"taking": False, "reason": "BORED"})
    assert r.status_code == 422


def test_report_rejects_unknown_fields(client: TestClient, engine) -> None:
    med_id, headers = _setup_medication(client, engine, "9300000009")
    r = client.post(f"/api/medications/{med_id}/report", headers=headers,
                    json={"taking": True, "reportType": "TAKING"})
    assert r.status_code == 422


def test_availability_rejects_unknown_quantity_note(client: TestClient, engine) -> None:
    med_id, headers = _setup_medication(client, engine, "9300000010")
    r = client.post(f"/api/medications/{med_id}/availability", headers=headers,
                    json={"present": True, "quantity_note": "plenty"})
    assert r.status_code == 422


def test_confirm_rejects_lowercase_status(client: TestClient, engine) -> None:
    """The old TS code compared against 'discontinued'. Only the enum value is accepted now."""
    med_id, headers = _setup_medication(client, engine, "9300000011")
    r = client.post(f"/api/medications/{med_id}/confirm", headers=headers,
                    json={"status": "discontinued", "confirmation_method": "call"})
    assert r.status_code == 422


# ── Authorization ───────────────────────────────────────────────────

def test_stranger_cannot_report_availability_or_confirm(client: TestClient, engine) -> None:
    med_id, _ = _setup_medication(client, engine, "9300000012")
    stranger = _register(client, "9300000013", "Ravi")["headers"]

    assert client.post(f"/api/medications/{med_id}/report", headers=stranger,
                       json={"taking": True}).status_code == 403
    assert client.post(f"/api/medications/{med_id}/availability", headers=stranger,
                       json={"present": True}).status_code == 403
    assert client.post(f"/api/medications/{med_id}/confirm", headers=stranger,
                       json={"status": "CONFIRMED", "confirmation_method": "x"}).status_code == 403
    assert client.get(f"/api/medications/{med_id}/state", headers=stranger).status_code == 403


def test_unknown_medication_is_404(client: TestClient, engine) -> None:
    _, headers = _setup_medication(client, engine, "9300000014")
    r = client.post("/api/medications/00000000-0000-0000-0000-000000000000/report",
                    headers=headers, json={"taking": True})
    assert r.status_code == 404


def test_source_comes_from_token_role_not_request(client: TestClient, engine) -> None:
    """A patient-role user is recorded as source=patient. The body cannot override it."""
    caregiver = _register(client, "9300000015", "Asha")
    created = client.post(
        "/api/households", headers=caregiver["headers"],
        json={"household_name": "F", "patient_display_name": "Amma", "consent_recorded": True},
    ).json()
    member_id = created["patient"]["household_member_id"]
    med_id = _medication_for_member(engine, member_id)

    patient_user = _register(client, "9300000016", "Amma", role="patient")
    # Grant the patient-role user access (consent recorded by them), via the creator.
    grant = client.post(
        "/api/access", headers=caregiver["headers"],
        json={"caregiver_user_id": patient_user["user_id"], "household_member_id": member_id},
    ).json()
    client.post(f"/api/access/{grant['id']}/consent", headers=patient_user["headers"], json={})

    r = client.post(f"/api/medications/{med_id}/report", headers=patient_user["headers"],
                    json={"taking": True, "note": "source-check"})
    assert r.status_code == 201
    assert r.json()["source"] == "patient"


def _medication_for_member(engine, member_id: str) -> str:
    with Session(engine) as s:
        med = Medication(household_member_id=member_id, name_raw="Test 10mg")
        s.add(med)
        s.commit()
        return med.id


# ── State engine (pure) ─────────────────────────────────────────────

def _event(event_type: str, occurred_at: datetime, payload: str, medication_id: str = "m1") -> Event:
    return Event(
        household_member_id="hm1",
        medication_id=medication_id,
        event_type=event_type,
        payload=payload,
        source="caregiver",
        occurred_at=occurred_at,
        created_at=occurred_at,
    )


def test_last_event_wins_for_a_dimension() -> None:
    base = datetime(2026, 11, 1, tzinfo=UTC)
    events = [
        _event("MedicationReported", base, '{"medication_id":"m1","taking":true}'),
        _event("MedicationReported", base + timedelta(days=1), '{"medication_id":"m1","taking":false,"reason":"FORGOT"}'),
    ]
    state = compute_state("m1", events, now=base + timedelta(days=2))
    assert state.reported_taking.status == "STOPPED"
    assert state.reported_taking.details["reason"] == "FORGOT"


def test_evidence_older_than_threshold_is_stale() -> None:
    now = datetime(2026, 11, 13, tzinfo=UTC)
    old = now - timedelta(days=STALE_THRESHOLD_DAYS + 1)
    events = [_event("AvailabilityObserved", old, '{"medication_id":"m1","present":true}')]
    state = compute_state("m1", events, now=now)
    assert state.available.status == "PRESENT"
    assert state.available.stale is True
    assert state.available.age_days == STALE_THRESHOLD_DAYS + 1


def test_fresh_evidence_is_not_stale() -> None:
    now = datetime(2026, 11, 13, tzinfo=UTC)
    recent = now - timedelta(days=2)
    events = [_event("AvailabilityObserved", recent, '{"medication_id":"m1","present":false}')]
    state = compute_state("m1", events, now=now)
    assert state.available.status == "ABSENT"
    assert state.available.stale is False


def test_dimension_without_evidence_is_unknown_not_guessed() -> None:
    state = compute_state("m1", [], now=datetime(2026, 11, 13, tzinfo=UTC))
    assert state.prescribed.status == "UNKNOWN"
    assert state.available.status == "UNKNOWN"
    assert state.reported_taking.status == "UNKNOWN"
    assert state.confirmed_status.status == "UNKNOWN"


def test_dose_changes_build_history_and_current_dose() -> None:
    base = datetime(2026, 11, 1, tzinfo=UTC)
    events = [
        _event("DoseChanged", base, '{"medication_id":"m1","new_dose":"500mg","changed_by":"doctor"}'),
        _event("DoseChanged", base + timedelta(days=10), '{"medication_id":"m1","new_dose":"1000mg","changed_by":"doctor"}'),
    ]
    state = compute_state("m1", events, now=base + timedelta(days=11))
    assert state.current_dose == "1000mg"
    assert [c.dose for c in state.dose_history] == ["500mg", "1000mg"]
