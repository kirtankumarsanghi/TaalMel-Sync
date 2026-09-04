import { describe, it, expect, beforeAll, afterAll, vi, beforeEach } from 'vitest';
import request from 'supertest';
import { createApp } from '../src/app';
import { prisma } from '../src/db/client';
import {
  parseRawMedication,
  normalizeMedicationName,
  normalizeStrength,
  normalizeDosageForm,
  normalizeFrequency,
  normalizeMedication,
  resetDictionaryCache,
  loadDictionary,
} from '../src/services/normalizationService';
import { MedicationService } from '../src/services/medicationService';
import { checkInteractions } from '../src/services/safetyRulesService';

// Mock the queue so tests don't require Redis
vi.mock('../src/queue/prescriptionQueue', () => ({
  enqueueOcrJob: vi.fn().mockResolvedValue(true),
}));

// ─── Unit Tests: Parsing ─────────────────────────────────────────────────────

describe('parseRawMedication', () => {
  beforeEach(() => {
    resetDictionaryCache();
  });

  it('should parse "Metformin 500mg"', () => {
    const result = parseRawMedication('Metformin 500mg');
    expect(result.name).toBe('Metformin');
    expect(result.strength).toBe('500mg');
    expect(result.strengthUnit).toBe('mg');
  });

  it('should parse "Glucophage XR 1000 mg"', () => {
    const result = parseRawMedication('Glucophage XR 1000 mg');
    expect(result.name.toLowerCase()).toContain('glucophage');
    expect(result.strength).toBe('1000mg');
  });

  it('should parse "Tab Ecosprin 75mg" — prefix dosage form', () => {
    const result = parseRawMedication('Tab Ecosprin 75mg');
    expect(result.name).toBe('Ecosprin');
    expect(result.strength).toBe('75mg');
    expect(result.dosageForm).toBe('tablet');
  });

  it('should parse "Dolo 650" — bare number assumes mg', () => {
    const result = parseRawMedication('Dolo 650');
    expect(result.name).toBe('Dolo');
    expect(result.strength).toBe('650mg');
    expect(result.strengthUnit).toBe('mg');
  });

  it('should parse "Thyronorm 50mcg"', () => {
    const result = parseRawMedication('Thyronorm 50mcg');
    expect(result.name).toBe('Thyronorm');
    expect(result.strength).toBe('50mcg');
    expect(result.strengthUnit).toBe('mcg');
  });

  it('should parse "Cap Omez 20mg" — capsule prefix', () => {
    const result = parseRawMedication('Cap Omez 20mg');
    expect(result.name).toBe('Omez');
    expect(result.strength).toBe('20mg');
    expect(result.dosageForm).toBe('capsule');
  });

  it('should parse "Insulin Glargine 100iu/ml"', () => {
    const result = parseRawMedication('Insulin Glargine 100iu/ml');
    expect(result.name).toContain('Insulin');
    expect(result.strength).toBe('100iu/ml');
  });

  it('should handle empty string gracefully', () => {
    const result = parseRawMedication('');
    expect(result.name).toBe('');
    expect(result.strength).toBeNull();
  });

  it('should handle null/undefined gracefully', () => {
    const result = parseRawMedication(null as any);
    expect(result.name).toBe('');
  });

  it('should parse name with trailing dosage form — "Amlodipine 5mg tablet"', () => {
    const result = parseRawMedication('Amlodipine 5mg tablet');
    expect(result.name).toBe('Amlodipine');
    expect(result.strength).toBe('5mg');
    expect(result.dosageForm).toBe('tablet');
  });
});

// ─── Unit Tests: Name Resolution ─────────────────────────────────────────────

