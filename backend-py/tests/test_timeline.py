from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import Session, select

from app.db import models
from app.ocr.diagnoses import diagnoses_from_text
from app.services import conditions as conditions_service
from app.services import timeline as timeline_service


# ── Diagnosis extraction ────────────────────────────────────────────

def test_labelled_diagnosis_is_split_into_named_conditions() -> None:
    text = "KAMAKSHI SKIN CLINIC\nDx Acne grade III & Nodules.\nRx\nTab Sotret NF 16mg OD\n"
    assert diagnoses_from_text(text) == ["Acne grade III", "Nodules"]


def test_diagnosis_prefix_variants_are_recognised() -> None:
    assert diagnoses_from_text("Diagnosis: Acute gastroenteritis") == ["Acute gastroenteritis"]
    assert diagnoses_from_text("D/X: Type 2 diabetes; Hypertension") == [
        "Type 2 diabetes",
        "Hypertension",
    ]


def test_advice_and_unlabelled_lines_are_not_diagnoses() -> None:
    text = "Adv LFT\nFasting lipid profile\nAcne grade III\nReview in 2 weeks\n"
    assert diagnoses_from_text(text) == []


def test_empty_text_yields_no_conditions() -> None:
    assert diagnoses_from_text("") == []


# ── Timeline ────────────────────────────────────────────────────────

def _seed(session: Session) -> tuple[models.User, models.Patient]:
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


def _prescription(
    session: Session,
    member_id: str,
    *,
    date: datetime | None,
    prescriber: str,
    items: list[tuple[str, str | None, bool]],
) -> models.Prescription:
    prescription = models.Prescription(
        household_member_id=member_id,
        prescribed_by=prescriber,
        prescribed_on=date,
        file_storage_key=f"k/{uuid4()}",
        original_filename=f"{prescriber}.png",
        mime_type="image/png",
        file_size_bytes=1,
        file_hash=str(uuid4()),
        uploaded_by_user_id="u",
        verified=True,
    )
    session.add(prescription)
    session.flush()
    for name, dose, verified in items:
        session.add(
            models.PrescriptionItem(
                prescription_id=prescription.id,
                medication_name=name,
                dosage=dose,
                frequency="once daily",
                verified=verified,
            )
        )
    session.commit()
    return prescription


def test_timeline_groups_by_drug_and_tracks_dose_changes(session: Session) -> None:
    user, patient = _seed(session)
    member_id = patient.household_member_id

    _prescription(
        session, member_id,
        date=datetime(2023, 3, 1, tzinfo=UTC), prescriber="Dr A",
        items=[("Sotret NF", "10mg", True), ("Metformin", "500mg", True),
               ("Amoxicillin", "500mg", False)],
    )
    _prescription(
        session, member_id,
        date=datetime(2025, 6, 1, tzinfo=UTC), prescriber="Dr B",
        items=[("Sotret NF", "16mg", True)],
    )

    result = timeline_service.medication_timeline(
        session, user_id=user.id, patient_id=patient.id
    )

    by_name = {med["generic"].lower(): med for med in result["medications"]}
    sotret = next(
        med for med in result["medications"] if "Sotret NF" in med["written_names"]
    )
    assert len(sotret["episodes"]) == 2
    assert sotret["episodes"][0]["dose"] == "10mg"
    assert sotret["episodes"][0]["start"] == "2023-03-01"
    assert sotret["episodes"][1]["dose"] == "16mg"
    assert sotret["episodes"][1]["previous_dose"] == "10mg"
    assert sotret["episodes"][1]["dose_changed"] is True
    assert "metformin" in by_name

    written = {name.lower() for med in result["medications"] for name in med["written_names"]}
    assert "amoxicillin" not in written, "unverified items must not enter the history"
    assert {year["year"] for year in result["years"]} == {"2023", "2025"}


