import { prisma } from '../db/client';
import {
  normalizeMedication,
  findOrCreateCanonical,
  logNormalization,
  NormalizationInput,
  NormalizationResult,
} from './normalizationService';
import { appendEvent } from '../events/eventStore';
import { EVENT_TYPES, SOURCES } from '../events/eventTypes';
import { logAudit } from './auditTrailService';

export class MedicationService {
  /**
   * Create a medication record directly (legacy — used by medicationRoutes).
   */
  static async createMedication(data: {
    householdMemberId: string;
    nameRaw: string;
    nameGeneric: string;
    doseRaw: string | null;
    identityConfirmed: boolean;
  }) {
    return prisma.medication.create({
      data: {
        ...data,
        normalizationStatus: data.identityConfirmed ? 'MANUALLY_VERIFIED' : 'PENDING',
      },
    });
  }

  /**
   * Create a Medication record from a verified PrescriptionItem.
   * Runs the full normalization pipeline:
   *   parse → resolve name → normalize strength/form → find canonical → log
   */
  static async createFromPrescriptionItem(
    item: {
      id: string;
      medicationName: string;
      dosage: string | null;
      frequency: string | null;
      instructions: string | null;
    },
    householdMemberId: string,
    userId?: string | null,
  ) {
    const input: NormalizationInput = {
      nameRaw: item.medicationName,
      dosage: item.dosage,
      frequency: item.frequency,
      instructions: item.instructions,
    };

    const result = normalizeMedication(input);

    // Check for duplicates before creating
    return this.mergeOrCreate(householdMemberId, item, result, userId);
  }

  /**
   * Find existing medication records that might be the same medication.
   * Matches on: same generic name + same strength (if present).
   */
  static async findDuplicates(
    householdMemberId: string,
    genericName: string | null,
    strength?: string | null,
  ) {
    if (!genericName) return [];

    // SQLite doesn't support mode: 'insensitive', so query broadly and filter
    const where: any = {
      householdMemberId,
    };

    if (strength) {
      where.strength = strength;
    }

    const candidates = await prisma.medication.findMany({ where });
    return candidates.filter(
      (m) => m.nameGeneric && m.nameGeneric.toLowerCase() === genericName.toLowerCase()
    );
  }

  /**
   * Either merge with an existing duplicate or create a new medication record.
   * If a duplicate is found (same generic + same strength), updates it.
   * If no duplicate, creates a new record.
   */
  static async mergeOrCreate(
    householdMemberId: string,
    item: {
      id: string;
      medicationName: string;
      dosage: string | null;
      frequency: string | null;
      instructions: string | null;
    },
    normResult: NormalizationResult,
    userId?: string | null,
  ) {
    // Look for existing duplicate
    const duplicates = await this.findDuplicates(
      householdMemberId,
      normResult.nameGeneric,
      normResult.strength,
    );

    let canonicalId: string | null = null;

    // Create/find canonical if we have a generic name
    if (normResult.nameGeneric && normResult.status !== 'NEEDS_REVIEW') {
      const canonical = await findOrCreateCanonical(
        normResult.nameGeneric,
        normResult.strength,
        normResult.dosageForm,
        normResult.matchedEntry,
      );
      canonicalId = canonical.id;
    }

    if (duplicates.length > 0) {
      // Update existing — pick the first match
      const existing = duplicates[0];

      const updated = await prisma.medication.update({
        where: { id: existing.id },
        data: {
          // Update normalized fields but preserve raw values
          nameBrand: normResult.nameBrand || existing.nameBrand,
          strength: normResult.strength || existing.strength,
          strengthRaw: normResult.strengthRaw || existing.strengthRaw,
          dosageForm: normResult.dosageForm || existing.dosageForm,
          dosageFormRaw: normResult.dosageFormRaw || existing.dosageFormRaw,
          frequency: normResult.frequency || existing.frequency,
          frequencyRaw: normResult.frequencyRaw || existing.frequencyRaw,
          instructionsRaw: item.instructions || existing.instructionsRaw,
          instructions: item.instructions || existing.instructions,
          normalizationStatus: normResult.status,
          normalizationMethod: normResult.method,
          normalizationConfidence: normResult.confidence,
          canonicalId,
          prescriptionItemId: item.id,
          identityConfirmed: normResult.status === 'NORMALIZED',
        },
      });

      // Log normalization
      await logNormalization(existing.id, item.medicationName, normResult, 'Merged with existing record');

      return { medication: updated, action: 'MERGED' as const, normalization: normResult };
    }

    // Create new medication record
    const medication = await prisma.medication.create({
      data: {
        householdMemberId,
        nameRaw: item.medicationName,
        nameGeneric: normResult.nameGeneric,
        nameBrand: normResult.nameBrand,
        doseRaw: item.dosage,
        strength: normResult.strength,
        strengthRaw: normResult.strengthRaw,
        dosageForm: normResult.dosageForm,
        dosageFormRaw: normResult.dosageFormRaw,
        frequencyRaw: normResult.frequencyRaw,
        frequency: normResult.frequency,
        instructionsRaw: item.instructions,
        instructions: item.instructions,
        identityConfirmed: normResult.status === 'NORMALIZED',
        normalizationStatus: normResult.status,
        normalizationMethod: normResult.method,
        normalizationConfidence: normResult.confidence,
        canonicalId,
        prescriptionItemId: item.id,
      },
    });

    // Log normalization
    await logNormalization(medication.id, item.medicationName, normResult);

    return { medication, action: 'CREATED' as const, normalization: normResult };
  }

