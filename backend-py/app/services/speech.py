"""Speech-to-text for voice self-reports.

The problem: an elderly patient who cannot comfortably type in English still needs to
report whether they took a medicine. They speak; the system transcribes, then matches
the transcript against that patient's known medicine list.

Two rules that matter more than accuracy:
- If the transcript cannot be matched to exactly one medicine, nothing is recorded and
  a clarification is asked. Guessing would corrupt the record silently.
- The transcript is stored with the resulting report, so the source is auditable.

Whisper is the intended engine. It is heavy and optional, so it sits behind a provider
interface with a deterministic stub, exactly like OCR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

# Words that indicate a report, in English and in the launch languages. These are
# interface vocabulary, not medical content.
_TAKEN_WORDS = (
    "took", "taken", "take", "took it", "had it", "yes",
    "li", "le li", "liya", "kha li", "हाँ", "ले ली", "लिया",
    "எடுத்துக்கொண்டேன்", "ஆம்", "తీసుకున్నాను", "అవును",
    "নিয়েছি", "হ্যাঁ", "घेतले", "हो",
)
_NOT_TAKEN_WORDS = (
    "not", "no", "did not", "didnt", "didn't", "haven't", "havent", "missed", "skipped",
    "nahi", "nahin", "नहीं", "नही", "எடுத்துக்கொள்ளவில்லை", "இல்லை",
    "తీసుకోలేదు", "లేదు", "নিইনি", "না", "घेतले नाही", "नाही",
)


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None = None
    confidence: float = 0.0


class SpeechToTextProvider(Protocol):
    def transcribe(self, audio: bytes, mime_type: str, language: str | None = None) -> Transcript: ...


def whisper_available() -> bool:
    """Whether Whisper can be imported, without loading a model."""
    import importlib.util

    return importlib.util.find_spec("whisper") is not None


class SpeechUnavailable(RuntimeError):
    """Raised when no speech engine could be loaded."""


class SpeechInputError(RuntimeError):
    """Raised when the audio cannot be decoded."""


# ── Intent detection ─────────────────────────────────────────────────

@dataclass(frozen=True)
class ReportIntent:
    taking: bool | None
    matched_phrase: str | None
    confident: bool


def detect_intent(transcript: str) -> ReportIntent:
    """Decide whether a transcript says 'took it' or 'did not'.

    A negative phrase wins over a positive one: "no, I did not take it" contains both
    "no" and "take", and the safe reading is the negative one.
    """
    if not transcript or not transcript.strip():
        return ReportIntent(taking=None, matched_phrase=None, confident=False)

    lowered = transcript.lower()

    for phrase in _NOT_TAKEN_WORDS:
        if phrase in lowered:
            return ReportIntent(taking=False, matched_phrase=phrase, confident=True)

    for phrase in _TAKEN_WORDS:
        if phrase in lowered:
            return ReportIntent(taking=True, matched_phrase=phrase, confident=True)

    return ReportIntent(taking=None, matched_phrase=None, confident=False)


# ── Medicine matching ────────────────────────────────────────────────

@dataclass(frozen=True)
class MedicineMatch:
    medication_id: str | None
    name: str | None
    ambiguous: bool
    candidates: list[str]


def match_medicine(transcript: str, medicines: list[tuple[str, str]]) -> MedicineMatch:
    """Match a transcript against (medication_id, display_name) pairs.

    Returns ambiguous=True when more than one medicine is mentioned, so the caller can
    ask which one instead of recording the wrong one.
    """
    if not medicines:
        return MedicineMatch(None, None, False, [])

    lowered = transcript.lower()
    hits: list[tuple[str, str]] = []
    for medication_id, name in medicines:
        # Match on whole words so "pan" does not match "pantoprazole" incorrectly,
        # and so a short name cannot match inside an unrelated word.
        pattern = r"\b" + re.escape(name.lower()) + r"\b"
        if re.search(pattern, lowered):
            hits.append((medication_id, name))

    if len(hits) == 1:
        return MedicineMatch(hits[0][0], hits[0][1], False, [hits[0][1]])
    if len(hits) > 1:
        return MedicineMatch(None, None, True, [h[1] for h in hits])

    # No explicit name: if the patient has exactly one medicine, the report is
    # unambiguous and can be recorded against it.
    if len(medicines) == 1:
        return MedicineMatch(medicines[0][0], medicines[0][1], False, [medicines[0][1]])

    return MedicineMatch(None, None, False, [])


# ── Providers ────────────────────────────────────────────────────────

class StubSpeechToText:
    """Deterministic provider for development and tests.

    The transcript is taken from the audio bytes themselves, so a test can control the
    result without shipping an audio fixture.
    """

    def transcribe(self, audio: bytes, mime_type: str, language: str | None = None) -> Transcript:
        if not audio:
            raise SpeechInputError("The recording is empty.")
        try:
            text = audio.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SpeechInputError(
                "The audio could not be read. Record again in a quiet place."
            ) from exc
        return Transcript(text=text.strip(), language=language, confidence=0.9)


class WhisperSpeechToText:
    """Local Whisper. Loaded lazily so the app does not carry the model at import time."""

    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            import whisper  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SpeechUnavailable(
                "Whisper is not installed. Install it with `uv add openai-whisper`, "
                "or run with the stub speech provider."
            ) from exc
        self._model = whisper.load_model(self._model_size)
        return self._model

    def transcribe(self, audio: bytes, mime_type: str, language: str | None = None) -> Transcript:
        import io
        import tempfile

        model = self._load()
        # Whisper reads from a path; write to a temporary file and clean it up.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as handle:
            handle.write(audio)
            handle.flush()
            result = model.transcribe(handle.name, language=language, fp16=False)

        text = str(result.get("text", "")).strip()
        # Whisper does not return a single confidence; use segment probabilities if present.
        segments = result.get("segments") or []
        if segments:
            confidence = sum(float(s.get("avg_logprob", -1.0)) for s in segments) / len(segments)
            confidence = max(0.0, min(1.0, 1.0 + confidence))
        else:
            confidence = 0.5 if text else 0.0

        return Transcript(text=text, language=result.get("language") or language, confidence=confidence)
