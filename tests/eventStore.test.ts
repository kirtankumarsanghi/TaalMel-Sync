import { describe, it, expect, beforeEach, afterAll, beforeAll } from 'vitest';
import { prisma } from '../src/db/client';
import { appendEvent, getEventsForPatient, getEventsForMedication } from '../src/events/eventStore';
import { EVENT_TYPES, SOURCES } from '../src/events/eventTypes';
import { v4 as uuidv4 } from 'uuid';

describe('Event Store (Phase 4)', () => {
  let householdMemberId: string;
  let medicationId: string;
  let userId: string;

  beforeAll(async () => {
    // Setup necessary basic records for foreign keys
    const user = await prisma.user.create({
      data: {
        role: 'patient',
        name: 'Event Test User',
        passwordHash: 'dummy'
      }
    });
    userId = user.id;

    const household = await prisma.household.create({
      data: {
        name: 'Event Test Household',
        createdBy: user.id
      }
    });

    const member = await prisma.householdMember.create({
      data: {
        householdId: household.id,
        displayName: 'Event Patient',
        role: 'member'
      }
    });
    householdMemberId = member.id;

    const med = await prisma.medication.create({
      data: {
        householdMemberId,
        nameRaw: 'Test Med 100mg'
      }
    });
    medicationId = med.id;
  });

  afterAll(async () => {
    // Cleanup
    await prisma.case.deleteMany({});
    await prisma.event.deleteMany({});
    await prisma.medication.deleteMany({});
    await prisma.householdMember.deleteMany({});
    await prisma.household.deleteMany({});
    await prisma.user.deleteMany({ where: { id: userId } });
  });

  it('successfully appends a valid event and retrieves it', async () => {
    const payload = {
      medicationId,
      reportedByUserId: userId,
      reportType: 'TAKING',
      notes: 'Started today'
    };

    const event = await appendEvent({
      householdMemberId,
      medicationId,
      eventType: EVENT_TYPES.MEDICATION_REPORTED,
      payload,
      source: SOURCES.PATIENT,
      sourceUserId: userId
    });

    expect(event.id).toBeDefined();
    expect(event.eventType).toBe(EVENT_TYPES.MEDICATION_REPORTED);
    expect(event.payload).toEqual(payload);

    // Retrieve via patient
    const patientEvents = await getEventsForPatient(householdMemberId);
    expect(patientEvents.some(e => e.id === event.id)).toBe(true);

    // Retrieve via medication
    const medEvents = await getEventsForMedication(medicationId);
    expect(medEvents.some(e => e.id === event.id)).toBe(true);
  });

  it('rejects unknown event types', async () => {
    await expect(
      appendEvent({
        householdMemberId,
        eventType: 'NON_EXISTENT_TYPE',
        payload: {},
        source: SOURCES.SYSTEM
      })
    ).rejects.toThrow('Unknown event type: NON_EXISTENT_TYPE');
  });

  it('rejects invalid payload schemas', async () => {
    await expect(
      appendEvent({
        householdMemberId,
        eventType: EVENT_TYPES.PRESCRIPTION_UPLOADED,
        payload: {
          prescriptionId: 'not-a-uuid', // Invalid UUID
          fileStorageKey: 123 // Should be string
        },
        source: SOURCES.SYSTEM
      })
    ).rejects.toThrow(); // ZodError
  });

  it('handles idempotency gracefully', async () => {
    const idempotencyKey = uuidv4();
    const payload = {
      prescriptionId: uuidv4(),
      fileStorageKey: 's3://test',
      uploadedByUserId: userId
    };

    // First insertion
    const firstEvent = await appendEvent({
      householdMemberId,
      eventType: EVENT_TYPES.PRESCRIPTION_UPLOADED,
      payload,
      source: SOURCES.PATIENT,
      idempotencyKey
    });

    // Second insertion with SAME idempotency key should return the existing event
    const secondEvent = await appendEvent({
      householdMemberId,
      eventType: EVENT_TYPES.PRESCRIPTION_UPLOADED,
      payload: { ...payload, fileStorageKey: 'different' }, // even with diff payload
      source: SOURCES.PATIENT,
      idempotencyKey
    });

    expect(secondEvent.id).toBe(firstEvent.id);
    expect(secondEvent.payload.fileStorageKey).toBe('s3://test'); // Got original payload

    // Third insertion with DIFFERENT idempotency key should create new
    const thirdEvent = await appendEvent({
      householdMemberId,
      eventType: EVENT_TYPES.PRESCRIPTION_UPLOADED,
      payload,
      source: SOURCES.PATIENT,
      idempotencyKey: uuidv4() // new key
    });

    expect(thirdEvent.id).not.toBe(firstEvent.id);
  });

});
