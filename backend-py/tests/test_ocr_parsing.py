"""Text parsing for OCR output, and the OCR provider selection.

These tests do not load a vision model. They cover the part that turns text into
medicines — which is where the correctness risk actually lives — plus the provider
fallback behaviour.
"""

import pytest

from app.ocr import parsing
from app.ocr.base import MedicationCandidate
from app.ocr.lab_parsing import values_from_text
from app.ocr.parsing import candidates_from_text, parse_line, repair_digits
from app.ocr.provider import ocr_mode


# ── Lines that must be rejected ─────────────────────────────────────

@pytest.mark.parametrize(
    "line",
    [
        "Rx",
        "Patient: Mr Sharma   Age: 68",
        "Dr. A. Rao  MBBS  Reg No 12345",
        "Diagnosis: Type 2 Diabetes",
        "Date: 12/11/2026",
        "Signature",
        "-----",
        "",
        "   ",
        "Advice: low salt diet",
        "Follow-up after 2 weeks",
    ],
)
def test_non_medication_lines_are_rejected(line: str) -> None:
    assert parse_line(line) is None


# ── Lines that must be accepted ─────────────────────────────────────

@pytest.mark.parametrize(
    "line, name, dose, freq",
    [
        ("Tab Ecosprin 75mg OD", "Ecosprin", "75mg", "once daily"),
        ("Cap Omez 20mg BD", "Omez", "20mg", "twice daily"),
        ("Metformin 500mg twice daily", "Metformin", "500mg", "twice daily"),
        ("1. Tab Telma 40mg 1-0-0", "Telma", "40mg", "1-0-0"),
        ("Tab Thyronorm 50mcg OD for 30 days", "Thyronorm", "50mcg", "once daily"),
        ("Syp Calpol 5ml SOS", "Calpol", "5ml", "as needed"),
    ],
)
def test_medication_lines_are_parsed(line: str, name: str, dose: str, freq: str) -> None:
    parsed = parse_line(line)
    assert parsed is not None, line
    assert parsed.name == name
    assert parsed.dosage == dose
    assert parsed.schedule == freq


def test_serial_number_prefix_is_removed() -> None:
    parsed = parse_line("3) Tab Amlopin 5mg OD")
    assert parsed is not None
    assert parsed.name == "Amlopin"


def test_duration_is_captured_separately() -> None:
    parsed = parse_line("Tab Thyronorm 50mcg OD for 30 days")
    assert parsed is not None
    assert parsed.duration == "for 30 days"


# ── OCR digit confusions ────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2Omg", "20mg"),      # letter O for zero
        ("5O0mg", "500mg"),    # letter O in the middle
        ("l0mg", "10mg"),      # lowercase L for one
        ("20 mg", "20 mg"),    # already correct
    ],
)
def test_digit_confusions_are_repaired(raw: str, expected: str) -> None:
    assert repair_digits(raw) == expected


@pytest.mark.parametrize("name", ["Omez", "Insulin Glargine 100iu/ml", "Omnacortil", "Ilosone"])
def test_medicine_names_are_never_altered(name: str) -> None:
    assert repair_digits(name) == name


def test_confusion_is_repaired_in_a_real_line() -> None:
    parsed = parse_line("Cap Omez 2Omg BD")
    assert parsed is not None
    assert parsed.dosage == "20mg"
    assert parsed.name == "Omez"


# ── Whole document ──────────────────────────────────────────────────

def test_full_document_extracts_only_medicines() -> None:
    doc = """
Patient: Mr Sharma  Age: 68
Dr. A. Rao MBBS
Rx
Tab Ecosprin 75mg OD
Cap Omez 20mg BD
Metformin 500mg twice daily
Advice: low salt diet
"""
    candidates = candidates_from_text(doc)
    names = [c.medication_name for c in candidates]
    assert names == ["Ecosprin", "Omez", "Metformin"]


def test_duplicate_names_are_collapsed() -> None:
    doc = "Tab Ecosprin 75mg OD\nTab Ecosprin 75mg OD"
    assert len(candidates_from_text(doc)) == 1


