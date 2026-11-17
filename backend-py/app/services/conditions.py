"""Diagnosis records for the longitudinal history.

Extracted conditions are candidates, not facts: OCR reads "Acne grade III" from a page,
but a person confirms the wording before it groups anything. Duplicates are scoped to a
single source document, so the same condition recurring at a later visit is kept as a
separate, dated record rather than collapsed away.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from app.consent.service import AccessDenied, authorize_member
from app.db.models import Condition
from app.ocr.diagnoses import diagnoses_from_text


def _now() -> datetime:
    return datetime.now(UTC)


def sync_conditions_from_text(
    session: Session,
    *,
    household_member_id: str,
    raw_text: str,
    prescription_id: str | None = None,
    document_id: str | None = None,
) -> list[Condition]:
    """Store any explicitly-labelled diagnoses as unconfirmed candidates.

    Called from both intake paths. It never raises for unreadable text: a page without a
    diagnosis simply produces no rows.
    """
    names = diagnoses_from_text(raw_text)
    if not names:
        return []

    existing = {
        row.name.lower()
        for row in session.exec(
            select(Condition).where(
                Condition.household_member_id == household_member_id,
                Condition.source_prescription_id == prescription_id,
                Condition.source_document_id == document_id,
            )
        ).all()
    }

    created: list[Condition] = []
    for name in names:
        if name.lower() in existing:
            continue
        condition = Condition(
            household_member_id=household_member_id,
            name=name,
            name_raw=name,
            source_prescription_id=prescription_id,
            source_document_id=document_id,
            confirmed=False,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(condition)
        session.flush()
        existing.add(name.lower())
        created.append(condition)
    return created


def list_conditions(session: Session, *, user_id: str, household_member_id: str) -> list[Condition]:
    authorize_member(session, user_id, household_member_id)
    return list(
        session.exec(
            select(Condition)
            .where(Condition.household_member_id == household_member_id)
            .order_by(Condition.created_at)
        ).all()
    )


def verify_condition(
    session: Session, *, user_id: str, condition_id: str, name: str | None = None
) -> Condition:
    condition = session.get(Condition, condition_id)
    if condition is None:
        raise AccessDenied("Condition not found", status_code=404)
    authorize_member(session, user_id, condition.household_member_id)

    cleaned = (name or condition.name).strip()
    if not cleaned:
        raise AccessDenied("Condition name cannot be empty", status_code=400)
    if condition.name_raw is None:
        condition.name_raw = condition.name

    condition.name = cleaned[:120]
    condition.confirmed = True
    condition.confirmed_at = _now()
    condition.confirmed_by_user_id = user_id
    condition.updated_at = _now()
    session.add(condition)
    session.commit()
    return condition


def add_manual_condition(
    session: Session,
    *,
    user_id: str,
    household_member_id: str,
    name: str,
    onset_date: datetime | None = None,
) -> Condition:
    """A person states a condition that OCR missed. This is already confirmed."""
    authorize_member(session, user_id, household_member_id)
    cleaned = name.strip()
    if not cleaned:
        raise AccessDenied("Condition name cannot be empty", status_code=400)

    now = _now()
    condition = Condition(
        household_member_id=household_member_id,
        name=cleaned[:120],
        name_raw=None,
        onset_date=onset_date,
        confirmed=True,
        confirmed_at=now,
        confirmed_by_user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(condition)
    session.commit()
    return condition
