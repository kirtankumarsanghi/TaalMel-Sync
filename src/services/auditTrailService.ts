import { getEventsForMedication } from '../events/eventStore';
import { prisma } from '../db/client';

export async function logAudit(action: string, entityType: string, entityId: string, userId: string | null, details: Record<string, unknown>) {
  await prisma.auditRecord.create({
    data: {
      action,
      userId,
      details: typeof details === 'string' ? JSON.stringify({ entityId, entityType, message: details }) : JSON.stringify({ entityId, entityType, ...details })
    }
  });
}

export async function getAuditTrailForEntity(entityType: string, entityId: string) {
  const records = await prisma.auditRecord.findMany({
    orderBy: { createdAt: 'asc' }
  });
  // Filter in memory since Prisma schema doesn't have entityType/entityId
  return records.map(r => ({ ...r, details: typeof r.details === 'string' ? JSON.parse(r.details) : r.details }))
    .filter(r => r.details && r.details.entityType === entityType && r.details.entityId === entityId);
}

export async function getMedicationHistory(medicationId: string) {
  const events = await getEventsForMedication(medicationId);
  return events.map((e) => ({
    date: e.occurredAt,
    eventType: e.eventType,
    summary: describeEvent(e),
    source: e.source,
  }));
}

function describeEvent(e: { eventType: string; payload: string; source: string }) {
  const payload = e.payload as any;
  switch (e.eventType) {
    case 'PrescriptionUploaded':
      return `Prescribed by ${payload.doctor || 'doctor'}${payload.dose ? ` (${payload.dose})` : ''}`;
    case 'MedicationExtracted':
      return 'Medication extracted from uploaded prescription';
    case 'DoseChanged':
      return `Dose changed \u2192 ${payload.newDose}`;
    case 'MedicationReported':
      return payload.taking ? 'Patient confirmed taking' : `Patient reported stopped${payload.reason ? ` (${payload.reason})` : ''}`;
    case 'AvailabilityObserved':
      return `Availability check: ${payload.present ? 'present' : 'not found'}${payload.quantityNote ? ` \u2014 ${payload.quantityNote}` : ''}`;
    case 'MedicationConfirmed':
      return `${e.source === 'doctor' ? 'Doctor' : 'Caregiver'} confirmed status: ${payload.status}`;
    case 'ConflictDetected':
      return `Conflict opened (${payload.description})`;
    case 'ReasonRecorded':
      return `Reason recorded: ${payload.reasonCode}`;
    case 'ActionAssigned':
      return `Action assigned: ${payload.actionDescription}`;
    case 'CaseResolved':
      return `Resolved: ${payload.outcome}${payload.resolutionNote ? ` (${payload.resolutionNote})` : ''}`;
    default:
      return e.eventType;
  }
}

export async function explainCase(caseId: string) {
  const kase = await prisma.case.findUnique({
    where: { id: caseId },
    include: {
      triggerEvent: true
    }
  });
  if (!kase) throw new Error(`Case not found: ${caseId}`);

  let triggerEventPayload: Record<string, unknown> = {};
  if (kase.triggerEvent && kase.triggerEvent.payload) {
    triggerEventPayload = typeof kase.triggerEvent.payload === 'string' ? JSON.parse(kase.triggerEvent.payload) : kase.triggerEvent.payload;
  }

  return {
    what: 'Potential medication discrepancy',
    why: triggerEventPayload?.description || 'Evidence gap detected',
    source: kase.triggerEvent ? `Event recorded ${kase.triggerEvent.occurredAt} (${kase.triggerEvent.source})` : 'Unknown',
    status: kase.status,
    action: kase.actionTaken || 'Confirm the underlying facts before proceeding',
    taalmelDoesNot: 'change or stop any medication',
  };
}

export {};
