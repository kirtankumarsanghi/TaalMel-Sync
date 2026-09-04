import { Request, Response, NextFunction } from 'express';
import { prisma } from '../db/client';

/**
 * Verify the authenticated user is a member of the household referenced in req.params[paramName].
 * Attaches req.householdMembership with the member record.
 */
export function requireHouseholdMembership(paramName: string = 'id') {
  return async (req: Request, res: Response, next: NextFunction) => {
    try {
      const householdId = req.params[paramName];
      if (!householdId) {
        res.status(400).json({ error: `Missing parameter: ${paramName}` });
        return;
      }

      const userId = req.user!.sub || req.user!.id;
      
      // Check if user is a member of this household
      const membership = await prisma.householdMember.findFirst({
        where: { householdId, userId },
      });

      // Also check if user is the household creator
      const household = await prisma.household.findUnique({
        where: { id: householdId },
      });

      if (!membership && (!household || household.createdBy !== userId)) {
        res.status(403).json({ error: 'Not a member of this household' });
        return;
      }

      (req as any).householdMembership = membership;
      (req as any).household = household;
      next();
    } catch (err) {
      next(err);
    }
  };
}

/**
 * Verify the authenticated user has CaregiverAccess to the patient referenced in req.params[paramName].
 * The paramName refers to a Patient.id — we resolve through HouseholdMember to check access.
 */
export function requirePatientAccess(paramName: string = 'id') {
  return async (req: Request, res: Response, next: NextFunction) => {
    try {
      const patientId = req.params[paramName];
      if (!patientId) {
        res.status(400).json({ error: `Missing parameter: ${paramName}` });
        return;
      }

      const userId = req.user!.sub || req.user!.id;

      // Find patient → householdMember → check access
      const patient = await prisma.patient.findUnique({
        where: { id: patientId },
        include: { householdMember: { include: { household: true } } },
      });

      if (!patient) {
        res.status(404).json({ error: 'Patient not found' });
        return;
      }

      // Check CaregiverAccess
      const access = await prisma.caregiverAccess.findFirst({
        where: {
          caregiverUserId: userId,
          householdMemberId: patient.householdMemberId,
        },
      });

      // Also allow if user is the patient's own linked user
      const isSelf = patient.householdMember.userId === userId;

      // Also allow if user created the household
      const isHouseholdCreator = patient.householdMember.household.createdBy === userId;

      if (!access && !isSelf && !isHouseholdCreator) {
        res.status(403).json({ error: 'Not authorized to access this patient' });
        return;
      }

      (req as any).patient = patient;
      (req as any).caregiverAccess = access;
      next();
    } catch (err) {
      next(err);
    }
  };
}

/**
 * Verify that consent is recorded for the caregiver→patient relationship.
 * Must be used after requirePatientAccess.
 */
export function requireConsent() {
  return async (req: Request, res: Response, next: NextFunction) => {
    try {
      const access = (req as any).caregiverAccess;
      const patient = (req as any).patient;
      const userId = req.user!.sub || req.user!.id;

      // If user is the patient themselves, no consent gate needed
      if (patient && patient.householdMember?.userId === userId) {
        next();
        return;
      }

      if (!access) {
        res.status(403).json({ error: 'No caregiver access record found' });
        return;
      }

      if (!access.consentRecorded) {
        res.status(403).json({ error: 'Consent not recorded for this patient relationship' });
        return;
      }

      // Check that consent record exists and is not revoked
      const consent = await prisma.consent.findUnique({
        where: { caregiverAccessId: access.id },
      });

      if (consent && consent.revokedAt) {
        res.status(403).json({ error: 'Consent has been revoked' });
        return;
      }

      next();
    } catch (err) {
      next(err);
    }
  };
}
