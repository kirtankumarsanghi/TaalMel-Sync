import express, { Request, Response, NextFunction } from 'express';
import { requireAuth } from '../middleware/authMiddleware';
import { buildDoctorExport, buildMinimalInfoCard } from '../services/doctorExportService';

const router = express.Router();
router.use(requireAuth);

router.get('/household/:householdMemberId/doctor-export', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const data = await buildDoctorExport(req.params.householdMemberId);
    res.json(data);
  } catch (err) {
    next(err);
  }
});

router.get('/household/:householdMemberId/info-card', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const data = await buildMinimalInfoCard(req.params.householdMemberId);
    res.json(data);
  } catch (err) {
    next(err);
  }
});

export default router;

export {};
