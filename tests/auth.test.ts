import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import request from 'supertest';
import jwt from 'jsonwebtoken';
import { createApp } from '../src/app';
import { prisma } from '../src/db/client';

describe('Auth — Phase 1', () => {
  const app = createApp();
  const testPhone = `auth${Math.floor(Math.random() * 10000000).toString().padStart(7, '0')}`;
  const password = 'secureP@ss123';
  let accessToken = '';
  let refreshToken = '';
  let userId = '';

  afterAll(async () => {
    // Clean up test data
    try {
      const user = await prisma.user.findUnique({ where: { phone: testPhone } });
      if (user) {
        await prisma.refreshToken.deleteMany({ where: { userId: user.id } });
        await prisma.caregiverAccess.deleteMany({ where: { caregiverUserId: user.id } });
        await prisma.user.delete({ where: { id: user.id } });
      }
    } catch (_) { /* ignore cleanup errors */ }
    await prisma.$disconnect();
  });

  // ── Registration ──────────────────────────────────────────────────
  it('should register a new user and return access + refresh tokens', async () => {
    const res = await request(app)
      .post('/api/auth/register')
      .send({ name: 'Auth Test User', phone: testPhone, password, role: 'caregiver' });

    expect(res.status).toBe(201);
    expect(res.body).toHaveProperty('accessToken');
    expect(res.body).toHaveProperty('refreshToken');
    expect(res.body).toHaveProperty('user');
    expect(res.body.user.name).toBe('Auth Test User');
    expect(res.body.user.phone).toBe(testPhone);
    expect(res.body.user).not.toHaveProperty('passwordHash');

    accessToken = res.body.accessToken;
    refreshToken = res.body.refreshToken;
    userId = res.body.user.id;
  });

  it('should reject duplicate phone registration (409)', async () => {
    const res = await request(app)
      .post('/api/auth/register')
      .send({ name: 'Duplicate', phone: testPhone, password, role: 'caregiver' });

    expect(res.status).toBe(409);
    expect(res.body.error).toMatch(/already registered/i);
  });

  // ── Login ─────────────────────────────────────────────────────────
  it('should login with valid credentials', async () => {
    const res = await request(app)
      .post('/api/auth/login')
      .send({ phone: testPhone, password });

    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('accessToken');
    expect(res.body).toHaveProperty('refreshToken');
    expect(res.body.user.id).toBe(userId);

    // Update tokens for subsequent tests
    accessToken = res.body.accessToken;
    refreshToken = res.body.refreshToken;
  });

  it('should reject login with wrong password (401)', async () => {
    const res = await request(app)
      .post('/api/auth/login')
      .send({ phone: testPhone, password: 'wrongpassword' });

    expect(res.status).toBe(401);
    expect(res.body.error).toMatch(/invalid credentials/i);
  });

  it('should reject login with non-existent phone (401)', async () => {
    const res = await request(app)
      .post('/api/auth/login')
      .send({ phone: '0000000000', password });

    expect(res.status).toBe(401);
  });

  // ── GET /me ───────────────────────────────────────────────────────
  it('should return user profile via GET /me', async () => {
    const res = await request(app)
      .get('/api/auth/me')
      .set('Authorization', `Bearer ${accessToken}`);

    expect(res.status).toBe(200);
    expect(res.body.user.id).toBe(userId);
    expect(res.body.user.name).toBe('Auth Test User');
    expect(res.body.user).not.toHaveProperty('passwordHash');
  });

  it('should reject GET /me without token (401)', async () => {
    const res = await request(app).get('/api/auth/me');
    expect(res.status).toBe(401);
  });

  // ── Token refresh ─────────────────────────────────────────────────
  it('should refresh tokens with a valid refresh token', async () => {
    const res = await request(app)
      .post('/api/auth/refresh')
      .send({ refreshToken });

    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('accessToken');
    expect(res.body).toHaveProperty('refreshToken');
    // New tokens should be different
    expect(res.body.refreshToken).not.toBe(refreshToken);

    // Store new tokens
    accessToken = res.body.accessToken;
    refreshToken = res.body.refreshToken;
  });

  it('should reject reuse of a consumed refresh token (401)', async () => {
    // Use the current refresh token
    const firstRes = await request(app)
      .post('/api/auth/refresh')
      .send({ refreshToken });

    expect(firstRes.status).toBe(200);
    const oldRefreshToken = refreshToken;
    refreshToken = firstRes.body.refreshToken;
    accessToken = firstRes.body.accessToken;

    // Try to use the old (now revoked) refresh token
    const reuseRes = await request(app)
      .post('/api/auth/refresh')
      .send({ refreshToken: oldRefreshToken });

    expect(reuseRes.status).toBe(401);
  });

  it('should reject refresh with random UUID (401)', async () => {
    const res = await request(app)
      .post('/api/auth/refresh')
      .send({ refreshToken: '00000000-0000-0000-0000-000000000000' });

    expect(res.status).toBe(401);
  });

  // ── Token expiration ──────────────────────────────────────────────
  it('should reject an expired access token (401)', async () => {
    // Sign a token that expired 1 second ago
    const expiredToken = jwt.sign(
      { sub: userId, role: 'caregiver', name: 'Test' },
      process.env.JWT_SECRET || 'dev-secret',
      { expiresIn: '-1s' },
    );

    const res = await request(app)
      .get('/api/auth/me')
      .set('Authorization', `Bearer ${expiredToken}`);

    expect(res.status).toBe(401);
  });

  // ── Logout ────────────────────────────────────────────────────────
  it('should logout and invalidate refresh tokens', async () => {
    // First get fresh tokens
    const loginRes = await request(app)
      .post('/api/auth/login')
      .send({ phone: testPhone, password });

    const freshAccess = loginRes.body.accessToken;
    const freshRefresh = loginRes.body.refreshToken;

    // Logout
    const logoutRes = await request(app)
      .post('/api/auth/logout')
      .set('Authorization', `Bearer ${freshAccess}`);

    expect(logoutRes.status).toBe(200);

    // Try to refresh after logout
    const refreshRes = await request(app)
      .post('/api/auth/refresh')
      .send({ refreshToken: freshRefresh });

    expect(refreshRes.status).toBe(401);
  });

  // ── Validation ────────────────────────────────────────────────────
  it('should reject malformed registration body (400)', async () => {
    const res = await request(app)
      .post('/api/auth/register')
      .send({ name: '', phone: '', password: 'short' });

    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/validation failed/i);
    expect(res.body).toHaveProperty('details');
  });

  it('should reject registration with password < 8 chars (400)', async () => {
    const res = await request(app)
      .post('/api/auth/register')
      .send({ name: 'Test', phone: '1234567890', password: '1234567', role: 'caregiver' });

    expect(res.status).toBe(400);
  });

  it('should reject login with empty body (400)', async () => {
    const res = await request(app)
      .post('/api/auth/login')
      .send({});

    expect(res.status).toBe(400);
  });

  it('should reject refresh with non-UUID token (400)', async () => {
    const res = await request(app)
      .post('/api/auth/refresh')
      .send({ refreshToken: 'not-a-uuid' });

    expect(res.status).toBe(400);
  });
});
