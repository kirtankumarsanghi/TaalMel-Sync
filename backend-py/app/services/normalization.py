"""Medication name, strength, form, and frequency normalization.

Pure functions over the curated dictionary in app/data/medicationDictionary.json.
No database access here, so every rule is unit-testable. Persistence lives in
app/services/medications.py.

Name resolution order (first hit wins):
  1. exact generic match            -> EXACT_GENERIC_MATCH, 1.0
  2. exact brand match              -> BRAND_LOOKUP, 0.95
  3. first word is a generic        -> EXACT_GENERIC_MATCH, 0.9
  4. first word is a brand          -> BRAND_LOOKUP, 0.85
  5. prefix fuzzy (len >= 4):
       one hit   -> FUZZY_MATCH, min(0.75, 0.5 + 0.3 * similarity)
       many hits -> FUZZY_MATCH, 0.4 (best guess, ambiguous)
  6. otherwise                      -> UNRESOLVED, 0

Status: UNRESOLVED -> NEEDS_REVIEW; confidence >= 0.7 -> NORMALIZED;
>= 0.5 -> AMBIGUOUS; else NEEDS_REVIEW. A known strength adds +0.05 (capped at 1.0).
"""

import json
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Literal

DICT_PATH = Path(__file__).resolve().parent.parent / "data" / "medicationDictionary.json"

NormalizationMethod = Literal[
    "EXACT_GENERIC_MATCH", "BRAND_LOOKUP", "FUZZY_MATCH", "MANUAL", "UNRESOLVED"
]
NormalizationStatus = Literal[
    "NORMALIZED", "NEEDS_REVIEW", "AMBIGUOUS", "MANUALLY_VERIFIED", "PENDING"
]

CONFIDENCE_NORMALIZED = 0.7
CONFIDENCE_AMBIGUOUS = 0.5
MIN_FUZZY_LENGTH = 4


@dataclass(frozen=True)
class DictionaryEntry:
    generic_name: str
    brand_names: tuple[str, ...]
    strengths: tuple[str, ...]
    dosage_forms: tuple[str, ...]
    active_ingredient: str
    category: str


@dataclass(frozen=True)
class Dictionary:
    entries: tuple[DictionaryEntry, ...]
    dosage_form_aliases: dict[str, str]
    strength_pattern: re.Pattern[str]
    frequency_aliases: dict[str, str]
    generic_index: dict[str, DictionaryEntry] = field(repr=False)
    brand_index: dict[str, DictionaryEntry] = field(repr=False)


@lru_cache(maxsize=1)
def load_dictionary() -> Dictionary:
    raw = json.loads(DICT_PATH.read_text(encoding="utf-8"))
    entries = tuple(
        DictionaryEntry(
            generic_name=m["genericName"],
            brand_names=tuple(m["brandNames"]),
            strengths=tuple(m["strengths"]),
            dosage_forms=tuple(m["dosageForms"]),
            active_ingredient=m["activeIngredient"],
            category=m["category"],
        )
        for m in raw["medications"]
    )
    generic_index = {e.generic_name.lower(): e for e in entries}
    brand_index: dict[str, DictionaryEntry] = {}
    for e in entries:
        for brand in e.brand_names:
            brand_index[brand.lower()] = e
    return Dictionary(
        entries=entries,
        dosage_form_aliases={k.lower(): v for k, v in raw["dosageFormAliases"].items()},
        strength_pattern=re.compile(raw["strengthPattern"], re.IGNORECASE),
        frequency_aliases={k.lower(): v for k, v in raw["frequencyAliases"].items()},
        generic_index=generic_index,
        brand_index=brand_index,
    )


@dataclass(frozen=True)
class ParsedMedication:
    name: str
    strength: str | None
    strength_unit: str | None
    dosage_form: str | None
    remainder: str | None


@dataclass(frozen=True)
class NameResolution:
    generic_name: str | None
    brand_name: str | None
    method: NormalizationMethod
    confidence: float
    matched_entry: DictionaryEntry | None


@dataclass(frozen=True)
class NormalizationInput:
    name_raw: str
    dosage: str | None = None
    frequency: str | None = None
    instructions: str | None = None


@dataclass(frozen=True)
class NormalizationResult:
    name_generic: str | None
    name_brand: str | None
    strength: str | None
    strength_raw: str | None
    strength_unit: str | None
    dosage_form: str | None
    dosage_form_raw: str | None
    frequency: str | None
    frequency_raw: str | None
    active_ingredient: str | None
    category: str | None
    method: NormalizationMethod
    confidence: float
    status: NormalizationStatus
    matched_entry: DictionaryEntry | None


def parse_raw_medication(raw: str | None) -> ParsedMedication:
    if not raw or not raw.strip():
        return ParsedMedication("", None, None, None, None)

    d = load_dictionary()
    text = raw.strip()
    alias_keys = sorted(d.dosage_form_aliases, key=len, reverse=True)
    dosage_form: str | None = None
    dosage_form_raw: str | None = None

    prefix = re.match(
        rf"^({'|'.join(re.escape(k) for k in alias_keys)})\.?\s+", text, re.IGNORECASE
    )
    if prefix:
        dosage_form_raw = prefix.group(1)
        dosage_form = d.dosage_form_aliases.get(prefix.group(1).lower())
        text = text[prefix.end():].strip()

    strength: str | None = None
    strength_unit: str | None = None
    match = d.strength_pattern.search(text)
    if match:
        num, unit = match.group(1), match.group(2).lower()
        strength = f"{num}{unit}"
        strength_unit = unit
        if match.group(3) and match.group(4):
            strength = f"{num}{unit}/{match.group(3)}{match.group(4).lower()}"
        elif match.group(5):
            strength = f"{num}{unit}{match.group(5).lower()}"
        text = (text[: match.start()] + " " + text[match.end():]).strip()
    else:
        bare = re.search(r"\s+(\d+(?:\.\d+)?)\s*$", text)
        if bare:
            strength = f"{bare.group(1)}mg"
            strength_unit = "mg"
            text = text[: bare.start()].strip()

    if dosage_form is None:
        suffix = re.search(
            rf"\s+({'|'.join(re.escape(k) for k in alias_keys)})\.?\s*$", text, re.IGNORECASE
        )
        if suffix:
            dosage_form_raw = suffix.group(1)
            dosage_form = d.dosage_form_aliases.get(suffix.group(1).lower())
            text = text[: suffix.start()].strip()

    name = re.sub(r"\s+", " ", text).strip()
    return ParsedMedication(name, strength, strength_unit, dosage_form, dosage_form_raw)