describe('normalizeMedicationName', () => {
  beforeEach(() => {
    resetDictionaryCache();
  });

  it('should exactly match a generic name', () => {
    const result = normalizeMedicationName('Metformin');
    expect(result.genericName).toBe('Metformin');
    expect(result.method).toBe('EXACT_GENERIC_MATCH');
    expect(result.confidence).toBe(1.0);
  });

  it('should match case-insensitively for generic', () => {
    const result = normalizeMedicationName('metformin');
    expect(result.genericName).toBe('Metformin');
    expect(result.method).toBe('EXACT_GENERIC_MATCH');
  });

  it('should resolve brand name to generic — Glucophage → Metformin', () => {
    const result = normalizeMedicationName('Glucophage');
    expect(result.genericName).toBe('Metformin');
    expect(result.brandName).toBe('Glucophage');
    expect(result.method).toBe('BRAND_LOOKUP');
    expect(result.confidence).toBeGreaterThanOrEqual(0.9);
  });

  it('should resolve brand name to generic — Ecosprin → Aspirin', () => {
    const result = normalizeMedicationName('Ecosprin');
    expect(result.genericName).toBe('Aspirin');
    expect(result.method).toBe('BRAND_LOOKUP');
  });

  it('should resolve brand name to generic — Dolo → Paracetamol', () => {
    const result = normalizeMedicationName('Dolo');
    expect(result.genericName).toBe('Paracetamol');
    expect(result.method).toBe('BRAND_LOOKUP');
  });

  it('should resolve brand name to generic — Crocin → Paracetamol', () => {
    const result = normalizeMedicationName('Crocin');
    expect(result.genericName).toBe('Paracetamol');
  });

  it('should resolve brand name to generic — Lipitor → Atorvastatin', () => {
    const result = normalizeMedicationName('Lipitor');
    expect(result.genericName).toBe('Atorvastatin');
  });

  it('should resolve brand name to generic — Thyronorm → Levothyroxine', () => {
    const result = normalizeMedicationName('Thyronorm');
    expect(result.genericName).toBe('Levothyroxine');
  });

  it('should return UNRESOLVED for completely unknown medication', () => {
    const result = normalizeMedicationName('Xyzabc123Med');
    expect(result.genericName).toBeNull();
    expect(result.method).toBe('UNRESOLVED');
    expect(result.confidence).toBe(0);
  });

  it('should return UNRESOLVED for empty string', () => {
    const result = normalizeMedicationName('');
    expect(result.genericName).toBeNull();
    expect(result.method).toBe('UNRESOLVED');
  });

  it('should handle multi-word brand names as first-word prefix', () => {
    const result = normalizeMedicationName('Met XL');
    // "Met" as first word should match Metoprolol via brand "Met XL"
    // This tests the prefix matching logic
    expect(result.genericName).not.toBeNull();
  });
});

// ─── Unit Tests: Strength Normalization ──────────────────────────────────────

describe('normalizeStrength', () => {
  it('should normalize "500 mg" → "500mg"', () => {
    expect(normalizeStrength('500 mg')).toBe('500mg');
  });

  it('should normalize "500mg" → "500mg" (already normalized)', () => {
    expect(normalizeStrength('500mg')).toBe('500mg');
  });

  it('should preserve "0.5g" as-is', () => {
    expect(normalizeStrength('0.5g')).toBe('0.5g');
  });

  it('should normalize "50 mcg" → "50mcg"', () => {
    expect(normalizeStrength('50 mcg')).toBe('50mcg');
  });

  it('should return null for empty string', () => {
    expect(normalizeStrength('')).toBeNull();
  });

  it('should return null for null', () => {
    expect(normalizeStrength(null)).toBeNull();
  });

  it('should return null for undefined', () => {
    expect(normalizeStrength(undefined)).toBeNull();
  });

  it('should handle "100iu/ml"', () => {
    const result = normalizeStrength('100iu/ml');
    expect(result).toBe('100iu/ml');
  });

  it('should handle "1000 mg" (four digits)', () => {
    expect(normalizeStrength('1000 mg')).toBe('1000mg');
  });
});

// ─── Unit Tests: Dosage Form Normalization ───────────────────────────────────

describe('normalizeDosageForm', () => {
  it('should resolve "tab" → "tablet"', () => {
    expect(normalizeDosageForm('tab')).toBe('tablet');
  });

  it('should resolve "cap" → "capsule"', () => {
    expect(normalizeDosageForm('cap')).toBe('capsule');
  });

  it('should resolve "SR" → "sustained-release tablet"', () => {
    expect(normalizeDosageForm('SR')).toBe('sustained-release tablet');
  });

  it('should resolve "XR" → "extended-release tablet"', () => {
    expect(normalizeDosageForm('XR')).toBe('extended-release tablet');
  });

  it('should resolve "syp" → "syrup"', () => {
    expect(normalizeDosageForm('syp')).toBe('syrup');
  });

  it('should resolve "inj" → "injection"', () => {
    expect(normalizeDosageForm('inj')).toBe('injection');
  });

  it('should return null for null', () => {
    expect(normalizeDosageForm(null)).toBeNull();
  });

  it('should return unknown form as-is', () => {
    expect(normalizeDosageForm('lozenge')).toBe('lozenge');
  });
});

