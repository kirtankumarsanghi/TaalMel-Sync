import { z } from 'zod';
import { EVENT_TYPES, SOURCES } from './eventTypes';

// Base schema pieces
const SourceSchema = z.nativeEnum(SOURCES).or(z.string()); // Allow string fallback just in case

// 1. PRESCRIPTION_UPLOADED
export const PrescriptionUploadedSchema = z.object({
  prescriptionId: z.string().uuid(),
  fileStorageKey: z.string()
}).passthrough();

// 2. MEDICATION_EXTRACTED
export const MedicationExtractedSchema = z.object({
  prescriptionItemId: z.string().uuid(),
  nameRaw: z.string(),
  dosage: z.string().nullable().optional(),
  frequency: z.string().nullable().optional(),
  instructions: z.string().nullable().optional(),
  confidence: z.number().min(0).max(1)
}).passthrough();

// 3. MEDICATION_VERIFIED
export const MedicationVerifiedSchema = z.object({
  medicationId: z.string().uuid(),
  changesMade: z.boolean(),
  previousValues: z.record(z.any()).optional()
}).passthrough();

// 4. MEDICATION_REPORTED
export const MedicationReportedSchema = z.object({
  medicationId: z.string().uuid(),
  reportType: z.enum(['TAKING', 'STOPPED', 'CHANGED_DOSE']),
  notes: z.string().optional()
}).passthrough();

// 5. AVAILABILITY_OBSERVED
export const AvailabilityObservedSchema = z.object({
  medicationId: z.string().uuid(),
  status: z.enum(['AVAILABLE', 'RUNNING_LOW', 'OUT_OF_STOCK', 'NOT_FOUND']),
  quantityRemaining: z.number().optional()
}).passthrough();

// 6. MEDICATION_CONFIRMED
export const MedicationConfirmedSchema = z.object({
  medicationId: z.string().uuid(),
  confirmationMethod: z.string()
}).passthrough();

// 7. CONFLICT_DETECTED
export const ConflictDetectedSchema = z.object({
  medicationId: z.string().uuid(),
  conflictType: z.string(),
  description: z.string(),
  dimensionsInvolved: z.array(z.string())
}).passthrough();

// 8. REASON_RECORDED
export const ReasonRecordedSchema = z.object({
  medicationId: z.string().uuid(),
  reasonCode: z.string(),
  notes: z.string().optional()
}).passthrough();

// 9. ACTION_ASSIGNED
export const ActionAssignedSchema = z.object({
  medicationId: z.string().uuid(),
  assignedToUserId: z.string().uuid(),
  actionType: z.string(),
  dueDate: z.string().datetime().optional()
}).passthrough();

// 10. CASE_RESOLVED
export const CaseResolvedSchema = z.object({
  medicationId: z.string().uuid(),
  caseId: z.string().uuid(),
  resolutionNote: z.string().optional()
}).passthrough();

// A master map to route the validation
export const EventPayloadSchemas = {
  [EVENT_TYPES.PRESCRIPTION_UPLOADED]: PrescriptionUploadedSchema,
  [EVENT_TYPES.MEDICATION_EXTRACTED]: MedicationExtractedSchema,
  [EVENT_TYPES.MEDICATION_VERIFIED_FROM_PRESCRIPTION]: MedicationVerifiedSchema,
  [EVENT_TYPES.MEDICATION_REPORTED]: MedicationReportedSchema,
  [EVENT_TYPES.AVAILABILITY_OBSERVED]: AvailabilityObservedSchema,
  [EVENT_TYPES.MEDICATION_CONFIRMED]: MedicationConfirmedSchema,
  [EVENT_TYPES.CONFLICT_DETECTED]: ConflictDetectedSchema,
  [EVENT_TYPES.REASON_RECORDED]: ReasonRecordedSchema,
  [EVENT_TYPES.ACTION_ASSIGNED]: ActionAssignedSchema,
  [EVENT_TYPES.CASE_RESOLVED]: CaseResolvedSchema,
  // Ensure the existing normalization events are also supported
  [EVENT_TYPES.MEDICATION_NORMALIZED]: z.record(z.any()),
  [EVENT_TYPES.MEDICATION_NORMALIZATION_REVIEW]: z.record(z.any()),
  [EVENT_TYPES.MEDICATION_NORMALIZATION_VERIFIED]: z.record(z.any()),
  [EVENT_TYPES.PRESCRIPTION_OCR_COMPLETED]: z.record(z.any()),
  [EVENT_TYPES.PRESCRIPTION_OCR_FAILED]: z.record(z.any()),
  [EVENT_TYPES.PRESCRIPTION_VERIFIED]: z.record(z.any()),
  [EVENT_TYPES.DOSE_CHANGED]: z.record(z.any()),
} as const;

export function validateEventPayload(eventType: string, payload: unknown) {
  const schema = EventPayloadSchemas[eventType as keyof typeof EventPayloadSchemas];
  
  if (!schema) {
    throw new Error(`Unknown event type: ${eventType}`);
  }

  // Parse will throw ZodError if invalid
  return schema.parse(payload);
}
