import crypto from 'crypto';
import { prisma } from '../db/client';
import { getStorageService } from './storageService';
import { enqueueOcrJob } from '../queue/prescriptionQueue';
import { logAudit } from './auditTrailService';
import { EVENT_TYPES, SOURCES } from '../events/eventTypes';
import { appendEvent } from '../events/eventStore';
import { MedicationService } from './medicationService';

export class PrescriptionService {
  /**
   * Validates file, hashes for dedup, stores via StorageService, 
   * creates Prescription record with ocrStatus: PENDING, and enqueues OCR job.
   */
  static async uploadPrescription(
    file: Express.Multer.File,
    householdMemberId: string,
    userId: string
  ) {
    // Hash file for duplicate detection
    const hash = crypto.createHash('sha256').update(file.buffer).digest('hex');

    // Check duplicate
    const existing = await prisma.prescription.findUnique({
      where: {
        householdMemberId_fileHash: {
          householdMemberId,
          fileHash: hash
        }
      }
    });

    if (existing) {
      throw Object.assign(new Error('This prescription file has already been uploaded for this patient.'), { status: 409 });
    }

    const storage = getStorageService();
    const storageKey = `prescriptions/${householdMemberId}/${hash}-${file.originalname}`;

    // Upload to storage
    await storage.upload(storageKey, file.buffer, file.mimetype);

    // Create prescription record
    const prescription = await prisma.prescription.create({
      data: {
        householdMemberId,
        fileStorageKey: storageKey,
        originalFilename: file.originalname,
        mimeType: file.mimetype,
        fileSizeBytes: file.size,
        fileHash: hash,
        uploadedByUserId: userId,
        ocrStatus: 'PENDING'
      }
    });

    // Enqueue OCR job
    await enqueueOcrJob(prescription.id);

    return prescription;
  }

  /**
   * Retrieves prescription details including its extracted items.
   */
  static async getPrescription(id: string) {
    const prescription = await prisma.prescription.findUnique({
      where: { id },
      include: {
        items: true,
      }
    });

    if (!prescription) {
      throw Object.assign(new Error('Prescription not found'), { status: 404 });
    }

    return prescription;
  }

  /**
   * Retrieves all prescriptions for a given patient (household member).
   */
  static async getPrescriptionsForPatient(householdMemberId: string) {
    return prisma.prescription.findMany({
      where: { householdMemberId },
      include: {
        items: true,
      },
      orderBy: { createdAt: 'desc' }
    });
  }

  /**
   * Explicitly verify OCR-extracted items, updating the items and marking them verified.
   * After verification, automatically creates/merges Medication records via normalization.
   */
  static async verifyPrescription(
    prescriptionId: string,
    verifiedItems: Array<{
      itemId: string;
      medicationName: string;
      dosage?: string | null;
      frequency?: string | null;
      instructions?: string | null;
    }>,
    userId: string
  ) {
    const prescription = await prisma.prescription.findUnique({
      where: { id: prescriptionId },
      include: { items: true }
    });

    if (!prescription) {
      throw Object.assign(new Error('Prescription not found'), { status: 404 });
    }

    const now = new Date();
    const medicationResults: Array<{
      itemId: string;
      medicationId: string;
      action: 'CREATED' | 'MERGED';
      normalizationStatus: string;
    }> = [];

    await prisma.$transaction(async (tx) => {
      // 1. Update items
      for (const item of verifiedItems) {
        const existingItem = prescription.items.find(i => i.id === item.itemId);
        if (!existingItem) {
          throw Object.assign(new Error(`Item ${item.itemId} not found on this prescription`), { status: 400 });
        }

        await tx.prescriptionItem.update({
          where: { id: item.itemId },
          data: {
            medicationName: item.medicationName,
            dosage: item.dosage,
            frequency: item.frequency,
            instructions: item.instructions,
            verified: true,
            verifiedAt: now,
            verifiedByUserId: userId,
          }
        });
      }

      // 2. Update prescription level verified status
      await tx.prescription.update({
        where: { id: prescriptionId },
        data: {
          verified: true,
          verifiedAt: now,
          verifiedByUserId: userId
        }
      });
    });

    // 3. Run normalization for each verified item (outside transaction to avoid long locks)
    for (const item of verifiedItems) {
      try {
        const result = await MedicationService.createFromPrescriptionItem(
          {
            id: item.itemId,
            medicationName: item.medicationName,
            dosage: item.dosage || null,
            frequency: item.frequency || null,
            instructions: item.instructions || null,
          },
          prescription.householdMemberId,
          userId,
        );

        medicationResults.push({
          itemId: item.itemId,
          medicationId: result.medication.id,
          action: result.action,
          normalizationStatus: result.normalization.status,
        });

        // Emit MedicationExtracted event
        const eventType = result.normalization.status === 'NEEDS_REVIEW' || result.normalization.status === 'AMBIGUOUS'
          ? EVENT_TYPES.MEDICATION_NORMALIZATION_REVIEW
          : EVENT_TYPES.MEDICATION_NORMALIZED;

        await appendEvent({
          medicationId: result.medication.id,
          eventType,
          payload: {
            prescriptionId,
            prescriptionItemId: item.itemId,
            action: result.action,
            genericName: result.normalization.nameGeneric,
            method: result.normalization.method,
            confidence: result.normalization.confidence,
            status: result.normalization.status,
          },
          source: SOURCES.SYSTEM,
          sourceUserId: userId,
        });
      } catch (err) {
        // Log but don't fail the whole verification if one item's normalization fails
        console.error(`Normalization failed for item ${item.itemId}:`, err);
      }
    }

    await logAudit(
      EVENT_TYPES.PRESCRIPTION_VERIFIED,
      'Prescription',
      prescriptionId,
      userId,
      { itemCount: verifiedItems.length, medications: medicationResults }
    );

    // Reload with updated items
    const result = await this.getPrescription(prescriptionId);
    return { ...result, medicationResults };
  }
}
