"""Turn raw prescription text into medication candidates.

Deliberately separate from the OCR engine: the engine produces text, this module
decides what the text says. That split means the parsing rules are testable without
loading a vision model, and a different OCR engine can be swapped in unchanged.

The hard problem is precision, not recall. A photographed page might be a prescription,
a lab report, a pharmacy bill, or a discharge summary. Extracting "medicines" from a
bill is worse than extracting nothing: it silently corrupts the record. So this module
works in three stages:

  1. Classify the document. If it carries lab-report or invoice markers and no medicine
     evidence, it is not a prescription and nothing is extracted.
  2. Require per-line evidence. A line counts as a medicine only if its name resolves
     against the curated dictionary, or it is introduced by a dosage-form word
     (Tab / Cap / Syp / Inj). A bare "Road Bengaluru 560001" has neither.
  3. Strip every instruction token, not just the first, so the name stays a name.

Rules that matter:
- Never invent a medicine. Unrecognised lines are skipped, not guessed at.
- An unknown-but-plausible medicine (form word present, not in the dictionary) is kept
  and marked for human review, because silently dropping a real prescription is worse.
- Confidence reflects both the parser's understanding and the dictionary's agreement.
"""

import re
from dataclasses import dataclass

from app.ocr.base import MedicationCandidate
from app.services.normalization import (
    normalize_dosage_form,
    normalize_frequency,
    normalize_strength,
    resolve_name,
)

# ── Line-level vocabulary ────────────────────────────────────────────

# Lines that are never medicines: headers, patient details, signatures, totals.
_NON_MEDICATION_PATTERNS = (
    r"^\s*(rx|r/x)\s*$",
    r"\b(patient|age|sex|gender|address|diagnosis|advice|follow\s*-?\s*up|signature|signed)\b",
    r"\b(doctor|dr\.|clinic|hospital|centre|center|medical|registration|reg\.?\s*no|gstin|invoice)\b",
    r"\b(phone|mobile|tel|contact|email|website|thank\s+you|welcome)\b",
    r"\b(total|amount|qty|quantity|price|rate|tax|discount|subtotal|balance|paid|cash)\b",
    r"\b(test|result|unit|range|reference|sample|specimen|reported|normal|flag)\b",
    r"^\s*[-=_*.·]{2,}\s*$",
    r"^\s*\d+[.)]?\s*$",
)

_FORM_WORDS = (
    r"(?:tab|tablet|tabs|cap|capsule|caps|syp|syrup|inj|injection|susp|suspension|"
    r"drops?|oint|ointment|cream|gel|lotion|soap|facewash|spray|inhaler|patch|sachet)"
)

_STRENGTH = (
    r"\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu|units?|meq)"
    r"(?:\s*/\s*\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml))?"
)

_INSTRUCTION = (
    r"\b(?:od|bd|bid|tid|tds|qid|qds|hs|prn|sos|stat|ac|pc|om|on)\b"
    r"|\b\d\s*[-–]\s*0\s*[-–]\s*\d\b"
    r"|\b(?:once|twice|thrice|three|four)\s+(?:a\s+)?(?:daily|times)\b"
    r"|\bevery\s+\d+\s*(?:hours?|hrs?|days?)\b"
    r"|\b(?:before|after|with)\s+(?:meals?|food|breakfast|lunch|dinner|milk)\b"
    r"|\b(?:in\s+the\s+)?(?:morning|evening|night|bedtime|noon)\b"
    r"|\b(?:local(?:ly)?|application|apply)\b"
    r"|\bat\s+bedtime\b"
    r"|\b(?:empty\s+stomach|oral|orally|topical|subcutaneous|intravenous|iv|im)\b"
)

_DURATION = r"(?:\bx\s*)?(?:for\s+)?\d+\s*(?:days?|weeks?|months?|dys?|wks?)\b"

_QUANTITY = r"\b(?:take|giving|give)\b"

# Document-level markers. Presence of these, with no medicine evidence, means the upload
# is not a prescription.
_LAB_MARKERS = (
    r"\b(hba1c|haemoglobin|hemoglobin|creatinine|cholesterol|triglyceride|bilirubin|"
    r"platelet|leucocyte|erythrocyte|serum|urine|specimen|reference\s+range|"
    r"laboratory|diagnostics|pathology|lipid\s+profile|thyroid)\b",
)
_INVOICE_MARKERS = (
    r"\b(invoice|bill|receipt|gstin|gst\s*in|total\s+amount|sub\s*total|"
    r"qty|rate|discount|cash|paid|mrp|batch\s+no)\b",
)
_CLINICAL_MARKERS = (
    r"^\s*(rx|r/x)\s*$",
    rf"^\s*{_FORM_WORDS}\b",
    r"\b(prescription|dosage|dose|sig\.?|directions?)\b",
)


