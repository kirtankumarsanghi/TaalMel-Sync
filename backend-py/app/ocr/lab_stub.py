"""Deterministic stub lab-report parser.

Driven by the upload content so every path is testable:
- b"UNREADABLE_LAB" -> no values (the report is marked NEEDS_REVIEW, never guessed at)
- otherwise a small fixed set of values, including a date and lab name.

The real implementation will be a different provider behind the same interface.
"""

from app.ocr.base import LabResult, LabValueCandidate


class StubLabOcrProvider:
    def extract_lab(self, data: bytes, mime_type: str) -> LabResult:
        if b"UNREADABLE_LAB" in data:
            return LabResult(raw_text="", captured_on=None, lab_name=None, values=[])

        return LabResult(
            raw_text="HbA1c 8.2 %\nCreatinine 1.1 mg/dL",
            captured_on="2026-09-14",
            lab_name="Stub Diagnostics",
            values=[
                LabValueCandidate(
                    test_name="HbA1c", value="8.2", unit="%", reference_range_raw="4.0 - 5.6"
                ),
                LabValueCandidate(
                    test_name="Creatinine", value="1.1", unit="mg/dL", reference_range_raw="0.7 - 1.3"
                ),
            ],
        )
