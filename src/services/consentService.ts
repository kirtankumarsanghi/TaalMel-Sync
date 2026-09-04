import { prisma } from '../db/client';

export class ConsentService {
  /**
   * Record consent for a caregiver→patient relationship.
   */
  static async recordConsent(data: {
    caregiverAccessId: string;
    consentType?: string;
    consentMethod?: string;
  }) {
    const { caregiverAccessId, consentType = 'data_access', consentMethod = 'in_app' } = data;

    const access = await prisma.caregiverAccess.findUnique({
      where: { id: caregiverAccessId },
    });

    if (!access) {
      throw Object.assign(new Error('Caregiver access record not found'), { status: 404 });
    }

    // Create or update consent
    const existing = await prisma.consent.findUnique({
      where: { caregiverAccessId },
    });

    if (existing) {
      // Re-record — clear revocation if previously revoked
      const consent = await prisma.consent.update({
        where: { id: existing.id },
        data: {
          consentType,
          consentMethod,
          revokedAt: null,
          recordedAt: new Date(),
        },
      });

      await prisma.caregiverAccess.update({
        where: { id: caregiverAccessId },
        data: { consentRecorded: true },
      });

      return consent;
    }

    const consent = await prisma.consent.create({
      data: {
        caregiverAccessId,
        consentType,
        consentMethod,
      },
    });

    await prisma.caregiverAccess.update({
      where: { id: caregiverAccessId },
      data: { consentRecorded: true },
    });

    return consent;
  }

  /**
   * Check if consent exists and is active for a caregiver→patient relationship.
   */
  static async checkConsent(caregiverUserId: string, householdMemberId: string): Promise<boolean> {
    const access = await prisma.caregiverAccess.findFirst({
      where: { caregiverUserId, householdMemberId },
      include: { consent: true },
    });

    if (!access || !access.consentRecorded) return false;
    if (access.consent && access.consent.revokedAt) return false;

    return true;
  }

  /**
   * Revoke consent for a caregiver→patient relationship.
   */
  static async revokeConsent(caregiverAccessId: string) {
    const consent = await prisma.consent.findUnique({
      where: { caregiverAccessId },
    });

    if (!consent) {
      throw Object.assign(new Error('Consent record not found'), { status: 404 });
    }

    await prisma.consent.update({
      where: { id: consent.id },
      data: { revokedAt: new Date() },
    });

    await prisma.caregiverAccess.update({
      where: { id: caregiverAccessId },
      data: { consentRecorded: false },
    });

    return { revoked: true };
  }
}
