import { z } from 'zod';

export const MedicationReportSchema = z.object({
  taking: z.boolean(),
  reason: z.string().nullable().optional(),
});

export const AvailabilitySchema = z.object({
  present: z.boolean(),
  note: z.string().nullable().optional(),
  quantityNote: z.string().nullable().optional(),
});

export const ConfirmMedicationSchema = z.object({
  status: z.enum(['active', 'discontinued']),
  confirmedBySource: z.enum(['caregiver', 'patient', 'doctor']).optional(),
});

export {};
