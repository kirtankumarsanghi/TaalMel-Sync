import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import request from 'supertest';
import { createApp } from '../src/app';
import { prisma } from '../src/db/client';

describe('API Routes', () => {
  const app = createApp();
  let token = '';
  let householdMemberId = '';
  let medicationId = '';
  const testPhone = `123${Math.floor(Math.random() * 10000000).toString().padStart(7, '0')}`;

  beforeAll(async () => {
    // create a user
    const userRes = await request(app)
      .post('/api/auth/signup')
      .send({
        name: 'Route Test User',
        phone: testPhone,
        password: 'password123',
        role: 'caregiver'
      });
    
    token = userRes.body.token;

    const hhRes = await request(app)
      .post('/api/households/households')
      .set('Authorization', `Bearer ${token}`)
      .send({ householdName: 'Test Household', patientDisplayName: 'Test Member', relationship: 'self', consentRecorded: true });
    
    // Check if the response contains the member id
    householdMemberId = hhRes.body.memberId || hhRes.body.id;
  });

  afterAll(async () => {
    const user = await prisma.user.findUnique({ where: { phone: testPhone } });
    if (user) {
      await prisma.refreshToken.deleteMany({ where: { userId: user.id } });
      await prisma.consent.deleteMany({ where: { caregiverAccess: { caregiverUserId: user.id } } });
      await prisma.caregiverAccess.deleteMany({ where: { caregiverUserId: user.id } });
      const hhs = await prisma.household.findMany({ where: { createdBy: user.id } });
      for (const hh of hhs) {
        const members = await prisma.householdMember.findMany({ where: { householdId: hh.id } });
        for (const member of members) {
          const meds = await prisma.medication.findMany({ where: { householdMemberId: member.id } });
          for (const med of meds) {
            await prisma.event.deleteMany({ where: { medicationId: med.id } });
            await prisma.medication.delete({ where: { id: med.id } });
          }
          await prisma.householdMember.delete({ where: { id: member.id } });
        }
      }
      await prisma.household.deleteMany({ where: { createdBy: user.id } });
      await prisma.user.delete({ where: { id: user.id } });
    }
  });

  it('should return health status', async () => {
    const res = await request(app).get('/health');
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('status', 'ok');
  });

  it('should return 401 for unauthorized access', async () => {
    const res = await request(app).get(`/api/dashboard/household/${householdMemberId}/safety-check`);
    expect(res.status).toBe(401);
  });

  it('should add medication and check safety', async () => {
    const medRes = await request(app)
      .post(`/api/medications`)
      .set('Authorization', `Bearer ${token}`)
      .send({
        householdMemberId,
        nameRaw: 'Lisinopril',
        source: 'manual',
        dose: '10mg'
      });
    expect(medRes.status).toBe(201);
    medicationId = medRes.body.medicationId;

    const safetyRes = await request(app)
      .get(`/api/dashboard/household/${householdMemberId}/safety-check`)
      .set('Authorization', `Bearer ${token}`);
    
    expect(safetyRes.status).toBe(200);
    expect(safetyRes.body).toHaveProperty('pairs');
    expect(safetyRes.body).toHaveProperty('uncovered');
  });
});
