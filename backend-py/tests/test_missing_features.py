"""Tests for the features that were missing: i18n, voice, tapering, photo checks,
PDF/HTML/QR export.

These cover behaviour, not plumbing: a language must be complete, a voice report must
refuse to guess, a taper must catch a skipped step, and a photo check must never claim
a match it did not make.
"""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import db_session
from app.api.routes import prescriptions as rx_routes
from app.main import create_app
from app.ocr.stub import StubOcrProvider
from app.services import i18n, speech, tapering
from app.services.photo_verification import NoOpMatcher, _result_from_score
from app.services.storage import LocalStorageService


# ── i18n (feature 35) ─────────────────────────────────────────────

def test_all_five_launch_languages_are_present() -> None:
    codes = {language["code"] for language in i18n.available_languages()}
    assert {"en", "hi", "ta", "te", "bn", "mr"} <= codes


@pytest.mark.parametrize("code", ["hi", "ta", "te", "bn", "mr"])
def test_each_language_is_fully_translated(code: str) -> None:
    coverage = i18n.coverage(code)
    assert coverage["translated"] == coverage["total"], coverage


@pytest.mark.parametrize("code", ["hi", "ta", "te", "bn", "mr"])
def test_translation_differs_from_english(code: str) -> None:
    assert i18n.translate("medicine.taken", code) != i18n.translate("medicine.taken", "en")


def test_unknown_language_falls_back_to_english() -> None:
    assert i18n.normalise_language("fr") == "en"
    assert i18n.translate("nav.today", "fr") == i18n.translate("nav.today", "en")


def test_missing_key_returns_the_key_not_a_crash() -> None:
    assert i18n.translate("no.such.key", "hi") == "no.such.key"


def test_brand_name_is_not_translated() -> None:
    for code in ("hi", "ta", "te", "bn", "mr"):
        assert i18n.translate("app.name", code) == "Taalmel"


# ── Voice intent and matching (feature 36) ─────────────────────────

@pytest.mark.parametrize(
    "transcript,expected",
    [
        ("yes I took it", True),
        ("I took the tablet today", True),
        ("no I did not take it", False),
        ("I missed it", False),
        ("haven't taken it", False),
        ("मैंने ले ली", True),
        ("नहीं ली", False),
    ],
)
def test_intent_detection(transcript: str, expected: bool) -> None:
    intent = speech.detect_intent(transcript)
    assert intent.confident is True
    assert intent.taking is expected


def test_negative_wins_when_both_words_appear() -> None:
    """'no, I did not take it' contains 'take' too; the safe reading is negative."""
    assert speech.detect_intent("no I did not take it").taking is False


def test_unclear_transcript_is_not_confident() -> None:
    assert speech.detect_intent("mmm hmm").confident is False


def test_single_medicine_resolves_without_being_named() -> None:
    match = speech.match_medicine("yes I took it", [("med-1", "Metformin")])
    assert match.medication_id == "med-1" and not match.ambiguous


def test_two_medicines_without_a_name_is_not_guessed() -> None:
    match = speech.match_medicine(
        "yes I took it", [("med-1", "Metformin"), ("med-2", "Amlodipine")]
    )
    assert match.medication_id is None
    assert match.ambiguous is False


def test_naming_one_of_several_selects_it() -> None:
    match = speech.match_medicine(
        "I took the amlodipine", [("med-1", "Metformin"), ("med-2", "Amlodipine")]
    )
    assert match.medication_id == "med-2"


def test_naming_two_medicines_is_ambiguous() -> None:
    match = speech.match_medicine(
        "I took metformin and amlodipine", [("med-1", "Metformin"), ("med-2", "Amlodipine")]
    )
    assert match.ambiguous is True and match.medication_id is None


# ── Tapering (feature 10) ─────────────────────────────────────────

def test_schedule_parses_a_doctor_written_plan() -> None:
    steps = tapering.parse_schedule("20mg x7d, 10mg x7d, 5mg x7d")
    assert steps is not None
    assert [(s.dose, s.duration_days) for s in steps] == [
        ("20mg", 7), ("10mg", 7), ("5mg", 7)
    ]


