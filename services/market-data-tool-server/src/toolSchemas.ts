/**
 * OpenAI-style function-calling tool definitions. The agent side fetches
 * these from GET /tools/schema at startup rather than hardcoding them here
 * and there, so the schema has one source of truth.
 */
export const toolSchemas = [
  {
    name: "get_stock_quote",
    description:
      "Get the current stock price, day change, and trading volume for a given ticker symbol. Use for questions about current/live price or today's move, not historical filings.",
    endpoint: { method: "GET", path: "/tools/get_stock_quote" },
    parameters: {
      type: "object",
      properties: {
        ticker: {
          type: "string",
          description: "Stock ticker symbol, e.g. 'AMD' or 'NVDA'",
        },
      },
      required: ["ticker"],
      additionalProperties: false,
    },
  },
  {
    name: "get_company_fundamentals",
    description:
      "Get current company fundamentals for a given ticker: market cap, P/E ratio, EPS, and sector. Use for present-day valuation questions, not historical filing language.",
    endpoint: { method: "GET", path: "/tools/get_company_fundamentals" },
    parameters: {
      type: "object",
      properties: {
        ticker: {
          type: "string",
          description: "Stock ticker symbol, e.g. 'AMD' or 'NVDA'",
        },
      },
      required: ["ticker"],
      additionalProperties: false,
    },
  },
] as const;
