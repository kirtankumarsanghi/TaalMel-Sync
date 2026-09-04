import { EVENT_TYPES } from '../events/eventTypes';
import { appendEvent } from '../events/eventStore';
import { prisma } from '../db/client';

export const REASON_CODES = {
  CONFUSED_ABOUT_DOSE: 'CONFUSED_ABOUT_DOSE',
  RAN_OUT: 'RAN_OUT',
  FORGOT: 'FORGOT',
  COULD_NOT_AFFORD: 'COULD_NOT_AFFORD',
  DOCTOR_TOLD_TO_STOP: 'DOCTOR_TOLD_TO_STOP',
  SIDE_EFFECT: 'SIDE_EFFECT',
  PATIENT_DECLINED: 'PATIENT_DECLINED',
} as const;

export const REASON_RESPONSES = {
  [REASON_CODES.CONFUSED_ABOUT_DOSE]: {
    action: 'SHOW_INSTRUCTION_SIDE_BY_SIDE',
    description: "Show the original instruction + a plain-language explanation + its source, side by side, plus 'confirm with your doctor/pharmacist if unclear.'",
    closesCase: false,
  },
  [REASON_CODES.RAN_OUT]: {
    action: 'OPEN_CASE_NOTIFY_CAREGIVER',
    description: 'Opens a case, notifies caregiver, tracked to resolution.',
    closesCase: false,
  },
  [REASON_CODES.FORGOT]: {
    action: 'INCREASE_REMINDERS',
    description: 'Increases reminder frequency / caregiver-shared reminders.',
    closesCase: true,
  },
  [REASON_CODES.COULD_NOT_AFFORD]: {
    action: 'SHOW_AFFORDABILITY_RESOURCES',
    description: 'Shows named public affordability resources, then explicitly prompts discussing alternatives with a doctor/pharmacist. Never ends at \'here is a cheaper option.\'',
    closesCase: false,
  },
  [REASON_CODES.DOCTOR_TOLD_TO_STOP]: {
    action: 'MARK_DISCONTINUED_CONFIRMED',
    description: 'Marks discontinued-confirmed, closes case.',
    closesCase: true,
  },
  [REASON_CODES.SIDE_EFFECT]: {
    action: 'ROUTE_TO_PROFESSIONAL_FOLLOWUP',
    description: 'Recorded as-is, with no symptom interpretation or diagnosis — routed as \'follow-up with a healthcare professional recommended.\'',
    closesCase: false,
  },
  [REASON_CODES.PATIENT_DECLINED]: {
    action: 'ROUTE_FOR_AWARENESS_NO_OVERRIDE',
    description: 'Recorded without judgment — routed for caregiver awareness and, if relevant, a doctor conversation. Never overridden or pressured.',
    closesCase: false,
  },
} as const;

export interface RecordReasonParams {
  caseId: string;
  medicationId: string;
  reasonCode: keyof typeof REASON_CODES;
  freeTextNote?: string | null;
  source: string;
  sourceUserId?: string | null;
}

export async function recordReason({ caseId, medicationId, reasonCode, freeTextNote, source, sourceUserId }: RecordReasonParams) {
  if (!REASON_RESPONSES[reasonCode]) {
    throw new Error(`Unknown reason code: ${reasonCode}`);
  }

  const event = await appendEvent({
    medicationId,
    eventType: EVENT_TYPES.REASON_RECORDED,
    payload: { caseId, reasonCode, medicationId, freeTextNote: freeTextNote || null },
    source,
    sourceUserId,
  });

  await prisma.case.update({
    where: { id: caseId },
    data: { reasonCode }
  });

  return { event, responsePolicy: REASON_RESPONSES[reasonCode] };
}

export {};
