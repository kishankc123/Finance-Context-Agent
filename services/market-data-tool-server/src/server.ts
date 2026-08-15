import express, { NextFunction, Request, Response } from "express";
import { config } from "./config.js";
import { quoteRouter, quoteCache } from "./routes/quote.js";
import { fundamentalsRouter, fundamentalsCache } from "./routes/fundamentals.js";
import { toolSchemas } from "./toolSchemas.js";
import { rateLimit } from "./rateLimit.js";
import { MarketDataError } from "./types.js";

export function createServer() {
  const app = express();
  app.disable("x-powered-by");

  app.use(rateLimit(config.rateLimitWindowMs, config.rateLimitMaxRequests));

  app.get("/health", (_req, res) => {
    res.json({
      status: "ok",
      cache: { quote: quoteCache.stats(), fundamentals: fundamentalsCache.stats() },
    });
  });

  app.get("/tools/schema", (_req, res) => {
    res.json({ tools: toolSchemas });
  });

  app.use("/tools", quoteRouter);
  app.use("/tools", fundamentalsRouter);

  app.use((req, res) => {
    res.status(404).json({ error: { code: "NOT_FOUND", message: `No route for ${req.method} ${req.path}` } });
  });

  app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
    if (err instanceof MarketDataError) {
      res.status(err.status).json({ error: { code: err.code, message: err.message } });
      return;
    }
    res.status(500).json({ error: { code: "INTERNAL_ERROR", message: "Unexpected error" } });
  });

  return app;
}
