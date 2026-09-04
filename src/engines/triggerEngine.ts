import { EVENT_TYPES } from '../events/eventTypes';
import { computeMedicationState } from './medicationStateEngine';
import { detectAndOpenConflictCases } from './conflictDetection';
import { detectRepeatedReasonPattern } from './caseLifecycle';

const REFILL_WINDOW_DAYS_DEFAULT = 30;

export async function evaluateTriggers(event: { medicationId: string; eventType: string; payload: string }) {
  const notifications: Record<string, unknown>[] = [];
  const medicationId = event.medicationId;

  switch (event.eventType) {
    case EVENT_TYPES.PRESCRIPTION_UPLOADED:
    case EVENT_TYPES.MEDICATION_EXTRACTED:
      notifications.push({
        trigger: 'NEW_PRESCRIPTION_UPLOADED',
        message: 'New prescription uploaded — checking whether it changes the current medication list.',
        medicationId,
      });
      break;

    case EVENT_TYPES.MEDICATION_REPORTED:
    case EVENT_TYPES.AVAILABILITY_OBSERVED:
    case EVENT_TYPES.MEDICATION_CONFIRMED: {
      const opened = await detectAndOpenConflictCases(medicationId);
      for (const { caseId, conflict } of opened) {
        notifications.push({
          trigger: 'EVIDENCE_CONFLICT',
          message: conflict ? String((conflict as Record<string, unknown>).suggestedQuestion) : '',
          caseId,
          medicationId,
          conflictType: conflict ? String((conflict as Record<string, unknown>).type) : '',
        });
      }
      break;
    }

    default:
      break;
  }

  if (event.eventType === EVENT_TYPES.REASON_RECORDED) {
    const patterns = await detectRepeatedReasonPattern(medicationId);
    for (const p of patterns) {
      notifications.push({
        trigger: 'REPEATED_REASON_PATTERN',
        message: p.message,
        medicationId,
        reasonCode: p.reasonCode,
        occurrences: p.occurrences,
      });
    }
  }

  return notifications;
}

export async function checkRefillWindow(medicationId: string, { refillWindowDays = REFILL_WINDOW_DAYS_DEFAULT } = {}) {
  const state = await computeMedicationState(medicationId);
  const available = (state.dimensions as any).AVAILABLE;

  if (!available || !available.lastVerified) {
    return null; 
  }

  const nearlyEmpty = available.quantityNote === 'nearly empty';
  const windowElapsed = available.ageDays >= refillWindowDays;

  if (nearlyEmpty || windowElapsed) {
    return {
      trigger: windowElapsed ? 'REFILL_WINDOW_ELAPSED' : 'REFILL_LIKELY_NEEDED_SOON',
      message: windowElapsed
        ? 'Expected refill window has passed with no confirmation — please check availability.'
        : 'Refill may be needed soon.',
      medicationId,
      lastVerified: available.lastVerified,
      ageDays: available.ageDays,
    };
  }

  return null;
}

export {};