def test_timeline_keeps_undated_items_separate(session: Session) -> None:
    user, patient = _seed(session)
    member_id = patient.household_member_id
    _prescription(
        session, member_id, date=datetime(2024, 1, 5, tzinfo=UTC),
        prescriber="Dr A", items=[("Desowen Gel", None, True)],
    )
    _prescription(
        session, member_id, date=None,
        prescriber="Dr Old", items=[("Desowen Gel", None, True)],
    )

    result = timeline_service.medication_timeline(
        session, user_id=user.id, patient_id=patient.id
    )
    labels = [year["year"] for year in result["years"]]
    assert labels == ["2024", "date not recorded"]

    filtered = timeline_service.medication_timeline(
        session, user_id=user.id, patient_id=patient.id, year=2024
    )
    assert [year["year"] for year in filtered["years"]] == ["2024"]


def test_year_filter_narrows_the_medicine_list(session: Session) -> None:
    user, patient = _seed(session)
    member_id = patient.household_member_id
    _prescription(
        session, member_id, date=datetime(2022, 2, 2, tzinfo=UTC),
        prescriber="Dr A", items=[("Metformin", "500mg", True)],
    )
    _prescription(
        session, member_id, date=datetime(2024, 4, 4, tzinfo=UTC),
        prescriber="Dr B", items=[("Amlodipine", "5mg", True)],
    )

    result = timeline_service.medication_timeline(
        session, user_id=user.id, patient_id=patient.id, year=2022
    )
    written = {name.lower() for med in result["medications"] for name in med["written_names"]}
    assert written == {"metformin"}


def test_conditions_are_unconfirmed_until_verified(session: Session) -> None:
    user, patient = _seed(session)
    member_id = patient.household_member_id

    created = conditions_service.sync_conditions_from_text(
        session,
        household_member_id=member_id,
        raw_text="Dx Acne grade III & Nodules",
    )
    assert len(created) == 2
    assert all(condition.confirmed is False for condition in created)

    verified = conditions_service.verify_condition(
        session, user_id=user.id, condition_id=created[0].id, name="Acne vulgaris grade III"
    )
    assert verified.confirmed is True
    assert verified.name == "Acne vulgaris grade III"
    assert verified.name_raw == "Acne grade III", "the page wording is preserved"


def test_confirmed_condition_links_to_its_visit_medicines(session: Session) -> None:
    user, patient = _seed(session)
    member_id = patient.household_member_id
    prescription = _prescription(
        session, member_id,
        date=datetime(2023, 5, 10, tzinfo=UTC), prescriber="Dr Shobha",
        items=[("Sotret NF", "10mg", True), ("Desowen Gel", None, True)],
    )
    confirmed = models.Condition(
        household_member_id=member_id,
        name="Acne grade III",
        source_prescription_id=prescription.id,
        confirmed=True,
    )
    unconfirmed = models.Condition(
        household_member_id=member_id,
        name="Nodules",
        source_prescription_id=prescription.id,
        confirmed=False,
    )
    session.add(confirmed)
    session.add(unconfirmed)
    session.commit()

    result = timeline_service.medication_timeline(
        session, user_id=user.id, patient_id=patient.id
    )

    assert len(result["condition_links"]) == 1
    link = result["condition_links"][0]
    assert link["condition"]["name"] == "Acne grade III"
    assert link["date"] == "2023-05-10"
    names = {medicine["written_name"] for medicine in link["medicines"]}
    assert names == {"Sotret NF", "Desowen Gel"}
    assert "does not assert" in link["basis"]
    assert result["unconfirmed_conditions"] == 1


def test_repeated_sync_does_not_duplicate_the_same_source(session: Session) -> None:
    user, patient = _seed(session)
    member_id = patient.household_member_id
    _prescription(
        session, member_id, date=datetime(2023, 1, 1, tzinfo=UTC),
        prescriber="Dr A", items=[("Sotret NF", "10mg", True)],
    )
    prescription_id = session.exec(select(models.Prescription)).first().id

    first = conditions_service.sync_conditions_from_text(
        session, household_member_id=member_id, raw_text="Dx Acne grade III",
        prescription_id=prescription_id,
    )
    second = conditions_service.sync_conditions_from_text(
        session, household_member_id=member_id, raw_text="Dx Acne grade III",
        prescription_id=prescription_id,
    )
    assert len(first) == 1
    assert second == []
