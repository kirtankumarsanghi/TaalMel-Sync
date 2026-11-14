"""Google Cloud Vision document OCR provider.

This is the production path for handwritten Indian prescriptions. Cloud Vision's
DOCUMENT_TEXT_DETECTION is materially better than EasyOCR on cursive handwriting and
mixed printed/handwritten pages. It is optional because it needs an API key and sends
the image to Google; the local EasyOCR path remains the default.

The provider only produces text. Parsing and the human review gate are unchanged.
"""

from __future__ import annotations

import base64

from app.ocr.base import LabResult, OcrResult
from app.ocr.easyocr_provider import OcrInputError, _pdf_text, _render_pdf
from app.ocr.parsing import candidates_from_text

VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


class GoogleVisionProvider:
    def __init__(self, api_key: str, languages: tuple[str, ...] = ("en",)) -> None:
        if not api_key:
            raise OcrInputError("Google Vision is selected but TAALMEL_GOOGLE_VISION_API_KEY is empty.")
        self._api_key = api_key
        self._languages = languages

    def _image_bytes(self, data: bytes, mime_type: str) -> bytes:
        if mime_type == "application/pdf":
            return _render_pdf(data)
        return data

    def _read(self, data: bytes, mime_type: str) -> str:
        if mime_type == "application/pdf":
            text = _pdf_text(data)
            if text:
                return text
            data = _render_pdf(data)
        image = data
        payload = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(image).decode("ascii")},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                    "imageContext": {"languageHints": list(self._languages)},
                }
            ]
        }
        import httpx

        try:
            response = httpx.post(
                VISION_URL,
                params={"key": self._api_key},
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            body = response.json()
            first = (body.get("responses") or [{}])[0]
            if first.get("error"):
                raise OcrInputError(str(first["error"].get("message", "Vision OCR failed")))
            return str(first.get("fullTextAnnotation", {}).get("text", "") or "")
        except OcrInputError:
            raise
        except Exception as exc:
            raise OcrInputError(f"Google Vision OCR failed: {str(exc)[:200]}") from exc

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
