import express, { Request, Response, NextFunction } from 'express';
import { MedicationService } from '../services/medicationService';
import { requireAuth } from '../middleware/authMiddleware';
import { checkInteractions } from '../services/safetyRulesService';
import { computeMedicationState } from '../engines/medicationStateEngine';

const router = express.Router();
router.use(requireAuth);

router.get('/household/:householdMemberId/safety-check', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const meds = await MedicationService.getMedicationsForHousehold(req.params.householdMemberId);

    const confirmedGenericNames: string[] = [];

    for (const m of meds) {
      const state = await computeMedicationState(m.id);
      const confirmedStatus = (state.dimensions as any).CONFIRMED_STATUS;
      if (confirmedStatus && confirmedStatus.status === 'ACTIVE') {
        confirmedGenericNames.push(m.nameGeneric || m.nameRaw);
      }
    }

    if (confirmedGenericNames.length < 2) {
      res.json({
        pairs: [],
        uncovered: confirmedGenericNames,
        disclaimer: 'Fewer than two confirmed-active medications \u2014 no interaction pairs to check.',
      });
      return;
    }

    res.json(checkInteractions(confirmedGenericNames));
  } catch (err: unknown) {
    next(err);
  }
});

router.get('/medications/:medicationId/explain', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const med = await MedicationService.getMedicationById(req.params.medicationId);
    if (!med) {
      res.status(404).json({ error: 'Medication not found' });
      return;
    }

    res.json({
      originalInstruction: {
        text: `${med.nameRaw}${med.doseRaw ? ` \u2014 ${med.doseRaw}` : ''}`,
        source: 'Original prescription (verbatim)',
      },
      plainLanguage: {
        whatItsFor: `[Stub] Plain-language explanation of why ${med.nameGeneric || med.nameRaw} is prescribed would go here \u2014 wire an LLM call to generate this, always alongside (never replacing) the original instruction above.`,
        howToTake: '[Stub] Plain-language dosing guidance would go here.',
      },
      note: 'The app is never the source of a medical instruction, only a translator of one shown alongside it.',
    });
  } catch (err: unknown) {
    next(err);
  }
});

export default router;

export {};
