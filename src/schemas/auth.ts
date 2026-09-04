import { z } from 'zod';

export const RegisterSchema = z.object({
  name: z.string().min(1, 'Name is required').max(200),
  phone: z.string().min(1, 'Phone is required').max(20),
  password: z.string().min(8, 'Password must be at least 8 characters').max(128),
  role: z.enum(['caregiver', 'patient']),
});

export const LoginSchema = z.object({
  phone: z.string().min(1, 'Phone is required'),
  password: z.string().min(1, 'Password is required'),
});

export const RefreshSchema = z.object({
  refreshToken: z.string().uuid('Invalid refresh token format'),
});

// Keep old name as alias for backward compat with existing tests
export const SignupSchema = RegisterSchema;
