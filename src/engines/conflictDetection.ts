import { EVIDENCE_DIMENSIONS, EVENT_TYPES } from '../events/eventTypes';
import { computeMedicationState } from './medicationStateEngine';
import { appendEvent } from '../events/eventStore';
import { prisma } from '../db/client';

export async function detectConflicts(medicationId: string) {
  const state = await computeMedicationState(medicationId);
  const d = state.dimensions as Record<string, any>;
  const conflicts: Record<string, unknown>[] = [];

  const prescribedActive = d[EVIDENCE_DIMENSIONS.PRESCRIBED]?.status === 'ACTIVE';
  const confirmedDiscontinued = d[EVIDENCE_DIMENSIONS.CONFIRMED_STATUS]?.status === 'DISCONTINUED';
  const reportedStopped = d[EVIDENCE_DIMENSIONS.REPORTED_TAKING]?.status === 'STOPPED';
  const availablePresent = d[EVIDENCE_DIMENSIONS.AVAILABLE]?.status === 'PRESENT';
  const availableAbsent = d[EVIDENCE_DIMENSIONS.AVAILABLE]?.status === 'ABSENT';

  if (prescribedActive && reportedStopped && !confirmedDiscontinued) {
    conflicts.push({
      type: 'PRESCRIPTION_VS_REPORT',
      description: 'Prescription says Active; patient reported Stopped',
      dimensionsInvolved: [EVIDENCE_DIMENSIONS.PRESCRIBED, EVIDENCE_DIMENSIONS.REPORTED_TAKING],
      suggestedQuestion: 'Who told you to stop, and when?',
    });
  }

  if (d[EVIDENCE_DIMENSIONS.REPORTED_TAKING]?.status === 'TAKING' && availableAbsent) {
    conflicts.push({
      type: 'REPORT_VS_AVAILABILITY',
      description: 'Patient reports taking it; none was found available',
      dimensionsInvolved: [EVIDENCE_DIMENSIONS.REPORTED_TAKING, EVIDENCE_DIMENSIONS.AVAILABLE],
      suggestedQuestion: 'Is there a new strip we haven\u2019t recorded yet, or has this run out?',
    });
  }

  if (reportedStopped && availablePresent && !confirmedDiscontinued) {
    conflicts.push({
      type: 'STOPPED_BUT_UNEXPLAINED',
      description: 'Patient reported stopping; medicine is still available; no confirmed discontinuation',
      dimensionsInvolved: [EVIDENCE_DIMENSIONS.REPORTED_TAKING, EVIDENCE_DIMENSIONS.CONFIRMED_STATUS],
      suggestedQuestion: 'Why did you stop taking this?',
    });
  }

  return conflicts;
}

export async function detectAndOpenConflictCases(medicationId: string) {
  const conflicts = await detectConflicts(medicationId);
  const openedCases: Record<string, unknown>[] = [];

  for (const conflict of conflicts) {
    const conflictEvent = await appendEvent({
      medicationId,
      eventType: EVENT_TYPES.CONFLICT_DETECTED,
      payload: conflict,
      source: 'system',
    });

    const kase = await prisma.case.create({
      data: {
        medicationId,
        triggerEventId: conflictEvent.id,
        status: 'OPEN',
      }
    });

    openedCases.push({ caseId: kase.id, conflict, triggerEventId: conflictEvent.id });
  }

  return openedCases;
}

export {};
