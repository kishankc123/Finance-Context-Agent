import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import request from "supertest";

process.env.FINNHUB_API_KEY = "test-key";

const { createServer } = await import("../src/server.js");

describe("GET /tools/get_stock_quote", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns a quote for a valid ticker (happy path)", async () => {
    global.fetch = vi.fn(async () =>
      new Response(
        JSON.stringify({ c: 172.5, d: 1.25, dp: 0.73, v: 5_000_000, t: 1_700_000_000 }),
        { status: 200 },
      ),
    ) as unknown as typeof fetch;

    const app = createServer();
    const res = await request(app).get("/tools/get_stock_quote").query({ ticker: "amd" });

    expect(res.status).toBe(200);
    expect(res.body.ticker).toBe("AMD");
    expect(res.body.price).toBe(172.5);
    expect(res.body.cached).toBe(false);
  });

  it("returns 400 for a malformed ticker", async () => {
    const app = createServer();
    const res = await request(app).get("/tools/get_stock_quote").query({ ticker: "not a ticker!!" });

    expect(res.status).toBe(400);
    expect(res.body.error.code).toBe("INVALID_TICKER");
  });

  it("returns 404 when the upstream provider has no data for the ticker", async () => {
    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ c: 0, d: 0, dp: 0, t: 0 }), { status: 200 }),
    ) as unknown as typeof fetch;

    const app = createServer();
    const res = await request(app).get("/tools/get_stock_quote").query({ ticker: "ZZZZZZ" });

    expect(res.status).toBe(404);
    expect(res.body.error.code).toBe("UNKNOWN_TICKER");
  });
});
