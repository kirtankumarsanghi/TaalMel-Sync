import { z } from 'zod';
import { UuidSchema } from './common';

export const CreatePatientSchema = z.object({
  householdId: UuidSchema,
  displayName: z.string().min(1, 'Display name is required').max(200),
  relationship: z.string().max(100).optional(),
});

export const UpdatePatientSchema = z.object({
  displayName: z.string().min(1).max(200).optional(),
  relationship: z.string().max(100).nullable().optional(),
});

export const PatientIdParamSchema = z.object({
  id: UuidSchema,
});
