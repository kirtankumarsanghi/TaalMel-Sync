import { z } from 'zod';

export const ReasonSchema = z.object({
  medicationId: z.string().uuid(),
  reasonCode: z.string(),
  freeTextNote: z.string().nullable().optional(),
});

export const ActionSchema = z.object({
  medicationId: z.string().uuid(),
  actionDescription: z.string(),
});

export const ResolveCaseSchema = z.object({
  medicationId: z.string().uuid(),
  outcome: z.enum(['RESOLVED', 'STILL_UNCERTAIN']),
  resolutionNote: z.string().nullable().optional(),
});

export {};