def test_empty_document_yields_nothing() -> None:
    assert candidates_from_text("") == []
    assert candidates_from_text("   \n  ") == []


def test_confidence_reflects_understanding() -> None:
    """A line with name, dose and schedule is trusted more than one with only a dose."""
    full = candidates_from_text("Tab Ecosprin 75mg OD")[0]
    sparse = candidates_from_text("Tab Ecosprin 75mg")[0]
    assert full.confidence > sparse.confidence


def test_bare_name_with_no_dose_or_schedule_is_not_a_candidate() -> None:
    """Too ambiguous to call a medicine: it must be skipped, not guessed at."""
    assert candidates_from_text("Ecosprin tablet") == []


def test_confidence_stays_below_certainty() -> None:
    """Nothing from OCR may claim certainty; human verification is always required."""
    full = candidates_from_text("Tab Ecosprin 75mg OD for 30 days")[0]
    assert full.confidence < 1.0


# ── Lab parsing ─────────────────────────────────────────────────────

def test_lab_values_are_extracted_with_units_and_ranges() -> None:
    text = (
        "Stub Diagnostics Laboratory\n"
        "Date: 2026-09-14\n"
        "HbA1c : 8.2 %  4.0 - 5.6\n"
        "Creatinine 1.1 mg/dL  0.7 - 1.3\n"
    )
    result = values_from_text(text)
    by_name = {v.test_name: v for v in result.values}
    assert by_name["HbA1c"].value == "8.2"
    assert by_name["HbA1c"].unit == "%"
    assert by_name["HbA1c"].reference_range_raw == "4.0 - 5.6"
    assert by_name["Creatinine"].unit == "mg/dL"
    assert result.captured_on == "2026-09-14"


def test_lab_date_is_captured_in_dmy_order_too() -> None:
    result = values_from_text("HbA1c 8.2 %\nDate: 14/09/2026")
    assert result.captured_on == "2026-09-14"


def test_missing_unit_stays_none_rather_than_guessed() -> None:
    result = values_from_text("Haemoglobin 13.5")
    assert result.values
    assert result.values[0].unit is None


def test_lab_reference_ranges_are_not_interpreted() -> None:
    """Values are stored as printed; nothing records high/low/normal."""
    result = values_from_text("HbA1c 8.2 % 4.0 - 5.6")
    candidate = result.values[0]
    assert not hasattr(candidate, "flag")
    assert not hasattr(candidate, "status")
    assert candidate.reference_range_raw == "4.0 - 5.6"


def test_empty_lab_text_yields_no_values() -> None:
    assert values_from_text("").values == []


# ── Provider selection ──────────────────────────────────────────────

def test_ocr_mode_is_reported_not_guessed() -> None:
    assert ocr_mode() in {"easyocr", "stub"}


def test_forcing_stub_mode_uses_the_stub(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("TAALMEL_OCR_ENGINE", "stub")
    try:
        assert ocr_mode() == "stub"
    finally:
        get_settings.cache_clear()


def test_requiring_easyocr_when_missing_fails_loudly(monkeypatch) -> None:
    """Explicitly asking for real OCR must not silently fall back to the stub."""
    from app.config import get_settings
    from app.ocr import provider as provider_module
    from app.ocr.easyocr_provider import OcrUnavailable

    get_settings.cache_clear()
    monkeypatch.setenv("TAALMEL_OCR_ENGINE", "easyocr")
    monkeypatch.setattr(provider_module, "ocr_available", lambda: False)
    try:
        with pytest.raises(OcrUnavailable):
            ocr_mode()
    finally:
        get_settings.cache_clear()


def test_stub_candidates_are_still_typed() -> None:
    """The stub must satisfy the same interface as the real provider."""
    from app.ocr.stub import StubOcrProvider

    result = StubOcrProvider().extract(b"clean", "image/jpeg")
    assert result.candidates
    assert all(isinstance(c, MedicationCandidate) for c in result.candidates)


def test_parsing_module_has_no_engine_dependency() -> None:
    """Parsing must stay importable without any vision library installed."""
    assert not hasattr(parsing, "easyocr")
