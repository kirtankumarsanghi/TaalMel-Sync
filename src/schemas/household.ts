import { z } from 'zod';
import { UuidSchema } from './common';

export const CreateHouseholdSchema = z.object({
  name: z.string().min(1, 'Household name is required').max(200),
  patientDisplayName: z.string().min(1, 'Patient display name is required').max(200),
  relationship: z.string().max(100).optional(),
});

export const HouseholdIdParamSchema = z.object({
  id: UuidSchema,
});
