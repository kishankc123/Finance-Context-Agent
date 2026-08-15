import type { NextFunction, Request, Response } from "express";

interface Bucket {
  count: number;
  windowStart: number;
}

/**
 * Minimal fixed-window per-IP rate limiter. No external dependency needed
 * for a single-instance tool service; swap for a shared store if this
 * service is ever scaled horizontally.
 */
export function rateLimit(windowMs: number, maxRequests: number) {
  const buckets = new Map<string, Bucket>();

  return (req: Request, res: Response, next: NextFunction) => {
    const key = req.ip ?? "unknown";
    const now = Date.now();
    const bucket = buckets.get(key);

    if (!bucket || now - bucket.windowStart >= windowMs) {
      buckets.set(key, { count: 1, windowStart: now });
      next();
      return;
    }

    if (bucket.count >= maxRequests) {
      res.status(429).json({
        error: { code: "RATE_LIMITED", message: "Too many requests, slow down." },
      });
      return;
    }

    bucket.count++;
    next();
  };
}
