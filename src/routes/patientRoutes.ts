import express, { Request, Response, NextFunction } from 'express';
import { requireAuth } from '../middleware/authMiddleware';
import { requirePatientAccess } from '../middleware/authorize';
import { validate, validateParams } from '../middleware/validate';
import { CreatePatientSchema, UpdatePatientSchema, PatientIdParamSchema } from '../schemas/patient';
import { PatientService } from '../services/patientService';

const router = express.Router();
router.use(requireAuth);

// POST /api/patients — Create a new patient
router.post(
  '/',
  validate(CreatePatientSchema),
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const userId = req.user!.sub || req.user!.id!;
      const result = await PatientService.createPatient({
        ...req.body,
        userId,
      });
      res.status(201).json(result);
    } catch (err: any) {
      if (err.status) {
        res.status(err.status).json({ error: err.message });
        return;
      }
      next(err);
    }
  },
);

// GET /api/patients — List all patients the user can access
router.get('/', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const userId = req.user!.sub || req.user!.id!;
    const patients = await PatientService.getPatients(userId);
    res.json({ patients });
  } catch (err) {
    next(err);
  }
});

// GET /api/patients/:id — Get patient by ID (full auth chain)
router.get(
  '/:id',
  validateParams(PatientIdParamSchema),
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const userId = req.user!.sub || req.user!.id!;
      const patient = await PatientService.getPatientById(req.params.id, userId);

      if (!patient) {
        res.status(403).json({ error: 'Not authorized to access this patient' });
        return;
      }

      res.json({ patient });
    } catch (err) {
      next(err);
    }
  },
);

// PATCH /api/patients/:id — Update patient details
router.patch(
  '/:id',
  validateParams(PatientIdParamSchema),
  validate(UpdatePatientSchema),
  async (req: Request, res: Response, next: NextFunction) => {
    try {
      const userId = req.user!.sub || req.user!.id!;
      const updated = await PatientService.updatePatient(req.params.id, userId, req.body);
      res.json({ patient: updated });
    } catch (err: any) {
      if (err.status) {
        res.status(err.status).json({ error: err.message });
        return;
      }
      next(err);
    }
  },
);

import { PrescriptionService } from '../services/prescriptionService';

// GET /api/patients/:id/prescriptions
router.get('/:id/prescriptions', requireAuth, requirePatientAccess('id'), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const patient = (req as any).patient;
    const prescriptions = await PrescriptionService.getPrescriptionsForPatient(patient.householdMemberId);
    res.json(prescriptions);
  } catch (err) {
    next(err);
  }
});

export default router;
