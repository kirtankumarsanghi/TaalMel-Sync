import { Router, Request, Response, NextFunction } from 'express';
import { requireAuth } from '../middleware/authMiddleware';
import { validate, validateParams } from '../middleware/validate';
import {
  normalizationPreviewSchema,
  verifyNormalizationSchema,
  medicationParamSchema,
} from '../schemas/normalization';
import { MedicationService } from '../services/medicationService';
import { normalizeMedication, NormalizationInput } from '../services/normalizationService';

const router = Router();
router.use(requireAuth);

/**
 * GET /api/medications/needs-review/:householdMemberId
 * List medications needing normalization review for a patient.
 */
router.get(
  '/needs-review/:householdMemberId',
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { householdMemberId } = req.params;
      const medications = await MedicationService.getMedicationsNeedingReview(householdMemberId);
      res.json({
        count: medications.length,
        medications,
      });
    } catch (err) {
      next(err);
    }
  }
);

/**
 * POST /api/medications/:id/verify-normalization
 * Manually verify/correct a medication's normalization.
 */
router.post(
  '/:id/verify-normalization',
  validateParams(medicationParamSchema),
  validate(verifyNormalizationSchema),
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { id } = req.params;
      const userId = req.user!.id || req.user!.sub;
      const medication = await MedicationService.manuallyVerifyNormalization(
        id,
        req.body,
        userId,
      );
      res.json(medication);
    } catch (err) {
      next(err);
    }
  }
);

/**
 * POST /api/medications/normalize-preview
 * Preview normalization result without saving.
 * Useful for UI to show what the system would produce.
 */
router.post(
  '/normalize-preview',
  validate(normalizationPreviewSchema),
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const input: NormalizationInput = req.body;
      const result = normalizeMedication(input);

      res.json({
        input: {
          nameRaw: input.nameRaw,
          dosage: input.dosage || null,
          frequency: input.frequency || null,
        },
        result: {
          nameGeneric: result.nameGeneric,
          nameBrand: result.nameBrand,
          strength: result.strength,
          dosageForm: result.dosageForm,
          frequency: result.frequency,
          activeIngredient: result.activeIngredient,
          category: result.category,
          method: result.method,
          confidence: result.confidence,
          status: result.status,
        },
      });
    } catch (err) {
      next(err);
    }
  }
);

export default router;