  /**
   * Get all medications needing normalization review for a household member.
   */
  static async getMedicationsNeedingReview(householdMemberId: string) {
    return prisma.medication.findMany({
      where: {
        householdMemberId,
        normalizationStatus: { in: ['NEEDS_REVIEW', 'AMBIGUOUS'] },
      },
      include: {
        canonical: true,
      },
      orderBy: { createdAt: 'desc' },
    });
  }

  /**
   * Manually verify a medication's normalization, overriding the automated result.
   */
  static async manuallyVerifyNormalization(
    medicationId: string,
    verified: {
      nameGeneric: string;
      nameBrand?: string | null;
      strength?: string | null;
      dosageForm?: string | null;
    },
    userId: string,
  ) {
    const medication = await prisma.medication.findUnique({
      where: { id: medicationId },
    });

    if (!medication) {
      throw Object.assign(new Error('Medication not found'), { status: 404 });
    }

    // Find or create canonical for the verified data
    let canonicalId: string | null = null;
    if (verified.nameGeneric) {
      const canonical = await findOrCreateCanonical(
        verified.nameGeneric,
        verified.strength || null,
        verified.dosageForm || null,
        null, // No dictionary match for manual entry
      );
      canonicalId = canonical.id;
    }

    const updated = await prisma.medication.update({
      where: { id: medicationId },
      data: {
        nameGeneric: verified.nameGeneric,
        nameBrand: verified.nameBrand || medication.nameBrand,
        strength: verified.strength || medication.strength,
        dosageForm: verified.dosageForm || medication.dosageForm,
        normalizationStatus: 'MANUALLY_VERIFIED',
        normalizationMethod: 'MANUAL',
        normalizationConfidence: 1.0,
        canonicalId,
        identityConfirmed: true,
      },
    });

    // Log
    await logNormalization(medicationId, medication.nameRaw, {
      nameGeneric: verified.nameGeneric,
      nameBrand: verified.nameBrand || null,
      strength: verified.strength || null,
      strengthRaw: medication.strengthRaw,
      strengthUnit: null,
      dosageForm: verified.dosageForm || null,
      dosageFormRaw: medication.dosageFormRaw,
      frequency: medication.frequency,
      frequencyRaw: medication.frequencyRaw,
      activeIngredient: null,
      category: null,
      method: 'MANUAL',
      confidence: 1.0,
      status: 'MANUALLY_VERIFIED',
      matchedEntry: null,
    }, `Manually verified by user ${userId}`);

    // Emit event
    await appendEvent({
      medicationId,
      eventType: EVENT_TYPES.MEDICATION_NORMALIZATION_VERIFIED,
      payload: { verifiedBy: userId, genericName: verified.nameGeneric },
      source: SOURCES.CAREGIVER,
      sourceUserId: userId,
    });

    await logAudit(
      EVENT_TYPES.MEDICATION_NORMALIZATION_VERIFIED,
      'Medication',
      medicationId,
      userId,
      { genericName: verified.nameGeneric },
    );

    return updated;
  }

  static async getMedicationsForHousehold(householdMemberId: string) {
    return prisma.medication.findMany({
      where: { householdMemberId },
      include: { canonical: true },
    });
  }

  static async getMedicationById(medicationId: string) {
    return prisma.medication.findUnique({
      where: { id: medicationId },
      include: { canonical: true },
    });
  }
}
