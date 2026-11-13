"""Turn raw prescription text into medication candidates.

Deliberately separate from the OCR engine: the engine produces text, this module
decides what the text says. That split means the parsing rules are testable without
loading a vision model, and a different OCR engine can be swapped in unchanged.

Rules that matter:
- Never invent a medicine. If a line does not look like a medication line, it is skipped.
- Confidence comes from how much of the line was understood, not from the OCR engine's
  own score alone, so a clean-but-unrecognised line is not reported as confident.
- Everything starts unverified; this only proposes.
"""

import re
from dataclasses import dataclass

from app.ocr.base import MedicationCandidate
from app.services.normalization import normalize_dosage_form, normalize_frequency, normalize_strength

# Lines that are clearly not medicines: headers, patient details, signatures.
_NON_MEDICATION_PATTERNS = (
    r"^\s*(rx|r/x)\s*$",
    r"\b(patient|name|age|sex|date|address|diagnosis|advice|follow\s*-?\s*up|signature)\b",
    r"\b(doctor|dr\.?|clinic|hospital|registration|reg\.?\s*no|phone|mobile)\b",
    r"^\s*[-=_*]{2,}\s*$",
)

# A medicine line usually starts with an optional form word, then a name, then a strength.
_FORM_WORDS = r"(?:tab|tablet|tabs|cap|capsule|caps|syp|syrup|inj|injection|susp|suspension|drops?|oint|cream|gel|spray|inhaler|patch)"

_STRENGTH = r"\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu|units?|meq)(?:\s*/\s*\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml))?"

_DOSE_SCHEDULE = (
    r"\b(?:od|bd|bid|tid|tds|qid|qds|hs|prn|sos|stat|ac|pc|om|on)\b"
    r"|\b\d\s*[-–]\s*0\s*[-–]\s*\d\b"          # 1-0-1 style
    r"|\b(?:once|twice|thrice|three times|four times)\s+(?:a\s+)?daily\b"
    r"|\bevery\s+\d+\s*(?:hours?|hrs?)\b"
    r"|\b(?:before|after)\s+(?:meals?|food|breakfast|dinner|lunch)\b"
    r"|\bat\s+bedtime\b"
)

_DURATION = r"\b(?:for\s+)?\d+\s*(?:days?|weeks?|months?)\b"

# OCR reads digits and letters that look alike: "2Omg" (letter O) for "20mg", "l0mg"
# (lowercase L) for "10mg", "5O0mg" for "500mg". Repair is applied to a number+unit
# token as a whole, so medicine names such as "Omez" or "Insulin" are never rewritten:
# only characters between the first digit and the unit are converted.
_NUMBER_UNIT = re.compile(
    r"(?<![A-Za-z])\d[A-Za-z0-9]*(?:\s*/\s*\d[A-Za-z0-9]*)?\s*(?:mg|mcg|ml|g|iu|units?|meq)\b"
    # A leading lowercase L or capital O before a digit is a digit too ("l0mg", "O5mg").
    r"|(?<![A-Za-z])[lIO][\dOoIl]+\s*(?:mg|mcg|ml|g|iu|units?|meq)\b",
    re.IGNORECASE,
)
_LETTER_TO_DIGIT = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})


def fix_ocr_digits(text: str) -> str:
    """Repair letter-for-digit confusions inside changes-dosage tokens only."""

    def _repair(match: re.Match[str]) -> str:
        token = match.group(0)
        # Split off the trailing unit so only the numeric part is repaired.
        unit_match = re.search(r"(mg|mcg|ml|g|iu|units?|meq)\b", token, re.IGNORECASE)
        if unit_match is None:
            return token
        numeric, unit = token[: unit_match.start()], token[unit_match.start():]
        return numeric.translate(_LETTER_TO_DIGIT) + unit

    return _NUMBER_UNIT.sub(_repair, text)


@dataclass(frozen=True)
class ParsedLine:
    raw: str
    name: str
    dosage: str | None
    schedule: str | None
    duration: str | None
    form: str | None


def _is_medication_line(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 3:
        return False
    lowered = stripped.lower()
    for pattern in _NON_MEDICATION_PATTERNS:
        if re.search(pattern, lowered):
            return False
    # Require a strength, a schedule, or an explicit dosage form word. A bare word
    # is too ambiguous to call a medicine.
    has_strength = re.search(_STRENGTH, lowered) is not None
    has_schedule = re.search(_DOSE_SCHEDULE, lowered) is not None
    has_form = re.search(rf"^\s*{_FORM_WORDS}\b", lowered) is not None
    return has_strength or has_schedule or has_form


def parse_line(raw: str) -> ParsedLine | None:
    """Parse one prescription line. Returns None when it does not look like a medicine."""
    if not _is_medication_line(raw):
        return None

    text = raw.strip()
    text = fix_ocr_digits(text)
    # Drop a leading serial number such as "1." or "1)".
    text = re.sub(r"^\s*\d+\s*[.)]\s*", "", text)

    form: str | None = None
    form_match = re.match(rf"^\s*({_FORM_WORDS})\b\.?", text, re.IGNORECASE)
    if form_match:
        form = normalize_dosage_form(form_match.group(1))
        text = text[form_match.end():].strip()

    strength: str | None = None
    strength_match = re.search(_STRENGTH, text, re.IGNORECASE)
    if strength_match:
        strength = normalize_strength(strength_match.group(0))
        text = (text[: strength_match.start()] + " " + text[strength_match.end():]).strip()

    schedule: str | None = None
    schedule_match = re.search(_DOSE_SCHEDULE, text, re.IGNORECASE)
    if schedule_match:
        raw_schedule = schedule_match.group(0)
        schedule = normalize_frequency(raw_schedule) or raw_schedule
        text = (text[: schedule_match.start()] + " " + text[schedule_match.end():]).strip()

    duration: str | None = None
    duration_match = re.search(_DURATION, text, re.IGNORECASE)
    if duration_match:
        duration = duration_match.group(0).strip()
        text = (text[: duration_match.start()] + " " + text[duration_match.end():]).strip()

    name = re.sub(r"[\s,;:.\-–]+", " ", text).strip()
    if not name or not any(ch.isalpha() for ch in name):
        return None

    return ParsedLine(
        raw=raw.strip(),
        name=name,
        dosage=strength,
        schedule=schedule,
        duration=duration,
        form=form,
    )


def candidates_from_text(raw_text: str) -> list[MedicationCandidate]:
    """Turn whole-document OCR text into medication candidates."""
    if not raw_text or not raw_text.strip():
        return []

    candidates: list[MedicationCandidate] = []
    seen: set[str] = set()
    for line in raw_text.splitlines():
        parsed = parse_line(line)
        if parsed is None:
            continue
        key = parsed.name.lower()
        if key in seen:
            continue
        seen.add(key)

        instructions = ", ".join(part for part in (parsed.schedule, parsed.duration) if part) or None
        candidates.append(
            MedicationCandidate(
                medication_name=parsed.name,
                dosage=parsed.dosage,
                frequency=parsed.schedule,
                instructions=instructions,
                confidence=_line_confidence(parsed),
            )
        )
    return candidates


def _line_confidence(parsed: ParsedLine) -> float:
    """Confidence is about how much of the line was understood, and is deliberately
    conservative: a name alone is not enough to trust without review."""
    score = 0.5
    if parsed.dosage:
        score += 0.2
    if parsed.schedule:
        score += 0.2
    if parsed.form:
        score += 0.05
    if parsed.duration:
        score += 0.05
    return round(min(score, 0.9), 2)
