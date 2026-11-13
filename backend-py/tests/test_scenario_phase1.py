"""End-to-end Phase 1 scenario: the core loop from the plan.

PRESCRIBED -> OBSERVED -> RECONCILED -> WHY -> ACTION -> RESOLVED

Steps:
  1. register a caregiver, create a household with a patient
  2. upload a prescription, verify it -> a Medication exists with PRESCRIBED evidence
  3. report "not taking" and "stock present" -> conflicts are detected and cases open
  4. record the reason (RAN_OUT) -> the caregiver is notified, the case stays open
  5. assign an action and resolve the case -> it leaves the open list but stays in history
  6. replay the same idempotency key -> the original event is returned, no duplicate
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.db.models import Event, Notification
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


def test_full_core_loop(client: TestClient, engine) -> None:
    # 1. Register, create household + patient
    reg = client.post(
        "/api/auth/register",
        json={"name": "Asha", "phone": "9800000001", "password": "correct-horse-battery", "role": "caregiver"},
    )
    assert reg.status_code == 201
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    household = client.post(
        "/api/households",
        headers=headers,
        json={"household_name": "Sharma family", "patient_display_name": "Amma", "relationship": "mother", "consent_recorded": True},
    )
    assert household.status_code == 201
    member_id = household.json()["patient"]["household_member_id"]

    # 2. Upload + verify prescription -> Medication with PRESCRIBED evidence
    upload = client.post(
        "/api/prescriptions/upload",
        headers=headers,
        params={"household_member_id": member_id},
        files={"file": ("rx.jpg", b"scenario-scan", "image/jpeg")},
    )
    assert upload.status_code == 201, upload.text
    rx = upload.json()
    assert rx["ocr_status"] == "COMPLETED"

    verify = client.post(
        f"/api/prescriptions/{rx['id']}/verify",
        headers=headers,
        json={"items": [{"item_id": rx["items"][0]["id"], "medication_name": "Glucophage 500mg", "frequency": "bd"}]},
    )
    assert verify.status_code == 200, verify.text
    med_id = verify.json()["medication_results"][0]["medication_id"]

    state = client.get(f"/api/medications/{med_id}/state", headers=headers).json()
    assert state["prescribed"]["status"] == "ACTIVE"
    assert state["reported_taking"]["status"] == "UNKNOWN"  # nothing observed yet

    # 3. OBSERVED + RECONCILED: not taking, but stock present -> two conflicts, two cases
    client.post(f"/api/medications/{med_id}/report", headers=headers, json={"taking": False})
    client.post(f"/api/medications/{med_id}/availability", headers=headers, json={"present": True, "quantity_note": "ok"})

    cases = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    assert len(cases) == 2, [c["status"] for c in cases]
    case_id = cases[0]["id"]

    explain = client.get(f"/api/cases/{case_id}/explain", headers=headers).json()
    assert explain["why"]
    assert "Event recorded" in explain["source"]

    # 4. WHY: the real reason is that they ran out. The case stays open and the caregiver is told.
    reason = client.post(f"/api/cases/{case_id}/reason", headers=headers, json={"reason": "RAN_OUT"})
    assert reason.status_code == 200, reason.text
    assert reason.json()["case"]["status"] == "OPEN"
    assert reason.json()["action"] == "OPEN_CASE_NOTIFY_CAREGIVER"

    # 5. ACTION + RESOLVED: assign an action, then resolve. It leaves the open list but stays retrievable.
    action = client.post(f"/api/cases/{case_id}/action", headers=headers,
                         json={"action_description": "Arrange a refill from the pharmacy"})
    assert action.json()["status"] == "AWAITING_INFO"

    resolved = client.post(f"/api/cases/{case_id}/resolve", headers=headers,
                           json={"outcome": "RESOLVED", "resolution_note": "Refill collected"})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"

    still_open = client.get(f"/api/households/{member_id}/open-cases", headers=headers).json()
    assert case_id not in [c["id"] for c in still_open]

    history = client.get(f"/api/medications/{med_id}/history", headers=headers).json()
    types = [e["event_type"] for e in history]
    for required in ("MedicationNormalized", "MedicationReported", "AvailabilityObserved", "ConflictDetected", "ReasonRecorded", "CaseResolved"):
        assert required in types, (required, types)

    # 6. Replay the same idempotency key -> original event returned, no duplicate row
    key = {"Idempotency-Key": "scenario-report-1"}
    first = client.post(f"/api/medications/{med_id}/report", headers={**headers, **key},
                        json={"taking": True, "note": "refill collected"})
    second = client.post(f"/api/medications/{med_id}/report", headers={**headers, **key},
                         json={"taking": False})
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["payload"]["taking"] is True

    with Session(engine) as s:
        reports = s.exec(select(Event).where(Event.event_type == "MedicationReported")).all()
        # Two distinct reports (step 3 + step 6) plus the replayed one collapsed into the same row.
        assert len(reports) == 2
        assert any(n.rule is None for n in s.exec(select(Notification)).all())  # reason follow-up exists