def resolve_name(name: str | None) -> NameResolution:
    if not name or not name.strip():
        return NameResolution(None, None, "UNRESOLVED", 0.0, None)

    d = load_dictionary()
    clean = name.strip().lower()

    if entry := d.generic_index.get(clean):
        return NameResolution(entry.generic_name, None, "EXACT_GENERIC_MATCH", 1.0, entry)
    if entry := d.brand_index.get(clean):
        return NameResolution(entry.generic_name, name.strip(), "BRAND_LOOKUP", 0.95, entry)

    first_word = clean.split()[0]
    if entry := d.generic_index.get(first_word):
        return NameResolution(entry.generic_name, None, "EXACT_GENERIC_MATCH", 0.9, entry)
    if entry := d.brand_index.get(first_word):
        return NameResolution(entry.generic_name, first_word, "BRAND_LOOKUP", 0.85, entry)

    if len(clean) >= MIN_FUZZY_LENGTH:
        hits: list[tuple[DictionaryEntry, bool, float]] = []
        for gname, entry in d.generic_index.items():
            if gname.startswith(clean):
                hits.append((entry, False, len(clean) / len(gname)))
        for bname, entry in d.brand_index.items():
            if bname.startswith(clean):
                hits.append((entry, True, len(clean) / len(bname)))

        if len(hits) == 1:
            entry, is_brand, similarity = hits[0]
            return NameResolution(
                entry.generic_name,
                name.strip() if is_brand else None,
                "FUZZY_MATCH",
                min(0.75, 0.5 + similarity * 0.3),
                entry,
            )
        if len(hits) > 1:
            entry, is_brand, _ = max(hits, key=lambda h: h[2])
            return NameResolution(
                entry.generic_name,
                name.strip() if is_brand else None,
                "FUZZY_MATCH",
                0.4,
                entry,
            )

    return NameResolution(None, None, "UNRESOLVED", 0.0, None)


def normalize_strength(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    d = load_dictionary()
    match = d.strength_pattern.match(raw.strip())
    if not match:
        return raw.strip()
    num, unit = match.group(1), match.group(2).lower()
    if match.group(3) and match.group(4):
        return f"{num}{unit}/{match.group(3)}{match.group(4).lower()}"
    if match.group(5):
        return f"{num}{unit}{match.group(5).lower()}"
    return f"{num}{unit}"


def normalize_dosage_form(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    return load_dictionary().dosage_form_aliases.get(raw.strip().lower(), raw.strip())


def normalize_frequency(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    return load_dictionary().frequency_aliases.get(raw.strip().lower(), raw.strip())


def normalize_medication(data: NormalizationInput) -> NormalizationResult:
    if not data.name_raw or not data.name_raw.strip():
        return NormalizationResult(
            name_generic=None,
            name_brand=None,
            strength=None,
            strength_raw=None,
            strength_unit=None,
            dosage_form=None,
            dosage_form_raw=None,
            frequency=None,
            frequency_raw=data.frequency or None,
            active_ingredient=None,
            category=None,
            method="UNRESOLVED",
            confidence=0.0,
            status="NEEDS_REVIEW",
            matched_entry=None,
        )

    parsed = parse_raw_medication(data.name_raw)
    resolution = resolve_name(parsed.name)

    strength_raw = parsed.strength or data.dosage or None
    strength = normalize_strength(strength_raw)
    frequency_raw = data.frequency or None
    frequency = normalize_frequency(frequency_raw)

    confidence = resolution.confidence
    if resolution.matched_entry and strength:
        known = {s.lower() for s in resolution.matched_entry.strengths}
        if strength.lower() in known:
            confidence = min(1.0, confidence + 0.05)

    if resolution.method == "UNRESOLVED":
        status: NormalizationStatus = "NEEDS_REVIEW"
    elif confidence >= CONFIDENCE_NORMALIZED:
        status = "NORMALIZED"
    elif confidence >= CONFIDENCE_AMBIGUOUS:
        status = "AMBIGUOUS"
    else:
        status = "NEEDS_REVIEW"

    entry = resolution.matched_entry
    return NormalizationResult(
        name_generic=resolution.generic_name,
        name_brand=resolution.brand_name,
        strength=strength,
        strength_raw=strength_raw,
        strength_unit=parsed.strength_unit,
        dosage_form=parsed.dosage_form,
        dosage_form_raw=parsed.remainder if parsed.remainder != parsed.dosage_form else None,
        frequency=frequency,
        frequency_raw=frequency_raw,
        active_ingredient=entry.active_ingredient if entry else None,
        category=entry.category if entry else None,
        method=resolution.method,
        confidence=confidence,
        status=status,
        matched_entry=entry,
    )


def with_status(result: NormalizationResult, status: NormalizationStatus) -> NormalizationResult:
    return replace(result, status=status)
