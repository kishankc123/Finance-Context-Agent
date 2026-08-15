import { Router } from "express";
import { config } from "../config.js";
import { fetchQuote } from "../providers/finnhub.js";
import { TtlCache } from "../cache.js";
import { StockQuote, MarketDataError } from "../types.js";
import { parseTicker } from "../validation.js";

export const quoteCache = new TtlCache<StockQuote>(config.cacheTtlSeconds);

export const quoteRouter = Router();

quoteRouter.get("/get_stock_quote", async (req, res, next) => {
  try {
    const ticker = parseTicker(req.query.ticker);

    const cached = quoteCache.get(ticker);
    if (cached) {
      res.json({ ...cached, cached: true });
      return;
    }

    const quote = await fetchQuote(ticker);
    quoteCache.set(ticker, quote);
    res.json({ ...quote, cached: false });
  } catch (err) {
    next(err instanceof MarketDataError ? err : new MarketDataError(500, "INTERNAL_ERROR", "Unexpected error"));
  }
});
