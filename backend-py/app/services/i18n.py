"""Translations for the patient-facing interface.

Design constraints that matter here:
- Only *interface* strings live here: labels, prompts, buttons. Medical content —
  what a medicine is for, what a symptom means — is deliberately absent, because it
  must come from a reviewed clinical source, not from a translation file written by
  engineers.
- Adding a language means adding one file. No code change.
- A missing translation falls back to English rather than showing a key, so a patient
  never sees "medicine.taken_yesterday" on screen.

The five launch languages are the ones named in the design: Hindi, Tamil, Telugu,
Bengali, Marathi.
"""

import json
from functools import lru_cache
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parent / "translations"

LANGUAGES: dict[str, dict[str, str]] = {
    "en": {"name": "English", "native": "English"},
    "hi": {"name": "Hindi", "native": "हिन्दी"},
    "ta": {"name": "Tamil", "native": "தமிழ்"},
    "te": {"name": "Telugu", "native": "తెలుగు"},
    "bn": {"name": "Bengali", "native": "বাংলা"},
    "mr": {"name": "Marathi", "native": "मराठी"},
}

DEFAULT_LANGUAGE = "en"

# Interface strings only. Anything clinical is intentionally not translatable here.
BASE_STRINGS: dict[str, str] = {
    "app.name": "Taalmel",
    "nav.today": "Today",
    "nav.medicines": "Medicines",
    "nav.cases": "Cases",
    "nav.wellness": "Wellness",
    "nav.export": "Doctor export",
    "nav.safety": "Safety",
    "nav.questions": "Questions",
    "nav.help": "Help",
    "today.title": "Your medicines today",
    "today.empty": "No medicines have been added yet.",
    "medicine.taken": "Taken",
    "medicine.not_taken": "Not taken",
    "medicine.not_reported": "Not reported yet",
    "medicine.ask_me": "Ask me",
    "report.title": "Did you take your medicine?",
    "report.yes": "Yes, I took it",
    "report.no": "No, I did not",
    "report.thanks": "Thank you. This has been recorded.",
    "report.speak": "Speak your answer",
    "report.listening": "Listening…",
    "question.add": "Save a question for the doctor",
    "question.saved": "Saved. Taalmel does not answer medical questions.",
    "status.present": "At home",
    "status.absent": "Not at home",
    "status.unknown": "Not checked",
    "status.stale": "Needs re-checking",
    "common.back": "Back",
    "common.next": "Next",
    "common.cancel": "Cancel",
    "common.save": "Save",
    "common.loading": "Loading…",
    "help.disclaimer": "Taalmel records what happened to a medicine. It does not give medical advice.",
}


# Keys that are intentionally identical in every language.
UNTRANSLATED_KEYS = frozenset({"app.name"})


@lru_cache(maxsize=1)
def _translation_files() -> dict[str, dict[str, str]]:
    """Load any language file present on disk, so new languages need no code change."""
    loaded: dict[str, dict[str, str]] = {}
    if I18N_DIR.exists():
        for path in I18N_DIR.glob("*.json"):
            try:
                loaded[path.stem] = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # A broken translation file must not take the app down.
                continue
    return loaded


def available_languages() -> list[dict[str, str]]:
    files = _translation_files()
    languages: list[dict[str, str]] = []
    for code, meta in LANGUAGES.items():
        if code == DEFAULT_LANGUAGE or code in files:
            languages.append({"code": code, **meta})
    return languages


def normalise_language(code: str | None) -> str:
    if not code:
        return DEFAULT_LANGUAGE
    primary = code.split("-")[0].lower()
    return primary if primary in LANGUAGES else DEFAULT_LANGUAGE


def translate(key: str, language: str | None = None) -> str:
    code = normalise_language(language)
    if code == DEFAULT_LANGUAGE:
        return BASE_STRINGS.get(key, key)
    override = _translation_files().get(code, {})
    # Fall back to English rather than showing the key to a patient.
    return override.get(key) or BASE_STRINGS.get(key, key)


def catalogue(language: str | None = None) -> dict[str, str]:
    """The full string table for one language, merged over English."""
    code = normalise_language(language)
    merged = dict(BASE_STRINGS)
    if code != DEFAULT_LANGUAGE:
        merged.update({k: v for k, v in _translation_files().get(code, {}).items() if v})
    return merged


def coverage(language: str) -> dict[str, int]:
    """How completely a language is translated. Exposed so gaps are visible, not hidden.

    The brand name is excluded: it stays "Taalmel" in every language by design, so
    counting it would report a permanent 1-key gap as missing work.
    """
    code = normalise_language(language)
    translatable = [key for key in BASE_STRINGS if key not in UNTRANSLATED_KEYS]
    if code == DEFAULT_LANGUAGE:
        return {"translated": len(translatable), "total": len(translatable)}
    override = _translation_files().get(code, {})
    translated = sum(1 for key in translatable if override.get(key))
    return {"translated": translated, "total": len(translatable)}
