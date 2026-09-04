import { prisma } from './client';
import argon2 from 'argon2';
import { v4 as uuid } from 'uuid';

async function main() {
  console.log('--- Taalmel Sync Seed & Demo (Section 14) ---');
  console.log('1. Caregiver Setup & Access (Section 11)');
  
  const caregiverId = uuid();
  await prisma.user.create({
    data: {
      id: caregiverId,
      name: 'Ravi (Caregiver)',
      phone: '555-0101',
      passwordHash: await argon2.hash('password123'),
      role: 'caregiver'
    }
  });

  const household = await prisma.household.create({
    data: {
      name: 'Sharma Household',
      createdBy: caregiverId
    }
  });

  const member = await prisma.householdMember.create({
    data: {
      householdId: household.id,
      displayName: 'Mrs. Sharma (Mother)',
      relationship: 'Mother',
      isPatient: true
    }
  });

  await prisma.caregiverAccess.create({
    data: {
      caregiverUserId: caregiverId,
      householdMemberId: member.id,
      consentRecorded: true
    }
  });

  console.log('Created Caregiver, Household, and granted access.');
  
  console.log('\n2. Foundational Reality (Section 9.1)');
  const medication = await prisma.medication.create({
    data: {
      householdMemberId: member.id,
      nameRaw: 'glucophage',
      nameGeneric: 'Metformin',
      doseRaw: '500mg',
      identityConfirmed: true
    }
  });
  console.log(`Added medication: ${medication.nameRaw} (mapped to ${medication.nameGeneric})`);

  // We could simulate the event sourcing flow here directly
  console.log('\nDemo seed complete. Use endpoints for further event sourcing interactions.');
}

main()
  .catch(e => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });

export {};
