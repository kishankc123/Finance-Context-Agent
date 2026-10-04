# FinContext Agent

FinContext Agent is an AMD Developer Hackathon 2026 project for Track 1:
AI Agents and Agentic Workflows.

The project turns SEC filings into citation-grounded portfolio analysis. It
pre-ingests 10-K and 10-Q filings from EDGAR, detects changes in disclosure
language over time, scores holding-level risk, and produces analyst-style memos
that cite exact filing chunks.

This repository is no longer a collection of project ideas. It is the working
repo for the FinContext Agent MVP.

## What The Product Does

A user uploads a portfolio such as:

```text
AMD, NVDA, MSFT, JPM, TSLA
```

The system then answers questions like:

```text
What changed in supply-chain or customer concentration risk for my semiconductor holdings?
```

The answer should not be generic. It should point to evidence from SEC filings,
for example:

```text
AMD 10-K Item 1A paragraph 42
```

The required disclaimer is:

```text
This output is research assistance only and does not constitute investment advice.
```

The system never gives buy, sell, hold, or short recommendations.

## Why Hosted Inference

The prototype does not need to own 70B-class GPU serving. We tested AMD
Developer Cloud, but the available credit was not enough for comfortable
development and demo rehearsal with a 70B model. The final MVP uses NVIDIA NIM
hosted chat completions behind the Inference Gateway.

The model split is:

- Qwen2.5-14B for planning and disclosure-change classification.
- Qwen2.5-72B for the final analyst memo only.
- BAAI/bge-large-en-v1.5 for embeddings.
- BAAI/bge-reranker-large for reranking retrieval candidates.

The important architecture point is the Gateway contract: Agent API and
ingestion code call one local Gateway, and the Gateway handles provider routing,
request IDs, latency metrics, retries, and normalized errors.

## System Architecture

Everything application-specific runs on one lightweight backend host:

```text
HuggingFace Space
  React Static Space UI
    |
    v
Backend host
  Agent API, port 8090
    FastAPI plus LangGraph workflow
    |
    v
  Inference Gateway, port 8080
    Routes all model, embedding, and rerank calls
    |
    +-- NVIDIA NIM hosted chat completions
    +-- Embedding backend, port 8002
    +-- Reranker backend, port 8003
    +-- Qdrant vector store, port 6333
    +-- SQLite file, fincontext.db
```

Important rule: Agent API code and ingestion code call the Inference Gateway.
They do not call NVIDIA NIM, embedding backends, or reranker backends directly.

## Run The Whole App Locally

The local app has five running processes plus one SQLite file:

| Component         | Command           | Port                          |
| ------------------ | ----------------- | ----------------------------- |
| Qdrant             | Docker Compose    | `6333`                        |
| Embedding Service  | FastAPI / Uvicorn | `8002`                        |
| Inference Gateway  | FastAPI / Uvicorn | `8080`                        |
| Agent API          | FastAPI / Uvicorn | `8090`                        |
| React UI           | Vite              | shown by Vite, usually `5173` |
| SQLite             | local file        | no server process             |

### Quick Start

Once `.env` is configured (step 1 below) and each service's `requirements.txt`
is installed into its venv (steps 4-5), `scripts/dev_up.sh` starts Qdrant, the
embedding service, and the Inference Gateway together:

```bash
chmod +x scripts/dev_up.sh scripts/dev_down.sh   # one-time
./scripts/dev_up.sh
```

It waits for each service's health endpoint before starting the next, and
skips anything already running. Logs land in `.run/<service>.log`, PIDs in
`.run/<service>.pid`. Stop everything it started with:

```bash
./scripts/dev_down.sh
```

(Qdrant is a Docker container, not a process this script owns, so it's left
running — stop it separately with `docker compose -f infra/docker-compose.yml
stop qdrant` if you want it down too.)

You still start the Agent API, React UI, and ingestion worker yourself (steps
6, 7, and "Ingest Filing Data" below) since those aren't part of the shared
dev stack. The manual steps below are what `dev_up.sh` automates, useful if
you want to run a service in the foreground to watch its logs directly.

### 1. Configure Environment

```bash
cp configs/.env.example .env
```

Set these values in `.env`:

```bash
NIM_API_KEY=your-nim-api-key
NIM_BASE_URL=https://integrate.api.nvidia.com/v1
SEC_USER_AGENT=FinContextAgent/0.1 your-email@example.com
AGENT_API_KEY=your-local-dev-token
```

