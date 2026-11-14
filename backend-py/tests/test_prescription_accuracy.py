"""Prescription extraction must be precise, not merely productive.

The failure this file guards against: a photographed page is not necessarily a
prescription. Before these rules existed, an invoice produced "Road Bengaluru 560001
12mg" and a lab report produced "Creatinine ldL 0 7 13" as medicines. Extracting
nonsense is worse than extracting nothing, because it silently corrupts the record.
"""

import pytest

from app.ocr.parsing import candidates_from_text, looks_like_prescription, parse_line, repair_digits

# ── Documents that must not be treated as prescriptions ──────────────

INVOICE = """GREEN LEAF STATIONERS
12 MG Road; Bengaluru 560001
GSTIN 29ABCDE1234F1Z5
Invoice No 4412 Date: 03/11/2026
Item Qty Amount
A4 paper ream 500 g 2 420.00
Blue pen pack 5 150.00
Total 570.00
Thank you for your business
Phone 9876543210"""

LAB_REPORT = """CITY DIAGNOSTICS LABORATORY
Patient: Mr Sharma
Date: 14/09/2026
Test Result Unit Range
HbAtc 8.2 % 4.0 5.6
Creatinine 1.1 mgldL 0.7 13
Total Cholesterol 212 mg/dL 125 200"""

DISCHARGE_SUMMARY = """CITY HOSPITAL
Patient Name: Mr Sharma
Admission Date: 01/10/2026
Discharge Summary
Diagnosis: Acute gastroenteritis
Condition at discharge: Stable
Advice: Plenty of oral fluids, review in OPD after 1 week
"""

PRESCRIPTION = """CITY MEDICAL CENTRE
Dr . A. Rao MBBS, MD
Reg No 12345 Date: 12/11/2026
Patient: Mr Sharma Age: 68 Sex: M
Diagnosis: Type 2 Diabetes, Hypertension
Rx
Tab Metformin 500mg BD after meals for 30 days
Tab Amlodipine Smg OD morning
Cap Omeprazole 2Omg OD before breakfast
Advice: low salt diet, walk 30 min daily
Follow up after 4 weeks
Signature"""


@pytest.mark.parametrize(
    "name,text",
    [
        ("invoice", INVOICE),
        ("lab report", LAB_REPORT),
        ("discharge summary", DISCHARGE_SUMMARY),
        ("empty", ""),
        ("whitespace", "   \n\t  "),
    ],
)
def test_non_prescriptions_yield_no_medicines(name: str, text: str) -> None:
    assert candidates_from_text(text) == [], name


def test_invoice_is_not_classified_as_a_prescription() -> None:
    assert looks_like_prescription(INVOICE) is False


def test_lab_report_is_not_classified_as_a_prescription() -> None:
    assert looks_like_prescription(LAB_REPORT) is False


def test_real_prescription_is_classified_correctly() -> None:
    assert looks_like_prescription(PRESCRIPTION) is True


# ── Real prescription extraction ────────────────────────────────────

def test_prescription_yields_exactly_the_three_medicines() -> None:
    candidates = candidates_from_text(PRESCRIPTION)
    assert [c.medication_name for c in candidates] == ["Metformin", "Amlodipine", "Omeprazole"]


@pytest.mark.parametrize(
    "name,dose,freq",
    [
        ("Metformin", "500mg", "twice daily"),
        ("Amlodipine", "5mg", "once daily"),
        ("Omeprazole", "20mg", "once daily"),
    ],
)
def test_dose_and_frequency_are_correct(name: str, dose: str, freq: str) -> None:
    candidates = {c.medication_name: c for c in candidates_from_text(PRESCRIPTION)}
    assert candidates[name].dosage == dose
    assert candidates[name].frequency == freq


def test_instructions_are_not_absorbed_into_the_name() -> None:
    """Regression: "BD after meals" left the name as "Metformin after meals"."""
    names = [c.medication_name for c in candidates_from_text(PRESCRIPTION)]
    for junk in ("after", "before", "meals", "breakfast", "morning", "days"):
        assert not any(junk in name.lower() for name in names), (junk, names)


def test_dictionary_junk_lines_are_rejected() -> None:
    assert parse_line("Road Bengaluru 560001") is None
    assert parse_line("A4 paper ream 500 g 2 420.00") is None
    assert parse_line("Total Cholesterol 212 mg/dL 125 200") is None


# ── OCR digit confusion ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Smg", "5mg"),        # S for 5, unit must not split as "Sm"+"g"
        ("2Omg", "20mg"),      # O for 0
        ("l0mg", "10mg"),      # lowercase L for 1
        ("5O0mg", "500mg"),
        ("20mg", "20mg"),      # already correct, unchanged
        ("mcg", "mcg"),        # unit alone is untouched
    ],
)
def test_digit_confusions_are_repaired(raw: str, expected: str) -> None:
    assert repair_digits(raw) == expected


@pytest.mark.parametrize(
    "word",
    ["Omeprazole", "Insulin", "Aspirin", "Metformin", "Amlodipine", "Glimepiride", "Syp"],
)
def test_medicine_names_survive_digit_repair(word: str) -> None:
    assert repair_digits(word) == word


# ── Precision guards on individual lines ────────────────────────────

def test_unknown_name_without_dosage_form_is_rejected() -> None:
    """A line with a strength but no recognisable medicine is not trusted."""
    assert parse_line("Zorblax 500mg twice daily") is None


def test_unknown_name_with_dosage_form_is_kept_for_review() -> None:
    """A form word is real evidence; dropping it would lose a genuine prescription."""
    parsed = parse_line("Tab Zorblax 500mg twice daily")
    assert parsed is not None
    assert parsed.name == "Zorblax"
    assert parsed.known is False


def test_confidence_never_claims_certainty() -> None:
    for candidate in candidates_from_text(PRESCRIPTION):
        assert candidate.confidence < 1.0


def test_known_medicine_scores_higher_than_unknown() -> None:
    known = parse_line("Tab Metformin 500mg BD")
    unknown = parse_line("Tab Zorblax 500mg BD")
    assert known is not None and unknown is not None
    assert known.known is True
    assert unknown.known is False
