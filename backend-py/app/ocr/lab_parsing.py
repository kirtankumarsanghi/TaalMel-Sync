"""Parse lab-report text into test values.

Rules:
- Only rows that look like "Test — value [unit] [range]" are stored.
- The unit is taken from the text; if a unit is absent it stays None rather than guessed.
- Reference ranges are kept as printed ("4.0 - 5.6"); nothing is compared against them.
- A report date is captured when one is clearly present.
"""

import re
from datetime import date

from app.ocr.base import LabResult, LabValueCandidate

_DATE_PATTERNS = (
    (r"\b(\d{4})-(\d{2})-(\d{2})\b", "ymd"),
    (r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", "dmy"),
)

# A value is a number, optionally with a unit, optionally followed by a range.
_VALUE_ROW = re.compile(
    r"^\s*(?P<name>[A-Za-z][A-Za-z0-9 .()/%+\-]{1,40}?)"
    r"\s*[:=]?\s+"
    r"(?P<value>-?\d+(?:\.\d+)?)"
    r"\s*(?P<unit>%|mg/dL|mg/dl|g/dL|g/dl|mmol/L|mmol/l|mEq/L|meq/L|IU/L|iu/L|ng/mL|pg/mL|µg/mL|ug/mL|cells/µL)?"
    r"(?P<rest>.*)$"
)

_RANGE = re.compile(r"(\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?)")

_LAB_HINTS = ("laboratory", "diagnostics", "pathology", "lab", "report")


def _capture_date(text: str) -> str | None:
    for pattern, order in _DATE_PATTERNS:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            if order == "ymd":
                year, month, day = (int(match.group(i)) for i in (1, 2, 3))
            else:
                day, month, year = (int(match.group(i)) for i in (1, 2, 3))
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


def _capture_lab_name(text: str) -> str | None:
    for line in text.splitlines():
        lowered = line.lower()
        if any(hint in lowered for hint in _LAB_HINTS) and len(line.strip()) <= 80:
            return line.strip()
    return None


def values_from_text(raw_text: str) -> LabResult:
    if not raw_text or not raw_text.strip():
        return LabResult(raw_text="", captured_on=None, lab_name=None, values=[])

    values: list[LabValueCandidate] = []
    seen: set[str] = set()
    for line in raw_text.splitlines():
        match = _VALUE_ROW.match(line.strip())
        if not match:
            continue

        name = match.group("name").strip(" .:-")
        # Skip rows that are actually dates, page numbers, or a reference-range line.
        if not any(ch.isalpha() for ch in name) or len(name) < 2:
            continue
        lowered = name.lower()
        if lowered.startswith(("date", "page", "ref", "reference")):
            continue
        if lowered in seen:
            continue
        seen.add(lowered)

        range_match = _RANGE.search(match.group("rest") or "")
        values.append(
            LabValueCandidate(
                test_name=name,
                value=match.group("value"),
                unit=match.group("unit"),
                reference_range_raw=range_match.group(1).strip() if range_match else None,
            )
        )

    return LabResult(
        raw_text=raw_text,
        captured_on=_capture_date(raw_text),
        lab_name=_capture_lab_name(raw_text),
        values=values,
    )