`NIM_API_KEY` is required for planner and reasoner chat completions. Do not
commit `.env`. `AGENT_API_KEY` is a local environment key, you don't need to put into production. Generate one for you using `openssl rand -hex 32`.

### 2. Start Qdrant

From the repo root:

```bash
docker compose -f infra/docker-compose.yml up -d qdrant
curl http://localhost:6333/healthz
```

### 3. Create SQLite DB And Qdrant Collection

```bash
sqlite3 fincontext.db < infra/schema.sql
python3 infra/qdrant/init_collection.py
```

This creates the local metadata DB and the `fincontext_chunks` Qdrant
collection.

### 4. Start Embedding Service

Each service keeps its own virtualenv (`.venv-embeddings`, `.venv-gateway`,
`.venv-agent-api`, `.venv-ingestion`) so one service's dependency changes don't
break another. Create the venv once, then reuse it.

In a new terminal, from the repo root:

```bash
python3 -m venv .venv-embeddings
source .venv-embeddings/bin/activate
cd services/embedding-service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8002
```

First startup takes a bit longer while it downloads/loads the
`BAAI/bge-large-en-v1.5` and reranker models locally. Check it:

```bash
curl http://localhost:8002/docs
```

The Gateway proxies embedding/rerank calls here via `EMBEDDING_URL` /
`RERANKER_URL` in `.env` — start this before the Gateway.

### 5. Start Inference Gateway

In a new terminal, from the repo root:

```bash
python3 -m venv .venv-gateway
source .venv-gateway/bin/activate
cd services/inference-gateway
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Check it:

```bash
curl http://localhost:8080/health
```

### 6. Start Agent API

In a new terminal, from the repo root:

```bash
python3 -m venv .venv-agent-api
source .venv-agent-api/bin/activate
cd services/agent-api
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8090 --reload
```

Check it:

```bash
curl http://localhost:8090/health
```

### 7. Start React UI

In a new terminal:

```bash
cd apps/demo-ui
npm install
VITE_AGENT_API_URL=http://localhost:8090 npm run dev
```

Open the local Vite URL printed in the terminal, usually:

```text
http://localhost:5173
```

The UI can show sample data without the backend, but real analysis requires
Qdrant, SQLite, Inference Gateway, Agent API, NIM credentials, and configured
embedding/reranker backends to be working. NIM handles chat completions only in
the current code; document embeddings and reranking still go through the
Gateway to `EMBEDDING_URL` and `RERANKER_URL`.

## Ingest Filing Data

Before the UI can answer real questions, SQLite and Qdrant need filings in
them. This is a one-shot CLI you run yourself, not a live-demo path — see
`docs/ingestion-output-contract.md` for what it writes.

Requires Qdrant and the embedding service + Inference Gateway running (steps
above, or `./scripts/dev_up.sh`):

```bash
python3 -m venv .venv-ingestion
source .venv-ingestion/bin/activate
cd services/ingestion-worker
pip install -r requirements.txt
python ingest.py --tickers AAPL,MSFT --filing-types 10-K,10-Q --years 4
```

`SEC_USER_AGENT` loads automatically from the repo-root `.env` (via
`python-dotenv`) — no need to `export` it manually. It must identify your app
and include a real contact email, per SEC's fair-access policy.

Re-running the same command is safe: chunks are deduplicated by content hash,
so it only ingests what's missing (new tickers, or filings from a previous
run that failed partway through).

## Current Build State

Merged into `dev`:

- Shared schema package under `packages/schemas`.
- SQLite schema under `infra/schema.sql`.
- Qdrant collection init script.
- Ingestion worker foundation, validation CLI, and handoff export.
- Inference Gateway with NVIDIA NIM chat routing plus embedding/rerank proxy routes.
- Agent API endpoints, result cache, retrieval pipeline, and MVP LangGraph nodes.
- React Static Space demo UI with sample fallbacks and Agent API client.
- Demo-data backup and snapshot ops.
- Human-readable handoff and ingestion output contract docs.
- CI for Python services, frontend tests/build, and repository policy checks.

Open or pending:

- Real backend host deployment has not been verified.
- NIM credentials have not been validated through a live Gateway run.
- Embedding and reranker backends still need to be configured and tested.
- Real backend host ingestion has not run yet.
- Demo corpus has not been loaded into Qdrant/SQLite yet.
- HuggingFace Static Space has not been verified against a live public Agent API.

## Repository Map

```text
services/
  ingestion-worker/      EDGAR fetch, SEC HTML parse, chunk, embed, write data
  inference-gateway/     FastAPI proxy to NIM, embeddings, and reranker
  agent-api/             FastAPI plus LangGraph analysis workflow

