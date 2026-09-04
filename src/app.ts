import express, { Request, Response } from 'express';
import cors from 'cors';
import morgan from 'morgan';
import rateLimit from 'express-rate-limit';

import authRoutes from './routes/authRoutes';
import householdRoutes from './routes/householdRoutes';
import patientRoutes from './routes/patientRoutes';
import prescriptionRoutes from './routes/prescriptionRoutes';
import legacyHouseholdRoutes from './routes/legacyHouseholdRoutes';
import medicationRoutes from './routes/medicationRoutes';
import eventRoutes from './routes/eventRoutes';
import caseRoutes from './routes/caseRoutes';
import exportRoutes from './routes/exportRoutes';
import companionRoutes from './routes/companionRoutes';
import dashboardRoutes from './routes/dashboardRoutes';
import normalizationRoutes from './routes/normalizationRoutes';
import { errorHandler } from './middleware/errorHandler';

import pinoHttp from 'pino-http';
import pino from 'pino';

export function createApp() {
  const app = express();
  
  app.use(cors());
  app.use(express.json({ limit: '5mb' }));
  
  const logger = pino({ level: process.env.LOG_LEVEL || 'info' });
  app.use(pinoHttp({ logger }));

  const limiter = rateLimit({
    windowMs: 15 * 60 * 1000,
    max: 100,
    message: 'Too many requests from this IP, please try again later.'
  });
  app.use(limiter);

  app.get('/health', (_req: Request, res: Response) => {
    res.json({ status: 'ok', service: 'taalmel-sync' });
  });

  app.get('/', (_req: Request, res: Response) => {
    res.json({
      message: 'Welcome to Taalmel Sync API',
      note: "This is a backend API. Run 'npm run seed' for a full narrated demo in your terminal, or use curl/Postman against the endpoints below.",
      health: '/health',
      endpoints: {
        auth: '/api/auth (POST /register, POST /login, POST /refresh, POST /logout, GET /me)',
        households: '/api/households',
        patients: '/api/patients',
        medications: '/api/medications (includes /needs-review, /normalize-preview, /:id/verify-normalization)',
        evidence: '/api/evidence',
        cases: '/api/cases',
        exports: '/api/exports',
        companion: '/api/companion',
        dashboard: '/api/dashboard',
        prescriptions: '/api/prescriptions',
      },
    });
  });

  // Phase 1: Identity & patient management
  app.use('/api/auth', authRoutes);
  app.use('/api/households', householdRoutes);
  app.use('/api/patients', patientRoutes);

  // Phase 2: Prescriptions & OCR
  app.use('/api/prescriptions', prescriptionRoutes);

  // Legacy routes (backward compat for existing code/tests)
  app.use('/api/households', legacyHouseholdRoutes);

  // Existing domain routes
  app.use('/api/medications', medicationRoutes);
  app.use('/api/medications', normalizationRoutes);
  app.use('/api/evidence', eventRoutes);
  app.use('/api/cases', caseRoutes);
  app.use('/api/exports', exportRoutes);
  app.use('/api/companion', companionRoutes);
  app.use('/api/dashboard', dashboardRoutes);

  app.use(errorHandler);
  
  return app;
}

export {};
