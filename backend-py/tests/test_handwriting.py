from app.ocr.handwriting import fallback_candidates_from_text
from app.ocr.lab_parsing import values_from_text
from app.services.document_intake import classify_document


HANDWRITTEN = """KAMAKSHI SKIN CLINIC
Dr. Shobha
Kirtan Age 19
Dx Acne grade II
Rx
Tab Cefixime 200mg OD x 10 days
Cap Doxycycline 100mg BD
Moisturizer apply
"""


def test_handwritten_lines_are_kept_for_review() -> None:
    candidates = fallback_candidates_from_text(HANDWRITTEN)
    names = [candidate.medication_name.lower() for candidate in candidates]
    assert any("cefixime" in name for name in names)
    assert any("doxycycline" in name for name in names)
    assert all(candidate.confidence < 0.75 for candidate in candidates)


def test_invoice_still_yields_nothing() -> None:
    invoice = """GREEN LEAF STATIONERS
12 MG Road Bengaluru 560001
GSTIN 29ABCDE1234F1Z5
Invoice No 4412
A4 paper ream 500 g 2 420.00
Total 570.00"""
    assert fallback_candidates_from_text(invoice) == []


def test_address_and_signature_lines_are_not_candidates() -> None:
    text = """Rx
Tab Metformin 500mg BD
Road Bengaluru 560001
Signature
"""
    candidates = fallback_candidates_from_text(text)
    assert len(candidates) == 1
    assert "metformin" in candidates[0].medication_name.lower()


def test_classifier_separates_lab_and_discharge_documents() -> None:
    lab = """CITY DIAGNOSTICS LABORATORY
HbA1c 8.2 % reference range 4.0 - 5.6
Creatinine 1.1 mg/dL reference range 0.7 - 1.3
"""
    discharge = """CITY HOSPITAL
Discharge Summary
Admission Date: 01/10/2026
Diagnosis: Acute gastroenteritis
Condition at discharge: Stable
Advice: review in OPD
"""
    assert classify_document(lab, 0, 2) == "LAB_REPORT"
    assert classify_document(discharge, 0, 0) == "DISCHARGE_SUMMARY"
    assert classify_document("GSTIN 29ABCDE Invoice total amount 570.00", 0, 0) == "INVOICE"


def test_lab_parser_handles_units_ranges_and_qualitative_values() -> None:
    text = """HbA1c : 8.2 % 4.0 - 5.6
Vitamin D 25-OH 18 ng/mL 30 - 100
HBsAg Negative
TSH 4.2 mIU/mL 0.4 - 4.0
"""
    result = values_from_text(text)
    names = {value.test_name: value for value in result.values}
    assert names["HbA1c"].value == "8.2"
    assert names["HbA1c"].unit == "%"
    assert names["Vitamin D 25-OH"].unit == "ng/mL"
    assert names["HBsAg"].value == "Negative"
    assert names["TSH"].unit == "mIU/mL"
