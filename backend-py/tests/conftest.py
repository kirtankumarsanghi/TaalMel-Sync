from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.db.models  # noqa: F401  (registers tables)
from app.db import models


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def member_and_medication(session: Session) -> tuple[str, str]:
    user = models.User(role="caregiver", name="Asha", password_hash="x")
    session.add(user)
    session.flush()

    household = models.Household(name="Test Household", created_by=user.id)
    session.add(household)
    session.flush()

    member = models.HouseholdMember(household_id=household.id, display_name="Patient")
    session.add(member)
    session.flush()

    medication = models.Medication(
        household_member_id=member.id, name_raw="Metformin 500mg"
    )
    session.add(medication)
    session.commit()
    return member.id, medication.id


@pytest.fixture
def new_uuid() -> str:
    return str(uuid4())
