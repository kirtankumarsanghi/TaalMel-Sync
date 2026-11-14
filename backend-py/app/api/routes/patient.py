"""Patient-facing endpoints: language, voice reports, tapering, photo checks.

These exist so the accessibility and safety features are reachable over HTTP, not just
as services. Every one is consent-gated.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.api.deps import CurrentRoleDep, CurrentUserDep, SessionDep
from app.config import get_settings
from app.consent.service import authorize_patient
from app.db.models import Medication
from app.engines.state import compute_state
from app.engines.triggers import check_expiry
from app.events import store as events
from app.events.types import ReasonCode
from app.services import evidence, i18n, photo_verification, speech, tapering
from app.services.speech import SpeechToTextProvider, StubSpeechToText

router = APIRouter()


def speech_provider_dep() -> SpeechToTextProvider:
    """Pick a real engine only when it can actually run.

    Whisper fails lazily, at transcribe time, not at construction — so availability is
    checked here rather than guessed.
    """
    settings = get_settings()
    if settings.speech_engine == "stub":
        return StubSpeechToText()
    if speech.whisper_available():
        return speech.WhisperSpeechToText(settings.whisper_model)
    if settings.speech_engine == "whisper":
        raise speech.SpeechUnavailable(
            "TAALMEL_SPEECH_ENGINE=whisper but Whisper is not installed. "
            "Install it with `uv add openai-whisper`, or set the engine to 'stub'."
        )
    return StubSpeechToText()


def matcher_dep():
    return photo_verification.get_photo_matcher()


# ── i18n ────────────────────────────────────────────────────────────

class LanguageOut(BaseModel):
    code: str
    name: str
    native: str


class CatalogueOut(BaseModel):
    language: str
    strings: dict[str, str]
    coverage: dict[str, int]


@router.get("/i18n/languages", response_model=list[LanguageOut])
def list_languages() -> list[LanguageOut]:
    return [LanguageOut(**language) for language in i18n.available_languages()]


@router.get("/i18n/{language}", response_model=CatalogueOut)
def get_catalogue(language: str) -> CatalogueOut:
    code = i18n.normalise_language(language)
    return CatalogueOut(
        language=code, strings=i18n.catalogue(code), coverage=i18n.coverage(code)
    )


@router.get("/i18n/{language}/{key}")
def get_string(language: str, key: str) -> dict[str, str]:
    return {"language": i18n.normalise_language(language), "key": key, "value": i18n.translate(key, language)}


# ── Voice self-report ───────────────────────────────────────────────

class VoiceReportOut(BaseModel):
    recorded: bool
    medication_id: str | None = None
    medication_name: str | None = None
    taking: bool | None = None
    transcript: str
    clarification: str | None = None


@router.post("/households/{household_member_id}/voice-report", response_model=VoiceReportOut)
async def voice_report(
    household_member_id: str,
    audio: Annotated[UploadFile | None, File()] = None,
    transcript_text: Annotated[str | None, Form(alias="transcript")] = None,
    language: str | None = Query(default=None),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
    provider: SpeechToTextProvider = Depends(speech_provider_dep),
) -> VoiceReportOut:
    """Transcribe a spoken report and record it only if it is unambiguous.

    A browser that can transcribe locally may send `transcript` directly; otherwise the
    audio is sent to the configured speech provider. Nothing is recorded when the
    transcript is unclear, because a wrong entry is worse than a missing one.
    """
    if transcript_text and transcript_text.strip():
        transcript = speech.Transcript(text=transcript_text.strip(), language=language, confidence=1.0)
    else:
        if audio is None:
            return VoiceReportOut(
                recorded=False,
                transcript="",
                clarification="No audio or transcript was received. Please record again.",
            )
        data = await audio.read()
        try:
            transcript = provider.transcribe(data, audio.content_type or "audio/wav", language)
        except speech.SpeechInputError as exc:
            return VoiceReportOut(
                recorded=False, transcript="", clarification=f"{exc}. Please record again."
            )

    medicines = evidence.medicines_for_member(
        session, user_id=user_id, household_member_id=household_member_id
    )
    pairs = [(m.id, (m.name_generic or m.name_raw)) for m in medicines]

    intent = speech.detect_intent(transcript.text)
    match = speech.match_medicine(transcript.text, pairs)

    if match.ambiguous:
        return VoiceReportOut(
            recorded=False,
            transcript=transcript.text,
            clarification=(
                "I heard more than one medicine: " + ", ".join(match.candidates)
                + ". Please say just one."
            ),
        )
    if intent.taking is None:
        return VoiceReportOut(
            recorded=False,
            transcript=transcript.text,
            clarification=(
                "I could not tell whether you took it. Please say 'I took it' or "
                "'I did not take it'."
            ),
        )
    if match.medication_id is None:
        return VoiceReportOut(
            recorded=False,
            transcript=transcript.text,
            clarification="I could not tell which medicine. Please say the medicine name.",
        )

    evidence.report_taking(
        session,
        user_id=user_id,
        role="patient",
        medication_id=match.medication_id,
        taking=intent.taking,
        note=f"voice report: {transcript.text}",
        voice=True,
    )
    return VoiceReportOut(
        recorded=True,
        medication_id=match.medication_id,
        medication_name=match.name,
        taking=intent.taking,
        transcript=transcript.text,
    )


# ── Tapering ────────────────────────────────────────────────────────

class TaperStepOut(BaseModel):
    step: int
    dose: str
    duration_days: int


class TaperOut(BaseModel):
    medication_id: str
    medicine: str
    schedule: list[TaperStepOut]
    current_step: int | None
    expected_dose: str | None
    reported_dose: str | None
    finding: str
    detail: str


class TaperScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule_text: str = Field(min_length=1, max_length=300)
    prescribed_by: str | None = Field(default=None, max_length=120)


@router.get("/medications/{medication_id}/taper", response_model=TaperOut)
def get_taper(
    medication_id: str,
    day: int | None = Query(default=None, ge=0, le=3650),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> TaperOut:
    status = tapering.check(session, user_id=user_id, medication_id=medication_id, today_day=day)
    return TaperOut(
        medication_id=status.medication_id,
        medicine=status.medicine,
        schedule=[TaperStepOut(**vars(step)) for step in status.schedule],
        current_step=status.current_step,
        expected_dose=status.expected_dose,
        reported_dose=status.reported_dose,
        finding=status.finding,
        detail=status.detail,
    )


@router.post("/medications/{medication_id}/taper", response_model=TaperOut)
def set_taper(
    medication_id: str,
    body: TaperScheduleIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> TaperOut:
    tapering.set_schedule(
        session,
        user_id=user_id,
        medication_id=medication_id,
        schedule_text=body.schedule_text,
        prescribed_by=body.prescribed_by,
    )
    status = tapering.check(session, user_id=user_id, medication_id=medication_id)
    return TaperOut(
        medication_id=status.medication_id,
        medicine=status.medicine,
        schedule=[TaperStepOut(**vars(step)) for step in status.schedule],
        current_step=status.current_step,
        expected_dose=status.expected_dose,
        reported_dose=status.reported_dose,
        finding=status.finding,
        detail=status.detail,
    )


# ── Photo verification ─────────────────────────────────────────────

class PhotoVerificationOut(BaseModel):
    id: str
    medication_id: str
    outcome: str
    detail: str | None
    confidence: float | None
    created_at: str


@router.post("/medicines/{medication_id}/photo-verify", response_model=PhotoVerificationOut)
@router.post("/medications/{medication_id}/photo-verify", response_model=PhotoVerificationOut)
async def photo_verify(
    medication_id: str,
    photo: Annotated[UploadFile, File(...)],
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
    matcher=Depends(matcher_dep),
) -> PhotoVerificationOut:
    from app.services.storage import get_storage

    data = await photo.read()
    row = photo_verification.verify_photo(
        session,
        storage=get_storage(),
        matcher=matcher,
        user_id=user_id,
        medication_id=medication_id,
        photo=data,
        mime_type=photo.content_type or "image/png",
    )
    return PhotoVerificationOut(
        id=row.id,
        medication_id=row.medication_id,
        outcome=row.outcome,
        detail=row.detail,
        confidence=row.confidence,
        created_at=row.created_at.isoformat(),
    )


@router.get("/medications/{medication_id}/photo-verify", response_model=list[PhotoVerificationOut])
def photo_history(
    medication_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[PhotoVerificationOut]:
    return [
        PhotoVerificationOut(
            id=row.id,
            medication_id=row.medication_id,
            outcome=row.outcome,
            detail=row.detail,
            confidence=row.confidence,
            created_at=row.created_at.isoformat(),
        )
        for row in photo_verification.history(
            session, user_id=user_id, medication_id=medication_id
        )
    ]


class ExpiryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expiry_date: datetime
    present: bool = True


@router.post("/medicines/{medication_id}/expiry", response_model=dict)
@router.post("/medications/{medication_id}/expiry", response_model=dict)
def record_expiry(
    medication_id: str,
    body: ExpiryIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> dict:
    """Record the expiry printed on the strip and immediately reconcile it."""
    event = evidence.record_availability(
        session,
        user_id=user_id,
        medication_id=medication_id,
        present=body.present,
        expiry_date=body.expiry_date,
    )
    from app.services.reconciliation import detect_and_open_cases

    opened = detect_and_open_cases(session, user_id=user_id, medication_id=medication_id)
    return {"event_id": event.id, "opened_cases": [case.id for case in opened]}
