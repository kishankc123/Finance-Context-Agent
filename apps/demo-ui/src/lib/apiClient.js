/**
 * Agent API client for the browser UI.
 *
 * This is the only network boundary in the React frontend. It talks to Agent
 * API endpoints only and never bypasses the backend to reach storage, EDGAR,
 * model servers, the Inference Gateway, or embedding/rerank services.
 */

export class ApiError extends Error {
  constructor(message, { status = 0, payload = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export class AgentApiClient {
  constructor({ baseUrl, fetchImpl = (...args) => fetch(...args) }) {
    this.baseUrl = baseUrl;
    this.fetch = fetchImpl;
  }

  health() {
    return this.request("/health");
  }

  uploadPortfolio(file, portfolioName) {
    const body = new FormData();
    body.append("file", file);
    if (portfolioName) {
      body.append("name", portfolioName);
    }
    return this.request("/api/portfolio/upload", { method: "POST", body });
  }

  startAnalysis({ portfolioId, question }) {
    return this.request("/api/analyze", {
      method: "POST",
      json: { portfolio_id: portfolioId, question },
    });
  }

  getJob(jobId) {
    return this.request(`/api/jobs/${encodeURIComponent(jobId)}`);
  }

  getFindings(portfolioId) {
    return this.request(`/api/findings/${encodeURIComponent(portfolioId)}`);
  }

  getDiff(ticker, params = {}) {
    return this.request(`/api/diff/${encodeURIComponent(ticker)}${queryString(params)}`);
  }

  getDocuments(ticker, params = {}) {
    return this.request(`/api/documents/${encodeURIComponent(ticker)}${queryString(params)}`);
  }

  getBenchmarkMetrics() {
    return this.request("/api/benchmark/metrics");
  }

  async request(path, { method = "GET", json, body } = {}) {
    const headers = {};
    let requestBody = body;

    if (json !== undefined) {
      headers["Content-Type"] = "application/json";
      requestBody = JSON.stringify(json);
    }

    let response;
    try {
      response = await this.fetch(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: requestBody,
      });
    } catch (error) {
      throw new ApiError(`Agent API is unreachable at ${this.baseUrl}`, {
        payload: { cause: error?.message },
      });
    }

    const payload = await readPayload(response);
    if (!response.ok) {
      throw new ApiError(extractErrorMessage(payload, response.status), {
        status: response.status,
        payload,
      });
    }
    return payload;
  }
}

export function queryString(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function extractErrorMessage(payload, status) {
  if (payload?.error?.message) {
    return payload.error.message;
  }
  if (payload?.detail) {
    return typeof payload.detail === "string"
      ? payload.detail
      : JSON.stringify(payload.detail);
  }
  return `Agent API request failed with HTTP ${status}`;
}

async function readPayload(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { text };
  }
}
