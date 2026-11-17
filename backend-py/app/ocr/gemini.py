"""Gemini vision OCR provider.

Google AI Studio issues Gemini API keys without a billing account, which makes this the
practical free handwriting path. The model is asked to transcribe the page verbatim;
the app's own parser and human verification then decide what the text means.

The image is sent to Google. Use only with consent.
"""

from __future__ import annotations

import base64

from app.ocr.base import LabResult, OcrResult
from app.ocr.easyocr_provider import OcrInputError, _pdf_text, _render_pdf
from app.ocr.parsing import candidates_from_text

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = (
    "You are transcribing an Indian doctor's prescription. The page mixes printed "
    "letterhead with cursive handwriting, abbreviations, and arrows.\n"
    "Output plain text only, in this order:\n"
    "1. A short header: clinic or doctor name if printed, patient name, age, weight, "
    "and the written diagnosis. One fact per line. Prefix the diagnosis line with 'Dx '.\n"
    "2. A line containing only 'Rx'.\n"
    "3. One medicine per line, written as plain text the way a pharmacist would read it. "
    "Start each medicine line with Tab, Cap, Syp, Inj, Cream, Gel, Oint, Lotion, Soap, "
    "or Drops. Then the brand or generic name, the strength with its unit, and the "
    "schedule (OD, BD, TDS, HS, 1-0-1, morning, night, x N days, or the written duration). "
    "Keep extra instructions such as 'after food' or 'local application' on the same line. "
    "Read every numbered item. A gel, cream, or lotion is a medicine line even when the "
    "strength is not written. Do not merge two medicines onto one line.\n"
    "4. Advice or investigations that are not medicines, each on its own line, after the "
    "medicine lines. Do not put a dosage-form word on those lines.\n"
    "Rules: transcribe only what is on the page. Do not invent a medicine, a strength, "
    "or a duration that is not written. If a word is unreadable, write [unclear] in its "
    "place rather than guessing. Do not explain. Do not use markdown or bullet symbols.\n"
    "Handwriting: distinguish 1 from 7 and mg from g. A tablet strength is usually mg, "
    "not g. Copy the brand letters you can see; do not substitute a different drug. "
    "Common dermatology brands on such pages include Sotret, Isotretinoin, Adapalene, "
    "Benzac, Persol, and Desowen — use one of these only when the writing actually "
    "matches it, never as a guess."
)


class GeminiVisionProvider:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        if not api_key:
            raise OcrInputError("Gemini is selected but TAALMEL_GEMINI_API_KEY is empty.")
        self._api_key = api_key
        self._model = model

    def _image_bytes(self, data: bytes, mime_type: str) -> tuple[bytes, str]:
        if mime_type == "application/pdf":
            text = _pdf_text(data)
            if text:
                return b"", "text:" + text
            data = _render_pdf(data)
            return data, "image/png"
        return data, mime_type

    def _read(self, data: bytes, mime_type: str) -> str:
        image, kind = self._image_bytes(data, mime_type)
        if kind.startswith("text:"):
            return kind.removeprefix("text:")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": PROMPT},
                        {
                            "inline_data": {
                                "mime_type": kind,
                                "data": base64.b64encode(image).decode("ascii"),
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192},
        }
        import httpx

        # Google's free tier returns 503/429 when it is busy. That is transient and
        # must not become a failed document on the first attempt.
        retry_statuses = {429, 500, 502, 503, 504}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = httpx.post(
                    ENDPOINT.format(model=self._model),
                    params={"key": self._api_key},
                    json=payload,
                    timeout=60.0,
                )
                if response.status_code in retry_statuses and attempt < 2:
                    import time

                    time.sleep(1.5 * (attempt + 1))
                    continue
                response.raise_for_status()
                body = response.json()
                candidates = body.get("candidates") or []
                if not candidates:
                    raise OcrInputError(
                        str(
                            body.get("promptFeedback")
                            or body.get("error")
                            or "Gemini returned no text"
                        )
                    )
                parts = candidates[0].get("content", {}).get("parts") or []
                return "\n".join(str(part.get("text", "")) for part in parts).strip()
            except OcrInputError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    import time

                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
        raise OcrInputError(f"Gemini OCR failed: {str(last_error)[:250]}") from last_error

    def extract(self, data: bytes, mime_type: str) -> OcrResult:
        text = self._read(data, mime_type)
        candidates = candidates_from_text(text)
        if not candidates:
            from app.ocr.handwriting import fallback_candidates_from_text

            candidates = fallback_candidates_from_text(text)
        return OcrResult(raw_text=text, candidates=candidates)

    def read_text(self, data: bytes, mime_type: str) -> str:
        return self._read(data, mime_type)

    def extract_lab(self, data: bytes, mime_type: str) -> LabResult:
        from app.ocr.lab_parsing import values_from_text

        return values_from_text(self._read(data, mime_type))
