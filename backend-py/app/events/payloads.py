"""One Pydantic model per event type. This is the single source of truth for
event payload shape: routes and engines both build and read these models, so a
route cannot send a shape the engine does not understand.

extra="forbid" rejects unknown fields, so typos fail loudly instead of being
stored silently.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.events.types import Dimension, ReasonCode


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PrescriptionUploadedPayload(_Payload):
    prescription_id: UUID
    file_storage_key: str = Field(min_length=1)


class PrescriptionOcrCompletedPayload(_Payload):
    prescription_id: UUID
    item_count: int = Field(ge=0)


class PrescriptionOcrFailedPayload(_Payload):
    prescription_id: UUID
    error: str = Field(min_length=1)


class PrescriptionVerifiedPayload(_Payload):
    prescription_id: UUID
    verified_item_count: int = Field(ge=0)


class MedicationExtractedPayload(_Payload):
    prescription_item_id: UUID
    name_raw: str = Field(min_length=1)
    dosage: str | None = None
    frequency: str | None = None
    instructions: str | None = None
    confidence: float = Field(ge=0, le=1)


class MedicationNormalizedPayload(_Payload):
    medication_id: UUID
    name_generic: str | None
    method: str
    confidence: float = Field(ge=0, le=1)
    status: str


class MedicationNormalizationReviewPayload(_Payload):
    medication_id: UUID
    reason: str = Field(min_length=1)


class MedicationNormalizationVerifiedPayload(_Payload):
    medication_id: UUID
    name_generic: str | None


class MedicationReportedPayload(_Payload):
    """Patient or caregiver says whether the medicine is being taken."""

    medication_id: UUID
    taking: bool
    reason: ReasonCode | None = None
    note: str | None = None


class AvailabilityObservedPayload(_Payload):
    """Caregiver physically checks the medicine at home."""

    medication_id: UUID
    present: bool
    quantity_note: Literal["ok", "low", "nearly empty"] | None = None
    expiry_date: datetime | None = None
    note: str | None = None


class MedicationConfirmedPayload(_Payload):
    medication_id: UUID
    status: Literal["CONFIRMED", "DISCONTINUED", "UNCERTAIN"]
    confirmation_method: str = Field(min_length=1)


class DoseChangedPayload(_Payload):
    medication_id: UUID
    previous_dose: str | None = None
    new_dose: str = Field(min_length=1)
    changed_by: str = Field(min_length=1)


class ConflictDetectedPayload(_Payload):
    medication_id: UUID
    conflict_type: Literal[
        "PRESCRIPTION_VS_REPORT",
        "REPORT_VS_AVAILABILITY",
        "STOPPED_BUT_UNEXPLAINED",
        "EXPIRED_STOCK",
    ]
    description: str = Field(min_length=1)
    # Most conflicts compare two evidence dimensions. Expired stock is a fact about one
    # dimension (AVAILABLE), so a single dimension is permitted rather than fabricated.
    dimensions_involved: list[Dimension] = Field(min_length=1)


class ReasonRecordedPayload(_Payload):
    medication_id: UUID
    case_id: UUID
    reason_code: ReasonCode
    note: str | None = None


class ActionAssignedPayload(_Payload):
    medication_id: UUID
    case_id: UUID
    action_description: str = Field(min_length=1)
    assigned_to_user_id: UUID | None = None
    due_date: datetime | None = None


class CaseResolvedPayload(_Payload):
    medication_id: UUID
    case_id: UUID
    resolution_note: str | None = None


PAYLOAD_MODELS: dict[str, type[_Payload]] = {
    "PrescriptionUploaded": PrescriptionUploadedPayload,
    "PrescriptionOcrCompleted": PrescriptionOcrCompletedPayload,
    "PrescriptionOcrFailed": PrescriptionOcrFailedPayload,
    "PrescriptionVerified": PrescriptionVerifiedPayload,
    "MedicationExtracted": MedicationExtractedPayload,
    "MedicationNormalized": MedicationNormalizedPayload,
    "MedicationNormalizationReview": MedicationNormalizationReviewPayload,
    "MedicationNormalizationVerified": MedicationNormalizationVerifiedPayload,
    "MedicationReported": MedicationReportedPayload,
    "AvailabilityObserved": AvailabilityObservedPayload,
    "MedicationConfirmed": MedicationConfirmedPayload,
    "DoseChanged": DoseChangedPayload,
    "ConflictDetected": ConflictDetectedPayload,
    "ReasonRecorded": ReasonRecordedPayload,
    "ActionAssigned": ActionAssignedPayload,
    "CaseResolved": CaseResolvedPayload,
}