// ─── Unit Tests: Frequency Normalization ─────────────────────────────────────

describe('normalizeFrequency', () => {
  it('should resolve "od" → "once daily"', () => {
    expect(normalizeFrequency('od')).toBe('once daily');
  });

  it('should resolve "bd" → "twice daily"', () => {
    expect(normalizeFrequency('bd')).toBe('twice daily');
  });

  it('should resolve "tid" → "three times daily"', () => {
    expect(normalizeFrequency('tid')).toBe('three times daily');
  });

  it('should resolve "hs" → "at bedtime"', () => {
    expect(normalizeFrequency('hs')).toBe('at bedtime');
  });

  it('should resolve "sos" → "as needed"', () => {
    expect(normalizeFrequency('sos')).toBe('as needed');
  });

  it('should return null for null', () => {
    expect(normalizeFrequency(null)).toBeNull();
  });

  it('should return unknown frequency as-is', () => {
    expect(normalizeFrequency('every 8 hours')).toBe('every 8 hours');
  });
});

// ─── Unit Tests: Full Pipeline ───────────────────────────────────────────────

describe('normalizeMedication (full pipeline)', () => {
  beforeEach(() => {
    resetDictionaryCache();
  });

  it('should normalize a known brand + strength', () => {
    const result = normalizeMedication({ nameRaw: 'Glucophage 500mg', frequency: 'bd' });
    expect(result.nameGeneric).toBe('Metformin');
    expect(result.nameBrand).not.toBeNull();
    expect(result.strength).toBe('500mg');
    expect(result.frequency).toBe('twice daily');
    expect(result.status).toBe('NORMALIZED');
    expect(result.confidence).toBeGreaterThanOrEqual(0.7);
    expect(result.activeIngredient).toBe('Metformin Hydrochloride');
    expect(result.category).toBe('Antidiabetic');
  });

  it('should normalize a known generic name', () => {
    const result = normalizeMedication({ nameRaw: 'Metformin 1000mg' });
    expect(result.nameGeneric).toBe('Metformin');
    expect(result.nameBrand).toBeNull();
    expect(result.strength).toBe('1000mg');
    expect(result.status).toBe('NORMALIZED');
    expect(result.method).toBe('EXACT_GENERIC_MATCH');
    expect(result.confidence).toBe(1.0);
  });

  it('should normalize Dolo 650 → Paracetamol 650mg', () => {
    const result = normalizeMedication({ nameRaw: 'Dolo 650' });
    expect(result.nameGeneric).toBe('Paracetamol');
    expect(result.strength).toBe('650mg');
    expect(result.status).toBe('NORMALIZED');
  });

  it('should normalize Tab Ecosprin 75mg → Aspirin 75mg', () => {
    const result = normalizeMedication({ nameRaw: 'Tab Ecosprin 75mg' });
    expect(result.nameGeneric).toBe('Aspirin');
    expect(result.strength).toBe('75mg');
    expect(result.dosageForm).toBe('tablet');
  });

  it('should mark unknown medication as NEEDS_REVIEW', () => {
    const result = normalizeMedication({ nameRaw: 'SomeFakelyNewDrug 100mg' });
    expect(result.status).toBe('NEEDS_REVIEW');
    expect(result.nameGeneric).toBeNull();
    expect(result.method).toBe('UNRESOLVED');
    // Strength should still be extracted even if name is unknown
    expect(result.strength).toBe('100mg');
  });

  it('should handle empty nameRaw', () => {
    const result = normalizeMedication({ nameRaw: '' });
    expect(result.status).toBe('NEEDS_REVIEW');
    expect(result.nameGeneric).toBeNull();
    expect(result.confidence).toBe(0);
  });

  it('should pass through frequency from dosage field if strength not in name', () => {
    const result = normalizeMedication({ nameRaw: 'Metformin', dosage: '500mg', frequency: 'od' });
    expect(result.nameGeneric).toBe('Metformin');
    expect(result.strength).toBe('500mg');
    expect(result.frequency).toBe('once daily');
  });

  it('should normalize Thyronorm 50mcg correctly', () => {
    const result = normalizeMedication({ nameRaw: 'Thyronorm 50mcg' });
    expect(result.nameGeneric).toBe('Levothyroxine');
    expect(result.strength).toBe('50mcg');
  });

  it('should normalize Cap Omez 20mg', () => {
    const result = normalizeMedication({ nameRaw: 'Cap Omez 20mg' });
    expect(result.nameGeneric).toBe('Omeprazole');
    expect(result.strength).toBe('20mg');
    expect(result.dosageForm).toBe('capsule');
  });

  it('should never invent a generic name for unknown medications', () => {
    const result = normalizeMedication({ nameRaw: 'XyzUnknown123' });
    // Must not fabricate a generic name
    expect(result.nameGeneric).toBeNull();
    expect(result.status).not.toBe('NORMALIZED');
  });
});

