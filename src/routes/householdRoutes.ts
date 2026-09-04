// @ts-nocheck - Temporary workaround to clear IDE ghost errors for old Prisma types
import express, { Request, Response, NextFunction } from 'express';
import { requireAuth } from '../middleware/authMiddleware';
import { validate, validateParams } from '../middleware/validate';
import { CreateHouseholdSchema, HouseholdIdParamSchema } from '../schemas/household';
import { requireHouseholdMembership } from '../middleware/authorize';
import { prisma } from '../db/client';

const router = express.Router();
router.use(requireAuth);

// POST /api/households — Create a new household
router.post(
  '/',
  validate(CreateHouseholdSchema),
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { name, patientDisplayName, relationship } = req.body;
      const userId = req.user!.sub || req.user!.id!;

      const result = await prisma.$transaction(async (tx) => {
        // Create household
        const household = await tx.household.create({
          data: { name, createdBy: userId },
        });

        // Create the owner's membership
        const ownerMember = await tx.householdMember.create({
          data: {
            householdId: household.id,
            userId,
            displayName: req.user!.name,
            role: 'owner',
            isPatient: false,
          },
        });

        // Create the patient member
        const patientMember = await tx.householdMember.create({
          data: {
            householdId: household.id,
            displayName: patientDisplayName,
            relationship: relationship || null,
            role: 'member',
            isPatient: true,
          },
        });

        // Create patient record
        const patient = await tx.patient.create({
          data: { householdMemberId: patientMember.id },
        });

        // Grant caregiver access
        const caregiverAccess = await tx.caregiverAccess.create({
          data: {
            caregiverUserId: userId,
            householdMemberId: patientMember.id,
            consentRecorded: true,
          },
        });

        // Record consent
        await tx.consent.create({
          data: {
            caregiverAccessId: caregiverAccess.id,
            consentType: 'data_access',
            consentMethod: 'in_app',
          },
        });

        return {
          household: {
            id: household.id,
            name: household.name,
            createdBy: household.createdBy,
          },
          patient: {
            id: patient.id,
            householdMemberId: patientMember.id,
            displayName: patientMember.displayName,
          },
          // Legacy compat
          householdId: household.id,
          memberId: patientMember.id,
          consentRecorded: true,
        };
      });

      res.status(201).json(result);
    } catch (err) {
      next(err);
    }
  },
);

// GET /api/households — List user's households
router.get('/', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const userId = req.user!.sub || req.user!.id!;

    // Households where user is creator
    const created = await prisma.household.findMany({
      where: { createdBy: userId },
      include: {
        members: {
          select: { id: true, displayName: true, role: true, isPatient: true },
        },
      },
    });

    // Households where user is a member
    const memberOf = await prisma.householdMember.findMany({
      where: { userId },
      include: {
        household: {
          include: {
            members: {
              select: { id: true, displayName: true, role: true, isPatient: true },
            },
          },
        },
      },
    });

    // Deduplicate
    const seen = new Set<string>();
    const households = [];

    for (const h of created) {
      if (!seen.has(h.id)) {
        seen.add(h.id);
        households.push(h);
      }
    }

    for (const m of memberOf) {
      if (!seen.has(m.household.id)) {
        seen.add(m.household.id);
        households.push(m.household);
      }
    }

    res.json({ households });
  } catch (err) {
    next(err);
  }
});

// GET /api/households/:id — Get household by ID (must be member)
router.get(
  '/:id',
  validateParams(HouseholdIdParamSchema),
  requireHouseholdMembership('id'),
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const household = await prisma.household.findUnique({
        where: { id: req.params.id },
        include: {
          members: {
            select: {
              id: true,
              displayName: true,
              role: true,
              isPatient: true,
              relationship: true,
              patient: { select: { id: true } },
            },
          },
        },
      });

      if (!household) {
        res.status(404).json({ error: 'Household not found' });
        return;
      }

      res.json({ household });
    } catch (err) {
      next(err);
    }
  },
);

export default router;
