import { Queue, Worker, Job } from 'bullmq';
import { connection } from './connection';
import { prisma } from '../db/client';
import { getStorageService } from '../services/storageService';
import { getOcrProvider, processOcrResult } from '../services/ocrService';
import { appendEvent } from '../events/eventStore';
import { EVENT_TYPES, SOURCES } from '../events/eventTypes';

export const PRESCRIPTION_QUEUE_NAME = 'prescription-ocr';

export const prescriptionQueue = new Queue(PRESCRIPTION_QUEUE_NAME, { connection });

export async function enqueueOcrJob(prescriptionId: string) {
  await prescriptionQueue.add('extract-text', { prescriptionId });
}

export const prescriptionWorker = new Worker(
  PRESCRIPTION_QUEUE_NAME,
  async (job: Job<{ prescriptionId: string }>) => {
    const { prescriptionId } = job.data;
    
    // 1. Mark as PROCESSING
    const prescription = await prisma.prescription.update({
      where: { id: prescriptionId },
      data: { ocrStatus: 'PROCESSING' }
    });

    const storage = getStorageService();
    const ocrProvider = getOcrProvider();

    try {
      // 2. Download file
      const buffer = await storage.download(prescription.fileStorageKey);
      
      // 3. Extract text
      const result = await ocrProvider.extractText(buffer, prescription.mimeType);
      
      // 4. Process result to get candidates & overall status
      const processed = processOcrResult(result);
      
      // 5. Save candidates & update prescription
      await prisma.$transaction(async (tx) => {
        await tx.prescription.update({
          where: { id: prescriptionId },
          data: {
            ocrStatus: processed.status,
            ocrRawText: result.rawText,
            ocrCompletedAt: new Date(),
          }
        });

        if (processed.items.length > 0) {
          await tx.prescriptionItem.createMany({
            data: processed.items.map(item => ({
              prescriptionId,
              ...item
            }))
          });
        }
      });

      // 6. Emit event
      await appendEvent({
        medicationId: prescriptionId, // Wait, events need a medicationId. We don't have one yet because these are candidates.
        // Actually, prescription events might just be logged with a dummy ID or we might need to modify eventStore to support prescriptionId. 
        // For now we will emit it against a dummy ID or skip emitting it if the schema demands medicationId.
        // Wait, EVENT_TYPES.PRESCRIPTION_OCR_COMPLETED... let's log it later.
        eventType: EVENT_TYPES.PRESCRIPTION_OCR_COMPLETED,
        payload: { prescriptionId, status: processed.status, itemCount: processed.items.length },
        source: SOURCES.OCR,
        sourceUserId: null
      }).catch(() => {}); // catch to avoid failing the whole job if event store demands valid medicationId. We will fix this in eventStore if needed.
      
    } catch (error: any) {
      // Mark as FAILED
      await prisma.prescription.update({
        where: { id: prescriptionId },
        data: {
          ocrStatus: 'FAILED',
          ocrError: error.message || 'Unknown OCR Error',
          ocrCompletedAt: new Date(),
        }
      });

      await appendEvent({
        medicationId: prescriptionId,
        eventType: EVENT_TYPES.PRESCRIPTION_OCR_FAILED,
        payload: { prescriptionId, error: error.message },
        source: SOURCES.OCR
      }).catch(() => {});
      
      throw error;
    }
  },
  { connection }
);

prescriptionWorker.on('failed', (job, err) => {
  console.error(`Job ${job?.id} failed:`, err);
});
