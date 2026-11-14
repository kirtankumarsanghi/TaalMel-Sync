"""Audit trail for sensitive actions. Rows are written in the caller's transaction."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.db.models import AuditRecord


class AuditAction:
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    REGISTER = "REGISTER"
    LOGOUT = "LOGOUT"
    HOUSEHOLD_CREATED = "HOUSEHOLD_CREATED"
    PATIENT_CREATED = "PATIENT_CREATED"
    ACCESS_GRANTED = "ACCESS_GRANTED"
    CONSENT_RECORDED = "CONSENT_RECORDED"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    ACCESS_DENIED = "ACCESS_DENIED"
    PRESCRIPTION_UPLOADED = "PRESCRIPTION_UPLOADED"
    PRESCRIPTION_UPDATED = "PRESCRIPTION_UPDATED"
    PRESCRIPTION_ITEM_ADDED = "PRESCRIPTION_ITEM_ADDED"
    PRESCRIPTION_VERIFIED = "PRESCRIPTION_VERIFIED"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    MEDICATION_NORMALIZATION_VERIFIED = "MEDICATION_NORMALIZATION_VERIFIED"
    EVIDENCE_REPORTED = "EVIDENCE_REPORTED"
    EVIDENCE_AVAILABILITY_RECORDED = "EVIDENCE_AVAILABILITY_RECORDED"
    EVIDENCE_STATUS_CONFIRMED = "EVIDENCE_STATUS_CONFIRMED"
    DOSE_CHANGED = "DOSE_CHANGED"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    CASE_RESOLVED = "CASE_RESOLVED"
    REASON_RECORDED = "REASON_RECORDED"
    DOSE_CHANGED = "DOSE_CHANGED"
    EMERGENCY_CONTACT_ADDED = "EMERGENCY_CONTACT_ADDED"
    EMERGENCY_CONTACT_REMOVED = "EMERGENCY_CONTACT_REMOVED"
    DOCTOR_LINK_ISSUED = "DOCTOR_LINK_ISSUED"
    DOCTOR_EXPORT_VIEWED = "DOCTOR_EXPORT_VIEWED"
    LAB_REPORT_UPLOADED = "LAB_REPORT_UPLOADED"


def log(
    session: Session,
    action: str,
    *,
    user_id: str | None,
    details: dict[str, Any] | None = None,
) -> AuditRecord:
    record = AuditRecord(
        action=action,
        user_id=user_id,
        details=json.dumps(details or {}, default=str),
        created_at=datetime.now(UTC),
    )
    session.add(record)
    session.flush()
    return record