apps/
  demo-ui/               Vite React UI for HuggingFace Static Spaces

packages/
  schemas/               Shared Pydantic state, DB, and API contracts
  evals/                 Retrieval/diff/citation benchmark docs and fixtures

scripts/
  dev_up.sh              Start Qdrant, embedding service, Inference Gateway
  dev_down.sh            Stop services started by dev_up.sh

infra/
  schema.sql             SQLite tables, indexes, and FTS5 triggers
  docker-compose.yml     Lightweight prototype services, currently Qdrant
  qdrant/                Qdrant collection initialization
  ops/                   Demo backup and snapshot helpers

docs/
  architecture.md
  agent-design.md
  data-and-retrieval.md
  ingestion-output-contract.md
  fincontext-agent-explained.md
```

## Start Here If You Are New

Read these in order:

1. `docs/fincontext-agent-explained.md`
2. `docs/codex-work-handoff.md`
3. `docs/ingestion-output-contract.md`
4. `docs/architecture.md`
5. `TODO.md`

The first document explains the project from the ground up. The handoff doc
explains what was built by agents and why. The ingestion output contract tells
Kishan and retrieval/UI work exactly what data exists after ingestion.

## Ingestion In Plain English

Ingestion means: before the live demo, we download SEC filings and turn them
into searchable evidence.

The ingestion worker does this:

1. Resolve a ticker like `AMD` to its SEC CIK.
2. Fetch the company's filing list from EDGAR.
3. Download recent 10-K and 10-Q HTML filings.
4. Parse sections like Item 1A Risk Factors.
5. Split long sections into smaller chunks.
6. Give every chunk a citation anchor.
7. Send chunk text to the Inference Gateway for embeddings.
8. Store chunk text in SQLite for keyword search.
9. Store vectors in Qdrant for semantic search.

That is why Kishan can later retrieve and rerank chunks. The data is already
shaped for retrieval.

## Retrieval In Plain English

Retrieval means: given a question, find the most relevant SEC filing chunks.

The intended retrieval flow is:

1. Turn the user's question into an embedding.
2. Search Qdrant for semantically similar chunks.
3. Search SQLite FTS5 for keyword/BM25 matches.
4. Merge those candidate lists with Reciprocal Rank Fusion.
5. Send candidate chunk texts to the Gateway reranker.
6. Return the best chunks with text, source URL, and citation anchor.

Kishan's "ranking" work is mainly steps 4 and 5.

## Local Checks

Run focused checks for the parts that already exist. Install each service's
requirements first if the local environment does not already have them.

```bash
python3 -m pytest services/ingestion-worker/tests -x
python3 -m pytest services/inference-gateway/tests -x
python3 -m pytest infra/tests -x
```

Some future tests will require the backend host, Qdrant, Gateway, or live model
services. The current foundation tests mostly use mocked HTTP and temporary
SQLite files.

```bash
python3 -m pytest packages/evals/tests -x
```

## Branch And PR Rules

- Branch from `dev`.
- Open PRs back into `dev`.
- Do not commit directly to `dev` or `main`.
- Do not self-merge without teammate review.
- Do not commit `.env`, `fincontext.db`, Qdrant storage, model cache, or secrets.
- Commit messages should be atomic, for example:

```text
feat(ingestion): add validation CLI
docs(project): add beginner explainer
eval(evals): add retrieval fixture scaffolding
```

## Useful Docs

| Document                             | Purpose                                       |
| ------------------------------------ | --------------------------------------------- |
| `docs/fincontext-agent-explained.md` | Beginner-friendly full project explanation    |
| `docs/codex-work-handoff.md`         | What agent-built branches added and why       |
| `docs/ingestion-output-contract.md`  | SQLite/Qdrant fields used by retrieval and UI |
| `docs/data-and-retrieval.md`         | Retrieval architecture and Qdrant/BM25 design |
| `docs/agent-design.md`               | LangGraph node specs                          |
| `docs/api-contracts.md`              | Agent API request and response contracts      |
| `docs/demo-data-ops.md`              | SQLite backup and Qdrant snapshot commands    |
| `docs/demo-plan.md`                  | Judge-facing demo flow                        |
