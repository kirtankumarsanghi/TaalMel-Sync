import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import request from 'supertest';
import { createApp } from '../src/app';
import { prisma } from '../src/db/client';

describe('Households — Phase 1', () => {
  const app = createApp();
  const phone1 = `hh1_${Math.floor(Math.random() * 10000000).toString().padStart(7, '0')}`;
  const phone2 = `hh2_${Math.floor(Math.random() * 10000000).toString().padStart(7, '0')}`;
  const password = 'secureP@ss123';
  let token1 = '';
  let token2 = '';
  let user1Id = '';
  let user2Id = '';
  let householdId = '';

  beforeAll(async () => {
    // Register user 1
    const res1 = await request(app)
      .post('/api/auth/register')
      .send({ name: 'HH User 1', phone: phone1, password, role: 'caregiver' });
    token1 = res1.body.accessToken;
    user1Id = res1.body.user.id;

    // Register user 2
    const res2 = await request(app)
      .post('/api/auth/register')
      .send({ name: 'HH User 2', phone: phone2, password, role: 'caregiver' });
    token2 = res2.body.accessToken;
    user2Id = res2.body.user.id;
  });

  afterAll(async () => {
    // Clean up
    try {
      for (const userId of [user1Id, user2Id]) {
        await prisma.consent.deleteMany({
          where: { caregiverAccess: { caregiverUserId: userId } },
        });
        await prisma.caregiverAccess.deleteMany({ where: { caregiverUserId: userId } });
        await prisma.refreshToken.deleteMany({ where: { userId } });
      }

      const hhs = await prisma.household.findMany({
        where: { createdBy: { in: [user1Id, user2Id] } },
      });
      for (const hh of hhs) {
        const members = await prisma.householdMember.findMany({ where: { householdId: hh.id } });
        for (const m of members) {
          await prisma.patient.deleteMany({ where: { householdMemberId: m.id } });
        }
        await prisma.householdMember.deleteMany({ where: { householdId: hh.id } });
      }
      await prisma.household.deleteMany({ where: { createdBy: { in: [user1Id, user2Id] } } });

      for (const userId of [user1Id, user2Id]) {
        await prisma.user.delete({ where: { id: userId } }).catch(() => {});
      }
    } catch (_) { /* ignore */ }
    await prisma.$disconnect();
  });

  // ── Create ────────────────────────────────────────────────────────
  it('should create a household with owner membership', async () => {
    const res = await request(app)
      .post('/api/households')
      .set('Authorization', `Bearer ${token1}`)
      .send({ name: 'Test Household', patientDisplayName: 'Mom', relationship: 'mother' });

    expect(res.status).toBe(201);
    expect(res.body).toHaveProperty('household');
    expect(res.body.household.name).toBe('Test Household');
    expect(res.body).toHaveProperty('patient');
    expect(res.body.patient.displayName).toBe('Mom');
    // Legacy compat fields
    expect(res.body).toHaveProperty('householdId');
    expect(res.body).toHaveProperty('memberId');

    householdId = res.body.household.id;
  });

  it('should reject household creation without auth (401)', async () => {
    const res = await request(app)
      .post('/api/households')
      .send({ name: 'No Auth HH', patientDisplayName: 'Test' });

    expect(res.status).toBe(401);
  });

  it('should reject household creation with invalid body (400)', async () => {
    const res = await request(app)
      .post('/api/households')
      .set('Authorization', `Bearer ${token1}`)
      .send({ name: '' });

    expect(res.status).toBe(400);
  });

  // ── List ──────────────────────────────────────────────────────────
  it('should list only the user\'s households', async () => {
    const res = await request(app)
      .get('/api/households')
      .set('Authorization', `Bearer ${token1}`);

    expect(res.status).toBe(200);
    expect(res.body.households).toBeInstanceOf(Array);
    expect(res.body.households.length).toBeGreaterThanOrEqual(1);
    expect(res.body.households.some((h: any) => h.id === householdId)).toBe(true);
  });

  it('should NOT list user1\'s household for user2', async () => {
    const res = await request(app)
      .get('/api/households')
      .set('Authorization', `Bearer ${token2}`);

    expect(res.status).toBe(200);
    expect(res.body.households.some((h: any) => h.id === householdId)).toBe(false);
  });

  // ── Get by ID ─────────────────────────────────────────────────────
  it('should return household by ID for a member', async () => {
    const res = await request(app)
      .get(`/api/households/${householdId}`)
      .set('Authorization', `Bearer ${token1}`);

    expect(res.status).toBe(200);
    expect(res.body.household.id).toBe(householdId);
    expect(res.body.household.members).toBeInstanceOf(Array);
  });

  it('should reject get household for non-member (403)', async () => {
    const res = await request(app)
      .get(`/api/households/${householdId}`)
      .set('Authorization', `Bearer ${token2}`);

    expect(res.status).toBe(403);
  });

  it('should reject get with invalid UUID (400)', async () => {
    const res = await request(app)
      .get('/api/households/not-a-uuid')
      .set('Authorization', `Bearer ${token1}`);

    expect(res.status).toBe(400);
  });
});
