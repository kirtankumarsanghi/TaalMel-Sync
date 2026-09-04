import { test, expect, beforeAll, afterAll } from 'vitest';
import { v4 as uuid } from 'uuid';
import { appendEvent } from '../src/events/eventStore';
import { EVENT_TYPES, SOURCES } from '../src/events/eventTypes';
import { computeMedicationState } from '../src/engines/medicationStateEngine';
import { detectConflicts } from '../src/engines/conflictDetection';
import { recordReason, REASON_CODES } from '../src/engines/reasonClassification';
import { openCase, resolveCase } from '../src/engines/caseLifecycle';
import { prisma } from '../src/db/client';
import argon2 from 'argon2';

beforeAll(async () => {
  // Prisma will connect automatically
});

afterAll(async () => {
  await prisma.$disconnect();
});

async function makeMedication() {
  const creatorId = uuid();
  await prisma.user.create({
    data: {
      id: creatorId,
      role: 'caregiver',
      name: 'Test Caregiver',
      phone: `+1555${Math.floor(1000000 + Math.random() * 9000000)}`,
      passwordHash: await argon2.hash('x'),
    }
  });

  const household = await prisma.household.create({
    data: {
      name: 'Test HH',
      createdBy: creatorId
    }
  });

  const member = await prisma.householdMember.create({
    data: {
      householdId: household.id,
      displayName: 'Test Patient',
      isPatient: true
    }
  });

  const medication = await prisma.medication.create({
    data: {
      householdMemberId: member.id,
      nameRaw: 'Metformin',
      nameGeneric: 'Metformin'
    }
  });

  return medication.id;
}

test('medication state engine derives PRESCRIBED from an upload event', async () => {
  const medicationId = await makeMedication();
  await appendEvent({
    medicationId,
    eventType: EVENT_TYPES.PRESCRIPTION_UPLOADED,
    payload: { doctor: 'Dr. A', dose: '500mg', prescriptionId: uuid(), fileStorageKey: 's3/test', uploadedByUserId: uuid() },
    source: SOURCES.CAREGIVER,
  });
  const state = await computeMedicationState(medicationId);
  expect((state.dimensions as any).PRESCRIBED.status).toBe('ACTIVE');
  expect(state.currentDose).toBe('500mg');
});

test('conflict detection fires when prescription active but patient reports stopped', async () => {
  const medicationId = await makeMedication();
  await appendEvent({ medicationId, eventType: EVENT_TYPES.PRESCRIPTION_UPLOADED, payload: { doctor: 'Dr. A', prescriptionId: uuid(), fileStorageKey: 's3/test', uploadedByUserId: uuid() }, source: SOURCES.CAREGIVER });
  await appendEvent({ medicationId, eventType: EVENT_TYPES.MEDICATION_REPORTED, payload: { taking: false, medicationId, reportedByUserId: uuid(), reportType: 'STOPPED' }, source: SOURCES.PATIENT });

  const conflicts = await detectConflicts(medicationId);
  expect(conflicts.some((c) => c.type === 'PRESCRIPTION_VS_REPORT')).toBe(true);
});

test('no conflict once discontinuation is confirmed', async () => {
  const medicationId = await makeMedication();
  await appendEvent({ medicationId, eventType: EVENT_TYPES.PRESCRIPTION_UPLOADED, payload: { doctor: 'Dr. A', prescriptionId: uuid(), fileStorageKey: 's3/test', uploadedByUserId: uuid() }, source: SOURCES.CAREGIVER });
  await appendEvent({ medicationId, eventType: EVENT_TYPES.MEDICATION_REPORTED, payload: { taking: false, medicationId, reportedByUserId: uuid(), reportType: 'STOPPED' }, source: SOURCES.PATIENT });
  await appendEvent({ medicationId, eventType: EVENT_TYPES.MEDICATION_CONFIRMED, payload: { status: 'discontinued', medicationId, confirmedByUserId: uuid(), confirmationMethod: 'doctor_visit' }, source: SOURCES.DOCTOR });

  const conflicts = await detectConflicts(medicationId);
  expect(conflicts.some((c) => c.type === 'PRESCRIPTION_VS_REPORT')).toBe(false);
});

test('case lifecycle: open -> resolve, and cannot re-resolve a resolved case', async () => {
  const medicationId = await makeMedication();
  const kase = await openCase({ medicationId });
  expect(kase.status).toBe('OPEN');

  await recordReason({ caseId: kase.id, medicationId, reasonCode: REASON_CODES.RAN_OUT, source: SOURCES.PATIENT });
  const result = await resolveCase({ caseId: kase.id, medicationId, outcome: 'RESOLVED', source: SOURCES.CAREGIVER });
  expect(result.case.status).toBe('RESOLVED');

  await expect(resolveCase({ caseId: kase.id, medicationId, outcome: 'STILL_UNCERTAIN', source: SOURCES.CAREGIVER })).rejects.toThrow();
});

test('reason classification rejects unknown reason codes', async () => {
  const medicationId = await makeMedication();
  const kase = await openCase({ medicationId });
  await expect(recordReason({ caseId: kase.id, medicationId, reasonCode: 'NOT_A_REAL_REASON' as any, source: SOURCES.PATIENT })).rejects.toThrow();
});
