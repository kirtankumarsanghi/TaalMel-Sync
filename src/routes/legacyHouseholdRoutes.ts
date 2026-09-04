import express, { Request, Response, NextFunction } from 'express';
import { requireAuth } from '../middleware/authMiddleware';
import { HouseholdService } from '../services/householdService';

const router = express.Router();
router.use(requireAuth);

export async function requireHouseholdAccess(req: Request, res: Response, next: NextFunction) {
  try {
    const memberId = req.params.memberId || req.body.householdMemberId;
    if (!memberId) {
      res.status(400).json({ error: 'householdMemberId is required' });
      return;
    }

    const hasAccess = await HouseholdService.checkAccess(req.user!.id!, memberId);

    if (!hasAccess) {
      res.status(403).json({ error: 'Not authorized for this household member' });
      return;
    }
    next();
  } catch (err) {
    next(err);
  }
}

router.post('/households', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { householdName, patientDisplayName, relationship, consentRecorded } = req.body;
    if (!householdName || !patientDisplayName) {
      res.status(400).json({ error: 'householdName and patientDisplayName are required' });
      return;
    }

    const result = await HouseholdService.createHousehold({
      householdName,
      patientDisplayName,
      relationship,
      consentRecorded: !!consentRecorded,
      userId: req.user!.id!
    });

    res.status(201).json(result);
  } catch (err) {
    next(err);
  }
});

router.get('/members', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const members = await HouseholdService.getMembersForUser(req.user!.id!);
    res.json(members);
  } catch (err) {
    next(err);
  }
});

export default router;

export {};
