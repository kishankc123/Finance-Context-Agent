import { afterEach, describe, expect, it, vi } from "vitest";
import request from "supertest";

process.env.FINNHUB_API_KEY = "test-key";

const { createServer } = await import("../src/server.js");

describe("GET /tools/get_company_fundamentals", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns fundamentals for a valid ticker (happy path)", async () => {
    global.fetch = vi.fn(async (url: string | URL) => {
      const href = url.toString();
      if (href.includes("/stock/profile2")) {
        return new Response(
          JSON.stringify({ marketCapitalization: 250_000, finnhubIndustry: "Semiconductors" }),
          { status: 200 },
        );
      }
      return new Response(
        JSON.stringify({ metric: { peBasicExclExtraTTM: 45.2, epsBasicExclExtraItemsTTM: 2.5 } }),
        { status: 200 },
      );
    }) as unknown as typeof fetch;

    const app = createServer();
    const res = await request(app).get("/tools/get_company_fundamentals").query({ ticker: "nvda" });

    expect(res.status).toBe(200);
    expect(res.body.ticker).toBe("NVDA");
    expect(res.body.sector).toBe("Semiconductors");
    expect(res.body.peRatio).toBe(45.2);
    expect(res.body.marketCap).toBe(250_000 * 1_000_000);
  });

  it("returns 502 when the upstream provider is unreachable", async () => {
    global.fetch = vi.fn(async () => {
      throw new Error("network down");
    }) as unknown as typeof fetch;

    const app = createServer();
    const res = await request(app).get("/tools/get_company_fundamentals").query({ ticker: "AMD" });

    expect(res.status).toBe(502);
    expect(res.body.error.code).toBe("UPSTREAM_UNREACHABLE");
  });
});
