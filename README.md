---
title: FinContext Agent
emoji: 📊
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# FinContext Agent

FinContext Agent is a production-oriented financial research application that turns filings and evidence into citation-grounded portfolio context. The backend is Go-first, with Python reserved for future offline parsing and evaluation workflows where its document/NLP ecosystem is useful.

The current implementation includes the production service boundaries now:

- **HuggingFace Space / web UI**: Next.js analyst console exported as static assets.
- **Agent API**: Go service for portfolio context, agent run orchestration, citation validation, SQLite persistence, Qdrant health/collection setup, and UI/API serving.
- **Inference Gateway**: Go service that exposes OpenAI-compatible model endpoints and routes logical FinContext model names to NVIDIA NIM.
- **Qdrant**: vector database service for production retrieval.
- **SQLite**: production metadata/run persistence for the Go Agent API.
- **NVIDIA NIM**: hosted LLM inference target behind the Gateway.

The app still ships curated JSON fixtures so the product can run deterministically before live EDGAR ingestion, embedding, and reranking are fully connected.

## Architecture

```tex
Browser / HuggingFace Space
  |
  v
Agent API (Go, :8090)
  ├─ serves exported Next.js UI
  ├─ orchestrates agent runs
  ├─ validates every citation id
  ├─ persists runs and seeded metadata in SQLite
  ├─ checks/initializes Qdrant collection
  └─ calls Inference Gateway for model work

Inference Gateway (Go, :8080)
  ├─ POST /v1/chat/completions -> NVIDIA NIM
  ├─ POST /v1/embeddings -> configured embedding backend
  ├─ POST /v1/rerank -> configured reranker backend
  ├─ GET /health
  └─ GET /metrics

Qdrant (:6333)
  └─ fincontext_chunks collection, 1024-dimensional cosine vectors

SQLite
  └─ agent_runs, portfolios, evidence_citations
```

## Services

### Agent API

Entrypoint: `backend/cmd/agent-api`

Endpoints:

- `GET /api/health`
- `GET /api/demo/portfolio`
- `POST /api/agent-runs`
- `GET /api/agent-runs/{run_id}`
- `GET /api/agent-runs/{run_id}/events`
- `GET /api/diff?ticker=AMD&section=Item%201A&from=2022&to=2025`
- `POST /api/chat`
- `GET /api/metrics`

### Inference Gateway

Entrypoint: `backend/cmd/inference-gateway`

Endpoints:

- `GET /health`
- `GET /metrics`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `POST /v1/rerank`

Logical chat model routing:

- `fincontext-planner` -> `NIM_PLANNER_MODEL`
- `fincontext-reasoner` -> `NIM_REASONER_MODEL`

### Market Data Tool Server

Entrypoint: `services/market-data-tool-server` (Node.js/TypeScript, Express)

Live market data (current price, day change, volume, market cap, P/E, EPS,
sector) is deliberately **not** part of the Go Agent API. It lives in its
own small Node service for three reasons:

1. **Different lifecycle.** Filing evidence is static, curated, and
   citation-validated; live quotes are ephemeral, third-party, rate-limited
   data with no filing citation behind them. Keeping them in separate
   services means a live-data provider outage or rate limit never touches
   filing retrieval or memo generation.
2. **No change to the model boundary.** Agent API code is not supposed to
   call external data providers directly — that's the Inference Gateway's
   job for model calls. A dedicated tool service keeps that boundary
   intact instead of bolting a third-party HTTP client onto Agent API.
3. **Isolation blast radius.** If the free-tier market data API changes its
   contract or gets rate-limited, only this one small service needs to
   change, and it fails independently (agent-api degrades gracefully, the
   same pattern already used for Qdrant).

**Endpoints:**

- `GET /tools/get_stock_quote?ticker=AMD` — price, day change, volume
- `GET /tools/get_company_fundamentals?ticker=AMD` — market cap, P/E, EPS, sector
- `GET /tools/schema` — OpenAI/LangGraph-style function-calling tool
  definitions (name, description, JSON Schema params) for both tools above
