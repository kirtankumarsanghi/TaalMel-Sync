import { Request, Response, NextFunction } from 'express';

export function errorHandler(err: any, req: Request, res: Response, next: NextFunction) {
  if ((req as any).log) {
    (req as any).log.error(err);
  } else {
    console.error(err);
  }

  const status = err.status || 500;
  res.status(status).json({ error: err.message || 'Unexpected error' });
}

export {};
