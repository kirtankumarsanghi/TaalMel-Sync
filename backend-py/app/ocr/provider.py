"""Choose an OCR provider.

Real OCR is used when the engine is installed and enabled; otherwise the deterministic
stub is used. The choice is explicit and reported, never silent — a caller can always
tell which one ran, because the stub's behaviour is obvious and `ocr_mode()` says so.
"""

from app.config import get_settings
from app.ocr.base import LabOcrProvider, OcrProvider
from app.ocr.easyocr_provider import EasyOcrProvider, ocr_available
from app.ocr.lab_stub import StubLabOcrProvider
from app.ocr.stub import StubOcrProvider


def ocr_mode() -> str:
    """'easyocr' or 'stub'. Exposed so the running mode is visible, not guessed."""
    settings = get_settings()
    if settings.ocr_engine == "stub":
        return "stub"
    if ocr_available():
        return "easyocr"
    if settings.ocr_engine == "easyocr":
        # Explicitly requested but unavailable: fail loudly rather than pretend.
        from app.ocr.easyocr_provider import OcrUnavailable

        raise OcrUnavailable(
            "TAALMEL_OCR_ENGINE=easyocr but EasyOCR is not installed."
        )
    return "stub"


def get_ocr_provider() -> OcrProvider:
    if ocr_mode() == "easyocr":
        return EasyOcrProvider()
    return StubOcrProvider()


def get_lab_ocr_provider() -> LabOcrProvider:
    if ocr_mode() == "easyocr":
        return EasyOcrProvider()
    return StubLabOcrProvider()
