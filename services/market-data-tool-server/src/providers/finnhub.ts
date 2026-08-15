import { config } from "../config.js";
import { CompanyFundamentals, MarketDataError, StockQuote } from "../types.js";

interface FinnhubQuoteResponse {
  c: number; // current price
  d: number; // change
  dp: number; // percent change
  v?: number; // volume (not always present on /quote)
  t: number; // unix timestamp
}

interface FinnhubProfileResponse {
  marketCapitalization?: number;
  finnhubIndustry?: string;
}

interface FinnhubMetricResponse {
  metric?: {
    peBasicExclExtraTTM?: number;
    epsBasicExclExtraItemsTTM?: number;
  };
}

async function finnhubGet<T>(path: string, params: Record<string, string>): Promise<T> {
  if (!config.finnhubApiKey) {
    throw new MarketDataError(500, "MISSING_API_KEY", "FINNHUB_API_KEY is not configured");
  }
  const url = new URL(config.finnhubBaseUrl + path);
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value);
  url.searchParams.set("token", config.finnhubApiKey);

  let response: Response;
  try {
    response = await fetch(url, { signal: AbortSignal.timeout(5000) });
  } catch {
    throw new MarketDataError(502, "UPSTREAM_UNREACHABLE", "Failed to reach market data provider");
  }

  if (response.status === 429) {
    throw new MarketDataError(429, "UPSTREAM_RATE_LIMITED", "Market data provider rate limit exceeded");
  }
  if (!response.ok) {
    throw new MarketDataError(502, "UPSTREAM_ERROR", `Market data provider returned ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchQuote(ticker: string): Promise<StockQuote> {
  const data = await finnhubGet<FinnhubQuoteResponse>("/quote", { symbol: ticker });

  if (!data || data.c === 0) {
    throw new MarketDataError(404, "UNKNOWN_TICKER", `No quote data found for '${ticker}'`);
  }

  return {
    ticker,
    price: data.c,
    change: data.d,
    changePercent: data.dp,
    volume: data.v ?? null,
    asOf: new Date(data.t * 1000).toISOString(),
  };
}

export async function fetchFundamentals(ticker: string): Promise<CompanyFundamentals> {
  const [profile, metrics] = await Promise.all([
    finnhubGet<FinnhubProfileResponse>("/stock/profile2", { symbol: ticker }),
    finnhubGet<FinnhubMetricResponse>("/stock/metric", { symbol: ticker, metric: "all" }),
  ]);

  if (!profile || Object.keys(profile).length === 0) {
    throw new MarketDataError(404, "UNKNOWN_TICKER", `No fundamentals found for '${ticker}'`);
  }

  return {
    ticker,
    marketCap: profile.marketCapitalization ? profile.marketCapitalization * 1_000_000 : null,
    peRatio: metrics.metric?.peBasicExclExtraTTM ?? null,
    eps: metrics.metric?.epsBasicExclExtraItemsTTM ?? null,
    sector: profile.finnhubIndustry ?? null,
    asOf: new Date().toISOString(),
  };
}
