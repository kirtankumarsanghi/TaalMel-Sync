"""Choose an OCR provider.

Real OCR is used when the engine is installed and enabled; otherwise the deterministic
stub is used. The choice is explicit and reported, never silent — a caller can always
tell which one ran, because the stub's behaviour is obvious and `ocr_mode()` says so.
"""

from app.config import get_settings
from app.ocr.base import LabOcrProvider, OcrProvider
from app.ocr.easyocr_provider import EasyOcrProvider, OcrUnavailable, ocr_available
from app.ocr.lab_stub import StubLabOcrProvider
from app.ocr.stub import StubOcrProvider


def ocr_mode() -> str:
    """'google', 'trocr', 'easyocr', or 'stub'. Exposed so the mode is visible."""
    settings = get_settings()
    if settings.ocr_engine == "stub":
        return "stub"
    if settings.ocr_engine == "google" or (
        settings.ocr_engine == "auto" and settings.google_vision_api_key
    ):
        if not settings.google_vision_api_key:
            raise OcrUnavailable(
                "TAALMEL_OCR_ENGINE=google but TAALMEL_GOOGLE_VISION_API_KEY is empty."
            )
        return "google"
    if settings.ocr_engine == "gemini" or (
        settings.ocr_engine == "auto" and settings.gemini_api_key
    ):
        if not settings.gemini_api_key:
            raise OcrUnavailable(
                "TAALMEL_OCR_ENGINE=gemini but TAALMEL_GEMINI_API_KEY is empty."
            )
        return "gemini"
    if settings.ocr_engine == "trocr":
        from app.ocr.trocr_provider import trocr_available

        if not trocr_available():
            raise OcrUnavailable(
                "TAALMEL_OCR_ENGINE=trocr but transformers/torch/easyocr is not installed. "
                "Install the handwriting extra."
            )
        return "trocr"
    if ocr_available():
        return "easyocr"
    if settings.ocr_engine == "easyocr":
        raise OcrUnavailable("TAALMEL_OCR_ENGINE=easyocr but EasyOCR is not installed.")
    return "stub"


def get_ocr_provider() -> OcrProvider:
    settings = get_settings()
    mode = ocr_mode()
    languages = tuple(
        language.strip() for language in settings.ocr_languages.split(",") if language.strip()
    ) or ("en",)
    if mode == "google":
        from app.ocr.google_vision import GoogleVisionProvider

        return GoogleVisionProvider(settings.google_vision_api_key, languages)
    if mode == "gemini":
        from app.ocr.gemini import GeminiVisionProvider

        return GeminiVisionProvider(settings.gemini_api_key, settings.gemini_model)
    if mode == "trocr":
        from app.ocr.trocr_provider import TrOcrProvider

        return TrOcrProvider(settings.trocr_model)
    if mode == "easyocr":
        return EasyOcrProvider(languages)
    return StubOcrProvider()


def get_lab_ocr_provider() -> LabOcrProvider:
    mode = ocr_mode()
    if mode == "google":
        from app.ocr.google_vision import GoogleVisionProvider

        settings = get_settings()
        return GoogleVisionProvider(settings.google_vision_api_key)
    if mode == "gemini":
        from app.ocr.gemini import GeminiVisionProvider

        settings = get_settings()
        return GeminiVisionProvider(settings.gemini_api_key, settings.gemini_model)
    if mode in ("easyocr", "trocr"):
        return EasyOcrProvider()
    return StubLabOcrProvider()
