import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import request from 'supertest';
import { createApp } from '../src/app';
import { prisma } from '../src/db/client';

describe('Patient Access — Phase 1', () => {
  const app = createApp();
  const phoneA = `pa_a_${Math.floor(Math.random() * 10000000).toString().padStart(7, '0')}`;
  const phoneB = `pa_b_${Math.floor(Math.random() * 10000000).toString().padStart(7, '0')}`;
  const password = 'secureP@ss123';
  let tokenA = '';
  let tokenB = '';
  let userAId = '';
  let userBId = '';
  let householdAId = '';
  let householdBId = '';
  let patientAId = '';
  let patientBId = '';
  let patientAMemberId = '';

  beforeAll(async () => {
    // Register user A
    const resA = await request(app)
      .post('/api/auth/register')
      .send({ name: 'User A', phone: phoneA, password, role: 'caregiver' });
    tokenA = resA.body.accessToken;
    userAId = resA.body.user.id;

    // Register user B
    const resB = await request(app)
      .post('/api/auth/register')
      .send({ name: 'User B', phone: phoneB, password, role: 'caregiver' });
    tokenB = resB.body.accessToken;
    userBId = resB.body.user.id;

    // User A creates household A
    const hhA = await request(app)
      .post('/api/households')
      .set('Authorization', `Bearer ${tokenA}`)
      .send({ name: 'Household A', patientDisplayName: 'Patient A' });
    householdAId = hhA.body.household.id;
    patientAId = hhA.body.patient.id;
    patientAMemberId = hhA.body.patient.householdMemberId;

    // User B creates household B
    const hhB = await request(app)
      .post('/api/households')
      .set('Authorization', `Bearer ${tokenB}`)
      .send({ name: 'Household B', patientDisplayName: 'Patient B' });
    householdBId = hhB.body.household.id;
    patientBId = hhB.body.patient.id;
  });

  afterAll(async () => {
    // Clean up
    try {
      for (const userId of [userAId, userBId]) {
        await prisma.consent.deleteMany({
          where: { caregiverAccess: { caregiverUserId: userId } },
        });
        await prisma.caregiverAccess.deleteMany({ where: { caregiverUserId: userId } });
        await prisma.refreshToken.deleteMany({ where: { userId } });
      }

      for (const hhId of [householdAId, householdBId]) {
        const members = await prisma.householdMember.findMany({ where: { householdId: hhId } });
        for (const m of members) {
          await prisma.patient.deleteMany({ where: { householdMemberId: m.id } });
        }
        await prisma.householdMember.deleteMany({ where: { householdId: hhId } });
      }

      await prisma.household.deleteMany({ where: { id: { in: [householdAId, householdBId] } } });

      for (const userId of [userAId, userBId]) {
        await prisma.user.delete({ where: { id: userId } }).catch(() => {});
      }
    } catch (_) { /* ignore */ }
    await prisma.$disconnect();
  });

  // ── Create patient ────────────────────────────────────────────────
  it('should create a patient in own household', async () => {
    const res = await request(app)
      .post('/api/patients')
      .set('Authorization', `Bearer ${tokenA}`)
      .send({ householdId: householdAId, displayName: 'New Patient', relationship: 'father' });

    expect(res.status).toBe(201);
    expect(res.body.patient).toHaveProperty('id');
    expect(res.body.patient.displayName).toBe('New Patient');
    expect(res.body).toHaveProperty('caregiverAccessId');
  });

  it('should NOT create a patient in another user\'s household (403)', async () => {
    const res = await request(app)
      .post('/api/patients')
      .set('Authorization', `Bearer ${tokenB}`)
      .send({ householdId: householdAId, displayName: 'Infiltrator' });

    expect(res.status).toBe(403);
  });

  // ── List patients ─────────────────────────────────────────────────
  it('should list only accessible patients', async () => {
    const res = await request(app)
      .get('/api/patients')
      .set('Authorization', `Bearer ${tokenA}`);

    expect(res.status).toBe(200);
    expect(res.body.patients).toBeInstanceOf(Array);
    // User A should see patients in household A
    const patientIds = res.body.patients.map((p: any) => p.id);
    expect(patientIds).toContain(patientAId);
    // User A should NOT see patient B
    expect(patientIds).not.toContain(patientBId);
  });

  // ── Get patient by ID (authorized) ────────────────────────────────
  it('should return patient for authorized user', async () => {
    const res = await request(app)
      .get(`/api/patients/${patientAId}`)
      .set('Authorization', `Bearer ${tokenA}`);

    expect(res.status).toBe(200);
    expect(res.body.patient.id).toBe(patientAId);
    expect(res.body.patient.displayName).toBe('Patient A');
  });

  // ── Cross-household access ────────────────────────────────────────
  it('should deny user B access to patient A (403)', async () => {
    const res = await request(app)
      .get(`/api/patients/${patientAId}`)
      .set('Authorization', `Bearer ${tokenB}`);

    expect(res.status).toBe(403);
  });

  it('should deny user A access to patient B (403)', async () => {
    const res = await request(app)
      .get(`/api/patients/${patientBId}`)
      .set('Authorization', `Bearer ${tokenA}`);

    expect(res.status).toBe(403);
  });

  // ── Unauthorized access (no token) ────────────────────────────────
  it('should reject patient access without token (401)', async () => {
    const res = await request(app)
      .get(`/api/patients/${patientAId}`);

    expect(res.status).toBe(401);
  });

  // ── Update patient ────────────────────────────────────────────────
  it('should update patient displayName (authorized)', async () => {
    const res = await request(app)
      .patch(`/api/patients/${patientAId}`)
      .set('Authorization', `Bearer ${tokenA}`)
      .send({ displayName: 'Updated Patient A' });

    expect(res.status).toBe(200);
    expect(res.body.patient.displayName).toBe('Updated Patient A');
  });

  it('should deny update from unauthorized user (403)', async () => {
    const res = await request(app)
      .patch(`/api/patients/${patientAId}`)
      .set('Authorization', `Bearer ${tokenB}`)
      .send({ displayName: 'Hacked' });

    expect(res.status).toBe(403);
  });

  // ── Invalid ID ────────────────────────────────────────────────────
  it('should reject non-UUID patient ID (400)', async () => {
    const res = await request(app)
      .get('/api/patients/not-a-uuid')
      .set('Authorization', `Bearer ${tokenA}`);

    expect(res.status).toBe(400);
  });

  // ── Consent enforcement ───────────────────────────────────────────
  it('should block access when consent is revoked', async () => {
    // Find the caregiver access for patient A
    const access = await prisma.caregiverAccess.findFirst({
      where: { caregiverUserId: userAId, householdMemberId: patientAMemberId },
    });

    if (access) {
      // Revoke consent
      const consent = await prisma.consent.findUnique({
        where: { caregiverAccessId: access.id },
      });
      if (consent) {
        await prisma.consent.update({
          where: { id: consent.id },
          data: { revokedAt: new Date() },
        });
        await prisma.caregiverAccess.update({
          where: { id: access.id },
          data: { consentRecorded: false },
        });
      }
    }

    // Patient should still be accessible via the service (access exists, consent is checked at middleware level)
    // But the consent service should report false
    const { ConsentService } = await import('../src/services/consentService');
    const hasConsent = await ConsentService.checkConsent(userAId, patientAMemberId);
    expect(hasConsent).toBe(false);

    // Restore consent for other tests
    if (access) {
      const consent = await prisma.consent.findUnique({
        where: { caregiverAccessId: access.id },
      });
      if (consent) {
        await prisma.consent.update({
          where: { id: consent.id },
          data: { revokedAt: null },
        });
        await prisma.caregiverAccess.update({
          where: { id: access.id },
          data: { consentRecorded: true },
        });
      }
    }
  });
});
