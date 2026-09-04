import express, { Request, Response, NextFunction } from 'express';
import { requireAuth } from '../middleware/authMiddleware';
import { validate } from '../middleware/validate';
import { MedicationReportSchema, AvailabilitySchema, ConfirmMedicationSchema } from '../schemas/events';
import { appendEvent } from '../events/eventStore';
import { EVENT_TYPES } from '../events/eventTypes';
import { evaluateTriggers } from '../engines/triggerEngine';
import { getMedicationHistory } from '../services/auditTrailService';

const router = express.Router();
router.use(requireAuth);

router.post('/medications/:medicationId/report', validate(MedicationReportSchema), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { taking, reason } = req.body;

    const event = await appendEvent({
      medicationId: req.params.medicationId,
      eventType: EVENT_TYPES.MEDICATION_REPORTED,
      payload: { taking, reason: reason || null },
      source: req.user!.role,
      sourceUserId: req.user!.id,
    });
    const notifications = await evaluateTriggers(event);
    res.status(201).json({ event, notifications });
  } catch (err) {
    next(err);
  }
});

router.post('/medications/:medicationId/availability', validate(AvailabilitySchema), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { present, note, quantityNote } = req.body;

    const event = await appendEvent({
      medicationId: req.params.medicationId,
      eventType: EVENT_TYPES.AVAILABILITY_OBSERVED,
      payload: { present, note: note || null, quantityNote: quantityNote || null },
      source: req.user!.role,
      sourceUserId: req.user!.id,
    });
    const notifications = await evaluateTriggers(event);
    res.status(201).json({ event, notifications });
  } catch (err) {
    next(err);
  }
});

router.post('/medications/:medicationId/confirm', validate(ConfirmMedicationSchema), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { status, confirmedBySource } = req.body;

    const event = await appendEvent({
      medicationId: req.params.medicationId,
      eventType: EVENT_TYPES.MEDICATION_CONFIRMED,
      payload: { status },
      source: confirmedBySource || req.user!.role,
      sourceUserId: req.user!.id,
    });
    const notifications = await evaluateTriggers(event);
    res.status(201).json({ event, notifications });
  } catch (err) {
    next(err);
  }
});

router.get('/medications/:medicationId/history', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const history = await getMedicationHistory(req.params.medicationId);
    res.json(history);
  } catch (err) {
    next(err);
  }
});

export default router;

export {};
