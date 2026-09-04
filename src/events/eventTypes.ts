export const EVENT_TYPES = {
  PRESCRIPTION_UPLOADED: 'PrescriptionUploaded',
  PRESCRIPTION_OCR_COMPLETED: 'PrescriptionOcrCompleted',
  PRESCRIPTION_OCR_FAILED: 'PrescriptionOcrFailed',
  PRESCRIPTION_VERIFIED: 'PrescriptionVerified',
  MEDICATION_VERIFIED_FROM_PRESCRIPTION: 'MedicationVerifiedFromPrescription',
  MEDICATION_EXTRACTED: 'MedicationExtracted',
  MEDICATION_REPORTED: 'MedicationReported',
  AVAILABILITY_OBSERVED: 'AvailabilityObserved',
  MEDICATION_CONFIRMED: 'MedicationConfirmed',
  DOSE_CHANGED: 'DoseChanged',
  CONFLICT_DETECTED: 'ConflictDetected',
  REASON_RECORDED: 'ReasonRecorded',
  ACTION_ASSIGNED: 'ActionAssigned',
  CASE_RESOLVED: 'CaseResolved',
  MEDICATION_NORMALIZED: 'MedicationNormalized',
  MEDICATION_NORMALIZATION_REVIEW: 'MedicationNormalizationReview',
  MEDICATION_NORMALIZATION_VERIFIED: 'MedicationNormalizationVerified',
} as const;

export const SOURCES = {
  PATIENT: 'patient',
  CAREGIVER: 'caregiver',
  DOCTOR: 'doctor',
  OCR: 'ocr',
  SYSTEM: 'system',
} as const;

export const EVIDENCE_DIMENSIONS = {
  PRESCRIBED: 'PRESCRIBED',
  AVAILABLE: 'AVAILABLE',
  REPORTED_TAKING: 'REPORTED_TAKING',
  CONFIRMED_STATUS: 'CONFIRMED_STATUS',
} as const;

export {};
