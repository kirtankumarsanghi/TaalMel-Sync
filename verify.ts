import { PrismaClient } from '@prisma/client';
const prisma = new PrismaClient();

async function check() {
  const users = await prisma.user.findMany({ take: 3 });
  for (const user of users) {
    console.log(`User: ${user.phone}, Hash: ${user.passwordHash}`);
  }
  await prisma.$disconnect();
}

check();
