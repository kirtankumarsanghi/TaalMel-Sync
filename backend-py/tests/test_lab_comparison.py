from datetime import UTC, datetime

from sqlmodel import Session

from app.db import models
from app.services.lab_comparison import (
    canonical_test_name,
    compare_to_range,
    lab_comparison,
    parse_numeric,
    parse_reference_range,
)


# ── Parsing ─────────────────────────────────────────────────────────

def test_canonical_names_group_qualifiers_and_punctuation() -> None:
    assert canonical_test_name("HbA1c") == canonical_test_name(" HBA1C ")
    assert canonical_test_name("Vitamin D 25-OH") == canonical_test_name("Vitamin D 25 OH")
    assert canonical_test_name("Cholesterol (Total)") == "cholesterol"


def test_numeric_values_parse_and_qualitative_do_not() -> None:
    assert parse_numeric("8.2") == 8.2
    assert parse_numeric("<0.5") == 0.5
    assert parse_numeric("1,20,000") == 120000.0
    assert parse_numeric("Negative") is None
    assert parse_numeric("Trace") is None


def test_reference_ranges_parse_in_every_printed_form() -> None:
    assert parse_reference_range("4.0 - 5.6") == (4.0, 5.6)
    assert parse_reference_range("0.7–1.3") == (0.7, 1.3)
    assert parse_reference_range("< 5") == (None, 5.0)
    assert parse_reference_range("> 30") == (30.0, None)
    assert parse_reference_range("") == (None, None)


def test_status_is_position_against_printed_range_only() -> None:
    assert compare_to_range(8.2, 4.0, 5.6) == "ABOVE"
    assert compare_to_range(4.5, 4.0, 5.6) == "WITHIN"
    assert compare_to_range(1.1, 2.0, 4.0) == "BELOW"
    assert compare_to_range(8.2, None, None) == "NOT_COMPARABLE"
    assert compare_to_range(None, 4.0, 5.6) == "NOT_COMPARABLE"


# ── Service ─────────────────────────────────────────────────────────

def _patient(session: Session) -> tuple[models.User, models.Patient]:
    user = models.User(role="caregiver", name="Asha", password_hash="x")
    session.add(user)
    session.flush()
    household = models.Household(name="Family", created_by=user.id)
    session.add(household)
    session.flush()
    member = models.HouseholdMember(
        household_id=household.id, display_name="Amma", user_id=user.id
    )
    session.add(member)
    session.flush()
    patient = models.Patient(household_member_id=member.id)
    session.add(patient)
    session.commit()
    return user, patient


def _report(
    session: Session,
    member_id: str,
    captured_on: str,
    values: list[tuple[str, str, str | None, str | None]],
) -> None:
    report = models.LabReport(
        household_member_id=member_id,
        file_storage_key="k",
        original_filename="lab.pdf",
        mime_type="application/pdf",
        file_size_bytes=1,
        file_hash=captured_on,
        uploaded_by_user_id="u",
        ocr_status="COMPLETED",
        captured_on=captured_on,
    )
    session.add(report)
    session.flush()
    for name, value, unit, ref in values:
        session.add(
            models.LabValue(
                lab_report_id=report.id,
                test_name=name,
                value=value,
                unit=unit,
                reference_range_raw=ref,
            )
        )
    session.commit()


def test_comparison_tracks_a_test_across_reports(session: Session) -> None:
    user, patient = _patient(session)
    member_id = patient.household_member_id
    _report(session, member_id, "2023-03-01", [("HbA1c", "7.1", "%", "4.0 - 5.6")])
    _report(session, member_id, "2025-06-01", [("HbA1c", "8.2", "%", "4.0 - 5.6")])

    result = lab_comparison(session, user_id=user.id, patient_id=patient.id)
    test = next(item for item in result["tests"] if item["test_name"] == "HbA1c")

    assert len(test["points"]) == 2
    assert test["latest_value"] == "8.2"
    assert test["latest_status"] == "ABOVE"
    assert test["trend"] == "UP"
    assert test["change"] == 1.1
    assert result["summary"]["above"] == 1


def test_different_units_are_not_compared(session: Session) -> None:
    user, patient = _patient(session)
    member_id = patient.household_member_id
    _report(session, member_id, "2024-01-01", [("Creatinine", "1.1", "mg/dL", "0.7 - 1.3")])
    _report(session, member_id, "2024-06-01", [("Creatinine", "97", "umol/L", "62 - 106")])

    result = lab_comparison(session, user_id=user.id, patient_id=patient.id)
    creatinine = [item for item in result["tests"] if item["test_name"] == "Creatinine"]
    assert len(creatinine) == 2, "each unit must be its own series"
    for series in creatinine:
        assert len(series["points"]) == 1
        assert series["trend"] is None


def test_qualitative_results_are_not_compared(session: Session) -> None:
    user, patient = _patient(session)
    _report(
        session,
        patient.household_member_id,
        "2024-02-02",
        [("HBsAg", "Negative", None, None)],
    )
    result = lab_comparison(session, user_id=user.id, patient_id=patient.id)
    test = next(item for item in result["tests"] if item["test_name"] == "HBsAg")
    assert test["latest_status"] == "NOT_COMPARABLE"
    assert test["trend"] is None
    assert "not a diagnosis" in result["note"]