@dataclass(frozen=True)
class ParsedLine:
    raw: str
    name: str
    dosage: str | None
    schedule: str | None
    duration: str | None
    form: str | None
    extra_instructions: str | None
    # True when the name matched the medicine dictionary. False means it looked like a
    # medicine (form word present) but the name is unknown, so it needs review.
    known: bool = False


# ── Counting-digit repair ────────────────────────────────────────────

# OCR confuses letters with digits inside numbers: "Smg" for 5mg, "2Omg" for 20mg,
# "l0mg" for 10mg, "5O0mg" for 500mg. Repair is confined to a token that ends in a
# unit, and letters are only converted *inside* the numeric part, so a medicine name
# such as "Omeprazole", "Insulin" or "Syp" is never altered.
_UNIT_END = re.compile(
    # Match a whole alphanumeric token, then decide where the unit starts. Matching the
    # unit greedily inside the regex fails on "Smg" (it splits as "Sm"+"g"), so the
    # split is done in code instead.
    r"(?<![A-Za-z])(?P<token>[0-9OoIlSsBbZz][A-Za-z0-9OoIl]*)\b",
)
_UNIT_SUFFIXES = ("units", "unit", "mcg", "mg", "ml", "meq", "iu", "g")
_DIGIT_CONFUSIONS = {
    "O": "0", "o": "0",
    "I": "1", "l": "1", "|": "1",
    "S": "5", "s": "5",
    "B": "8",
    "Z": "2", "z": "2",
}


def repair_digits(text: str) -> str:
    """Correct letter-for-digit confusions in a number that ends in a dosage unit."""

    def _fix(match: re.Match[str]) -> str:
        token = match.group("token")
        lowered = token.lower()

        # Find the longest unit suffix this token ends with.
        unit = next((u for u in _UNIT_SUFFIXES if lowered.endswith(u)), None)
        if unit is None:
            return token
        numeric = token[: len(token) - len(unit)]
        if not numeric:
            return token

        has_digit = any(ch.isdigit() for ch in numeric)
        single_letter = len(numeric) == 1 and numeric.upper() in _DIGIT_CONFUSIONS
        if not (has_digit or single_letter):
            return token

        repaired = "".join(_DIGIT_CONFUSIONS.get(ch, ch) for ch in numeric)
        if not any(ch.isdigit() for ch in repaired):
            return token
        return f"{repaired}{token[len(token) - len(unit):]}"

    return _UNIT_END.sub(_fix, text)


# ── Document classification ──────────────────────────────────────────

def looks_like_prescription(raw_text: str) -> bool:
    """Decide whether this document is worth extracting medicines from at all.

    A prescription must show clinical structure (an Rx marker, a dosage-form word, or a
    prescriber) *and* must not be dominated by lab-report or invoice vocabulary.
    """
    if not raw_text or not raw_text.strip():
        return False

    lowered = raw_text.lower()

    clinical_hits = sum(
        len(re.findall(pattern, lowered, re.MULTILINE)) for pattern in _CLINICAL_MARKERS
    )
    if clinical_hits == 0:
        return False

    lab_hits = sum(len(re.findall(pattern, lowered)) for pattern in _LAB_MARKERS)
    invoice_hits = sum(len(re.findall(pattern, lowered)) for pattern in _INVOICE_MARKERS)

    # A lab report or a bill wins unless the clinical structure is clearly stronger.
    if lab_hits >= 2 and lab_hits > clinical_hits:
        return False
    if invoice_hits >= 2 and invoice_hits > clinical_hits:
        return False
    return True


# ── Line parsing ─────────────────────────────────────────────────────

