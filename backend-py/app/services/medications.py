"""Medication persistence built on the pure normalization rules.

- create_or_merge_from_item: turns one verified prescription item into a Medication.
  If the same member already has a medication with the same generic name and strength,
  it merges into that row instead of creating a duplicate.
- verify_normalization: a caregiver overrides the automated result. Recorded as
  MANUALLY_VERIFIED and emitted as an event.
Every change writes a NormalizationLog row.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.audit import service as audit
from app.consent.service import authorize_member
from app.db.models import Medication, MedicationCanonical, NormalizationLog, PrescriptionItem
from app.events import store as events
from app.events.payloads import (
    MedicationNormalizationVerifiedPayload,
    MedicationNormalizedPayload,
    MedicationNormalizationReviewPayload,
)
from app.events.types import EventType, Source
from app.services.normalization import (
    NormalizationInput,
    NormalizationResult,
    normalize_medication,
)


class MedicationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class MedicationOutcome:
    medication: Medication
    action: str  # "CREATED" | "MERGED"
    normalization: NormalizationResult


def _now() -> datetime:
    return datetime.now(UTC)


def _find_or_create_canonical(
    session: Session, result: NormalizationResult
) -> MedicationCanonical | None:
    if not result.name_generic or result.status == "NEEDS_REVIEW":
        return None
    candidates = session.exec(
        select(MedicationCanonical).where(
            MedicationCanonical.generic_name == result.name_generic,
            MedicationCanonical.strength == result.strength,
            MedicationCanonical.dosage_form == result.dosage_form,
        )
    ).all()
    if candidates:
        return candidates[0]

    entry = result.matched_entry
    canonical = MedicationCanonical(
        generic_name=result.name_generic,
        brand_names=json.dumps(list(entry.brand_names)) if entry else "[]",
        strength=result.strength,
        dosage_form=result.dosage_form,
        active_ingredient=entry.active_ingredient if entry else None,
        category=entry.category if entry else None,
    )
    session.add(canonical)
    session.flush()
    return canonical


def _log(
    session: Session,
    medication_id: str,
    input_raw: str,
    result: NormalizationResult,
    review_note: str | None = None,
) -> None:
    session.add(
        NormalizationLog(
            medication_id=medication_id,
            input_raw=input_raw,
            output_generic=result.name_generic,
            output_strength=result.strength,
            output_form=result.dosage_form,
            method=result.method,
            confidence=result.confidence,
            status=result.status,
            review_note=review_note,
            created_at=_now(),
        )
    )


def _find_duplicate(session: Session, member_id: str, result: NormalizationResult) -> Medication | None:
    if not result.name_generic:
        return None
    query = select(Medication).where(Medication.household_member_id == member_id)
    if result.strength:
        query = query.where(Medication.strength == result.strength)
    for med in session.exec(query).all():
        if med.name_generic and med.name_generic.lower() == result.name_generic.lower():
            return med
    return None


def create_or_merge_from_item(
    session: Session,
    *,
    user_id: str,
    item: PrescriptionItem,
    household_member_id: str,
) -> MedicationOutcome:
    raw = NormalizationInput(
        name_raw=item.medication_name,
        dosage=item.dosage,
        frequency=item.frequency,
        instructions=item.instructions,
    )
    result = normalize_medication(raw)
    canonical = _find_or_create_canonical(session, result)
    duplicate = _find_duplicate(session, household_member_id, result)
    now = _now()

    if duplicate is not None:
        med = duplicate
        med.name_brand = result.name_brand or med.name_brand
        med.strength = result.strength or med.strength
        med.strength_raw = result.strength_raw or med.strength_raw
        med.dosage_form = result.dosage_form or med.dosage_form
        med.dosage_form_raw = result.dosage_form_raw or med.dosage_form_raw
        med.frequency = result.frequency or med.frequency
        med.frequency_raw = result.frequency_raw or med.frequency_raw
        med.instructions_raw = item.instructions or med.instructions_raw
        med.instructions = item.instructions or med.instructions
        med.normalization_status = result.status
        med.normalization_method = result.method
        med.normalization_confidence = result.confidence
        med.canonical_id = canonical.id if canonical else med.canonical_id
        med.prescription_item_id = item.id
        med.identity_confirmed = result.status == "NORMALIZED"
        med.updated_at = now
        action = "MERGED"
        review_note = "Merged with existing record"
    else:
        med = Medication(
            household_member_id=household_member_id,
            name_raw=item.medication_name,
            name_generic=result.name_generic,
            name_brand=result.name_brand,
            dose_raw=item.dosage,
            strength=result.strength,
            strength_raw=result.strength_raw,
            dosage_form=result.dosage_form,
            dosage_form_raw=result.dosage_form_raw,
            frequency_raw=result.frequency_raw,
            frequency=result.frequency,
            instructions_raw=item.instructions,
            instructions=item.instructions,
            identity_confirmed=result.status == "NORMALIZED",
            normalization_status=result.status,
            normalization_method=result.method,
            normalization_confidence=result.confidence,
            canonical_id=canonical.id if canonical else None,
            prescription_item_id=item.id,
            created_at=now,
            updated_at=now,
        )
        action = "CREATED"
        review_note = None
    session.add(med)
    session.flush()

    _log(session, med.id, item.medication_name, result, review_note)

    if result.status in ("NEEDS_REVIEW", "AMBIGUOUS"):
        events.append_event(
            session,
            event_type=EventType.MEDICATION_NORMALIZATION_REVIEW,
            payload=MedicationNormalizationReviewPayload(
                medication_id=med.id,
                reason=f"{result.method} with status {result.status} (confidence {result.confidence:.2f})",
            ),
            source=Source.SYSTEM,
            medication_id=med.id,
            source_user_id=user_id,
        )
    else:
        events.append_event(
            session,
            event_type=EventType.MEDICATION_NORMALIZED,
            payload=MedicationNormalizedPayload(
                medication_id=med.id,
                name_generic=result.name_generic,
                method=result.method,
                confidence=result.confidence,
                status=result.status,
            ),
            source=Source.SYSTEM,
            medication_id=med.id,
            source_user_id=user_id,
        )

    return MedicationOutcome(medication=med, action=action, normalization=result)


def list_for_member(session: Session, *, user_id: str, household_member_id: str) -> list[Medication]:
    """Every medication for a patient, newest first."""
    authorize_member(session, user_id, household_member_id)
    return list(
        session.exec(
            select(Medication)
            .where(Medication.household_member_id == household_member_id)
            .order_by(Medication.created_at.desc())  # type: ignore[union-attr]
        ).all()
    )


def list_needing_review(session: Session, *, user_id: str, household_member_id: str) -> list[Medication]:
    authorize_member(session, user_id, household_member_id)
    return list(
        session.exec(
            select(Medication)
            .where(
                Medication.household_member_id == household_member_id,
                Medication.normalization_status.in_(["NEEDS_REVIEW", "AMBIGUOUS"]),  # type: ignore[attr-defined]
            )
            .order_by(Medication.created_at.desc())  # type: ignore[union-attr]
        ).all()
    )


def verify_normalization(
    session: Session,
    *,
    user_id: str,
    medication_id: str,
    name_generic: str,
    name_brand: str | None = None,
    strength: str | None = None,
    dosage_form: str | None = None,
) -> Medication:
    med = session.get(Medication, medication_id)
    if med is None:
        raise MedicationError("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)

    manual = NormalizationResult(
        name_generic=name_generic,
        name_brand=name_brand,
        strength=strength,
        strength_raw=med.strength_raw,
        strength_unit=None,
        dosage_form=dosage_form,
        dosage_form_raw=med.dosage_form_raw,
        frequency=med.frequency,
        frequency_raw=med.frequency_raw,
        active_ingredient=None,
        category=None,
        method="MANUAL",
        confidence=1.0,
        status="MANUALLY_VERIFIED",
        matched_entry=None,
    )
    canonical = _find_or_create_canonical(session, manual)

    med.name_generic = name_generic
    med.name_brand = name_brand or med.name_brand
    med.strength = strength or med.strength
    med.dosage_form = dosage_form or med.dosage_form
    med.normalization_status = "MANUALLY_VERIFIED"
    med.normalization_method = "MANUAL"
    med.normalization_confidence = 1.0
    med.canonical_id = canonical.id if canonical else None
    med.identity_confirmed = True
    med.updated_at = _now()
    session.add(med)
    session.flush()

    _log(session, med.id, med.name_raw, manual, review_note=f"Manually verified by user {user_id}")

    events.append_event(
        session,
        event_type=EventType.MEDICATION_NORMALIZATION_VERIFIED,
        payload=MedicationNormalizationVerifiedPayload(
            medication_id=med.id, name_generic=name_generic
        ),
        source=Source.CAREGIVER,
        medication_id=med.id,
        source_user_id=user_id,
        created_by=user_id,
    )
    audit.log(
        session,
        audit.AuditAction.MEDICATION_NORMALIZATION_VERIFIED,
        user_id=user_id,
        details={"medication_id": med.id, "name_generic": name_generic},
    )
    session.commit()
    return med
