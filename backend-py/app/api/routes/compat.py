"""Compatibility and product-level routes.

These paths are the ones named in the product specification. Several of them are
aliases over the same services as the canonical routes; keeping them here makes the
documented API true without duplicating logic.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.api.deps import CurrentRoleDep, CurrentUserDep, SessionDep
from app.config import get_settings
from app.consent.service import AccessDenied, authorize_member, authorize_patient
from app.db.models import (
    DoctorGrant,
    HouseholdMember,
    LabReport,
    LabValue,
    Medication,
    RefillOrder,
    SymptomReport,
)
from app.events import store as events
from app.events.types import ReasonCode
from app.services import (
    companion,
    doctor_export,
    evidence,
    lab_reports,
    pharmacy,
    wellness,
)
from app.services.storage import get_storage

router = APIRouter()


def _member(session: Session, user_id: str, patient_id: str) -> str:
    return authorize_patient(session, user_id, patient_id).household_member_id


# ── Self-reports ─────────────────────────────────────────────────────

class SelfReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    medication_id: str
    taking: bool
    reason: ReasonCode | None = None
    note: str | None = Field(default=None, max_length=500)


class SelfReportOut(BaseModel):
    id: str
    medication_id: str | None
    taking: bool
    reason: str | None
    note: str | None
    source: str
    occurred_at: datetime


@router.post("/patients/{patient_id}/self-report", response_model=SelfReportOut, status_code=201)
def self_report(
    patient_id: str,
    body: SelfReportIn,
    user_id: str = CurrentUserDep,
    role: str = CurrentRoleDep,
    session: Session = SessionDep,
) -> SelfReportOut:
    member_id = _member(session, user_id, patient_id)
    med = session.get(Medication, body.medication_id)
    if med is None or med.household_member_id != member_id:
        raise AccessDenied("Medication not found for this patient", status_code=404)
    event = evidence.report_taking(
        session,
        user_id=user_id,
        role=role or "patient",
        medication_id=body.medication_id,
        taking=body.taking,
        reason=body.reason,
        note=body.note,
    )
    payload = events.decode_payload(event)
    return SelfReportOut(
        id=event.id,
        medication_id=event.medication_id,
        taking=bool(payload.get("taking")),
        reason=payload.get("reason"),
        note=payload.get("note"),
        source=event.source,
        occurred_at=event.occurred_at,
    )


@router.get("/patients/{patient_id}/self-reports", response_model=list[SelfReportOut])
def self_reports(
    patient_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[SelfReportOut]:
    member_id = _member(session, user_id, patient_id)
    rows: list[SelfReportOut] = []
    for event in events.events_for_member(session, member_id):
        if event.event_type != "MedicationReported":
            continue
        payload = events.decode_payload(event)
        rows.append(
            SelfReportOut(
                id=event.id,
                medication_id=event.medication_id,
                taking=bool(payload.get("taking")),
                reason=payload.get("reason"),
                note=payload.get("note"),
                source=event.source,
                occurred_at=event.occurred_at,
            )
        )
    return sorted(rows, key=lambda row: row.occurred_at, reverse=True)


# ── Lab reports ──────────────────────────────────────────────────────

class LabValueOut(BaseModel):
    test_name: str
    value: str
    unit: str | None
    reference_range_raw: str | None


class LabReportOut(BaseModel):
    id: str
    original_filename: str
    ocr_status: str
    ocr_error: str | None
    captured_on: str | None
    lab_name: str | None
    created_at: datetime
    values: list[LabValueOut]


def _lab_out(session: Session, report: LabReport) -> LabReportOut:
    values = session.exec(select(LabValue).where(LabValue.lab_report_id == report.id)).all()
    return LabReportOut(
        id=report.id,
        original_filename=report.original_filename,
        ocr_status=report.ocr_status,
        ocr_error=report.ocr_error,
        captured_on=report.captured_on,
        lab_name=report.lab_name,
        created_at=report.created_at,
        values=[
            LabValueOut(
                test_name=v.test_name,
                value=v.value,
                unit=v.unit,
                reference_range_raw=v.reference_range_raw,
            )
            for v in values
        ],
    )


@router.post("/patients/{patient_id}/lab-reports/upload", response_model=LabReportOut, status_code=201)
async def upload_lab_report(
    patient_id: str,
    file: UploadFile = File(...),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> LabReportOut:
    member_id = _member(session, user_id, patient_id)
    data = await file.read(lab_reports.MAX_UPLOAD_BYTES + 1)
    report = lab_reports.upload_lab_report(
        session,
        storage=get_storage(),
        user_id=user_id,
        household_member_id=member_id,
        data=data,
        mime_type=file.content_type or "",
        filename=file.filename or "",
    )
    from app.ocr.provider import get_lab_ocr_provider

    report = lab_reports.process_lab_report(
        session, storage=get_storage(), provider=get_lab_ocr_provider(), lab_report_id=report.id
    )
    return _lab_out(session, report)


@router.get("/patients/{patient_id}/lab-reports", response_model=list[LabReportOut])
def list_lab_reports(
    patient_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[LabReportOut]:
    member_id = _member(session, user_id, patient_id)
    reports = session.exec(
        select(LabReport)
        .where(LabReport.household_member_id == member_id)
        .order_by(LabReport.created_at.desc())  # type: ignore[union-attr]
    ).all()
    return [_lab_out(session, report) for report in reports]


@router.get("/patients/{patient_id}/lab-adherence-timeline")
def lab_adherence_timeline(
    patient_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[dict]:
    member_id = _member(session, user_id, patient_id)
    return [asdict(finding) for finding in lab_reports.assemble_findings(session, member_id)]


# ── Doctor export aliases + optional doctor dashboard ────────────────

def _serialize_export(export: doctor_export.DoctorExport) -> dict:
    from app.api.routes.exports import _serialize

    return _serialize(export)


@router.get("/doctors/export/{patient_id}")
def doctor_export_alias(
    patient_id: str,
    format: str = Query(default="json", pattern="^(json)$"),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> dict:
    patient = authorize_patient(session, user_id, patient_id)
    export = doctor_export.build_export(
        session, user_id=user_id, household_member_id=patient.household_member_id
    )
    return _serialize_export(export)


@router.get("/doctors/export/{patient_id}/qr")
def doctor_export_qr(
    patient_id: str,
    base_url: str = Query(default=""),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> dict:
    from app.auth import doctor_link
    from app.services import qr as qr_service

    patient = authorize_patient(session, user_id, patient_id)
    # Ensure the caller can read the export before issuing a link.
    doctor_export.build_export(
        session, user_id=user_id, household_member_id=patient.household_member_id
    )
    link = doctor_link.issue_token(
        patient.household_member_id, lifetime_minutes=get_settings().doctor_link_minutes
    )
    origin = (base_url or get_settings().public_base_url).rstrip("/")
    url = f"{origin}{link.url_path}" if origin else link.url_path
    png = qr_service.render_qr_png(url)
    return {
        "url": url,
        "token": link.token,
        "expires_at": link.expires_at.isoformat(),
        "qr_png_base64": base64.b64encode(png).decode("ascii"),
    }


class DoctorRedeemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str


class DoctorPatientOut(BaseModel):
    household_member_id: str
    name: str
    granted_at: datetime
    expires_at: datetime | None


@router.post("/doctor/redeem", response_model=DoctorPatientOut, status_code=201)
def doctor_redeem(
    body: DoctorRedeemIn,
    user_id: str = CurrentUserDep,
    role: str = CurrentRoleDep,
    session: Session = SessionDep,
) -> DoctorPatientOut:
    if role != "doctor":
        raise AccessDenied("Only a doctor account can redeem a doctor link", status_code=403)
    from app.auth import doctor_link

    member_id = doctor_link.verify_token(body.token)
    member = session.get(HouseholdMember, member_id)
    if member is None:
        raise AccessDenied("Patient not found", status_code=404)

    grant = session.exec(
        select(DoctorGrant).where(
            DoctorGrant.doctor_user_id == user_id,
            DoctorGrant.household_member_id == member_id,
        )
    ).first()
    if grant is None:
        grant = DoctorGrant(doctor_user_id=user_id, household_member_id=member_id)
        session.add(grant)
        session.commit()
    return DoctorPatientOut(
        household_member_id=member_id,
        name=member.display_name,
        granted_at=grant.granted_at,
        expires_at=grant.expires_at,
    )


@router.get("/doctor/patients", response_model=list[DoctorPatientOut])
def doctor_patients(
    user_id: str = CurrentUserDep,
    role: str = CurrentRoleDep,
    session: Session = SessionDep,
) -> list[DoctorPatientOut]:
    if role != "doctor":
        raise AccessDenied("Doctor account required", status_code=403)
    rows: list[DoctorPatientOut] = []
    for grant in session.exec(
        select(DoctorGrant).where(DoctorGrant.doctor_user_id == user_id)
    ).all():
        if grant.expires_at is not None and grant.expires_at <= datetime.now(UTC):
            continue
        member = session.get(HouseholdMember, grant.household_member_id)
        if member is None:
            continue
        rows.append(
            DoctorPatientOut(
                household_member_id=member.id,
                name=member.display_name,
                granted_at=grant.granted_at,
                expires_at=grant.expires_at,
            )
        )
    return rows


@router.get("/doctor/patients/{member_id}/export")
def doctor_patient_export(
    member_id: str,
    user_id: str = CurrentUserDep,
    role: str = CurrentRoleDep,
    session: Session = SessionDep,
) -> dict:
    if role != "doctor":
        raise AccessDenied("Doctor account required", status_code=403)
    grant = session.exec(
        select(DoctorGrant).where(
            DoctorGrant.doctor_user_id == user_id,
            DoctorGrant.household_member_id == member_id,
        )
    ).first()
    if grant is None:
        raise AccessDenied("No saved access to this patient", status_code=403)
    if grant.expires_at is not None and grant.expires_at <= datetime.now(UTC):
        raise AccessDenied("Saved access has expired", status_code=403)
    grant.last_viewed_at = datetime.now(UTC)
    session.add(grant)
    session.commit()
    return _serialize_export(doctor_export.build_export_without_access(session, member_id))


# ── Refill list + pharmacy ordering ─────────────────────────────────

@router.get("/patients/{patient_id}/refill-list")
def refill_list(
    patient_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> list[dict]:
    member_id = _member(session, user_id, patient_id)
    return [asdict(item) for item in companion.refill_list(
        session, user_id=user_id, household_member_id=member_id
    )]


class RefillOrderOut(BaseModel):
    id: str
    provider: str
    provider_order_id: str | None
    status: str
    detail: str | None
    items: list[dict]
    created_at: datetime


def _order_out(order: RefillOrder) -> RefillOrderOut:
    return RefillOrderOut(
        id=order.id,
        provider=order.provider,
        provider_order_id=order.provider_order_id,
        status=order.status,
        detail=order.detail,
        items=json.loads(order.items_json),
        created_at=order.created_at,
    )


@router.post("/households/{household_member_id}/refill-orders", response_model=RefillOrderOut, status_code=201)
def create_refill_order(
    household_member_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> RefillOrderOut:
    member = authorize_member(session, user_id, household_member_id)
    items = companion.refill_list(
        session, user_id=user_id, household_member_id=household_member_id
    )
    if not items:
        raise AccessDenied("No medicines are currently due for refill", status_code=400)

    payload = [
        {"name": item.name, "dose": item.dose, "reason": item.reason} for item in items
    ]
    result = pharmacy.get_pharmacy_provider().create_order(member.display_name, payload)
    order = RefillOrder(
        household_member_id=household_member_id,
        requested_by_user_id=user_id,
        provider=result.provider,
        provider_order_id=result.provider_order_id,
        status=result.status,
        items_json=json.dumps(payload),
        detail=result.detail,
    )
    session.add(order)
    session.commit()
    return _order_out(order)


@router.get("/refill-orders/{order_id}", response_model=RefillOrderOut)
def get_refill_order(
    order_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> RefillOrderOut:
    order = session.get(RefillOrder, order_id)
    if order is None:
        raise AccessDenied("Order not found", status_code=404)
    authorize_member(session, user_id, order.household_member_id)
    return _order_out(order)


# ── Symptoms: care connector, never medical guidance ────────────────

class SymptomIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symptom_text: str = Field(min_length=1, max_length=1000)
    severity: Literal["ROUTINE", "URGENT", "EMERGENCY"] = "ROUTINE"


class SymptomOut(BaseModel):
    id: str
    symptom_text: str
    severity: str
    care_action: str


_CARE_ACTIONS = {
    "EMERGENCY": "Call your local emergency number now.",
    "URGENT": "Contact a doctor or clinic today.",
    "ROUTINE": "Recorded. Discuss it at the next doctor visit.",
}


@router.post("/patients/{patient_id}/symptoms", response_model=SymptomOut, status_code=201)
def report_symptom(
    patient_id: str,
    body: SymptomIn,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> SymptomOut:
    member_id = _member(session, user_id, patient_id)
    action = _CARE_ACTIONS[body.severity]
    row = SymptomReport(
        household_member_id=member_id,
        reported_by_user_id=user_id,
        symptom_text=body.symptom_text,
        severity=body.severity,
        care_action=action,
    )
    session.add(row)
    session.commit()
    return SymptomOut(
        id=row.id,
        symptom_text=row.symptom_text,
        severity=row.severity,
        care_action=row.care_action,
    )


@router.get("/patients/{patient_id}/wellness-timeline")
def wellness_timeline(
    patient_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> list[dict]:
    rows = wellness.patient_timeline(
        session, user_id=user_id, patient_id=patient_id, limit=limit
    )
    return [
        {
            "date": row.date.isoformat(),
            "kind": row.kind,
            "title": row.title,
            "detail": row.detail,
            "source": row.source,
        }
        for row in rows
    ]


@router.post("/patients/{patient_id}/voice-report")
async def patient_voice_report(
    patient_id: str,
    audio: UploadFile | None = File(default=None),
    transcript: str | None = Form(default=None),
    language: str | None = Query(default=None),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
):
    from app.api.routes.patient import speech_provider_dep, voice_report

    member_id = _member(session, user_id, patient_id)
    return await voice_report(
        household_member_id=member_id,
        audio=audio,
        transcript_text=transcript,
        language=language,
        user_id=user_id,
        session=session,
        provider=speech_provider_dep(),
    )

