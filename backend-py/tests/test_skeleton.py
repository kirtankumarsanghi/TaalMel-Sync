from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import models
from app.main import create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_all_phase1_tables_create_and_round_trip() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    expected = {
        "users", "refresh_tokens", "households", "household_members", "patients",
        "caregiver_access", "consents", "medication_canonicals", "medications",
        "normalization_logs", "prescriptions", "prescription_items", "events",
        "cases", "conflicts", "notifications", "audit_records",
    }
    assert expected.issubset(SQLModel.metadata.tables.keys())

    with Session(engine) as session:
        user = models.User(role="caregiver", name="Asha", password_hash="x")
        session.add(user)
        session.commit()
        session.refresh(user)
        rows = session.exec(select(models.User).where(models.User.name == "Asha")).all()
        assert len(rows) == 1
        assert rows[0].id == user.id
