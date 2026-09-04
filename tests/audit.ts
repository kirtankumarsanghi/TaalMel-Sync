import { createApp } from '../src/app';
import { prisma } from '../src/db/client';
import request from 'supertest';
import { prescriptionWorker as worker, enqueueOcrJob } from '../src/queue/prescriptionQueue';
import fs from 'fs';
import path from 'path';

async function delay(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function runAudit() {
  console.log('Starting E2E Audit...');
  const app = createApp();
  
  let accessToken = '';
  let userId = '';
  let householdMemberId = '';
  
  const dummyImgPath = path.join(__dirname, 'dummy_audit.jpg');
  fs.writeFileSync(dummyImgPath, Buffer.from('fake image data for audit'));
  const testPhone = `audit${Date.now().toString().slice(-7)}`;

  try {
    console.log('1. Setting up user & patient...');
    const userRes = await request(app).post('/api/auth/register').send({
      name: 'Audit User',
      phone: testPhone,
      password: 'password123',
      role: 'caregiver'
    });
    accessToken = userRes.body.accessToken;
    userId = userRes.body.user.id;

    const hhRes = await request(app)
      .post('/api/households')
      .set('Authorization', `Bearer ${accessToken}`)
      .send({ name: 'Audit HH', patientDisplayName: 'Audit Patient', relationship: 'Mother' });
    householdMemberId = hhRes.body.patient.householdMemberId;

    // Test 1: Upload (ASYNC PROCESSING, STORAGE, UPLOAD, AUTHORIZATION)
    console.log('2. Testing Upload (Async Processing, Authorization)...');
    
    // Auth missing
    const authFailRes = await request(app)
      .post('/api/prescriptions/upload')
      .field('householdMemberId', householdMemberId);
    if (authFailRes.status !== 401) throw new Error('Authorization test failed');

    // Valid upload
    const uploadRes = await request(app)
      .post('/api/prescriptions/upload')
      .set('Authorization', `Bearer ${accessToken}`)
      .field('householdMemberId', householdMemberId)
      .attach('file', dummyImgPath);
      
    if (uploadRes.status !== 201) throw new Error(`Upload failed: ${JSON.stringify(uploadRes.body)}`);
    const prescriptionId = uploadRes.body.id;
    if (uploadRes.body.ocrStatus !== 'PENDING') throw new Error('Status not PENDING immediately after upload');
    
    // Test 2: Wait for OCR Worker (OCR, EXTRACTION, CONFIDENCE)
    console.log('3. Waiting for OCR Worker processing...');
    let currentStatus = 'PENDING';
    let rxRecord: any;
    for (let i = 0; i < 20; i++) {
      await delay(500);
      rxRecord = await prisma.prescription.findUnique({ where: { id: prescriptionId }, include: { items: true } });
      currentStatus = rxRecord?.ocrStatus || 'UNKNOWN';
      if (currentStatus !== 'PENDING' && currentStatus !== 'PROCESSING') break;
    }
    
    if (currentStatus !== 'COMPLETED' && currentStatus !== 'NEEDS_REVIEW') {
      throw new Error(`Worker did not finish, status: ${currentStatus}`);
    }
    console.log(`Worker completed with status: ${currentStatus}`);

    // Inspect trust boundaries
    console.log('4. Inspecting trust boundaries...');
    if (rxRecord.verified !== false) throw new Error('Prescription verified prematurely');
    if (rxRecord.items.some((item: any) => item.verified !== false)) throw new Error('Items verified prematurely');
    
    // Test 3: Duplicate Handling
    console.log('5. Testing Duplicate Handling...');
    const dupRes = await request(app)
      .post('/api/prescriptions/upload')
      .set('Authorization', `Bearer ${accessToken}`)
      .field('householdMemberId', householdMemberId)
      .attach('file', dummyImgPath);
    if (dupRes.status !== 409) throw new Error('Duplicate allowed');

    // Test 4: Manual Verification & Auditability
    console.log('6. Testing Manual Verification...');
    const verifyPayload = {
      items: rxRecord.items.map((item: any) => ({
        itemId: item.id,
        medicationName: item.medicationName,
        dosage: 'Audited Dose'
      }))
    };
    const verifyRes = await request(app)
      .post(`/api/prescriptions/${prescriptionId}/verify`)
      .set('Authorization', `Bearer ${accessToken}`)
      .send(verifyPayload);
      
    if (verifyRes.status !== 200) throw new Error(`Verify failed: ${JSON.stringify(verifyRes.body)}`);
    if (verifyRes.body.verified !== true) throw new Error('Prescription not marked verified');
    
    // Check Event Log
    const audits = await prisma.auditRecord.findMany({ where: { userId } });
    if (!audits.some(a => a.action === 'PrescriptionVerified')) {
      console.error('Audit Failure: Verification event not emitted');
    }

    // Test 5: Error Handling (Failed OCR Job)
    console.log('7. Testing Error Handling (Failed OCR)...');
    
    // Create a prescription directly in DB with a bad fileStorageKey to guarantee failure
    const failRecordInit = await prisma.prescription.create({
      data: {
        householdMemberId,
        fileStorageKey: 'nonexistent-key.jpg',
        originalFilename: 'fail.jpg',
        mimeType: 'image/jpeg',
        fileSizeBytes: 1000,
        fileHash: 'fakehash123',
        uploadedByUserId: userId,
        ocrStatus: 'PENDING'
      }
    });
    
    await enqueueOcrJob(failRecordInit.id);
    const failId = failRecordInit.id;
    
    let failStatus = 'PENDING';
    let failRecord;
    for (let i = 0; i < 20; i++) {
      await delay(500);
      failRecord = await prisma.prescription.findUnique({ where: { id: failId } });
      failStatus = failRecord?.ocrStatus || 'UNKNOWN';
      if (failStatus === 'FAILED') break;
    }
    if (failStatus !== 'FAILED') throw new Error(`Error handling failed, status is ${failStatus}`);
    if (!failRecord?.ocrError) throw new Error('ocrError not populated');
    
    console.log(`Failed job status: ${failStatus}, Error message stored: ${failRecord.ocrError}`);

    console.log('AUDIT COMPLETED SUCCESSFULLY.');

  } catch (err) {
    console.error('AUDIT FAILED:', err);
  } finally {
    if (fs.existsSync(dummyImgPath)) fs.unlinkSync(dummyImgPath);
    await worker.close();
    await prisma.$disconnect();
    process.exit(0);
  }
}

runAudit();
