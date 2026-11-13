from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.db.models import Case, Conflict, Event
from app.engines.cases import VALID_TRANSITIONS, can_transition
from app.engines.conflicts import detect
from app.engines.state import DimensionState, MedicationState
from app.events.types import CaseStatus, Dimension
from app.main import create_app
from app.ocr.stub import StubOcrProvider
from app.services.storage import LocalStorageService


# ── Pure conflict rules (no database) ───────────────────────────────

NOW = datetime(2026, 11, 13, tzinfo=UTC)


def _dim(status: str, age_days: int = 1, stale: bool = False) -> DimensionState:
    return DimensionState(
        status=status,
        last_verified=NOW - timedelta(days=age_days),
        age_days=age_days,
        stale=stale,
        source_event_id="e",
    )


def _unknown() -> DimensionState:
    return DimensionState(status="UNKNOWN", last_verified=None, age_days=None, stale=False, source_event_id=None)


def _state(
    prescribed: DimensionState | None = None,
    available: DimensionState | None = None,
    reported: DimensionState | None = None,
    confirmed: DimensionState | None = None,
) -> MedicationState:
    return MedicationState(
        medication_id="m",
        prescribed=prescribed or _unknown(),
        available=available or _unknown(),
        reported_taking=reported or _unknown(),
        confirmed_status=confirmed or _unknown(),
        current_dose=None,
        dose_history=[],
        event_count=0,
    )


def test_prescription_active_but_reported_stopped_is_a_conflict() -> None:
    result = detect(_state(prescribed=_dim("ACTIVE"), reported=_dim("STOPPED")))
    types = [c.conflict_type for c in result.conflicts]
    assert "PRESCRIPTION_VS_REPORT" in types


def test_confirmed_discontinuation_explains_stopping() -> None:
    result = detect(_state(
        prescribed=_dim("ACTIVE"),
        reported=_dim("STOPPED"),
        confirmed=_dim("DISCONTINUED"),
    ))
    assert not any(c.conflict_type == "PRESCRIPTION_VS_REPORT" for c in result.conflicts)


def test_reported_taking_but_absent_is_a_conflict() -> None:
    result = detect(_state(reported=_dim("TAKING"), available=_dim("ABSENT")))
    assert [c.conflict_type for c in result.conflicts] == ["REPORT_VS_AVAILABILITY"]


def test_stopped_while_still_present_is_unexplained() -> None:
    result = detect(_state(reported=_dim("STOPPED"), available=_dim("PRESENT")))
    assert [c.conflict_type for c in result.conflicts] == ["STOPPED_BUT_UNEXPLAINED"]


def test_consistent_evidence_has_no_conflict() -> None:
    result = detect(_state(prescribed=_dim("ACTIVE"), reported=_dim("TAKING"), available=_dim("PRESENT")))
    assert result.conflicts == ()


def test_stale_evidence_does_not_trigger_a_conflict() -> None:
    """Comparing a 90-day-old 'stopped' report with fresh evidence would be a false alarm."""
    stale_report = _dim("STOPPED", age_days=90, stale=True)
    result = detect(_state(prescribed=_dim("ACTIVE"), reported=stale_report))
    assert result.conflicts == ()
    assert Dimension.REPORTED_TAKING in result.stale_dimensions


def test_each_conflict_names_at_least_one_dimension_and_a_question() -> None:
    result = detect(_state(prescribed=_dim("ACTIVE"), reported=_dim("STOPPED"), available=_dim("PRESENT")))
    assert result.conflicts
    for c in result.conflicts:
        # Expired stock is a fact about a single dimension; the others compare two or more.
        assert len(c.dimensions_involved) >= 1
        assert c.suggested_question.endswith("?")


# ── Case transitions (pure) ─────────────────────────────────────────

def test_transition_table_matches_reference() -> None:
    assert can_transition("OPEN", CaseStatus.RESOLVED)
    assert can_transition("OPEN", CaseStatus.AWAITING_INFO)
    assert can_transition("STILL_UNCERTAIN", CaseStatus.OPEN)
    assert not can_transition("RESOLVED", CaseStatus.OPEN)
    assert not can_transition("RESOLVED", CaseStatus.STILL_UNCERTAIN)
    assert VALID_TRANSITIONS[CaseStatus.RESOLVED] == frozenset()


def test_unknown_status_is_rejected_not_crashed() -> None:
    assert can_transition("NOT_A_STATUS", CaseStatus.RESOLVED) is False


# ── HTTP: detection, lifecycle, and the old-code bugs ───────────────

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
    """Returns (medication_id, household_member_id, headers) for an active prescription."""
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


def test_stopped_report_with_stock_present_opens_one_case_per_conflict_type(client: TestClient, engine) -> None:
    """Prescription is active and the patient stopped while stock is present: two distinct conflicts.

    Evidence writes now run reconciliation themselves, so the cases exist without an explicit /detect.
    """
    med_id, member_id, headers = _setup(client, "9400000001")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False, "reason": "FORGOT"})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})

    cases = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    assert len(cases) == 2, cases
    assert all(c["status"] == "OPEN" for c in cases)

    with Session(engine) as s:
        conflict_events = s.exec(select(Event).where(Event.event_type == "ConflictDetected")).all()
        payloads = [e.payload for e in conflict_events]
        assert len(conflict_events) == 2
        assert any('"conflict_type": "STOPPED_BUT_UNEXPLAINED"' in p for p in payloads)
        assert any('"conflict_type": "PRESCRIPTION_VS_REPORT"' in p for p in payloads)
        assert len(s.exec(select(Conflict)).all()) == 2


