import { prisma } from '../db/client';

export class HouseholdService {
  static async checkAccess(userId: string, memberId: string) {
    const access = await prisma.caregiverAccess.findFirst({
      where: { caregiverUserId: userId, householdMemberId: memberId }
    });

    const member = await prisma.householdMember.findUnique({ where: { id: memberId } });

    return access || (member && member.userId === userId);
  }

  static async createHousehold(data: { householdName: string, patientDisplayName: string, relationship?: string, consentRecorded: boolean, userId: string }) {
    const { householdName, patientDisplayName, relationship, consentRecorded, userId } = data;

    return prisma.$transaction(async (tx) => {
      const household = await tx.household.create({
        data: {
          name: householdName,
          createdBy: userId
        }
      });

      const member = await tx.householdMember.create({
        data: {
          householdId: household.id,
          displayName: patientDisplayName,
          relationship: relationship || null,
          isPatient: true
        }
      });

      await tx.caregiverAccess.create({
        data: {
          caregiverUserId: userId,
          householdMemberId: member.id,
          consentRecorded: !!consentRecorded
        }
      });

      return { householdId: household.id, memberId: member.id, consentRecorded: !!consentRecorded };
    });
  }

  static async getMembersForUser(userId: string) {
    const accesses = await prisma.caregiverAccess.findMany({
      where: { caregiverUserId: userId },
      include: { householdMember: true }
    });
    return accesses.map(a => a.householdMember);
  }

  static async getMedicationsForMember(householdMemberId: string) {
    return prisma.medication.findMany({
      where: { householdMemberId }
    });
  }

  static async createDoctorQuestion(data: { medicationId?: string, householdMemberId: string, questionText: string, raisedBy: string }) {
    const question = await prisma.doctorQuestion.create({
      data: {
        medicationId: data.medicationId || null,
        householdMemberId: data.householdMemberId,
        questionText: data.questionText,
        raisedBy: data.raisedBy,
      }
    });

    let relevantInstruction: { name: string; dose: string | null } | null = null;
    if (data.medicationId) {
      const med = await prisma.medication.findUnique({ where: { id: data.medicationId } });
      relevantInstruction = med ? { name: med.nameGeneric || med.nameRaw, dose: med.doseRaw } : null;
    }

    return { question, relevantInstruction };
  }

  static async getDoctorQuestions(householdMemberId: string, status: string = 'PENDING') {
    return prisma.doctorQuestion.findMany({
      where: {
        householdMemberId,
        status,
      },
      orderBy: { createdAt: 'asc' }
    });
  }

  static async markQuestionDiscussed(questionId: string) {
    await prisma.doctorQuestion.update({
      where: { id: questionId },
      data: {
        status: 'DISCUSSED',
        discussedAt: new Date()
      }
    });
  }
}
