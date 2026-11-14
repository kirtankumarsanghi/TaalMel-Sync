"""Medicine photo verification.

The caregiver photographs the actual strip or bottle. The system compares it against the
prescription record to catch lookalike errors — a different brand, a different strength.

The honest position: without a trained image-similarity model, the answer is
NOT_CHECKED. That is a real answer, and a useful one, because "not checked" tells the
caregiver to look at the strip themselves. Reporting MATCH from a weak comparison would
be actively dangerous, so the default is never MATCH.
"""

import hashlib
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlmodel import Session

from app.consent.service import authorize_member
from app.db.models import Medication, PhotoVerification
from app.services.reconciliation import CaseError
from app.services.storage import StorageService

Outcome = Literal["MATCH", "NO_MATCH", "NOT_CHECKED"]

# A comparison must clear this to be reported as a match at all. Deliberately high:
# a false MATCH is worse than an honest NOT_CHECKED.
MATCH_THRESHOLD = 0.85


@dataclass(frozen=True)
class Comparison:
    outcome: Outcome
    confidence: float | None
    detail: str


class ImageMatcher(Protocol):
    def compare(self, photo: bytes, mime_type: str, expected_name: str) -> Comparison: ...


class NoOpMatcher:
    """Fallback when no OCR/vision engine is available. Never fakes a MATCH."""

    def compare(self, photo: bytes, mime_type: str, expected_name: str) -> Comparison:
        return Comparison(
            outcome="NOT_CHECKED",
            confidence=None,
            detail=(
                f"No visual comparison was run, so this photo has not been checked against "
                f"the prescription. Please confirm the name, strength and manufacturer "
                f"yourself: expected {expected_name}."
            ),
        )


class OcrPhotoMatcher:
    """Compare text read from a strip/bottle photo against the expected medicine name."""

    def __init__(self, provider: object) -> None:
        self._provider = provider

    def compare(self, photo: bytes, mime_type: str, expected_name: str) -> Comparison:
        from difflib import SequenceMatcher

        from app.services.normalization import load_dictionary

        try:
            ocr_result = self._provider.extract(photo, mime_type)  # type: ignore[attr-defined]
        except Exception:
            return _result_from_score(None, expected_name)

        raw = (ocr_result.raw_text or "").strip().lower()
        if not raw:
            return _result_from_score(None, expected_name)

        # Build target aliases (expected generic + known brand names)
        targets = {expected_name.strip().lower()}
        dictionary = load_dictionary()
        entry = dictionary.generic_index.get(expected_name.strip().lower()) or dictionary.brand_index.get(
            expected_name.strip().lower()
        )
        if entry is not None:
            targets.add(entry.generic_name.lower())
            targets.update(b.lower() for b in entry.brand_names)

        tokens = [t for t in raw.replace("\n", " ").split() if len(t) >= 3]
        best = 0.0
        for target in targets:
            if target in raw:
                best = 1.0
                break
            for token in tokens:
                ratio = SequenceMatcher(None, target, token).ratio()
                if ratio > best:
                    best = ratio

        return _result_from_score(best, expected_name)


def get_photo_matcher() -> ImageMatcher:
    """Return OcrPhotoMatcher when real EasyOCR is available, else NoOpMatcher."""
    from app.ocr.provider import get_ocr_provider, ocr_mode

    if ocr_mode() == "easyocr":
        return OcrPhotoMatcher(get_ocr_provider())
    return NoOpMatcher()


def _result_from_score(score: float | None, expected_name: str) -> Comparison:
    """Turn a matcher score into a reported outcome, refusing weak matches."""
    if score is None:
        return Comparison(
            outcome="NOT_CHECKED",
            confidence=None,
            detail="No comparison score was produced, so this photo is not checked.",
        )
    if score >= MATCH_THRESHOLD:
        return Comparison(
            outcome="MATCH",
            confidence=round(score, 3),
            detail=f"The photo is consistent with {expected_name}. A person still confirms.",
        )
    if score <= 0.35:
        return Comparison(
            outcome="NO_MATCH",
            confidence=round(score, 3),
            detail=(
                f"The photo does not look like {expected_name}. Do not take it until "
                f"someone checks the packaging."
            ),
        )
    # Between the two: deliberately not a verdict either way.
    return Comparison(
        outcome="NOT_CHECKED",
        confidence=round(score, 3),
        detail=(
            "The comparison was inconclusive, so this is not a confirmation. "
            f"Please check the packaging reads {expected_name}."
        ),
    )


def verify_photo(
    session: Session,
    *,
    storage: StorageService,
    matcher: ImageMatcher,
    user_id: str,
    medication_id: str,
    photo: bytes,
    mime_type: str,
) -> PhotoVerification:
    med = session.get(Medication, medication_id)
    if med is None:
        raise CaseError("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)

    if not photo:
        raise CaseError("The photo is empty.", status_code=400)
    if mime_type not in {"image/jpeg", "image/png"}:
        raise CaseError("Only JPEG and PNG photos are accepted.", status_code=400)

    expected = med.name_generic or med.name_raw
    comparison = matcher.compare(photo, mime_type, expected)

    file_hash = hashlib.sha256(photo).hexdigest()
    key = f"medicine-photos/{med.household_member_id}/{file_hash}.png"
    storage.upload(key, photo)

    row = PhotoVerification(
        medication_id=medication_id,
        household_member_id=med.household_member_id,
        file_storage_key=key,
        file_hash=file_hash,
        outcome=comparison.outcome,
        detail=comparison.detail,
        confidence=comparison.confidence,
        taken_by_user_id=user_id,
    )
    session.add(row)
    session.commit()
    return row


def history(session: Session, *, user_id: str, medication_id: str) -> list[PhotoVerification]:
    med = session.get(Medication, medication_id)
    if med is None:
        raise CaseError("Medication not found", status_code=404)
    authorize_member(session, user_id, med.household_member_id)
    from sqlmodel import select

    return list(
        session.exec(
            select(PhotoVerification)
            .where(PhotoVerification.medication_id == medication_id)
            .order_by(PhotoVerification.created_at.desc())  # type: ignore[union-attr]
        ).all()
    )
