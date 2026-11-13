"""OCR provider interface and the confidence rule that decides review vs. completion."""

from dataclasses import dataclass, field
from typing import Protocol

CONFIDENCE_THRESHOLD = 0.75


@dataclass(frozen=True)
class MedicationCandidate:
    medication_name: str
    dosage: str | None
    frequency: str | None
    instructions: str | None
    confidence: float


@dataclass(frozen=True)
class OcrResult:
    raw_text: str
    candidates: list[MedicationCandidate] = field(default_factory=list)


class OcrProvider(Protocol):
    def extract(self, data: bytes, mime_type: str) -> OcrResult: ...


@dataclass(frozen=True)
class LabValueCandidate:
    test_name: str
    value: str
    unit: str | None
    reference_range_raw: str | None


@dataclass(frozen=True)
class LabResult:
    raw_text: str
    captured_on: str | None
    lab_name: str | None
    values: list[LabValueCandidate] = field(default_factory=list)


class LabOcrProvider(Protocol):
    """Separate from prescription OCR: a lab report is a table of values, not free text."""

    def extract_lab(self, data: bytes, mime_type: str) -> LabResult: ...


def status_for(candidates: list[MedicationCandidate]) -> str:
    """FAILED when nothing was found; NEEDS_REVIEW if any item is below threshold; else COMPLETED."""
    if not candidates:
        return "FAILED"
    if any(c.confidence < CONFIDENCE_THRESHOLD for c in candidates):
        return "NEEDS_REVIEW"
    return "COMPLETED"