def test_repeat_detection_does_not_open_duplicate_cases(client: TestClient, engine) -> None:
    """Regression: the TS code opened a new case on every run for the same conflict."""
    med_id, member_id, headers = _setup(client, "9400000002")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})

    # Triggered run already opened two cases; an explicit run must open nothing.
    assert len(client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()) == 2
    assert client.post(f"/api/medications/{med_id}/detect", headers=headers).json() == []

    with Session(engine) as s:
        assert len(s.exec(select(Case)).all()) == 2


def test_no_conflict_when_evidence_is_consistent(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9400000003")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": True})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    assert client.post(f"/api/medications/{med_id}/detect", headers=headers).json() == []


def test_assign_action_moves_open_case_to_awaiting_info(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9400000004")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    case_id = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()[0]["id"]

    r = client.post(f"/api/cases/{case_id}/action", headers=headers,
                    json={"action_description": "Call the doctor's clinic"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "AWAITING_INFO"
    assert r.json()["action_taken"] == "Call the doctor's clinic"


def test_resolved_case_stays_out_of_open_list_but_is_still_retrievable(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9400000005")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    opened = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    case_id = opened[0]["id"]
    other_id = opened[1]["id"]

    open_before = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    assert {c["id"] for c in open_before} == {case_id, other_id}

    r = client.post(f"/api/cases/{case_id}/resolve", headers=headers,
                    json={"outcome": "RESOLVED", "resolution_note": "Doctor confirmed stop"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "RESOLVED"
    assert r.json()["resolved_at"] is not None

    open_after = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    assert [c["id"] for c in open_after] == [other_id]
    with Session(engine) as s:
        assert s.get(Case, case_id) is not None
        assert any(e.event_type == "CaseResolved" for e in s.exec(select(Event)).all())


def test_resolved_case_cannot_be_reopened_or_changed(client: TestClient, engine) -> None:
    """Regression: the TS code let a bad transition throw an unhandled error."""
    med_id, member_id, headers = _setup(client, "9400000006")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    case_id = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()[0]["id"]
    client.post(f"/api/cases/{case_id}/resolve", headers=headers, json={"outcome": "RESOLVED"})

    again = client.post(f"/api/cases/{case_id}/resolve", headers=headers, json={"outcome": "STILL_UNCERTAIN"})
    assert again.status_code == 409
    action = client.post(f"/api/cases/{case_id}/action", headers=headers,
                         json={"action_description": "too late"})
    assert action.status_code == 409


def test_resolve_rejects_outcome_outside_allowed_set(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9400000007")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    case_id = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()[0]["id"]

    r = client.post(f"/api/cases/{case_id}/resolve", headers=headers, json={"outcome": "OPEN"})
    assert r.status_code == 400


def test_stranger_cannot_detect_or_act_on_cases(client: TestClient, engine) -> None:
    med_id, member_id, headers = _setup(client, "9400000008")
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True})
    case_id = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()[0]["id"]

    stranger = client.post(
        "/api/auth/register",
        json={"name": "Ravi", "phone": "9400000009", "password": "correct-horse-battery", "role": "caregiver"},
    ).json()
    s_headers = {"Authorization": f"Bearer {stranger['access_token']}"}
    assert client.post(f"/api/medications/{med_id}/detect", headers=s_headers).status_code == 403


def test_resolving_one_conflict_does_not_close_a_same_type_conflict(
    client: TestClient, engine
) -> None:
    """Regression: conflicts were closed by type, so one resolution closed them all.

    The reachable path: marking a case STILL_UNCERTAIN deliberately leaves its conflict
    row OPEN, so a later re-detection can produce a second conflict of the same type.
    Resolving one case must close only its own conflict.
    """
    from app.db.models import Conflict

    med_id, member_id, headers = _setup(client, "9400000011")

    # First conflict, then mark it uncertain: the case leaves the open list, the
    # conflict row stays OPEN by design.
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    first = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    assert first
    client.post(
        f"/api/cases/{first[0]['id']}/resolve",
        headers=headers,
        json={"outcome": "STILL_UNCERTAIN"},
    )

    # Re-detection creates a second conflict of the same type.
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": True})
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})

    with Session(engine) as s:
        both = s.exec(
            select(Conflict).where(
                Conflict.medication_id == med_id,
                Conflict.type == "PRESCRIPTION_VS_REPORT",
                Conflict.status == "OPEN",
            )
        ).all()
    assert len(both) == 2, [c.status for c in both]

    # Resolve the currently open case; only ITS conflict may close.
    current = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    assert current
    resolved_case_id = current[0]["id"]
    client.post(
        f"/api/cases/{resolved_case_id}/resolve", headers=headers, json={"outcome": "RESOLVED"}
    )

    from app.db.models import Case

    with Session(engine) as s:
        case = s.get(Case, resolved_case_id)
        assert case is not None and case.trigger_event_id is not None
        own = s.exec(
            select(Conflict).where(Conflict.trigger_event_id == case.trigger_event_id)
        ).first()
        other = s.exec(
            select(Conflict).where(
                Conflict.medication_id == med_id,
                Conflict.type == "PRESCRIPTION_VS_REPORT",
                Conflict.trigger_event_id != case.trigger_event_id,
            )
        ).first()

    # The conflict belonging to the resolved case is the one that closed...
    assert own is not None and own.status == "RESOLVED"
    # ...and the unrelated same-type conflict is untouched.
    assert other is not None and other.status == "OPEN"