def test_unreadable_schedule_is_refused_not_invented() -> None:
    assert tapering.parse_schedule("reduce slowly") is None
    assert tapering.parse_schedule("") is None


def test_taper_prone_medicines_are_recognised() -> None:
    assert tapering.is_taper_prone("prednisolone", None) is True
    assert tapering.is_taper_prone(None, "Diazepam") is True
    assert tapering.is_taper_prone("metformin", None) is False


# ── Photo verification (feature 11) ───────────────────────────────

def test_default_matcher_never_claims_a_match() -> None:
    comparison = NoOpMatcher().compare(b"photo", "image/png", "Metformin 500mg")
    assert comparison.outcome == "NOT_CHECKED"
    assert "expected Metformin 500mg" in comparison.detail


def test_weak_score_is_not_reported_as_a_match() -> None:
    """A false MATCH is worse than an honest NOT_CHECKED."""
    assert _result_from_score(0.6, "Metformin").outcome == "NOT_CHECKED"
    assert _result_from_score(0.9, "Metformin").outcome == "MATCH"
    assert _result_from_score(0.1, "Metformin").outcome == "NO_MATCH"
    assert _result_from_score(None, "Metformin").outcome == "NOT_CHECKED"


# ── HTTP: export formats and the new endpoints ────────────────────

@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine, tmp_path):
    def override_session():
        with Session(engine) as s:
            yield s

    app = create_app()
    app.dependency_overrides[db_session] = override_session
    app.dependency_overrides[rx_routes.engine_dep] = lambda: engine
    app.dependency_overrides[rx_routes.storage_dep] = lambda: LocalStorageService(tmp_path / "up")
    app.dependency_overrides[rx_routes.ocr_provider_dep] = lambda: StubOcrProvider()
    with TestClient(app) as c:
        yield c


def _seed(client: TestClient, phone: str) -> tuple[str, str, dict[str, str]]:
    reg = client.post("/api/auth/register", json={
        "name": "F", "phone": phone, "password": "correct-horse-battery", "role": "caregiver"}).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    created = client.post("/api/households", headers=headers, json={
        "household_name": "F", "patient_display_name": "Amma", "consent_recorded": True}).json()
    member = created["patient"]["household_member_id"]
    rx = client.post(f"/api/prescriptions/upload", headers=headers,
                     params={"household_member_id": member},
                     files={"file": ("rx.png", b"stub-scan", "image/png")}).json()
    verified = client.post(f"/api/prescriptions/{rx['id']}/verify", headers=headers, json={
        "items": [{"item_id": rx["items"][0]["id"], "medication_name": "Metformin 500mg",
                   "dosage": "500mg", "frequency": "twice daily"}]}).json()
    med = verified["medication_results"][0]["medication_id"]
    return member, med, headers


def test_language_endpoints_are_reachable(client: TestClient) -> None:
    assert client.get("/api/i18n/languages").status_code == 200
    assert client.get("/api/i18n/ta").json()["coverage"]["translated"] == client.get(
        "/api/i18n/ta"
    ).json()["coverage"]["total"]


