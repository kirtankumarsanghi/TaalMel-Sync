"""Real OCR via EasyOCR, with PaddleOCR as an optional fallback.

Design notes:
- The engine is loaded lazily on first use. Importing the app must not load a
  multi-hundred-megabyte model, and tests must not need it.
- EasyOCR is asked for English plus any configured Indian scripts. If a script pack is
  unavailable the engine still runs; it simply returns less text rather than failing.
- This provider only produces text. Deciding what the text means is `app.ocr.parsing`.
- PDFs are rendered to an image first, because EasyOCR reads images, not PDF pages.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from app.ocr.base import LabResult, OcrResult, status_for
from app.ocr.parsing import candidates_from_text

# Languages EasyOCR can be asked for. Indian-language packs need separate model files,
# so they are opt-in; English is always included.
DEFAULT_LANGUAGES = ("en",)


class OcrUnavailable(RuntimeError):
    """Raised when no OCR engine could be loaded."""


class OcrInputError(RuntimeError):
    """Raised when the uploaded file cannot be decoded as an image or PDF."""


@dataclass
class _Engine:
    reader: Any
    languages: tuple[str, ...]


_engine: _Engine | None = None


def _load_engine(languages: tuple[str, ...]) -> _Engine:
    """Load EasyOCR once and reuse it, supplying a small, fixed script list.

    'gpu=False' is intentional: this runs on a caregiver's modest hardware, and CPU is
    slower but predictable. Vision models that need a GPU are a deployment decision.
    """
    global _engine
    if _engine is not None and _engine.languages == languages:
        return _engine

    try:
        import easyocr  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on install
        raise OcrUnavailable(
            "EasyOCR is not installed. Install it with `uv add easyocr` or run with the stub provider."
        ) from exc

    reader = easyocr.Reader(list(languages), gpu=False, verbose=False)
    _engine = _Engine(reader=reader, languages=languages)
    return _engine


def _pdf_text(data: bytes, page_limit: int = 20) -> str:
    """Return the PDF's own text layer when it has one.

    Generated reports and many hospital PDFs already contain selectable text. Running
    OCR over a rendered page throws that accuracy away, so use the text layer first and
    only rasterize scanned PDFs.
    """
    try:
        import pymupdf  # PyMuPDF >= 2.x
    except ImportError:  # pragma: no cover - older PyMuPDF only exposes `fitz`
        try:
            import fitz as pymupdf  # type: ignore[no-redef]
        except ImportError:
            return ""

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return ""

    pages: list[str] = []
    for index in range(min(page_limit, document.page_count)):
        pages.append(document.load_page(index).get_text("text"))
    return "\n".join(pages).strip()


def _render_pdf(data: bytes, page_limit: int = 3) -> bytes:
    """Render the first pages of a PDF to a PNG, since the OCR engine takes images."""
    try:
        import pymupdf  # PyMuPDF >= 2.x
    except ImportError:  # pragma: no cover - older PyMuPDF only exposes `fitz`
        try:
            import fitz as pymupdf  # type: ignore[no-redef]
        except ImportError as exc:
            raise OcrUnavailable(
                "PDF input needs PyMuPDF. Install it with `uv add pymupdf`, or upload an image."
            ) from exc

    document = pymupdf.open(stream=data, filetype="pdf")
    if document.page_count == 0:
        raise OcrUnavailable("The PDF has no pages.")

    # A prescription is usually one page; read the first few at high enough DPI that
    # small print survives.
    images = []
    for index in range(min(page_limit, document.page_count)):
        pixmap = document.load_page(index).get_pixmap(dpi=300)
        images.append(pixmap.tobytes("png"))

    if len(images) == 1:
        return images[0]

    # Stack pages vertically so a single OCR pass can read them.
    from PIL import Image  # type: ignore[import-not-found]

    opened = [Image.open(io.BytesIO(raw)).convert("RGB") for raw in images]
    width = max(im.width for im in opened)
    height = sum(im.height for im in opened)
    canvas = Image.new("RGB", (width, height), "white")
    offset = 0
    for im in opened:
        canvas.paste(im, (0, offset))
        offset += im.height
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


class EasyOcrProvider:
    """Production OCR provider. Produces text, then parses it into candidates."""

    def __init__(self, languages: tuple[str, ...] = DEFAULT_LANGUAGES, engine: Any | None = None) -> None:
        self._languages = languages
        self._injected = engine

    def _read(self, data: bytes, mime_type: str) -> str:
        if mime_type == "application/pdf":
            text = _pdf_text(data)
            if text:
                return text
            data = _render_pdf(data)

        reader = self._injected if self._injected is not None else _load_engine(self._languages).reader

        # paragraph=True merges nearby lines into prose, which destroys the line structure
        # a prescription depends on ("Tab A 5mg OD" / "Cap B 20mg BD" become one string).
        # Read with bounding boxes and rebuild lines by vertical position instead.
        try:
            blocks = reader.readtext(data, detail=1, paragraph=False)
        except OcrInputError:  # pragma: no cover - defensive
            raise
        except Exception as exc:
            # Some EasyOCR builds do not accept `paragraph`. Only retry when the message
            # names that argument; any other failure is a decode problem and must surface
            # as a clear error rather than a stack trace from inside a vision library.
            if "paragraph" in str(exc).lower():
                try:
                    blocks = reader.readtext(data, detail=1)
                except Exception as inner:
                    raise OcrInputError(
                        "The uploaded file could not be read as an image. "
                        "Try a clearer photo or a PDF."
                    ) from inner
            else:
                raise OcrInputError(
                    "The uploaded file could not be read as an image. "
                    "Try a clearer photo or a PDF."
                ) from exc

        return _blocks_to_lines(blocks)

    def extract(self, data: bytes, mime_type: str) -> OcrResult:
        text = self._read(data, mime_type)
        candidates = candidates_from_text(text)
        if not candidates:
            from app.ocr.handwriting import fallback_candidates_from_text

            candidates = fallback_candidates_from_text(text)
        return OcrResult(raw_text=text, candidates=candidates)

    def read_text(self, data: bytes, mime_type: str) -> str:
        """Raw text from an image/PDF. Used by label verification as well as intake."""
        return self._read(data, mime_type)

    def extract_lab(self, data: bytes, mime_type: str) -> LabResult:
        """Lab reports are tables, so values are parsed row by row from the same text."""
        from app.ocr.lab_parsing import values_from_text

        text = self._read(data, mime_type)
        return values_from_text(text)


def _blocks_to_lines(blocks: Any) -> str:
    """Rebuild text lines from EasyOCR's (box, text, confidence) blocks.

    Boxes on roughly the same horizontal band are one line; within a line, left-to-right
    order is preserved. This keeps "Tab Ecosprin 75mg OD" on its own line.
    """
    if not blocks:
        return ""

    rows: list[tuple[float, float, str]] = []
    for item in blocks:
        try:
            box, text, _confidence = item
            ys = [point[1] for point in box]
            xs = [point[0] for point in box]
        except (TypeError, ValueError, IndexError):
            continue
        if not str(text).strip():
            continue
        rows.append((sum(ys) / len(ys), min(xs), str(text).strip()))

    rows.sort(key=lambda r: (r[0], r[1]))

    # Group blocks whose vertical centres are within a tolerance of each other.
    lines: list[list[tuple[float, float, str]]] = []
    for row in rows:
        if lines and abs(row[0] - lines[-1][0][0]) <= 12:
            lines[-1].append(row)
        else:
            lines.append([row])

    return "\n".join(
        " ".join(text for _y, _x, text in sorted(line, key=lambda r: r[1])) for line in lines
    )


def ocr_available() -> bool:
    """Whether a real OCR engine can be used, without loading the model."""
    try:
        import importlib.util

        return importlib.util.find_spec("easyocr") is not None
    except Exception:  # pragma: no cover
        return False


__all__ = [
    "DEFAULT_LANGUAGES",
    "EasyOcrProvider",
    "OcrInputError",
    "OcrUnavailable",
    "ocr_available",
    "status_for",
]