- `GET /health` — cache hit-rate stats + liveness

Responses are cached in-memory per ticker (`CACHE_TTL_SECONDS`, default 90s)
to stay under the free-tier provider's rate limit; the cache is a small
`Map`-backed TTL store with a swappable interface, so a Redis-backed cache
is a drop-in replacement if this needs to run as more than one instance.
The service also rate-limits its own inbound requests per IP.

**How the Go side talks to it:** `backend/internal/marketdata` is a thin
HTTP client (`Client.GetQuote`, `Client.GetFundamentals`,
`Client.FetchToolSchemas`). `FetchToolSchemas` is called at Agent API
startup so tool definitions are registered from the Node service's
`/tools/schema` response rather than hardcoded twice. Routing between
"this needs live data" vs. "this is a filing question" is a small keyword
heuristic in `marketdata.NeedsLiveMarketData`, used by
`provider.FixtureProvider` before it decides whether to call the tool
service in addition to citation-backed filing evidence — see
`backend/internal/provider/provider.go`. A tool call failure never fails
the chat answer; it just falls back to filing-only content, since every
factual memo claim still has to trace to a validated citation.

**Run it locally:**

```bash
cd services/market-data-tool-server
cp .env.example .env   # set FINNHUB_API_KEY (free tier: https://finnhub.io/register)
npm install
npm run dev
```

**Run the full stack (including this service) via docker-compose:** see
below — `market-data-tool-server` is wired into `infra/docker-compose.yml`
and `agent-api` picks it up via `MARKET_DATA_URL`.

## Local Production Stack

Create env config:

```bash
cp configs/.env.example .env
```

Start the production-shaped stack:

```bash
docker compose -f infra/docker-compose.yml --env-file .env up --build
```

Then open:

```text
http://localhost:8090
```

Health checks:

```bash
curl http://localhost:8090/api/health
curl http://localhost:8080/health
curl http://localhost:6333/healthz
```

## HuggingFace Space

The root `Dockerfile` builds one public container for HuggingFace Spaces. It runs the Go Agent API and serves the exported Next.js UI. For a single-container Space, Qdrant/Gateway/NIM can be external services configured by env vars:

```text
PORT=7860
FIXTURE_DIR=/app/data/fixtures
STATIC_DIR=/app/public
SQLITE_DB_PATH=/tmp/fincontext.db
QDRANT_URL=https://your-qdrant-host
INFERENCE_GATEWAY_URL=https://your-gateway-host
NIM_API_KEY=...
```

For production, prefer separate long-running services for Agent API, Inference Gateway, Qdrant, and embedding/reranker backends.

## Development

Backend tests:

```bash
cd backend
GOCACHE=../.gocache GOMODCACHE=../.gomodcache go test ./...
```

Run Gateway:

```bash
cd backend
PORT=8080 NIM_API_KEY=... go run ./cmd/inference-gateway
```

Run Agent API:

```bash
cd backend
FIXTURE_DIR=../data/fixtures \
SQLITE_DB_PATH=../fincontext.db \
QDRANT_URL=http://localhost:6333 \
INFERENCE_GATEWAY_URL=http://localhost:8080 \
go run ./cmd/agent-api
```

Frontend only:

```bash
cd apps/demo-ui
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8090 npm run dev
```

## Current Production Readiness

Implemented:

- Go Agent API service boundary
- Go Inference Gateway service boundary
- SQLite persistence for agent runs and seeded fixture metadata
- Qdrant health and collection initialization
- NIM-compatible chat proxy in the Gateway
- Embedding and reranker proxy routes in the Gateway
- Next.js analyst console
- Dockerfiles and Compose stack
- Citation fixture validation at startup

Still to build for full live production:

- EDGAR ingestion pipeline that writes chunks to SQLite and Qdrant
- Real embedding backend and reranker backend deployment
- Agent nodes that use retrieval results instead of curated fixtures
- Auth, rate limiting, tenant/user model, and production observability
- Public/private networking rules for Space -> Agent API -> Gateway/Qdrant

The fixture mode is now a bootstrap mode, not the target architecture.
