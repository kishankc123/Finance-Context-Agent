import { MarketDataError } from "./types.js";

const TICKER_PATTERN = /^[A-Z]{1,6}(\.[A-Z]{1,2})?$/;

export function parseTicker(raw: unknown): string {
  if (typeof raw !== "string" || raw.trim().length === 0) {
    throw new MarketDataError(400, "INVALID_TICKER", "ticker is required");
  }
  const ticker = raw.trim().toUpperCase();
  if (!TICKER_PATTERN.test(ticker)) {
    throw new MarketDataError(
      400,
      "INVALID_TICKER",
      `'${raw}' is not a valid ticker symbol`,
    );
  }
  return ticker;
}
