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
    "Transcribe every word and number on this medical page exactly as written. "
    "Preserve the line breaks. Do not explain, do not summarise, do not add medicines, "
    "do not correct spelling, and do not omit handwriting. Output only the transcription."
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
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 4096},
        }
        import httpx

        try:
            response = httpx.post(
                ENDPOINT.format(model=self._model),
                params={"key": self._api_key},
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            body = response.json()
            candidates = body.get("candidates") or []
            if not candidates:
                raise OcrInputError(
                    str(body.get("promptFeedback") or body.get("error") or "Gemini returned no text")
                )
            parts = candidates[0].get("content", {}).get("parts") or []
            return "\n".join(str(part.get("text", "")) for part in parts).strip()
        except OcrInputError:
            raise
        except Exception as exc:
            raise OcrInputError(f"Gemini OCR failed: {str(exc)[:250]}") from exc

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
