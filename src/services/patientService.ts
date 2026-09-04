// @ts-nocheck - Temporary workaround to clear IDE ghost errors for old Prisma types
import { prisma } from '../db/client';

export class PatientService {
  /**
   * Create a new patient linked to a household.
   * Verifies the creating user is a member/creator of the household.
   * Creates HouseholdMember + Patient + CaregiverAccess in a transaction.
   */
  static async createPatient(data: {
    householdId: string;
    displayName: string;
    relationship?: string;
    userId: string;
  }) {
    const { householdId, displayName, relationship, userId } = data;

    // Verify household exists and user has access
    const household = await prisma.household.findUnique({ where: { id: householdId } });
    if (!household) {
      throw Object.assign(new Error('Household not found'), { status: 404 });
    }

    // Check user is creator or member of household
    const isMember = await prisma.householdMember.findFirst({
      where: { householdId, userId },
    });
    const isCreator = household.createdBy === userId;

    if (!isMember && !isCreator) {
      throw Object.assign(new Error('Not a member of this household'), { status: 403 });
    }

    return prisma.$transaction(async (tx) => {
      const member = await tx.householdMember.create({
        data: {
          householdId,
          displayName,
          relationship: relationship || null,
          role: 'member',
          isPatient: true,
        },
      });

      const patient = await tx.patient.create({
        data: {
          householdMemberId: member.id,
        },
      });

      // Grant caregiver access to creator
      const caregiverAccess = await tx.caregiverAccess.create({
        data: {
          caregiverUserId: userId,
          householdMemberId: member.id,
          consentRecorded: false,
        },
      });

      return {
        patient: {
          id: patient.id,
          householdMemberId: member.id,
          displayName: member.displayName,
          relationship: member.relationship,
          householdId,
        },
        caregiverAccessId: caregiverAccess.id,
      };
    });
  }

  /**
   * List all patients the user has access to (via CaregiverAccess or self-link).
   */
  static async getPatients(userId: string) {
    // Via CaregiverAccess
    const accesses = await prisma.caregiverAccess.findMany({
      where: { caregiverUserId: userId },
      include: {
        householdMember: {
          include: {
            patient: true,
            household: true,
          },
        },
      },
    });

    const patientsFromAccess = accesses
      .filter((a) => a.householdMember.patient)
      .map((a) => ({
        id: a.householdMember.patient!.id,
        householdMemberId: a.householdMember.id,
        displayName: a.householdMember.displayName,
        relationship: a.householdMember.relationship,
        householdId: a.householdMember.householdId,
        householdName: a.householdMember.household.name,
        consentRecorded: a.consentRecorded,
      }));

    // Via self-link (user is the patient)
    const selfMembers = await prisma.householdMember.findMany({
      where: { userId },
      include: {
        patient: true,
        household: true,
      },
    });

    const patientsFromSelf = selfMembers
      .filter((m) => m.patient)
      .map((m) => ({
        id: m.patient!.id,
        householdMemberId: m.id,
        displayName: m.displayName,
        relationship: m.relationship,
        householdId: m.householdId,
        householdName: m.household.name,
        consentRecorded: true, // self-access doesn't need consent
      }));

    // Deduplicate by patient id
    const seen = new Set<string>();
    const combined = [];
    for (const p of [...patientsFromAccess, ...patientsFromSelf]) {
      if (!seen.has(p.id)) {
        seen.add(p.id);
        combined.push(p);
      }
    }
    return combined;
  }

  /**
   * Get a single patient by ID with full authorization chain.
   * Returns null if patient doesn't exist or user has no access.
   */
  static async getPatientById(patientId: string, userId: string) {
    const patient = await prisma.patient.findUnique({
      where: { id: patientId },
      include: {
        householdMember: {
          include: { household: true },
        },
      },
    });

    if (!patient) return null;

    // Check access
    const access = await prisma.caregiverAccess.findFirst({
      where: {
        caregiverUserId: userId,
        householdMemberId: patient.householdMemberId,
      },
    });

    const isSelf = patient.householdMember.userId === userId;
    const isCreator = patient.householdMember.household.createdBy === userId;

    if (!access && !isSelf && !isCreator) return null;

    return {
      id: patient.id,
      householdMemberId: patient.householdMemberId,
      displayName: patient.householdMember.displayName,
      relationship: patient.householdMember.relationship,
      householdId: patient.householdMember.householdId,
      householdName: patient.householdMember.household.name,
      createdAt: patient.createdAt,
      updatedAt: patient.updatedAt,
    };
  }

  /**
   * Update patient details (displayName, relationship).
   */
  static async updatePatient(
    patientId: string,
    userId: string,
    data: { displayName?: string; relationship?: string | null },
  ) {
    const patient = await prisma.patient.findUnique({
      where: { id: patientId },
      include: {
        householdMember: {
          include: { household: true },
        },
      },
    });

    if (!patient) {
      throw Object.assign(new Error('Patient not found'), { status: 404 });
    }

    // Check access
    const access = await prisma.caregiverAccess.findFirst({
      where: {
        caregiverUserId: userId,
        householdMemberId: patient.householdMemberId,
      },
    });

    const isSelf = patient.householdMember.userId === userId;
    const isCreator = patient.householdMember.household.createdBy === userId;

    if (!access && !isSelf && !isCreator) {
      throw Object.assign(new Error('Not authorized to update this patient'), { status: 403 });
    }

    const updateData: any = {};
    if (data.displayName !== undefined) updateData.displayName = data.displayName;
    if (data.relationship !== undefined) updateData.relationship = data.relationship;

    const updatedMember = await prisma.householdMember.update({
      where: { id: patient.householdMemberId },
      data: updateData,
    });

    return {
      id: patient.id,
      householdMemberId: updatedMember.id,
      displayName: updatedMember.displayName,
      relationship: updatedMember.relationship,
      householdId: updatedMember.householdId,
    };
  }
}