def _is_medication_line(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 3:
        return False
    lowered = stripped.lower()
    for pattern in _NON_MEDICATION_PATTERNS:
        if re.search(pattern, lowered, re.MULTILINE):
            return False
    # A line with no letters at all cannot be a medicine.
    return any(ch.isalpha() for ch in stripped)


def _strip_repeatedly(text: str, pattern: str) -> tuple[str, list[str]]:
    """Remove every match of a pattern, returning the remainder and what was removed."""
    found: list[str] = []
    while True:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return text.strip(), found
        found.append(match.group(0).strip())
        text = (text[: match.start()] + " " + text[match.end():]).strip()


def parse_line(raw: str) -> ParsedLine | None:
    """Parse one prescription line. Returns None when it does not look like a medicine."""
    if not _is_medication_line(raw):
        return None

    text = raw.strip()
    text = repair_digits(text)
    # Drop a leading serial number such as "1." or "1)".
    text = re.sub(r"^\s*\d+\s*[.)]\s*", "", text)

    form: str | None = None
    form_match = re.search(rf"\b({_FORM_WORDS})\b\.?", text, re.IGNORECASE)
    if form_match:
        form = normalize_dosage_form(form_match.group(1))
        text = (text[: form_match.start()] + " " + text[form_match.end():]).strip()

    strength: str | None = None
    strength_match = re.search(_STRENGTH, text, re.IGNORECASE)
    if strength_match:
        strength = normalize_strength(strength_match.group(0))
        text = (text[: strength_match.start()] + " " + text[strength_match.end():]).strip()

    # Every instruction and duration token is removed, not just the first, so
    # "BD after meals for 30 days" leaves the name clean.
    text, schedule_parts = _strip_repeatedly(text, _INSTRUCTION)
    text, duration_parts = _strip_repeatedly(text, _DURATION)
    text, take_parts = _strip_repeatedly(text, _QUANTITY)

    schedule = normalize_frequency(schedule_parts[0]) if schedule_parts else None
    leftover = [part for part in schedule_parts[1:] if part.lower() != (schedule or "").lower()]
    extras = " ".join(leftover + duration_parts + take_parts) or None

    name = re.sub(r"[\s,;:.\-–—/]+", " ", text).strip()
    name = re.sub(r"\s+[a-zA-Z]$", "", name).strip()
    if not name or not any(ch.isalpha() for ch in name):
        return None
    # A name made only of unit words is a misparse, not a medicine.
    if re.fullmatch(r"(?:mg|mcg|ml|g|iu|units?|meq|tablet|capsule)", name, re.IGNORECASE):
        return None

    resolution = resolve_name(name)
    known = resolution.method != "UNRESOLVED"

    # Evidence gate: either the dictionary knows it, or a dosage-form word introduced it.
    if not known and form is None:
        return None

    return ParsedLine(
        raw=raw.strip(),
        name=name,
        dosage=strength,
        schedule=schedule,
        duration=duration_parts[0] if duration_parts else None,
        form=form,
        extra_instructions=extras,
        known=known,
    )


def candidates_from_text(raw_text: str) -> list[MedicationCandidate]:
    """Turn whole-document OCR text into medication candidates."""
    if not raw_text or not raw_text.strip():
        return []
    if not looks_like_prescription(raw_text):
        return []

    candidates: list[MedicationCandidate] = []
    seen: set[str] = set()
    for line in raw_text.splitlines():
        parsed = parse_line(line)
        if parsed is None:
            continue
        # Normalise the name through the dictionary so "Omez" and "Omeprazole" collapse.
        resolution = resolve_name(parsed.name)
        canonical = resolution.generic_name or parsed.name
        key = canonical.lower()
        if key in seen:
            continue
        seen.add(key)

        instructions = parsed.extra_instructions
        candidates.append(
            MedicationCandidate(
                medication_name=parsed.name,
                dosage=parsed.dosage,
                frequency=parsed.schedule,
                instructions=instructions,
                confidence=_line_confidence(parsed, resolution),
            )
        )
    return candidates


def _line_confidence(parsed: ParsedLine, resolution) -> float:
    """Confidence is about how much was understood, and how well the dictionary agrees.

    Deliberately capped below 1.0: human verification is always required.
    """
    score = 0.35 if parsed.known else 0.25
    if parsed.dosage:
        score += 0.2
    if parsed.schedule:
        score += 0.2
    if parsed.form:
        score += 0.05
    if parsed.duration:
        score += 0.05

    # Dictionary agreement raises confidence; a fuzzy match should never look certain.
    if resolution.method == "EXACT_GENERIC_MATCH":
        score += 0.1
    elif resolution.method == "BRAND_LOOKUP":
        score += 0.08
    elif resolution.method == "FUZZY_MATCH":
        score += 0.0

    return round(min(score, 0.92), 2)
