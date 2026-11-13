"""Parity suite: the cases from tests/normalization.test.ts, ported.

If one of these fails, the Python normalizer has drifted from the TypeScript reference.
"""

import pytest

from app.services.normalization import (
    NormalizationInput,
    normalize_dosage_form,
    normalize_frequency,
    normalize_medication,
    normalize_strength,
    parse_raw_medication,
    resolve_name,
)

# ── Parsing ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, name, strength, form",
    [
        ("Metformin 500mg", "Metformin", "500mg", None),
        ("Tab Ecosprin 75mg", "Ecosprin", "75mg", "tablet"),
        ("Dolo 650", "Dolo", "650mg", None),
        ("Thyronorm 50mcg", "Thyronorm", "50mcg", None),
        ("Cap Omez 20mg", "Omez", "20mg", "capsule"),
        ("Amlodipine 5mg tablet", "Amlodipine", "5mg", "tablet"),
    ],
)
def test_parse_raw_medication(raw: str, name: str, strength: str, form: str | None) -> None:
    parsed = parse_raw_medication(raw)
    assert parsed.name == name
    assert parsed.strength == strength
    assert parsed.dosage_form == form


def test_parse_glucophage_xr_keeps_brand_and_strength() -> None:
    parsed = parse_raw_medication("Glucophage XR 1000 mg")
    assert parsed.name.lower().startswith("glucophage")
    assert parsed.strength == "1000mg"


def test_parse_insulin_compound_strength() -> None:
    parsed = parse_raw_medication("Insulin Glargine 100iu/ml")
    assert "Insulin" in parsed.name
    assert parsed.strength == "100iu/ml"


def test_parse_empty_is_safe() -> None:
    parsed = parse_raw_medication("")
    assert parsed.name == ""
    assert parsed.strength is None


# ── Name resolution ─────────────────────────────────────────────────

def test_exact_generic_match() -> None:
    r = resolve_name("Metformin")
    assert r.generic_name == "Metformin"
    assert r.method == "EXACT_GENERIC_MATCH"
    assert r.confidence == 1.0


def test_generic_match_is_case_insensitive() -> None:
    assert resolve_name("metformin").generic_name == "Metformin"


@pytest.mark.parametrize(
    "brand, generic",
    [
        ("Glucophage", "Metformin"),
        ("Ecosprin", "Aspirin"),
        ("Dolo", "Paracetamol"),
        ("Crocin", "Paracetamol"),
        ("Lipitor", "Atorvastatin"),
        ("Thyronorm", "Levothyroxine"),
    ],
)
def test_brand_lookup(brand: str, generic: str) -> None:
    r = resolve_name(brand)
    assert r.generic_name == generic
    assert r.method == "BRAND_LOOKUP"


def test_brand_lookup_confidence_meets_threshold() -> None:
    assert resolve_name("Glucophage").confidence >= 0.9


def test_unknown_medication_is_unresolved() -> None:
    r = resolve_name("Xyzabc123Med")
    assert r.generic_name is None
    assert r.method == "UNRESOLVED"
    assert r.confidence == 0


def test_empty_name_is_unresolved() -> None:
    r = resolve_name("")
    assert r.generic_name is None
    assert r.method == "UNRESOLVED"


def test_multi_word_brand_resolves_via_first_word() -> None:
    assert resolve_name("Met XL").generic_name is not None


# ── Strength ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("500 mg", "500mg"),
        ("500mg", "500mg"),
        ("0.5g", "0.5g"),
        ("50 mcg", "50mcg"),
        ("100iu/ml", "100iu/ml"),
        ("1000 mg", "1000mg"),
    ],
)
def test_normalize_strength(raw: str, expected: str) -> None:
    assert normalize_strength(raw) == expected


@pytest.mark.parametrize("raw", ["", None])
def test_normalize_strength_empty(raw: str | None) -> None:
    assert normalize_strength(raw) is None


# ── Dosage form and frequency ───────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("tab", "tablet"),
        ("cap", "capsule"),
        ("SR", "sustained-release tablet"),
        ("XR", "extended-release tablet"),
        ("syp", "syrup"),
        ("inj", "injection"),
        ("lozenge", "lozenge"),
    ],
)
def test_normalize_dosage_form(raw: str, expected: str) -> None:
    assert normalize_dosage_form(raw) == expected


