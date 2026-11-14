"""Local handwritten-text OCR using Microsoft TrOCR.

TrOCR is a line-level handwriting model. A full prescription page is therefore split
into lines with EasyOCR's detector, each crop is transcribed by TrOCR, and the lines are
rejoined in reading order. This is optional because it downloads a model and needs the
`handwriting` extra; Google Vision is the lighter production alternative.

Every line is returned with low confidence. The existing verify screen is still the gate:
nothing becomes a medication until a person confirms it.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from app.ocr.base import LabResult, OcrResult
from app.ocr.easyocr_provider import OcrInputError, _pdf_text, _render_pdf
from app.ocr.parsing import candidates_from_text


def trocr_available() -> bool:
    return (
        importlib.util.find_spec("transformers") is not None
        and importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("easyocr") is not None
    )


class TrOcrProvider:
    def __init__(self, model_name: str = "microsoft/trocr-small-handwritten") -> None:
        self._model_name = model_name
        self._processor: Any = None
        self._model: Any = None
        self._reader: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise OcrInputError(
                "TrOCR needs `transformers`. Install the handwriting extra: "
                "`uv add --optional handwriting transformers sentencepiece`."
            ) from exc
        self._processor = TrOCRProcessor.from_pretrained(self._model_name)
        self._model = VisionEncoderDecoderModel.from_pretrained(self._model_name)
        self._model.eval()

    def _line_boxes(self, image) -> list[tuple[int, int, int, int]]:
        import numpy as np

        if self._reader is None:
            import easyocr

            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        blocks = self._reader.readtext(np.array(image), detail=1, paragraph=False)
        boxes: list[tuple[int, int, int, int]] = []
        for item in blocks:
            try:
                box = item[0]
            except (TypeError, IndexError, KeyError):
                continue
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
            width, height = x2 - x1, y2 - y1
            # Skip tiny text (letterhead, footers) and absurd boxes.
            if width < 55 or height < 12 or width > image.width * 0.98:
                continue
            boxes.append((x1, y1, x2, y2))
        boxes.sort(key=lambda b: (b[1], b[0]))
        return boxes[:24]

    def _read(self, data: bytes, mime_type: str) -> str:
        from io import BytesIO

        from PIL import Image

        if mime_type == "application/pdf":
            text = _pdf_text(data)
            if text:
                return text
            data = _render_pdf(data)
        image = Image.open(BytesIO(data)).convert("RGB")
        self._load()

        boxes = self._line_boxes(image)
        if not boxes:
            boxes = [(0, 0, image.width, image.height)]

        lines: list[str] = []
        crops = []
        for x1, y1, x2, y2 in boxes:
            pad = 4
            crop = image.crop(
                (max(0, x1 - pad), max(0, y1 - pad), min(image.width, x2 + pad), min(image.height, y2 + pad))
            )
            if crop.width < 8 or crop.height < 8:
                continue
            crops.append(crop)

        if not crops:
            return ""
        import torch

        for start in range(0, len(crops), 8):
            batch = crops[start : start + 8]
            pixel_values = self._processor(images=batch, return_tensors="pt").pixel_values
            with torch.no_grad():
                generated = self._model.generate(pixel_values, max_length=64)
            texts = self._processor.batch_decode(generated, skip_special_tokens=True)
            lines.extend(text.strip() for text in texts if text.strip())
        return "\n".join(lines)

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