// ─── Unit Tests: Dictionary Loading ──────────────────────────────────────────

describe('Medication Dictionary', () => {
  it('should load the dictionary without errors', () => {
    resetDictionaryCache();
    const dict = loadDictionary();
    expect(dict.medications.length).toBeGreaterThan(30);
    expect(dict.dosageFormAliases).toBeDefined();
    expect(dict.frequencyAliases).toBeDefined();
  });

  it('should contain expected medications', () => {
    const dict = loadDictionary();
    const names = dict.medications.map((m) => m.genericName);
    expect(names).toContain('Metformin');
    expect(names).toContain('Aspirin');
    expect(names).toContain('Paracetamol');
    expect(names).toContain('Levothyroxine');
    expect(names).toContain('Warfarin');
  });
});

// ─── Unit Tests: Safety Rules with Normalized Names ──────────────────────────

describe('Safety Rules with Normalization', () => {
  it('should detect interaction using brand names (Ecosprin + Warf)', () => {
    // Ecosprin → Aspirin, Warf → Warfarin → should flag interaction
    const result = checkInteractions(['Ecosprin', 'Warf']);
    expect(result.normalizedNames).toContain('Aspirin');
    expect(result.normalizedNames).toContain('Warfarin');
    const flagged = result.pairs.find((p) => p.result === 'INTERACTION_FLAGGED');
    expect(flagged).toBeDefined();
  });

  it('should detect interaction using generic names (Aspirin + Warfarin)', () => {
    const result = checkInteractions(['Aspirin', 'Warfarin']);
    const flagged = result.pairs.find((p) => p.result === 'INTERACTION_FLAGGED');
    expect(flagged).toBeDefined();
  });

  it('should return NOT_COVERED for unknown medications', () => {
    const result = checkInteractions(['UnknownDrug', 'Aspirin']);
    const uncoveredPair = result.pairs.find((p) => p.result === 'NOT_COVERED');
    expect(uncoveredPair).toBeDefined();
  });
});

// ─── Integration Tests ───────────────────────────────────────────────────────

