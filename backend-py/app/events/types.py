from enum import StrEnum


class EventType(StrEnum):
    PRESCRIPTION_UPLOADED = "PrescriptionUploaded"
    PRESCRIPTION_OCR_COMPLETED = "PrescriptionOcrCompleted"
    PRESCRIPTION_OCR_FAILED = "PrescriptionOcrFailed"
    PRESCRIPTION_VERIFIED = "PrescriptionVerified"
    MEDICATION_EXTRACTED = "MedicationExtracted"
    MEDICATION_NORMALIZED = "MedicationNormalized"
    MEDICATION_NORMALIZATION_REVIEW = "MedicationNormalizationReview"
    MEDICATION_NORMALIZATION_VERIFIED = "MedicationNormalizationVerified"
    MEDICATION_REPORTED = "MedicationReported"
    AVAILABILITY_OBSERVED = "AvailabilityObserved"
    MEDICATION_CONFIRMED = "MedicationConfirmed"
    DOSE_CHANGED = "DoseChanged"
    CONFLICT_DETECTED = "ConflictDetected"
    REASON_RECORDED = "ReasonRecorded"
    ACTION_ASSIGNED = "ActionAssigned"
    CASE_RESOLVED = "CaseResolved"


class Source(StrEnum):
    PATIENT = "patient"
    CAREGIVER = "caregiver"
    DOCTOR = "doctor"
    OCR = "ocr"
    SYSTEM = "system"


class Dimension(StrEnum):
    PRESCRIBED = "PRESCRIBED"
    AVAILABLE = "AVAILABLE"
    REPORTED_TAKING = "REPORTED_TAKING"
    CONFIRMED_STATUS = "CONFIRMED_STATUS"


class ReasonCode(StrEnum):
    RAN_OUT = "RAN_OUT"
    FORGOT = "FORGOT"
    CONFUSED_ABOUT_DOSE = "CONFUSED_ABOUT_DOSE"
    SIDE_EFFECT = "SIDE_EFFECT"
    COULD_NOT_AFFORD = "COULD_NOT_AFFORD"
    DOCTOR_TOLD_TO_STOP = "DOCTOR_TOLD_TO_STOP"
    PATIENT_DECLINED = "PATIENT_DECLINED"
    EXPIRED = "EXPIRED"


class CaseStatus(StrEnum):
    OPEN = "OPEN"
    AWAITING_INFO = "AWAITING_INFO"
    RESOLVED = "RESOLVED"
    STILL_UNCERTAIN = "STILL_UNCERTAIN"
