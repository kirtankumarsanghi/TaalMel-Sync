import express, { Request, Response, NextFunction } from 'express';
import { validate } from '../middleware/validate';
import { RegisterSchema, LoginSchema, RefreshSchema, SignupSchema } from '../schemas/auth';
import { AuthService } from '../services/authService';
import { requireAuth } from '../middleware/authMiddleware';

const router = express.Router();

// POST /api/auth/register
router.post('/register', validate(RegisterSchema), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const result = await AuthService.register(req.body);
    res.status(201).json(result);
  } catch (err: any) {
    if (err.status) {
      res.status(err.status).json({ error: err.message });
      return;
    }
    next(err);
  }
});

// POST /api/auth/login
router.post('/login', validate(LoginSchema), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const result = await AuthService.login(req.body);
    res.json(result);
  } catch (err: any) {
    if (err.status) {
      res.status(err.status).json({ error: err.message });
      return;
    }
    next(err);
  }
});

// POST /api/auth/refresh
router.post('/refresh', validate(RefreshSchema), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const result = await AuthService.refresh(req.body.refreshToken);
    res.json(result);
  } catch (err: any) {
    if (err.status) {
      res.status(err.status).json({ error: err.message });
      return;
    }
    next(err);
  }
});

// POST /api/auth/logout
router.post('/logout', requireAuth, async (req: Request, res: Response, next: NextFunction) => {
  try {
    await AuthService.logout(req.user!.sub || req.user!.id!);
    res.json({ message: 'Logged out' });
  } catch (err) {
    next(err);
  }
});

// GET /api/auth/me
router.get('/me', requireAuth, async (req: Request, res: Response, next: NextFunction) => {
  try {
    const user = await AuthService.me(req.user!.sub || req.user!.id!);
    res.json({ user });
  } catch (err: any) {
    if (err.status) {
      res.status(err.status).json({ error: err.message });
      return;
    }
    next(err);
  }
});

// Legacy: keep /signup alias for existing tests
router.post('/signup', validate(SignupSchema), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const result = await AuthService.register(req.body);
    // Return in legacy format: { token, user }
    res.status(201).json({
      token: result.accessToken,
      refreshToken: result.refreshToken,
      user: result.user,
    });
  } catch (err: any) {
    if (err.status === 409) {
      res.status(409).json({ error: err.message });
      return;
    }
    if (err.status) {
      res.status(err.status).json({ error: err.message });
      return;
    }
    next(err);
  }
});

export default router;
