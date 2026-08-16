# Dev Branch Status & Next Steps (Phase 2)

This document captures where the `dev` (Python + LangGraph) branch actually
stands as of this analysis, and the concrete steps to get it to a genuinely
working, end-to-end state before adding any new features.

## The simple version

Think of the project as an assembly line with 4 stations:

1. **Planner** — figures out what to look for based on the user's portfolio
2. **Retrieval** — pulls the relevant paragraphs from the filing
3. **Disclosure diff** — compares this year's wording to last year's, spots what changed
4. **Memo writer** — writes the final summary with citations

**The good news:** this assembly line is actually built and wired together
correctly in the code (real LangGraph graph, real node-to-node handoff, real
API endpoint that runs it and saves the result). That part works.

**The problem:** the shelves are empty. Before the assembly line can do
anything useful, it needs raw material — real filing text, chopped up and
stored so it can be searched. That step has never actually been run for a
real company. The code exists and is tested, but nobody has hit "go" on it
yet.

There's also a smaller blocker underneath: two of the stations need a
"translator" service — one that turns text into numbers a computer can
search (**embeddings**), and one that ranks search results (**reranking**).
Nothing is currently running to do that translation, so even loading the
shelves can't fully happen until this is turned on.

**Correct order of operations:**

1. Turn on the translator service (embeddings + reranking) — can run free, on your own machine
2. Load the shelves — run real filings through ingestion
3. Run the full assembly line against that real data and actually look at
   what it produces — this has never been done with real data, only fake
   test data

## Detailed status

### What's already working (verified in code)

- The LangGraph agent is real, not a stub. [`services/agent-api/app/graph.py`](../services/agent-api/app/graph.py)
  builds an actual `StateGraph` with 4 connected nodes: `portfolio_context_planner
  → filing_retrieval → disclosure_change → analyst_memo`, compiled and run via
  `.ainvoke()`. There is also a plain-async fallback path used only if the
  `langgraph` import fails — worth confirming you're on the real graph path,
  not silently falling back.
- `POST /api/analyze` in [`services/agent-api/main.py`](../services/agent-api/main.py)
  calls the graph and stores the resulting memo in
  `analysis_jobs.results_json`. `GET /api/findings` reads it back. Question-in
  → memo-out is a real, connected path.
- The Inference Gateway cleanly abstracts model backends
  ([`services/inference-gateway/router.py`](../services/inference-gateway/router.py)) —
  swapping the chat model provider later is a config change, not a rewrite.
- Ingestion code (parser, chunker, embedder, SQLite/Qdrant writer) is written
  and unit-tested.

### What's NOT actually done yet

1. **No real corpus has ever been ingested.** `services/ingestion-worker/ingest.py`
   has never been run end-to-end against real tickers. SQLite/Qdrant are
   currently empty of real filing data.
2. **The graph has never been run against real ingested data** — only against
   mocked/fallback state in tests. `TODO.md` explicitly leaves this unchecked.
   This is the real answer to "is the agent functional": functional in tests,
   unverified in reality.
3. **Nothing is running behind the embedding/reranker URLs.** The Gateway
   routes to `EMBEDDING_URL` / `RERANKER_URL` (default `localhost:8002` /
   `8003`), but no service is deployed there yet. This blocks step 1 above,
   since ingestion cannot produce embeddings without it.

### Infrastructure needed — paid vs. free

| Component | What it needs | Cost |
|---|---|---|
| Chat completions (planner + reasoner) | NIM via `NIM_API_KEY` | Free trial credit from build.nvidia.com, then paid. **Free swap available:** point the Gateway's `CHAT_MODEL_ROUTES` at a free OpenAI-compatible provider (Groq free tier, OpenRouter free models, or local Ollama) — no architecture change needed. |
| Embeddings (BGE-large-en-v1.5) | Service behind `EMBEDDING_URL` | Free — self-host with `sentence-transformers` in a small local FastAPI wrapper, runs fine on CPU at prototype scale. |
| Reranker (BGE-reranker-large) | Service behind `RERANKER_URL` | Free — same approach, self-hosted via `sentence-transformers` / `FlagEmbedding`. |
| Qdrant | Vector store | Free — Docker Compose locally, or Qdrant Cloud's free 1GB tier. |
| SQLite | Metadata store | Free, local file. |
| SEC EDGAR | Filing source | Free — no API key, just a compliant `SEC_USER_AGENT` header, stay under 10 req/s. |
| Agent API / Gateway hosting | Somewhere to run the FastAPI services | Free tiers exist for prototype scale (Render, Fly.io, Railway); real daily users eventually require paid hosting — not a now-problem. |
| Frontend | Static hosting | HuggingFace Spaces free static tier. |

**Bottom line:** the whole pipeline can be made to actually work for **$0**,
using NIM's free trial (or a free swap) plus self-hosted embeddings/reranker.
The only piece that's genuinely paid past a trial is NIM, and it's also the
easiest piece to swap out.

## Next steps — do these in order

### 1. Stand up the embedding + reranker services (free, local)

Create a small local service (or two) using `sentence-transformers` /
`FlagEmbedding` that exposes:

- `POST /v1/embeddings` — wraps `BAAI/bge-large-en-v1.5`, returns 1024-dim vectors
- `POST /v1/rerank` — wraps `BAAI/bge-reranker-large`

Run it on `localhost:8002` (embeddings) and `localhost:8003` (reranker) to
match `configs/.env.example` defaults, or update `EMBEDDING_URL` /
`RERANKER_URL` to wherever you run them.

### 2. Get a chat model backend working

Either:
- Sign up at build.nvidia.com and set `NIM_API_KEY` in `.env` (uses free trial credit), or
- Swap `services/inference-gateway/router.py`'s `CHAT_MODEL_ROUTES` to point at a free provider (Groq, OpenRouter, or local Ollama) instead of NIM.

### 3. Start storage services

```bash
cp configs/.env.example .env
# fill in NIM_API_KEY (or your swapped provider), SEC_USER_AGENT, etc.

docker compose -f infra/docker-compose.yml up -d qdrant
sqlite3 fincontext.db < infra/schema.sql
python3 infra/qdrant/init_collection.py
```

### 4. Start the Gateway and Agent API

```bash
cd services/inference-gateway
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080

# in a second terminal
cd services/agent-api
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8090
```

### 5. Run real ingestion (the "load the shelves" step)

Pick 1–2 real tickers (e.g. AMD, NVDA) and run:

```bash
cd services/ingestion-worker
python3 ingest.py --tickers AMD,NVDA --filing-types 10-K --years 2023,2024
```

### 6. Validate the ingestion actually worked

```bash
python3 validate_ingestion.py
```

Confirm SQLite `chunks` count roughly matches Qdrant point count, and
citation anchors look correctly formatted.

### 7. Run the real end-to-end test

Call `POST /api/analyze` with a real portfolio containing one of your
ingested tickers, then check `GET /api/findings/{portfolio_id}`. Read the
actual memo and citations it produces.

**This is the first point at which you can honestly say "the agent is
connected to LangGraph and functional against real data."** Everything
before this step has only ever been validated against test fixtures.

### 8. After that works

Only once step 7 produces a real, sane memo with real citations should new
features (on-demand ingestion, filing monitoring, exportable memos,
evaluation harness, etc.) be picked back up.
