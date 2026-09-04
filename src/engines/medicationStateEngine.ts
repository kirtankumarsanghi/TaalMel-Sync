import { EVIDENCE_DIMENSIONS, EVENT_TYPES } from '../events/eventTypes';
import { getEventsForMedication } from '../events/eventStore';

export const STALE_THRESHOLD_DAYS = 30;

function daysAgo(date: Date): number {
  const now = Date.now();
  return Math.floor((now - date.getTime()) / (1000 * 60 * 60 * 24));
}

export interface DimensionState {
  status: string | null;
  lastVerified: Date | null;
  ageDays: number | null;
  stale: boolean;
  sourceEventId: string | null;
}

function dimension(status: string | null, lastVerified: Date | null, sourceEventId: string | null): DimensionState {
  if (!lastVerified) {
    return { status: 'UNKNOWN', lastVerified: null, ageDays: null, stale: false, sourceEventId: null };
  }
  const ageDays = daysAgo(lastVerified);
  return {
    status,
    lastVerified,
    ageDays,
    stale: ageDays > STALE_THRESHOLD_DAYS,
    sourceEventId,
  };
}

export async function computeMedicationState(medicationId: string) {
  const events = await getEventsForMedication(medicationId);

  let prescribed: { value: DimensionState; doctor: string | null } | null = null;
  let available: { value: DimensionState; note: string | null; quantityNote: string | null } | null = null;
  let reportedTaking: { value: DimensionState; reasonIfStopped: string | null } | null = null;
  let confirmedStatus: { value: DimensionState; confirmedBy: string | null } | null = null;
  let doseHistory: { dose: string | null; changedAt: Date; eventId: string }[] = [];
  let currentDose: string | null = null;

  for (const evt of events) {
    const payload = (typeof evt.payload === 'string' ? JSON.parse(evt.payload) : evt.payload) as Record<string, unknown>;
    switch (evt.eventType) {
      case EVENT_TYPES.PRESCRIPTION_UPLOADED:
      case EVENT_TYPES.MEDICATION_EXTRACTED:
        prescribed = {
          value: dimension('ACTIVE', evt.occurredAt, evt.id),
          doctor: (payload?.doctor as string) || null,
        };
        if (payload?.dose) currentDose = payload.dose as string;
        break;

      case EVENT_TYPES.DOSE_CHANGED:
        doseHistory.push({ dose: (payload?.newDose as string) || null, changedAt: evt.occurredAt, eventId: evt.id });
        currentDose = (payload?.newDose as string) || currentDose;
        break;

      case EVENT_TYPES.AVAILABILITY_OBSERVED:
        available = {
          value: dimension(payload?.present ? 'PRESENT' : 'ABSENT', evt.occurredAt, evt.id),
          note: (payload?.note as string) || null,
          quantityNote: (payload?.quantityNote as string) || null,
        };
        break;

      case EVENT_TYPES.MEDICATION_REPORTED:
        reportedTaking = {
          value: dimension(payload?.taking ? 'TAKING' : 'STOPPED', evt.occurredAt, evt.id),
          reasonIfStopped: (payload?.reason as string) || null,
        };
        break;

      case EVENT_TYPES.MEDICATION_CONFIRMED:
        confirmedStatus = {
          value: dimension(
            payload?.status === 'discontinued' ? 'DISCONTINUED' : 'ACTIVE',
            evt.occurredAt,
            evt.id
          ),
          confirmedBy: evt.source,
        };
        break;

      default:
        break;
    }
  }

  return {
    medicationId,
    dimensions: {
      [EVIDENCE_DIMENSIONS.PRESCRIBED]: prescribed
        ? { ...prescribed.value, doctor: prescribed.doctor }
        : dimension(null, null, null),
      [EVIDENCE_DIMENSIONS.AVAILABLE]: available
        ? { ...available.value, note: available.note, quantityNote: available.quantityNote }
        : dimension(null, null, null),
      [EVIDENCE_DIMENSIONS.REPORTED_TAKING]: reportedTaking
        ? { ...reportedTaking.value, reasonIfStopped: reportedTaking.reasonIfStopped }
        : dimension(null, null, null),
      [EVIDENCE_DIMENSIONS.CONFIRMED_STATUS]: confirmedStatus
        ? { ...confirmedStatus.value, confirmedBy: confirmedStatus.confirmedBy }
        : dimension(null, null, null),
    },
    currentDose,
    doseHistory,
    eventCount: events.length,
  };
}

export {};
