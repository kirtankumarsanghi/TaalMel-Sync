"""Deterministic stub OCR. Used in dev and tests until EasyOCR/PaddleOCR is wired in.

Behaviour is driven by the upload's content so tests can exercise each path:
- bytes containing b"FAIL_OCR" raise, to exercise the failure path.
- bytes containing b"EMPTY_OCR" return no candidates.
- bytes containing b"LOW_CONFIDENCE" return a candidate below the review threshold.
- anything else returns one confident candidate.
"""

from app.ocr.base import MedicationCandidate, OcrResult


class OcrExtractionError(RuntimeError):
    pass


class StubOcrProvider:
    def extract(self, data: bytes, mime_type: str) -> OcrResult:
        if b"FAIL_OCR" in data:
            raise OcrExtractionError("Stub OCR forced failure")
        if b"EMPTY_OCR" in data:
            return OcrResult(raw_text="", candidates=[])
        confidence = 0.5 if b"LOW_CONFIDENCE" in data else 0.85
        return OcrResult(
            raw_text="Rx\nPatient: Stub Patient\nLisinopril 10mg\nTake 1 tablet daily",
            candidates=[
                MedicationCandidate(
                    medication_name="Lisinopril",
                    dosage="10mg",
                    frequency="daily",
                    instructions="Take 1 tablet",
                    confidence=confidence,
                )
            ],
        )
