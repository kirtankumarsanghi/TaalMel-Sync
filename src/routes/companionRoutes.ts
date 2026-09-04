// @ts-nocheck - Temporary workaround to clear IDE ghost errors for old Prisma types
import express, { Request, Response, NextFunction } from 'express';
import { requireAuth } from '../middleware/authMiddleware';
import { computeMedicationState, DimensionState } from '../engines/medicationStateEngine';
import { getEventsForHouseholdMember } from '../events/eventStore';
import { checkRefillWindow } from '../engines/triggerEngine';
import { listOpenCasesForHouseholdMember } from '../engines/caseLifecycle';
import { HouseholdService } from '../services/householdService';

const router = express.Router();
router.use(requireAuth);

router.get('/household/:householdMemberId/today', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const meds = await HouseholdService.getMedicationsForMember(req.params.householdMemberId);
    const today = await Promise.all(meds.map(async (m) => {
      const state = await computeMedicationState(m.id);
      return {
        medicationId: m.id,
        name: m.nameGeneric || m.nameRaw,
        dose: state.currentDose,
        confirmedStatus: (state.dimensions as Record<string, DimensionState>).CONFIRMED_STATUS?.status,
        reportedTaking: (state.dimensions as Record<string, DimensionState>).REPORTED_TAKING?.status,
      };
    }));
    res.json({ date: new Date().toISOString().slice(0, 10), medications: today });
  } catch (err) {
    next(err);
  }
});

router.get('/household/:householdMemberId/changes', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const sinceDays = Number(req.query.sinceDays) || 90;
    const sinceDate = new Date(Date.now() - sinceDays * 24 * 60 * 60 * 1000);

    const allEvents = await getEventsForHouseholdMember(req.params.householdMemberId);
    const events = allEvents.filter(e => e.occurredAt >= sinceDate);

    const relevant = events.filter((e) =>
      ['DoseChanged', 'MedicationConfirmed', 'PrescriptionUploaded', 'MedicationExtracted', 'CaseResolved'].includes(
        e.eventType
      )
    );

    const openCases = await listOpenCasesForHouseholdMember(req.params.householdMemberId);

    res.json({
      sinceDate: sinceDate.toISOString(),
      changes: relevant.map((e) => ({ date: e.occurredAt, type: e.eventType, detail: e.payload })),
      unresolvedCount: openCases.length,
    });
  } catch (err) {
    next(err);
  }
});

router.post('/household/:householdMemberId/questions', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { medicationId, questionText, raisedBy } = req.body;
    if (!questionText) {
      res.status(400).json({ error: 'questionText is required' });
      return;
    }

    const { question, relevantInstruction } = await HouseholdService.createDoctorQuestion({
      medicationId,
      householdMemberId: req.params.householdMemberId,
      questionText,
      raisedBy: raisedBy || req.user!.role,
    });

    res.status(201).json({
      id: question.id,
      saved: true,
      relevantInstruction,
      note: 'Saved to your Ask My Doctor list. Taalmel does not answer clinical questions.',
    });
  } catch (err) {
    next(err);
  }
});

router.get('/household/:householdMemberId/questions', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const status = (req.query.status as string) || 'PENDING';
    const rows = await HouseholdService.getDoctorQuestions(req.params.householdMemberId, status);
    res.json(rows);
  } catch (err) {
    next(err);
  }
});

router.post('/questions/:questionId/discussed', async (req: Request, res: Response, next: NextFunction) => {
  try {
    await HouseholdService.markQuestionDiscussed(req.params.questionId);
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
});

router.get('/household/:householdMemberId/dashboard', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const meds = await HouseholdService.getMedicationsForMember(req.params.householdMemberId);
    let confirmed = 0;
    let needsVerification = 0;
    const refillAlerts: Record<string, unknown>[] = [];

    for (const m of meds) {
      const state = await computeMedicationState(m.id);
      const confirmedDim = (state.dimensions as Record<string, DimensionState>).CONFIRMED_STATUS;
      if (confirmedDim && confirmedDim.status && !confirmedDim.stale) {
        confirmed += 1;
      } else {
        needsVerification += 1;
      }

      const refill = await checkRefillWindow(m.id);
      if (refill) refillAlerts.push({ name: m.nameGeneric || m.nameRaw, ...refill });
    }

    const openCases = await listOpenCasesForHouseholdMember(req.params.householdMemberId);

    res.json({
      totalMedications: meds.length,
      confirmed,
      needsVerification,
      openIssues: openCases.length,
      refillAlerts,
    });
  } catch (err) {
    next(err);
  }
});

router.get('/household/:householdMemberId/record-completeness', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const meds = await HouseholdService.getMedicationsForMember(req.params.householdMemberId);
    if (meds.length === 0) {
      res.json({ medications: 0, completenessPercent: null });
      return;
    }

    let totalChecks = 0;
    let passedChecks = 0;
    const perDimension = ['PRESCRIBED', 'AVAILABLE', 'REPORTED_TAKING', 'CONFIRMED_STATUS'];


    let openConflicts = 0;

    for (const m of meds) {
      const state = await computeMedicationState(m.id);
      for (const dim of perDimension) {
        totalChecks += 1;
        const d = (state.dimensions as Record<string, DimensionState>)[dim];
        if (d && d.status && !d.stale) passedChecks += 1;
      }
      
      const cases = await listOpenCasesForHouseholdMember(m.householdMemberId);
      openConflicts += cases.length;
    }

    res.json({
      medications: meds.length,
      completenessPercent: Math.round((passedChecks / totalChecks) * 100),
      openConflicts,
      disclaimer: 'This measures the completeness of Taalmel\u2019s record, not the patient\u2019s health.',
    });
  } catch (err) {
    next(err);
  }
});

export default router;

export {};
