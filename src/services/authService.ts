import argon2 from 'argon2';
import jwt from 'jsonwebtoken';
import { v4 as uuid } from 'uuid';
import crypto from 'crypto';
import { prisma } from '../db/client';

const ACCESS_TOKEN_EXPIRY = process.env.ACCESS_TOKEN_EXPIRY || '15m';
const REFRESH_TOKEN_EXPIRY_DAYS = parseInt(process.env.REFRESH_TOKEN_EXPIRY_DAYS || '7', 10);
const JWT_SECRET = process.env.JWT_SECRET || 'dev-secret';

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
}

export interface AuthUser {
  id: string;
  role: string;
  name: string;
  phone: string | null;
}

export class AuthService {
  // ── Register ─────────────────────────────────────────────────────
  static async register(data: { name: string; phone: string; password: string; role: string }) {
    const { name, phone, password, role } = data;

    const existing = await prisma.user.findUnique({ where: { phone } });
    if (existing) {
      throw Object.assign(new Error('Phone number already registered'), { status: 409 });
    }

    const passwordHash = await argon2.hash(password, { type: argon2.argon2id });
    const user = await prisma.user.create({
      data: { role, name, phone, passwordHash },
    });

    const tokens = await this.issueTokenPair(user.id, user.role, user.name);
    return { ...tokens, user: this.sanitizeUser(user) };
  }

  // ── Login ────────────────────────────────────────────────────────
  static async login(data: { phone: string; password: string }) {
    const { phone, password } = data;
    const user = await prisma.user.findUnique({ where: { phone } });

    if (!user || !(await argon2.verify(user.passwordHash, password))) {
      throw Object.assign(new Error('Invalid credentials'), { status: 401 });
    }

    const tokens = await this.issueTokenPair(user.id, user.role, user.name);
    return { ...tokens, user: this.sanitizeUser(user) };
  }

  // ── Refresh ──────────────────────────────────────────────────────
  static async refresh(rawRefreshToken: string) {
    // Hash the incoming token to compare with stored hash
    const tokenHash = this.hashToken(rawRefreshToken);

    const stored = await prisma.refreshToken.findFirst({
      where: { tokenHash },
    });

    if (!stored) {
      throw Object.assign(new Error('Invalid refresh token'), { status: 401 });
    }

    // Check if token was revoked (possible reuse attack)
    if (stored.revokedAt) {
      // Revoke entire family — token reuse detected
      await prisma.refreshToken.updateMany({
        where: { family: stored.family },
        data: { revokedAt: new Date() },
      });
      throw Object.assign(new Error('Refresh token reuse detected'), { status: 401 });
    }

    // Check expiry
    if (stored.expiresAt < new Date()) {
      throw Object.assign(new Error('Refresh token expired'), { status: 401 });
    }

    // Revoke the old token
    await prisma.refreshToken.update({
      where: { id: stored.id },
      data: { revokedAt: new Date() },
    });

    // Issue new pair with same family
    const user = await prisma.user.findUniqueOrThrow({ where: { id: stored.userId } });
    const tokens = await this.issueTokenPair(user.id, user.role, user.name, stored.family);
    return { ...tokens, user: this.sanitizeUser(user) };
  }

  // ── Logout ───────────────────────────────────────────────────────
  static async logout(userId: string) {
    // Revoke all refresh tokens for the user
    await prisma.refreshToken.updateMany({
      where: { userId, revokedAt: null },
      data: { revokedAt: new Date() },
    });
  }

  // ── Me ───────────────────────────────────────────────────────────
  static async me(userId: string) {
    const user = await prisma.user.findUnique({ where: { id: userId } });
    if (!user) {
      throw Object.assign(new Error('User not found'), { status: 404 });
    }
    return this.sanitizeUser(user);
  }

  // ── Internals ────────────────────────────────────────────────────
  private static async issueTokenPair(
    userId: string,
    role: string,
    name: string,
    family?: string,
  ): Promise<TokenPair> {
    const accessToken = jwt.sign(
      { sub: userId, role, name },
      JWT_SECRET,
      { expiresIn: ACCESS_TOKEN_EXPIRY as jwt.SignOptions['expiresIn'] },
    );

    const rawRefresh = uuid();
    const tokenHash = this.hashToken(rawRefresh);
    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + REFRESH_TOKEN_EXPIRY_DAYS);

    await prisma.refreshToken.create({
      data: {
        tokenHash,
        userId,
        family: family || uuid(),
        expiresAt,
      },
    });

    return { accessToken, refreshToken: rawRefresh };
  }

  private static hashToken(token: string): string {
    return crypto.createHash('sha256').update(token).digest('hex');
  }

  private static sanitizeUser(user: { id: string; role: string; name: string; phone: string | null }): AuthUser {
    return { id: user.id, role: user.role, name: user.name, phone: user.phone };
  }

  // Legacy compat: signToken for existing code that uses it
  static signToken(payload: { id: string; role: string; name: string }) {
    return jwt.sign(
      { sub: payload.id, role: payload.role, name: payload.name },
      JWT_SECRET,
      { expiresIn: ACCESS_TOKEN_EXPIRY as jwt.SignOptions['expiresIn'] },
    );
  }

  // Legacy compat: signup alias
  static async signup(data: { name: string; phone: string; password: string; role: string }) {
    return this.register(data);
  }
}