describe('Medication Normalization Integration', () => {
  const app = createApp();
  let accessToken = '';
  let userId = '';
  let householdMemberId = '';
  let patientId = '';

  const testPhone = `norm${Math.floor(Math.random() * 10000000).toString().padStart(7, '0')}`;
  const password = 'securePassword123';

  beforeAll(async () => {
    // 1. Create a user
    const userRes = await request(app).post('/api/auth/register').send({
      name: 'Normalization Test User',
      phone: testPhone,
      password,
      role: 'caregiver',
    });
    accessToken = userRes.body.accessToken;
    userId = userRes.body.user.id;

    // 2. Create a household & patient
    const hhRes = await request(app)
      .post('/api/households')
      .set('Authorization', `Bearer ${accessToken}`)
      .send({ name: 'Norm Test Household', patientDisplayName: 'Norm Patient', relationship: 'Father' });

    patientId = hhRes.body.patient.id;
    householdMemberId = hhRes.body.patient.householdMemberId;
  });

  afterAll(async () => {
    try {
      // Clean up in reverse order
      await prisma.normalizationLog.deleteMany({});
      await prisma.event.deleteMany({
        where: { medication: { householdMemberId } },
      });
      await prisma.medication.deleteMany({ where: { householdMemberId } });
      await prisma.medicationCanonical.deleteMany({});
      await prisma.prescriptionItem.deleteMany({
        where: { prescription: { uploadedByUserId: userId } },
      });
      await prisma.prescription.deleteMany({ where: { uploadedByUserId: userId } });

      const user = await prisma.user.findUnique({ where: { phone: testPhone } });
      if (user) {
        await prisma.auditRecord.deleteMany({ where: { userId: user.id } });
        await prisma.consent.deleteMany({
          where: { caregiverAccess: { caregiverUserId: user.id } },
        });
        await prisma.caregiverAccess.deleteMany({ where: { caregiverUserId: user.id } });
        await prisma.patient.deleteMany({
          where: { householdMember: { household: { createdBy: user.id } } },
        });
        await prisma.householdMember.deleteMany({
          where: { household: { createdBy: user.id } },
        });
        await prisma.household.deleteMany({ where: { createdBy: user.id } });
        await prisma.refreshToken.deleteMany({ where: { userId: user.id } });
        await prisma.user.delete({ where: { id: user.id } });
      }
    } catch (_) {}
    await prisma.$disconnect();
  });

  describe('Prescription verification triggers normalization', () => {
    let prescriptionId = '';
    let itemId = '';

    beforeAll(async () => {
      // Create a prescription record manually (simulating upload + OCR completion)
      const prescription = await prisma.prescription.create({
        data: {
          householdMemberId,
          fileStorageKey: 'test/norm-test.jpg',
          originalFilename: 'norm-test.jpg',
          mimeType: 'image/jpeg',
          fileSizeBytes: 100,
          fileHash: `normtest-${Date.now()}`,
          uploadedByUserId: userId,
          ocrStatus: 'NEEDS_REVIEW',
        },
      });
      prescriptionId = prescription.id;

      // Add OCR-extracted items
      const item1 = await prisma.prescriptionItem.create({
        data: {
          prescriptionId,
          medicationName: 'Glucophage 500mg',
          dosage: '500mg',
          frequency: 'bd',
          instructions: 'After meals',
          confidence: 0.85,
          verified: false,
        },
      });
      itemId = item1.id;

      await prisma.prescriptionItem.create({
        data: {
          prescriptionId,
          medicationName: 'Ecosprin 75mg',
          dosage: '75mg',
          frequency: 'od',
          instructions: 'Before breakfast',
          confidence: 0.9,
          verified: false,
        },
      });
    });

    it('should create medication records on verification', async () => {
      // Get prescription items
      const prescription = await prisma.prescription.findUnique({
        where: { id: prescriptionId },
        include: { items: true },
      });

      const items = prescription!.items;

      const res = await request(app)
        .post(`/api/prescriptions/${prescriptionId}/verify`)
        .set('Authorization', `Bearer ${accessToken}`)
        .send({
          items: items.map((item) => ({
            itemId: item.id,
            medicationName: item.medicationName,
            dosage: item.dosage,
            frequency: item.frequency,
            instructions: item.instructions,
          })),
        });

      expect(res.status).toBe(200);
      expect(res.body.verified).toBe(true);
      expect(res.body.medicationResults).toBeDefined();
      expect(res.body.medicationResults.length).toBe(2);

      // Check normalization results
      const glucophageResult = res.body.medicationResults.find(
        (r: any) => r.normalizationStatus === 'NORMALIZED'
      );
      expect(glucophageResult).toBeDefined();
    });

    it('should have created medication records in the database', async () => {
      const medications = await MedicationService.getMedicationsForHousehold(householdMemberId);
      expect(medications.length).toBeGreaterThanOrEqual(2);

      const metformin = medications.find((m) => m.nameGeneric === 'Metformin');
      expect(metformin).toBeDefined();
      expect(metformin!.nameRaw).toBe('Glucophage 500mg');
      expect(metformin!.strength).toBe('500mg');
      expect(metformin!.normalizationStatus).toBe('NORMALIZED');
      expect(metformin!.normalizationMethod).toBe('BRAND_LOOKUP');
      expect(metformin!.identityConfirmed).toBe(true);

      const aspirin = medications.find((m) => m.nameGeneric === 'Aspirin');
      expect(aspirin).toBeDefined();
      expect(aspirin!.nameRaw).toBe('Ecosprin 75mg');
      expect(aspirin!.strength).toBe('75mg');
    });

    it('should have created canonical records', async () => {
      const canonicals = await prisma.medicationCanonical.findMany({});
      expect(canonicals.length).toBeGreaterThanOrEqual(2);

      const metforminCanonical = canonicals.find(
        (c) => c.genericName === 'Metformin'
      );
      expect(metforminCanonical).toBeDefined();
      expect(metforminCanonical!.strength).toBe('500mg');
    });

    it('should have logged normalization events', async () => {
      const logs = await prisma.normalizationLog.findMany({
        orderBy: { createdAt: 'desc' },
      });
      expect(logs.length).toBeGreaterThanOrEqual(2);
    });
  });

  describe('Duplicate detection', () => {
    it('should merge when same generic + same strength is added again', async () => {
      const result = await MedicationService.createFromPrescriptionItem(
        {
          id: 'dup-test-item-1',
          medicationName: 'Glycomet 500mg',  // Different brand, same generic+strength
          dosage: '500mg',
          frequency: null,
          instructions: null,
        },
        householdMemberId,
      );

      // Should merge with existing Metformin 500mg, not create a new one
      expect(result.action).toBe('MERGED');
      expect(result.normalization.nameGeneric).toBe('Metformin');
    });

    it('should create new record for same generic but different strength', async () => {
      const result = await MedicationService.createFromPrescriptionItem(
        {
          id: 'dup-test-item-2',
          medicationName: 'Metformin 1000mg',
          dosage: '1000mg',
          frequency: null,
          instructions: null,
        },
        householdMemberId,
      );

      // Different strength = different medication record
      expect(result.action).toBe('CREATED');
      expect(result.normalization.nameGeneric).toBe('Metformin');
      expect(result.normalization.strength).toBe('1000mg');
    });
  });

  describe('Review queue', () => {
    beforeAll(async () => {
      // Create a medication with unknown name that needs review
      await MedicationService.createFromPrescriptionItem(
        {
          id: 'review-test-item-1',
          medicationName: 'SomeUnknownMedicine 50mg',
          dosage: '50mg',
          frequency: null,
          instructions: null,
        },
        householdMemberId,
      );
    });

    it('should list medications needing review via API', async () => {
      const res = await request(app)
        .get(`/api/medications/needs-review/${householdMemberId}`)
        .set('Authorization', `Bearer ${accessToken}`);

      expect(res.status).toBe(200);
      expect(res.body.count).toBeGreaterThanOrEqual(1);
      const unknownMed = res.body.medications.find(
        (m: any) => m.nameRaw === 'SomeUnknownMedicine 50mg'
      );
      expect(unknownMed).toBeDefined();
      expect(unknownMed.normalizationStatus).toBe('NEEDS_REVIEW');
    });
  });

  describe('Manual verification', () => {
    let needsReviewMedId = '';

    beforeAll(async () => {
      const meds = await MedicationService.getMedicationsNeedingReview(householdMemberId);
      if (meds.length > 0) {
        needsReviewMedId = meds[0].id;
      }
    });

    it('should allow manual normalization override via API', async () => {
      if (!needsReviewMedId) return; // Skip if no medication needs review

      const res = await request(app)
        .post(`/api/medications/${needsReviewMedId}/verify-normalization`)
        .set('Authorization', `Bearer ${accessToken}`)
        .send({
          nameGeneric: 'TestGenericName',
          strength: '50mg',
          dosageForm: 'tablet',
        });

      expect(res.status).toBe(200);
      expect(res.body.nameGeneric).toBe('TestGenericName');
      expect(res.body.normalizationStatus).toBe('MANUALLY_VERIFIED');
      expect(res.body.normalizationConfidence).toBe(1.0);
      expect(res.body.identityConfirmed).toBe(true);
    });
  });

  describe('Normalize preview (no-save)', () => {
    it('should return normalization result without saving', async () => {
      const res = await request(app)
        .post('/api/medications/normalize-preview')
        .set('Authorization', `Bearer ${accessToken}`)
        .send({
          nameRaw: 'Crocin 650mg',
          frequency: 'tid',
        });

      expect(res.status).toBe(200);
      expect(res.body.result.nameGeneric).toBe('Paracetamol');
      expect(res.body.result.strength).toBe('650mg');
      expect(res.body.result.frequency).toBe('three times daily');
      expect(res.body.result.status).toBe('NORMALIZED');
      expect(res.body.result.method).toBe('BRAND_LOOKUP');
    });

    it('should show NEEDS_REVIEW for unknown medication preview', async () => {
      const res = await request(app)
        .post('/api/medications/normalize-preview')
        .set('Authorization', `Bearer ${accessToken}`)
        .send({
          nameRaw: 'CompletelyMadeUpDrugName',
        });

      expect(res.status).toBe(200);
      expect(res.body.result.status).toBe('NEEDS_REVIEW');
      expect(res.body.result.nameGeneric).toBeNull();
    });

    it('should reject empty nameRaw', async () => {
      const res = await request(app)
        .post('/api/medications/normalize-preview')
        .set('Authorization', `Bearer ${accessToken}`)
        .send({
          nameRaw: '',
        });

      expect(res.status).toBe(400);
    });
  });
});
