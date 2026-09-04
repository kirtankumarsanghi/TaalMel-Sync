import { z } from 'zod';

export const uploadPrescriptionSchema = z.object({
  householdMemberId: z.string().uuid(),
});

export const prescriptionParamsSchema = z.object({
  id: z.string().uuid(),
});

export const verifyPrescriptionItemSchema = z.object({
  itemId: z.string().uuid(),
  medicationName: z.string().min(1),
  dosage: z.string().optional().nullable(),
  frequency: z.string().optional().nullable(),
  instructions: z.string().optional().nullable(),
});

export const verifyPrescriptionSchema = z.object({
  items: z.array(verifyPrescriptionItemSchema).min(1),
});
