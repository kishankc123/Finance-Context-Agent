# Project Assessment: FinContext Agent

Date: 2026-10-02. Goal: deploy the project as a public portfolio demo covering 20–25 tickers.

Figures marked "estimate" are scaled from the real ingestion run (4 filings, 254 chunks, ~63 chunks per 10-K) and have not been measured at full scale.

## 1. What is done

- **Agent API (FastAPI):** portfolio upload, analyze, and job-status endpoints; optional bearer-token auth (`AGENT_API_KEY`); CORS configured for the browser demo.
- **Analysis workflow (LangGraph):** four nodes in sequence: planner, filing retrieval, disclosure change, analyst memo. Orchestration is in `services/agent-api/app/graph.py`. Parallelism lives inside nodes via `asyncio.gather` / `asyncio.to_thread` (per-ticker retrieval, per-pair classification).
- **Hybrid retrieval:** BM25 (SQLite FTS5) + Qdrant vector search, reciprocal rank fusion, reranking, section-diversity filtering. Repaired end to end in a recent commit.
- **Ingestion worker:** resolves tickers to CIKs, downloads EDGAR HTML, extracts Items 1, 1A, 7, 7A, 8, chunks with citation anchors, embeds via the Gateway, writes to Qdrant and SQLite. Rate-limited to 10 requests/second with the required SEC User-Agent. Validated on real data.
- **Inference Gateway:** single entry point for all model calls (NVIDIA NIM chat, embeddings, reranking).
- **Embedding service:** local embedding/reranker FastAPI service exists.
- **Demo UI:** Vite React app in `apps/demo-ui/` that calls only the Agent API.
- **Compliance rules:** citations on every factual claim, no investment recommendations, mandatory disclaimer, risk scores with confidence and citations.

Current data: `fincontext.db` holds 4 filings (AAPL and MSFT, 2 10-Ks each) and 254 chunks (1.7 MB).

## 2. What is not done

1. Ingest 20–25 tickers (only 2 ingested so far).
2. Choose the demo portfolio and make sure `demo/seed_portfolio.csv` tickers match the ingested set.
3. Provision a server (VM, Docker, persistent disk).
4. Verify NIM end to end with real credentials through the Gateway.
5. Set up HTTPS, firewall, and rate limiting.
6. Publish the React UI as a public site.
7. Run one full analysis on the deployed copy and check that memo citations map to real chunks.

## 3. Ingestion sizing for 20–25 tickers (estimate)

| Item | Estimate |
|---|---|
| Filings | ~350–400 (4 10-Ks + 12 10-Qs per ticker, 4 years) |
| Chunks | ~12–15k |
| Embedding volume | ~15M tokens |
| Storage | ~60 MB vectors + ~60 MB SQLite, under 1 GB total |
| SEC download | a few minutes at 10 requests/second |
| Total time | ~30–60 minutes, mostly parsing and embedding |

The worker processes tickers sequentially (`ingest.py`, `for ticker in tickers`). That is acceptable at this size. Re-runs skip work already done (dedup by `text_hash` plus local cache). Add concurrency only if scaling well beyond 50 tickers.

Suggested ticker mix: about 5 sectors with 4–5 names each (for example tech, banks, pharma, energy, retail), so same-sector disclosure drift is comparable.

## 4. Local vs live

| Area | Local | Live |
|---|---|---|
| Hosting | Laptop | Always-on VM |
| Data | Local `fincontext.db` and Qdrant | Same, on persistent disk with backups |
| Embeddings / reranking | Local models | Hosted embedding API or a GPU box (key decision) |
| Addresses | `localhost` | Public HTTPS for the Agent API only; Gateway, Qdrant, SQLite private |
| Security | Not reachable by others | Firewall, rate limiting, CORS limited to the UI domain |
| Cost | Free | VM rent plus NIM usage (each analysis makes several paid calls) |
| Secrets | Local `.env` | Server environment variables, never committed |
| Ingestion | Run by hand | Run once before launch, not live during the demo |

## 5. Risks

- **API key in a static site.** If the UI is static and the API requires `AGENT_API_KEY`, the key ships in the browser bundle. Use rate limits and a spending cap, or a small proxy that holds the key.
- **Embedding consistency.** Stored vectors and live query embeddings must come from the same model. Changing providers at deployment means re-ingesting everything.
- **Cost exposure.** A public demo can drive up NIM spend. Set a hard cap.

## 6. Suggested order

1. Decide the embedding approach (hosted API or self-run).
2. Pick the 20–25 tickers and update the seed portfolio.
3. Provision one VM; run Qdrant, Gateway, and Agent API with Docker.
4. Smoke-test ingestion with 2 tickers on the server, then ingest the rest and run `validate_ingestion.py`.
5. Add HTTPS, rate limits, and a spending cap.
6. Publish the UI and run one full end-to-end analysis.

## Overall

The code is ahead of the deployment. The remaining work is mostly infrastructure and data, not new features.
