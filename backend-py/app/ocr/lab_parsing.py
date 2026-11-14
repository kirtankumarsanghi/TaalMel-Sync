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

# A value is a number (or a common qualitative result). The unit is matched first
# when present, so a test name containing a number ("Vitamin D 25-OH") is not split.
_VALUE = (
    r"(?P<value>[<>]?\s*-?\d+(?:[.,]\d+)?|Positive|Negative|Reactive|Non-reactive|Normal|Abnormal|Nil|Trace)"
)
_UNIT = (
    r"(?P<unit>%|10\^3/µL|10\^3/uL|10\^6/µL|10\^6/uL|cells/µL|cells/cumm|lakhs/cumm|/hpf|/HPF|"
    r"mg/dL|mg/dl|g/dL|g/dl|mg/L|mg/l|ug/dl|µg/dl|mcg/dl|mmol/L|mmol/l|mEq/L|meq/L|"
    r"mIU/mL|mIU/ml|mIU/L|mIU/l|µIU/mL|uIU/mL|IU/L|iu/L|U/L|u/l|"
    r"ng/mL|ng/dL|pg/mL|µg/mL|ug/mL|mosm/kg)"
)
_NAME = r"(?P<name>[A-Za-z][A-Za-z0-9 .()/%+\-]{1,40}?)"

_VALUE_ROW_WITH_UNIT = re.compile(
    rf"^\s*{_NAME}\s*[:=]?\s+{_VALUE}\s*{_UNIT}\s*(?P<rest>.*)$", re.IGNORECASE
)
_VALUE_ROW_NO_UNIT = re.compile(
    rf"^\s*{_NAME}\s*[:=]?\s+{_VALUE}\s*(?P<rest>.*)$", re.IGNORECASE
)

_RANGE = re.compile(
    r"([<>]?\s*\d+(?:[.,]\d+)?\s*[-–]\s*\d+(?:[.,]\d+)?|\b(?:up\s+to|less\s+than)\s+\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)

_LAB_HINTS = ("laboratory", "diagnostics", "pathology", "lab", "report")

# Report metadata and explanatory prose that is not a test result.
_SKIP_NAME_WORDS = (
    "booking",
    "sample collection",
    "smart report",
    "performed",
    "throughput",
    "out of",
    "healthy",
    "acceptable",
    "borderline",
    "impaired",
    "prediabetes",
    "nafld",
    "score",
    "date",
    "page",
    "reference",
    "normal",
    "abnormal",
    "high",
    "low",
    "test not taken",
    "no. of test",
    "per hour",
    "using",
    "calculated",
    "vital",
    "parameter",
    "latest result",
    "your latest",
)

# A known test name is still a valid row when the unit is missing; the value is stored
# as printed and the unit stays None rather than being guessed.
_KNOWN_TEST_WORDS = (
    "haemoglobin",
    "hemoglobin",
    "glucose",
    "creatinine",
    "cholesterol",
    "triglyceride",
    "platelet",
    "wbc",
    "rbc",
    "esr",
    "hba1c",
    "tsh",
    "calcium",
    "sodium",
    "potassium",
    "bilirubin",
    "alt",
    "ast",
    "sgpt",
    "sgot",
    "urea",
    "uric acid",
    "iron",
    "ferritin",
    "vitamin",
)


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
    lines = raw_text.splitlines()
    for index, line in enumerate(lines):
        # Reports frequently put the test name and the result on separate lines:
        #   Alanine Aminotransferase
        #   (ALT/SGPT) : 27 U/L
        # Try the line alone, then the line joined with the next one.
        attempts = [line.strip()]
        if index + 1 < len(lines):
            attempts.append(f"{line.strip()} {lines[index + 1].strip()}")
        match = None
        for attempt in attempts:
            match = _VALUE_ROW_WITH_UNIT.match(attempt) or _VALUE_ROW_NO_UNIT.match(attempt)
            if match:
                break
        if not match:
            continue

        name = match.group("name").strip(" .:-")
        # Skip rows that are actually dates, page numbers, or a reference-range line.
        if not any(ch.isalpha() for ch in name) or len(name) < 2:
            continue
        lowered = name.lower()
        if lowered.startswith(("date", "page", "ref", "reference")):
            continue
        if any(word in lowered for word in _SKIP_NAME_WORDS):
            continue
        if lowered in {"positive", "negative", "reactive", "non-reactive", "normal", "abnormal", "nil", "trace"}:
            continue
        if " - " in name:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)

        range_match = _RANGE.search(match.group("rest") or "")
        unit = match.groupdict().get("unit")
        value = match.group("value")
        qualitative = value.lower() in {
            "positive", "negative", "reactive", "non-reactive", "normal",
            "abnormal", "nil", "trace",
        }
        # A quantitative lab value normally prints a unit or a reference range.
        # A known test name is still valid without one; the unit stays None.
        known_test = any(word in lowered for word in _KNOWN_TEST_WORDS)
        if unit is None and range_match is None and not qualitative and not known_test:
            continue
        values.append(
            LabValueCandidate(
                test_name=name,
                value=value,
                unit=unit,
                reference_range_raw=range_match.group(1).strip() if range_match else None,
            )
        )

    # Category headings are often merged with the test name ("Iron studies Serum
    # Iron"). When one name contains another, keep the shorter, more specific one.
    unique: list[LabValueCandidate] = []
    for value in values:
        replaced = False
        for index, existing in enumerate(unique):
            left = existing.test_name.lower()
            right = value.test_name.lower()
            if left in right or right in left:
                if len(value.test_name) < len(existing.test_name):
                    unique[index] = value
                replaced = True
                break
        if not replaced:
            unique.append(value)

    return LabResult(
        raw_text=raw_text,
        captured_on=_capture_date(raw_text),
        lab_name=_capture_lab_name(raw_text),
        values=unique,
    )
