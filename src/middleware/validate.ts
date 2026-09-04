import { Request, Response, NextFunction } from 'express';
import { ZodSchema, ZodError } from 'zod';

export function validate(schema: ZodSchema) {
  return (req: Request, res: Response, next: NextFunction) => {
    try {
      req.body = schema.parse(req.body);
      next();
    } catch (err: any) {
      if (err instanceof ZodError) {
        res.status(400).json({ error: 'Validation failed', details: err.errors });
      } else {
        next(err);
      }
    }
  };
}

export function validateParams(schema: ZodSchema) {
  return (req: Request, res: Response, next: NextFunction) => {
    try {
      req.params = schema.parse(req.params) as any;
      next();
    } catch (err: any) {
      if (err instanceof ZodError) {
        res.status(400).json({ error: 'Invalid parameters', details: err.errors });
      } else {
        next(err);
      }
    }
  };
}

export function validateQuery(schema: ZodSchema) {
  return (req: Request, res: Response, next: NextFunction) => {
    try {
      (req as any).validatedQuery = schema.parse(req.query);
      next();
    } catch (err: any) {
      if (err instanceof ZodError) {
        res.status(400).json({ error: 'Invalid query parameters', details: err.errors });
      } else {
        next(err);
      }
    }
  };
}
