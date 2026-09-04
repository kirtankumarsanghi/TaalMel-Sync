import { EVENT_TYPES } from '../events/eventTypes';
import { appendEvent } from '../events/eventStore';
import { prisma } from '../db/client';

const VALID_TRANSITIONS: Record<string, string[]> = {
  OPEN: ['AWAITING_INFO', 'RESOLVED', 'STILL_UNCERTAIN'],
  AWAITING_INFO: ['RESOLVED', 'STILL_UNCERTAIN', 'OPEN'],
  RESOLVED: [],
  STILL_UNCERTAIN: ['OPEN', 'AWAITING_INFO'],
};

export async function getCase(caseId: string) {
  return prisma.case.findUnique({ where: { id: caseId } });
}

export async function openCase({ medicationId, triggerEventId }: { medicationId: string; triggerEventId?: string }) {
  const kase = await prisma.case.create({
    data: {
      medicationId,
      triggerEventId,
      status: 'OPEN'
    }
  });
  return kase;
}

export async function assignAction({ caseId, medicationId, actionDescription, source, sourceUserId }: { caseId: string, medicationId: string, actionDescription: string, source: string, sourceUserId?: string | null }) {
  const current = await getCase(caseId);
  if (!current) throw new Error(`Case not found: ${caseId}`);

  const event = await appendEvent({
    medicationId,
    eventType: EVENT_TYPES.ACTION_ASSIGNED,
    payload: { caseId, actionDescription, medicationId },
    source,
    sourceUserId,
  });

  const updatedCase = await prisma.case.update({
    where: { id: caseId },
    data: {
      actionTaken: actionDescription,
      status: current.status === 'OPEN' ? 'AWAITING_INFO' : current.status
    }
  });

  return { event, case: updatedCase };
}

export async function resolveCase({ caseId, medicationId, outcome, resolutionNote, source, sourceUserId }: { caseId: string, medicationId: string, outcome: string, resolutionNote?: string | null, source: string, sourceUserId?: string | null }) {
  if (!['RESOLVED', 'STILL_UNCERTAIN'].includes(outcome)) {
    throw new Error(`Invalid case outcome: ${outcome}`);
  }
  const current = await getCase(caseId);
  if (!current) throw new Error(`Case not found: ${caseId}`);
  if (!VALID_TRANSITIONS[current.status].includes(outcome)) {
    throw new Error(`Cannot transition case from ${current.status} to ${outcome}`);
  }

  const event = await appendEvent({
    medicationId,
    eventType: EVENT_TYPES.CASE_RESOLVED,
    payload: { caseId, outcome, medicationId, resolutionNote: resolutionNote || undefined },
    source,
    sourceUserId,
  });

  const updatedCase = await prisma.case.update({
    where: { id: caseId },
    data: {
      status: outcome,
      resolutionNote: resolutionNote || null,
      resolvedAt: outcome === 'RESOLVED' ? new Date() : current.resolvedAt
    }
  });

  return { event, case: updatedCase };
}

export async function listCasesForMedication(medicationId: string) {
  return prisma.case.findMany({
    where: { medicationId },
    orderBy: { openedAt: 'desc' }
  });
}

export async function listOpenCasesForHouseholdMember(householdMemberId: string) {
  return prisma.case.findMany({
    where: {
      medication: { householdMemberId },
      status: { in: ['OPEN', 'AWAITING_INFO'] }
    },
    orderBy: { openedAt: 'desc' }
  });
}

export async function detectRepeatedReasonPattern(medicationId: string, { threshold = 3 } = {}) {
  const groups = await prisma.case.groupBy({
    by: ['reasonCode'],
    where: {
      medicationId,
      reasonCode: { not: null }
    },
    _count: {
      reasonCode: true
    },
    having: {
      reasonCode: {
        _count: {
          gte: threshold
        }
      }
    }
  });

  return groups.map((g) => ({
    reasonCode: g.reasonCode!,
    occurrences: g._count.reasonCode,
    message: `Repeated ${g.reasonCode!.toLowerCase().replace(/_/g, ' ')} — follow-up recommended.`,
  }));
}

export {};
