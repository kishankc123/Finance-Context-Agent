export const config = {
  port: Number(process.env.PORT ?? 8091),
  finnhubApiKey: process.env.FINNHUB_API_KEY ?? "",
  finnhubBaseUrl: process.env.FINNHUB_BASE_URL ?? "https://finnhub.io/api/v1",
  cacheTtlSeconds: Number(process.env.CACHE_TTL_SECONDS ?? 90),
  rateLimitWindowMs: Number(process.env.RATE_LIMIT_WINDOW_MS ?? 60_000),
  rateLimitMaxRequests: Number(process.env.RATE_LIMIT_MAX_REQUESTS ?? 30),
};
