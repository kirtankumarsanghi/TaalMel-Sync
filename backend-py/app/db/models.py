"""Phase 1 SQLModel tables. Column names mirror the original prisma/schema.prisma (snake_case).

The TypeScript prototype has been removed; this module is now the source of truth.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(default_factory=_uuid, primary_key=True)
    role: str
    name: str
    phone: str | None = Field(default=None, unique=True)
    email: str | None = Field(default=None, unique=True)
    password_hash: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    id: str = Field(default_factory=_uuid, primary_key=True)
    token_hash: str
    user_id: str = Field(foreign_key="users.id", index=True)
    family: str = Field(index=True)
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


class Household(SQLModel, table=True):
    __tablename__ = "households"

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    created_by: str = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class HouseholdMember(SQLModel, table=True):
    __tablename__ = "household_members"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_id: str = Field(foreign_key="households.id")
    user_id: str | None = Field(default=None, foreign_key="users.id")
    display_name: str
    relationship: str | None = None
    role: str = "member"
    is_patient: bool = True
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Patient(SQLModel, table=True):
    __tablename__ = "patients"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_member_id: str = Field(foreign_key="household_members.id", unique=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class CaregiverAccess(SQLModel, table=True):
    __tablename__ = "caregiver_access"

    id: str = Field(default_factory=_uuid, primary_key=True)
    caregiver_user_id: str = Field(foreign_key="users.id")
    household_member_id: str = Field(foreign_key="household_members.id")
    granted_at: datetime = Field(default_factory=_now)
    consent_recorded: bool = False
    # Temporary access handoff: when this passes, the row grants nothing. Enforced at
    # read time, so no background job is needed to expire it.
    expires_at: datetime | None = None
    updated_at: datetime = Field(default_factory=_now)


class Consent(SQLModel, table=True):
    __tablename__ = "consents"

    id: str = Field(default_factory=_uuid, primary_key=True)
    caregiver_access_id: str = Field(foreign_key="caregiver_access.id", unique=True)
    consent_type: str = "data_access"
    consent_method: str = "in_app"
    recorded_at: datetime = Field(default_factory=_now)
    revoked_at: datetime | None = None
    updated_at: datetime = Field(default_factory=_now)


class MedicationCanonical(SQLModel, table=True):
    __tablename__ = "medication_canonicals"

    id: str = Field(default_factory=_uuid, primary_key=True)
    generic_name: str
    brand_names: str = "[]"
    strength: str | None = None
    strength_unit: str | None = None
    dosage_form: str | None = None
    active_ingredient: str | None = None
    category: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Medication(SQLModel, table=True):
    __tablename__ = "medications"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_member_id: str = Field(foreign_key="household_members.id", index=True)
    name_raw: str
    name_generic: str | None = None
    name_brand: str | None = None
    dose_raw: str | None = None
    strength: str | None = None
    strength_raw: str | None = None
    dosage_form: str | None = None
    dosage_form_raw: str | None = None
    frequency_raw: str | None = None
    frequency: str | None = None
    duration_raw: str | None = None
    duration: str | None = None
    instructions_raw: str | None = None
    instructions: str | None = None
    identity_confirmed: bool = False
    normalization_status: str = Field(default="PENDING", index=True)
    normalization_method: str | None = None
    normalization_confidence: float | None = None
    canonical_id: str | None = Field(default=None, foreign_key="medication_canonicals.id", index=True)
    prescription_item_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class NormalizationLog(SQLModel, table=True):
    __tablename__ = "normalization_logs"

    id: str = Field(default_factory=_uuid, primary_key=True)
    medication_id: str = Field(foreign_key="medications.id", index=True)
    input_raw: str
    output_generic: str | None = None
    output_strength: str | None = None
    output_form: str | None = None
    method: str
    confidence: float
    status: str
    review_note: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Prescription(SQLModel, table=True):
    __tablename__ = "prescriptions"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_member_id: str = Field(foreign_key="household_members.id", index=True)
    prescribed_by: str | None = None
    prescribed_on: datetime | None = None
    file_storage_key: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    file_hash: str
    ocr_status: str = Field(default="PENDING", index=True)
    ocr_raw_text: str | None = None
    ocr_completed_at: datetime | None = None
    ocr_error: str | None = None
    uploaded_by_user_id: str = Field(foreign_key="users.id")
    verified: bool = False
    verified_at: datetime | None = None
    verified_by_user_id: str | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PrescriptionItem(SQLModel, table=True):
    __tablename__ = "prescription_items"

    id: str = Field(default_factory=_uuid, primary_key=True)
    prescription_id: str = Field(foreign_key="prescriptions.id", index=True)
    medication_name: str
    dosage: str | None = None
    frequency: str | None = None
    instructions: str | None = None
    confidence: float = 0
    ocr_raw_value: str | None = None
    verified: bool = False
    verified_at: datetime | None = None
    verified_by_user_id: str | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Event(SQLModel, table=True):
    """Append-only evidence log. No update or delete paths in application code."""

    __tablename__ = "events"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_member_id: str = Field(foreign_key="household_members.id", index=True)
    medication_id: str | None = Field(default=None, foreign_key="medications.id", index=True)
    event_type: str = Field(index=True)
    payload: str
    source: str
    source_user_id: str | None = Field(default=None, foreign_key="users.id")
    idempotency_key: str | None = Field(default=None, unique=True)
    occurred_at: datetime = Field(default_factory=_now)
    created_at: datetime = Field(default_factory=_now)
    created_by: str | None = Field(default=None, foreign_key="users.id")


class Case(SQLModel, table=True):
    __tablename__ = "cases"

    id: str = Field(default_factory=_uuid, primary_key=True)
    medication_id: str = Field(foreign_key="medications.id", index=True)
    trigger_event_id: str | None = Field(default=None, foreign_key="events.id")
    reason_code: str | None = None
    status: str = Field(default="OPEN", index=True)
    action_taken: str | None = None
    opened_at: datetime = Field(default_factory=_now)
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    updated_at: datetime = Field(default_factory=_now)


class Conflict(SQLModel, table=True):
    __tablename__ = "conflicts"

    id: str = Field(default_factory=_uuid, primary_key=True)
    medication_id: str = Field(foreign_key="medications.id")
    # The event that raised this conflict. Cases point at the same event, so resolving a
    # case can close exactly the conflict it came from rather than every conflict of the
    # same type on this medication.
    trigger_event_id: str | None = Field(default=None, foreign_key="events.id", unique=True)
    type: str
    description: str
    dimensions_involved: str
    suggested_question: str | None = None
    status: str = "OPEN"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    id: str = Field(default_factory=_uuid, primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    title: str
    body: str
    is_read: bool = False
    # Rule that produced this notification, plus the dedupe key for that rule + subject.
    rule: str | None = None
    dedupe_key: str | None = Field(default=None, unique=True)
    # Delivery is tracked separately from creation: a row is written even when no
    # channel is configured, and the failure is visible rather than silent.
    channel: str | None = None
    delivered_at: datetime | None = None
    delivery_error: str | None = None
    delivery_attempts: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class EmergencyContact(SQLModel, table=True):
    """A user who is notified when something is CRITICAL (expired medicine, out of stock)."""

    __tablename__ = "emergency_contacts"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_member_id: str = Field(foreign_key="household_members.id", index=True)
    user_id: str = Field(foreign_key="users.id")
    relationship: str | None = None
    created_at: datetime = Field(default_factory=_now)


class DoctorQuestion(SQLModel, table=True):
    """A question the family wants to raise at the next appointment.

    The app stores it and never answers it. It appears in the doctor export.
    """

    __tablename__ = "doctor_questions"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_member_id: str = Field(foreign_key="household_members.id", index=True)
    medication_id: str | None = Field(default=None, foreign_key="medications.id")
    question_text: str
    raised_by: str
    status: str = Field(default="PENDING", index=True)
    created_at: datetime = Field(default_factory=_now)
    discussed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=_now)


class LabReport(SQLModel, table=True):
    """An uploaded lab report. Values are stored as printed; nothing is interpreted."""

    __tablename__ = "lab_reports"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_member_id: str = Field(foreign_key="household_members.id", index=True)
    file_storage_key: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    file_hash: str
    captured_on: str | None = None  # ISO date printed on the report
    lab_name: str | None = None
    ocr_status: str = Field(default="PENDING", index=True)
    ocr_raw_text: str | None = None
    ocr_error: str | None = None
    uploaded_by_user_id: str = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class LabValue(SQLModel, table=True):
    __tablename__ = "lab_values"

    id: str = Field(default_factory=_uuid, primary_key=True)
    lab_report_id: str = Field(foreign_key="lab_reports.id", index=True)
    test_name: str
    value: str
    unit: str | None = None
    reference_range_raw: str | None = None
    created_at: datetime = Field(default_factory=_now)


class MedicalDocument(SQLModel, table=True):
    """Any uploaded clinical document, including ones with no structured parser.

    Prescriptions and lab reports also create their specialised rows; this table is the
    unified intake record so a patient's uploads are never lost when the type is a
    discharge summary, a doctor's note, or an unreadable page.
    """

    __tablename__ = "medical_documents"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_member_id: str = Field(foreign_key="household_members.id", index=True)
    document_type: str = Field(default="OTHER", index=True)
    original_filename: str
    mime_type: str
    file_size_bytes: int
    file_hash: str
    file_storage_key: str
    ocr_status: str = Field(default="PENDING", index=True)
    ocr_error: str | None = None
    raw_text: str | None = None
    extracted_json: str | None = None
    captured_on: str | None = None
    uploaded_by_user_id: str = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class TaperSchedule(SQLModel, table=True):
    """A gradual-reduction plan exactly as the prescriber wrote it.

    Stored verbatim: the app tracks deviation, it never invents a taper.
    """

    __tablename__ = "taper_schedules"

    id: str = Field(default_factory=_uuid, primary_key=True)
    medication_id: str = Field(foreign_key="medications.id", unique=True)
    schedule_text: str
    steps: str = "0"
    prescribed_by: str | None = None
    # The date the schedule started. Without this the tracker cannot know which step
    # the patient should be on today; day counting is no longer caller-supplied.
    started_on: datetime = Field(default_factory=_now)
    active: bool = True
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PhotoVerification(SQLModel, table=True):
    """A caregiver's photo of the physical medicine, with its comparison outcome.

    Default outcome is NOT_CHECKED: a comparison is only a statement when a real
    matcher ran. "Not checked" must never be read as "confirmed correct".
    """

    __tablename__ = "photo_verifications"

    id: str = Field(default_factory=_uuid, primary_key=True)
    medication_id: str = Field(foreign_key="medications.id", index=True)
    household_member_id: str = Field(foreign_key="household_members.id")
    file_storage_key: str
    file_hash: str
    outcome: str = "NOT_CHECKED"
    detail: str | None = None
    confidence: float | None = None
    taken_by_user_id: str = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=_now)


class AuditRecord(SQLModel, table=True):
    __tablename__ = "audit_records"

    id: str = Field(default_factory=_uuid, primary_key=True)
    action: str
    user_id: str | None = Field(default=None, foreign_key="users.id")
    details: str
    created_at: datetime = Field(default_factory=_now)


class RefillOrder(SQLModel, table=True):
    """A refill request sent to a pharmacy provider.

    The provider is pluggable: without credentials the mock provider records the order
    and returns a deterministic acknowledgement, so the workflow is testable and honest.
    """

    __tablename__ = "refill_orders"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_member_id: str = Field(foreign_key="household_members.id", index=True)
    requested_by_user_id: str = Field(foreign_key="users.id")
    provider: str
    provider_order_id: str | None = None
    status: str = Field(default="PENDING", index=True)
    items_json: str
    detail: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class DoctorGrant(SQLModel, table=True):
    """An optional doctor account's saved access to one patient.

    The public token route remains the default; this lets a doctor who chooses to log
    in keep a list of patients instead of re-scanning a QR at every visit.
    """

    __tablename__ = "doctor_grants"

    id: str = Field(default_factory=_uuid, primary_key=True)
    doctor_user_id: str = Field(foreign_key="users.id", index=True)
    household_member_id: str = Field(foreign_key="household_members.id", index=True)
    granted_at: datetime = Field(default_factory=_now)
    expires_at: datetime | None = None
    last_viewed_at: datetime | None = None


class SymptomReport(SQLModel, table=True):
    """A patient's own description of a symptom.

    The app records it and routes to care. It does not diagnose, triage by symptom
    content, or name a medicine. Severity is the patient's own selection.
    """

    __tablename__ = "symptom_reports"

    id: str = Field(default_factory=_uuid, primary_key=True)
    household_member_id: str = Field(foreign_key="household_members.id", index=True)
    reported_by_user_id: str = Field(foreign_key="users.id")
    symptom_text: str
    severity: str = Field(default="ROUTINE")
    care_action: str
    created_at: datetime = Field(default_factory=_now)
