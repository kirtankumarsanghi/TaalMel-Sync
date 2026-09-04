import { z } from 'zod';

export const normalizationPreviewSchema = z.object({
  nameRaw: z.string().min(1, 'Medication name is required'),
  dosage: z.string().optional().nullable(),
  frequency: z.string().optional().nullable(),
  instructions: z.string().optional().nullable(),
  duration: z.string().optional().nullable(),
});

export const verifyNormalizationSchema = z.object({
  nameGeneric: z.string().min(1, 'Generic name is required'),
  nameBrand: z.string().optional().nullable(),
  strength: z.string().optional().nullable(),
  dosageForm: z.string().optional().nullable(),
});

export const householdMemberParamSchema = z.object({
  householdMemberId: z.string().uuid(),
});

export const medicationParamSchema = z.object({
  id: z.string().uuid(),
});