def test_normalize_dosage_form_none() -> None:
    assert normalize_dosage_form(None) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("od", "once daily"),
        ("bd", "twice daily"),
        ("tid", "three times daily"),
        ("hs", "at bedtime"),
        ("sos", "as needed"),
        ("every 8 hours", "every 8 hours"),
    ],
)
def test_normalize_frequency(raw: str, expected: str) -> None:
    assert normalize_frequency(raw) == expected


def test_normalize_frequency_none() -> None:
    assert normalize_frequency(None) is None


# ── Full pipeline ───────────────────────────────────────────────────

def test_known_brand_with_strength_and_frequency_is_normalized() -> None:
    r = normalize_medication(NormalizationInput(name_raw="Glucophage 500mg", frequency="bd"))
    assert r.name_generic == "Metformin"
    assert r.name_brand is not None
    assert r.strength == "500mg"
    assert r.frequency == "twice daily"
    assert r.status == "NORMALIZED"
    assert r.confidence >= 0.7
    assert r.active_ingredient == "Metformin Hydrochloride"
    assert r.category == "Antidiabetic"


def test_known_generic_is_exact_match_with_full_confidence() -> None:
    r = normalize_medication(NormalizationInput(name_raw="Metformin 1000mg"))
    assert r.name_generic == "Metformin"
    assert r.name_brand is None
    assert r.strength == "1000mg"
    assert r.status == "NORMALIZED"
    assert r.method == "EXACT_GENERIC_MATCH"
    assert r.confidence == 1.0


def test_dolo_650_normalizes_to_paracetamol() -> None:
    r = normalize_medication(NormalizationInput(name_raw="Dolo 650"))
    assert r.name_generic == "Paracetamol"
    assert r.strength == "650mg"
    assert r.status == "NORMALIZED"


def test_tab_ecosprin_normalizes_to_aspirin() -> None:
    r = normalize_medication(NormalizationInput(name_raw="Tab Ecosprin 75mg"))
    assert r.name_generic == "Aspirin"
    assert r.strength == "75mg"
    assert r.dosage_form == "tablet"


def test_unknown_medication_needs_review_but_keeps_strength() -> None:
    r = normalize_medication(NormalizationInput(name_raw="SomeFakelyNewDrug 100mg"))
    assert r.status == "NEEDS_REVIEW"
    assert r.name_generic is None
    assert r.method == "UNRESOLVED"
    assert r.strength == "100mg"


def test_empty_name_needs_review_with_zero_confidence() -> None:
    r = normalize_medication(NormalizationInput(name_raw=""))
    assert r.status == "NEEDS_REVIEW"
    assert r.name_generic is None
    assert r.confidence == 0


def test_dosage_field_supplies_strength_when_name_has_none() -> None:
    r = normalize_medication(NormalizationInput(name_raw="Metformin", dosage="500mg", frequency="od"))
    assert r.name_generic == "Metformin"
    assert r.strength == "500mg"
    assert r.frequency == "once daily"


def test_thyronorm_50mcg_normalizes_to_levothyroxine() -> None:
    r = normalize_medication(NormalizationInput(name_raw="Thyronorm 50mcg"))
    assert r.name_generic == "Levothyroxine"
    assert r.strength == "50mcg"


def test_cap_omez_normalizes_to_omeprazole() -> None:
    r = normalize_medication(NormalizationInput(name_raw="Cap Omez 20mg"))
    assert r.name_generic == "Omeprazole"
    assert r.strength == "20mg"
    assert r.dosage_form == "capsule"


def test_never_invents_generic_for_unknown() -> None:
    r = normalize_medication(NormalizationInput(name_raw="XyzUnknown123"))
    assert r.name_generic is None
    assert r.status != "NORMALIZED"


def test_known_strength_adds_confidence_boost() -> None:
    known = normalize_medication(NormalizationInput(name_raw="Metformin 500mg"))
    unknown_strength = normalize_medication(NormalizationInput(name_raw="Metformin 777mg"))
    assert known.confidence >= unknown_strength.confidence
