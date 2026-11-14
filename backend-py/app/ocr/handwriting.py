"""Handwriting-tolerant candidate extraction.

Printed-text OCR is not the hard case in India; handwritten prescriptions are. A
general OCR engine may return the right words but with broken line structure, and the
strict parser correctly refuses to guess. That leaves the caregiver with an empty
review screen even though text was readable.

This module is the safety valve: when a handwriting-capable provider has produced text
but the strict parser found no medicines, keep plausible prescription lines as
low-confidence candidates for a person to correct. It never claims they are verified.
"""

from __future__ import annotations

import re

from app.ocr.base import MedicationCandidate
from app.ocr.parsing import (
    _FORM_WORDS,
    _NON_MEDICATION_PATTERNS,
    _STRENGTH,
    looks_like_prescription,
    parse_line,
    repair_digits,
)
from app.services.normalization import normalize_frequency, normalize_strength

MAX_FALLBACK_CANDIDATES = 20

_SERIAL = re.compile(r"^\s*(?:\d+|[ivx]+)\s*[.)\-:]\s*", re.IGNORECASE)
_STRENGTH_RE = re.compile(_STRENGTH, re.IGNORECASE)
_FORM_RE = re.compile(rf"\b({_FORM_WORDS})\b", re.IGNORECASE)
_FREQ_RE = re.compile(
    r"\b(od|bd|bid|tid|tds|qid|qds|hs|prn|sos|stat|ac|pc|om|on)\b", re.IGNORECASE
)


def _skip_line(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 3 or not any(ch.isalpha() for ch in stripped):
        return True
    lowered = stripped.lower()
    for pattern in _NON_MEDICATION_PATTERNS:
        if re.search(pattern, lowered, re.MULTILINE):
            return True
    return False


def _clean_name(line: str) -> str:
    text = repair_digits(line.strip())
    text = _SERIAL.sub("", text)
    text = _FORM_RE.sub(" ", text, count=1)
    text = _STRENGTH_RE.sub(" ", text, count=1)
    text = _FREQ_RE.sub(" ", text)
    text = re.sub(r"\b(?:x|for)\s*\d+\s*(?:days?|d)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .,;:-")
    return text[:120]


def fallback_candidates_from_text(raw_text: str) -> list[MedicationCandidate]:
    """Keep plausible handwritten lines for human review.

    The document-level gate is reused so an invoice or lab report still yields nothing.
    A line must contain a dosage-form word or a strength; that is evidence it is a
    medicine line, not a patient address or a signature.
    """
    if not raw_text or not raw_text.strip():
        return []
    if not looks_like_prescription(raw_text):
        return []

    found: list[MedicationCandidate] = []
    seen: set[str] = set()
    for line in raw_text.splitlines():
        if _skip_line(line):
            continue

        parsed = parse_line(line)
        if parsed is not None:
            name = parsed.name
            dosage = parsed.dosage
            frequency = parsed.schedule
            instructions = parsed.extra_instructions
            confidence = min(parsed_confidence(parsed), 0.55)
        else:
            if not _FORM_RE.search(line) and not _STRENGTH_RE.search(line):
                continue
            name = _clean_name(line)
            if len(name) < 2:
                continue
            strength = _STRENGTH_RE.search(line)
            dosage = normalize_strength(strength.group(0)) if strength else None
            freq = _FREQ_RE.search(line)
            frequency = normalize_frequency(freq.group(0)) if freq else None
            instructions = None
            confidence = 0.25

        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(
            MedicationCandidate(
                medication_name=name,
                dosage=dosage,
                frequency=frequency,
                instructions=instructions,
                confidence=confidence,
            )
        )
        if len(found) >= MAX_FALLBACK_CANDIDATES:
            break
    return found


def parsed_confidence(parsed) -> float:
    """The strict parser's line confidence, itself capped below certainty."""
    from app.ocr.parsing import _line_confidence
    from app.services.normalization import resolve_name

    return _line_confidence(parsed, resolve_name(parsed.name))
