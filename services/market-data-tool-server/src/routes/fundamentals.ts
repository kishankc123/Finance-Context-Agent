import { Router } from "express";
import { config } from "../config.js";
import { fetchFundamentals } from "../providers/finnhub.js";
import { TtlCache } from "../cache.js";
import { CompanyFundamentals, MarketDataError } from "../types.js";
import { parseTicker } from "../validation.js";

export const fundamentalsCache = new TtlCache<CompanyFundamentals>(config.cacheTtlSeconds);

export const fundamentalsRouter = Router();

fundamentalsRouter.get("/get_company_fundamentals", async (req, res, next) => {
  try {
    const ticker = parseTicker(req.query.ticker);

    const cached = fundamentalsCache.get(ticker);
    if (cached) {
      res.json({ ...cached, cached: true });
      return;
    }

    const fundamentals = await fetchFundamentals(ticker);
    fundamentalsCache.set(ticker, fundamentals);
    res.json({ ...fundamentals, cached: false });
  } catch (err) {
    next(err instanceof MarketDataError ? err : new MarketDataError(500, "INTERNAL_ERROR", "Unexpected error"));
  }
});