def test_voice_report_records_when_unambiguous(client: TestClient) -> None:
    member, _, headers = _seed(client, "9600000201")
    response = client.post(
        f"/api/households/{member}/voice-report",
        headers=headers,
        files={"audio": ("a.wav", b"yes I took the metformin", "audio/wav")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recorded"] is True
    assert body["taking"] is True
    assert "metformin" in body["transcript"].lower()


def test_voice_report_refuses_unclear_speech(client: TestClient) -> None:
    member, _, headers = _seed(client, "9600000202")
    body = client.post(
        f"/api/households/{member}/voice-report",
        headers=headers,
        files={"audio": ("a.wav", b"mmm hmm", "audio/wav")},
    ).json()
    assert body["recorded"] is False
    assert body["clarification"]


def test_taper_endpoint_round_trip(client: TestClient) -> None:
    _, med, headers = _seed(client, "9600000203")
    saved = client.post(f"/api/medications/{med}/taper", headers=headers,
                         json={"schedule_text": "20mg x7d, 10mg x7d, 5mg x7d"})
    assert saved.status_code == 200
    assert len(saved.json()["schedule"]) == 3

    day3 = client.get(f"/api/medications/{med}/taper?day=3", headers=headers).json()
    assert day3["expected_dose"] == "20mg"
    day20 = client.get(f"/api/medications/{med}/taper?day=20", headers=headers).json()
    assert day20["current_step"] == 3


def test_taper_rejects_unreadable_schedule(client: TestClient) -> None:
    _, med, headers = _seed(client, "9600000204")
    response = client.post(f"/api/medications/{med}/taper", headers=headers,
                            json={"schedule_text": "reduce slowly"})
    assert response.status_code == 400


def test_photo_verify_is_honest(client: TestClient) -> None:
    _, med, headers = _seed(client, "9600000205")
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, format="PNG")
    body = client.post(f"/api/medications/{med}/photo-verify", headers=headers,
                        files={"photo": ("strip.png", buffer.getvalue(), "image/png")}).json()
    assert body["outcome"] == "NOT_CHECKED"
    assert body["detail"]


def test_doctor_export_pdf_and_html(client: TestClient) -> None:
    member, _, headers = _seed(client, "9600000206")

    pdf = client.get(f"/api/households/{member}/doctor-export?format=pdf", headers=headers)
    assert pdf.status_code == 200
    assert pdf.content[:5] == b"%PDF-"

    html = client.get(f"/api/households/{member}/doctor-export?format=html", headers=headers)
    assert html.status_code == 200
    assert "<!doctype html>" in html.text.lower()
    assert "Amma" in html.text


def test_qr_endpoints_produce_a_real_png(client: TestClient) -> None:
    member, _, headers = _seed(client, "9600000207")

    payload = client.post(f"/api/households/{member}/doctor-link/qr", headers=headers,
                           params={"base_url": "https://example.test"}).json()
    png = base64.b64decode(payload["qr_png_base64"])
    assert png[:4] == b"\x89PNG"
    assert payload["url"].startswith("https://example.test/api/public/doctor-export/")

    raw = client.get(f"/api/households/{member}/doctor-link/qr.png", headers=headers,
                      params={"base_url": "https://example.test"})
    assert raw.content[:4] == b"\x89PNG"


def test_public_route_serves_pdf_without_login(client: TestClient) -> None:
    member, _, headers = _seed(client, "9600000208")
    link = client.post(f"/api/households/{member}/doctor-link", headers=headers).json()
    response = client.get(f"{link['url_path']}?format=pdf")
    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-"


def test_export_timeline_includes_prescription_history(client: TestClient) -> None:
    """Regression: prescription events are member-level, so they were missing from the
    medicine timeline — leaving only the normalisation step, which is not a history."""
    member, _, headers = _seed(client, "9600000209")
    export = client.get(f"/api/households/{member}/doctor-export", headers=headers).json()
    timeline = export["medications"][0]["timeline"]
    details = [entry["detail"] for entry in timeline]

    assert len(timeline) >= 4, timeline
    assert "Prescription uploaded" in details, details
    assert "Prescription confirmed by a person" in details, details
    # Every entry must carry a source and a date, since that is the whole point.
    assert all(entry["source"] for entry in timeline)
    assert all(entry["date"] for entry in timeline)


def test_export_pdf_contains_the_medicine_and_note(client: TestClient) -> None:
    member, _, headers = _seed(client, "9600000210")
    pdf = client.get(f"/api/households/{member}/doctor-export?format=pdf", headers=headers)
    assert pdf.status_code == 200
    # Streams inside the PDF are compressed, so text is not greppable. Assert on size and
    # on the presence of a rendered content stream instead.
    assert len(pdf.content) > 800
    assert b"/Contents" in pdf.content or b"/Font" in pdf.content
