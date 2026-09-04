import express, { Request, Response, NextFunction } from 'express';
import { MedicationService } from '../services/medicationService';
import { requireAuth } from '../middleware/authMiddleware';
import { appendEvent } from '../events/eventStore';
import { EVENT_TYPES, SOURCES } from '../events/eventTypes';
import { computeMedicationState } from '../engines/medicationStateEngine';
import { evaluateTriggers } from '../engines/triggerEngine';
import { normalizeToGeneric } from '../services/normalizationService';

const router = express.Router();
router.use(requireAuth);

router.post('/', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { householdMemberId, nameRaw, dose, doctor, source } = req.body;
    if (!householdMemberId || !nameRaw) {
      res.status(400).json({ error: 'householdMemberId and nameRaw are required' });
      return;
    }

    const nameGeneric = normalizeToGeneric(nameRaw) || nameRaw;
    
    const medication = await MedicationService.createMedication({
      householdMemberId,
      nameRaw,
      nameGeneric,
      doseRaw: dose || null,
      identityConfirmed: source === 'manual'
    });

    const event = await appendEvent({
      medicationId: medication.id,
      eventType: EVENT_TYPES.MEDICATION_REPORTED,
      payload: { medicationId: medication.id, doctor: doctor || null, dose: dose || null, rawName: nameRaw, reportType: 'TAKING' },
      source: req.user!.role,
      sourceUserId: req.user!.id,
    });

    const notifications = await evaluateTriggers(event);

    res.status(201).json({ medicationId: medication.id, nameGeneric, event, notifications });
  } catch (err: unknown) {
    next(err);
  }
});

router.get('/:medicationId/state', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const state = await computeMedicationState(req.params.medicationId);
    res.json(state);
  } catch (err: unknown) {
    next(err);
  }
});

router.get('/household/:householdMemberId', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const meds = await MedicationService.getMedicationsForHousehold(req.params.householdMemberId);
    const withState = await Promise.all(meds.map(async (m) => ({ ...m, state: await computeMedicationState(m.id) })));
    res.json(withState);
  } catch (err: unknown) {
    next(err);
  }
});

router.post('/:medicationId/dose-change', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { newDose } = req.body;
    if (!newDose) {
      res.status(400).json({ error: 'newDose is required' });
      return;
    }

    const event = await appendEvent({
      medicationId: req.params.medicationId,
      eventType: EVENT_TYPES.DOSE_CHANGED,
      payload: { newDose },
      source: req.user!.role,
      sourceUserId: req.user!.id,
    });
    res.status(201).json({ event });
  } catch (err: unknown) {
    next(err);
  }
});

export default router;

export {};
