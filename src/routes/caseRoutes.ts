import express, { Request, Response, NextFunction } from 'express';
import { requireAuth } from '../middleware/authMiddleware';
import { validate } from '../middleware/validate';
import { ReasonSchema, ActionSchema, ResolveCaseSchema } from '../schemas/cases';
import { detectConflicts } from '../engines/conflictDetection';
import { recordReason, REASON_CODES, REASON_RESPONSES } from '../engines/reasonClassification';
import {
  assignAction,
  resolveCase,
  getCase,
  listCasesForMedication,
  listOpenCasesForHouseholdMember,
} from '../engines/caseLifecycle';
import { explainCase } from '../services/auditTrailService';
import { getAffordabilityResponse } from '../services/affordabilityService';

const router = express.Router();
router.use(requireAuth);

router.get('/reason-codes', (_req: Request, res: Response) => {
  res.json({ codes: REASON_CODES, responses: REASON_RESPONSES });
});

router.get('/medications/:medicationId/conflicts', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const conflicts = await detectConflicts(req.params.medicationId);
    res.json(conflicts);
  } catch (err) {
    next(err);
  }
});

router.get('/medications/:medicationId/cases', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const cases = await listCasesForMedication(req.params.medicationId);
    res.json(cases);
  } catch (err) {
    next(err);
  }
});

router.get('/household/:householdMemberId/open', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const cases = await listOpenCasesForHouseholdMember(req.params.householdMemberId);
    res.json(cases);
  } catch (err) {
    next(err);
  }
});

router.get('/:caseId/explain', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const explanation = await explainCase(req.params.caseId);
    res.json(explanation);
  } catch (err) {
    next(err);
  }
});

router.post('/:caseId/reason', validate(ReasonSchema), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { medicationId, reasonCode, freeTextNote } = req.body;
    const result = await recordReason({
      caseId: req.params.caseId,
      medicationId,
      reasonCode,
      freeTextNote,
      source: req.user!.role,
      sourceUserId: req.user!.id,
    });

    let affordability: any = null;
    if (reasonCode === REASON_CODES.COULD_NOT_AFFORD) {
      affordability = getAffordabilityResponse();
    }

    res.status(201).json({ ...result, affordability });
  } catch (err) {
    next(err);
  }
});

router.post('/:caseId/action', validate(ActionSchema), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { medicationId, actionDescription } = req.body;
    const result = await assignAction({
      caseId: req.params.caseId,
      medicationId,
      actionDescription,
      source: req.user!.role,
      sourceUserId: req.user!.id,
    });
    res.status(201).json(result);
  } catch (err) {
    next(err);
  }
});

router.post('/:caseId/resolve', validate(ResolveCaseSchema), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { medicationId, outcome, resolutionNote } = req.body;
    const result = await resolveCase({
      caseId: req.params.caseId,
      medicationId,
      outcome,
      resolutionNote,
      source: req.user!.role,
      sourceUserId: req.user!.id,
    });
    res.status(200).json(result);
  } catch (err) {
    next(err);
  }
});

router.get('/:caseId', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const kase = await getCase(req.params.caseId);
    if (!kase) {
      res.status(404).json({ error: 'Case not found' });
      return;
    }
    res.json(kase);
  } catch (err) {
    next(err);
  }
});

export default router;

export {};
