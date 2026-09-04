import { prisma } from '../db/client';
import { validateEventPayload } from './eventSchemas';
import { Prisma } from '@prisma/client';

export interface AppendEventParams {
  householdMemberId?: string | null;
  medicationId?: string | null;
  eventType: string;
  payload: Record<string, unknown> | string;
  source: string;
  sourceUserId?: string | null;
  idempotencyKey?: string | null;
  occurredAt?: string | Date | null;
  createdBy?: string | null;
}

/**
 * Appends an event to the immutable event log.
 * - Enforces strict schema validation based on eventType.
 * - Handles idempotency: if an idempotencyKey is provided and exists, returns the existing event without throwing.
 */
export async function appendEvent(params: AppendEventParams) {
  const { 
    medicationId = null, 
    eventType, 
    payload, 
    source, 
    sourceUserId = null, 
    idempotencyKey = null, 
    occurredAt = null,
    createdBy = null
  } = params;
  
  let householdMemberId = params.householdMemberId;

  // If householdMemberId isn't provided but medicationId is, fetch it
  if (!householdMemberId && medicationId) {
    const med = await prisma.medication.findUnique({
      where: { id: medicationId },
      select: { householdMemberId: true }
    });
    if (!med) throw new Error('Medication not found for event logging.');
    householdMemberId = med.householdMemberId;
  }

  if (!householdMemberId) {
    throw new Error('householdMemberId is required when appending an event.');
  }

  // 1. Validate Payload strictly
  const parsedPayload = typeof payload === 'string' ? JSON.parse(payload) : payload;
  validateEventPayload(eventType, parsedPayload);

  const now = new Date();
  
  try {
    const event = await prisma.event.create({
      data: {
        householdMemberId,
        medicationId,
        eventType,
        payload: JSON.stringify(parsedPayload),
        source,
        sourceUserId,
        idempotencyKey,
        occurredAt: occurredAt ? new Date(occurredAt) : now,
        createdAt: now,
        createdBy,
      }
    });

    return { 
      ...event, 
      payload: typeof event.payload === 'string' ? JSON.parse(event.payload) : event.payload 
    };
  } catch (error) {
    // 2. Handle Idempotency Constraints (Prisma Unique Constraint Error on idempotencyKey)
    if (error instanceof Prisma.PrismaClientKnownRequestError && error.code === 'P2002') {
      if (idempotencyKey) {
        // Find and return the existing event
        const existingEvent = await prisma.event.findUnique({
          where: { idempotencyKey }
        });
        if (existingEvent) {
          return {
            ...existingEvent,
            payload: typeof existingEvent.payload === 'string' ? JSON.parse(existingEvent.payload) : existingEvent.payload
          };
        }
      }
    }
    throw error;
  }
}

/**
 * Retrieves event history for a specific medication, ordered chronologically.
 */
export async function getEventsForMedication(medicationId: string) {
  const events = await prisma.event.findMany({
    where: { medicationId },
    orderBy: [
      { occurredAt: 'asc' },
      { createdAt: 'asc' }
    ]
  });
  return events.map(e => ({ 
    ...e, 
    payload: typeof e.payload === 'string' ? JSON.parse(e.payload) : e.payload 
  }));
}

/**
 * Retrieves event history for a specific patient (household member), ordered chronologically.
 */
export async function getEventsForPatient(householdMemberId: string) {
  const events = await prisma.event.findMany({
    where: { householdMemberId },
    orderBy: [
      { occurredAt: 'asc' },
      { createdAt: 'asc' }
    ]
  });
  return events.map(e => ({ 
    ...e, 
    payload: typeof e.payload === 'string' ? JSON.parse(e.payload) : e.payload 
  }));
}

/**
 * Retrieves a specific event by ID.
 */
export async function getEventById(eventId: string) {
  const event = await prisma.event.findUnique({
    where: { id: eventId }
  });
  if (!event) return null;
  return { 
    ...event, 
    payload: typeof event.payload === 'string' ? JSON.parse(event.payload) : event.payload 
  };
}

// NOTE: Strict immutability is enforced. There are no update or delete functions for events here.
