"""
FinContext Agent API

This module defines the FastAPI application for the FinContext Agent. It
exposes HTTP endpoints to interact with the agent pipeline including:

- health: checks dependent services (inference gateway, Qdrant)
- portfolio upload: accepts CSV uploads and creates portfolio records
- analyze: starts background LangGraph analysis jobs
- job status: query analysis job progress and results
- documents/findings/diff: access retrieved filing chunks, findings, and diffs
- chat: stream a short analyst response from the analysis graph
- benchmark metrics: lightweight diagnostics for demo metrics

The API uses `SQLiteClient` for metadata and job storage, `InferenceGatewayClient`
to reach model services, `QdrantSearchClient` for vector retrieval, and the
`analyze` graph to run the 4-node pipeline (planning, retrieval, diff,
memo generation).

Analysis results are stored in `analysis_jobs.results_json` after completion so
that `GET /api/findings` can read cached state instead of re-running the graph.
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from fincontext_schemas import (
    AnalysisState,
    AnalyzeRequest,
    AnalyzeResponse,
    BenchmarkMetricsResponse,
    BenchmarkScenarios,
    ChatDoneEvent,
    ChatRequest,
    ChatStageEvent,
    ChatTokenEvent,
    DiffChange,
    DiffResponse,
    DisclosureChangeSummary,
    DocumentsResponse,
    EmbeddingMetrics,
    EvidenceEntry,
    FindingsMemo,
    FindingsResponse,
    JobStatusResponse,
    ModelMetrics,
    PortfolioExposure,
    PortfolioImpact,
    PortfolioUploadResponse,
    ProviderInfo,
    RecentRequests,
    RerankerMetrics,
    RiskDriver,
    FindingsRiskScore,
)

from app.clients.db import SQLiteClient, utc_now
from app.clients.gateway import InferenceGatewayClient
from app.clients.qdrant import QdrantSearchClient
from app.graph import analyze


app = FastAPI(title="FinContext Agent API", version="0.1.0")

# ---------------------------------------------------------------------------
# CORS — required for HuggingFace Static Space (browser) to reach this API
# ---------------------------------------------------------------------------
_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "https://*.hf.space,http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.hf\.space",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# ---------------------------------------------------------------------------
# Optional bearer-token auth via AGENT_API_KEY env var
# ---------------------------------------------------------------------------
_bearer = HTTPBearer(auto_error=False)
_AGENT_API_KEY = os.getenv("AGENT_API_KEY", "")


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Validate bearer token when AGENT_API_KEY is set. No-op when key is empty."""
    if not _AGENT_API_KEY:
        return
    if credentials is None or credentials.credentials != _AGENT_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

# ---------------------------------------------------------------------------
# CSV parsing helper
# ---------------------------------------------------------------------------

def parse_portfolio_csv(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"ticker", "market_value"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        missing = sorted(required - set(reader.fieldnames or []))
        raise HTTPException(status_code=400, detail=f"CSV is missing required columns: {missing}")
    rows = []
    for row in reader:
        if not row.get("ticker"):
            continue
        rows.append(row)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV did not contain any holdings.")
    return rows


# ---------------------------------------------------------------------------
# Findings response builder (shared between run_job and get_findings)
# ---------------------------------------------------------------------------

def _build_findings_response(portfolio_id: str, job_id: str, analyzed_at: str, state: AnalysisState) -> FindingsResponse:
    """Build a FindingsResponse from a completed AnalysisState."""
    memo = state.memo
    if memo is None:
        raise HTTPException(status_code=404, detail="Analysis completed but no memo was generated.")

    risk_scores = [
        FindingsRiskScore(
            ticker=score.ticker,
            overall_score=score.score,
            score_delta=score.delta,
            confidence=score.confidence,
            drivers=[
                RiskDriver(
                    category="disclosure_change",
                    score=score.score,
                    summary=driver,
                    citation=score.citations[0].citation_anchor if score.citations else "",
                )
                for driver in score.top_drivers
            ],
            portfolio_impact=PortfolioImpact(
                holding_weight=next(
                    (h.weight for h in state.holdings if h.ticker == score.ticker), 0.0
                ),
                sector_weight=next(
                    (h.weight for h in state.holdings if h.ticker == score.ticker), 0.0
                ),
                exposure_level=score.portfolio_impact,
            ),
        )
        for score in state.risk_scores
    ]

    memo_response = FindingsMemo(
        executive_summary=memo.executive_summary,
        portfolio_exposure_affected=[
            PortfolioExposure(
                ticker=h.ticker,
                weight=h.weight,
                exposure_level="high" if h.weight >= 0.2 else "medium" if h.weight >= 0.1 else "low",
            )
            for h in state.holdings
        ],
        top_disclosure_changes=[
            DisclosureChangeSummary(
                ticker=change.ticker,
                section=change.section,
                change_type=change.change_type,
                materiality="high" if change.severity >= 0.66 else "medium" if change.severity >= 0.33 else "low",
                summary=change.summary,
                new_citation=change.new_citation.citation_anchor if change.new_citation else "",
                old_citation_anchor=change.old_citation.citation_anchor if change.old_citation else None,
                new_citation_anchor=change.new_citation.citation_anchor if change.new_citation else None,
            )
            for change in state.disclosure_changes
        ],
        evidence_table=[
            EvidenceEntry(
                citation_id=citation.chunk_id,
                citation_anchor=citation.citation_anchor,
                source_url=citation.source_url,
            )
            for citation in memo.evidence_table
        ],
        watchlist_questions=memo.watchlist_questions,
        limitations=memo.limitations,
        confidence=memo.citation_pass_rate,
        disclaimer=memo.disclaimer,
    )

    return FindingsResponse(
        portfolio_id=portfolio_id,
        job_id=job_id,
        analyzed_at=analyzed_at,
        risk_scores=risk_scores,
        memo=memo_response,
    )


# ---------------------------------------------------------------------------
# Background job runner — stores results_json so findings never re-run graph
# ---------------------------------------------------------------------------

async def run_job(job_id: str, request: AnalyzeRequest) -> None:
    db = SQLiteClient()
    try:
        await asyncio.to_thread(
            db.update_job,
            job_id,
            status="running",
            stage="planning",
            progress=0.05,
            started_at=utc_now(),
        )
        state = AnalysisState(
            user_id="demo",
            portfolio_id=request.portfolio_id,
            question=request.question,
        )
        result = await analyze(state)
        completed_at = utc_now()
        # Persist the full analysis state so GET /api/findings reads from DB, not graph.
        results_json = result.model_dump_json()
        await asyncio.to_thread(db.store_results, job_id, results_json)
        await asyncio.to_thread(
            db.update_job,
            job_id,
            status="completed" if not result.error else "failed",
            stage="complete",
            progress=1.0,
            citation_pass_rate=result.citation_pass_rate,
            findings_count=len(result.disclosure_changes),
            error=result.error,
            completed_at=completed_at,
        )
    except Exception as exc:  # noqa: BLE001 - background jobs must persist failures
        await asyncio.to_thread(
            db.update_job,
            job_id,
            status="failed",
            stage="complete",
            progress=1.0,
            error=str(exc),
            completed_at=utc_now(),
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    gateway_status: dict[str, Any]
    try:
        async with InferenceGatewayClient(timeout=5.0) as gateway:
            gateway_status = await gateway.health()
    except Exception as exc:  # noqa: BLE001 - health endpoint reports dependency detail
        gateway_status = {"ok": False, "error": str(exc)}
    qdrant_status = await QdrantSearchClient().health()
    return {"ok": True, "service": "agent-api", "gateway": gateway_status, "qdrant": qdrant_status}


@app.post("/api/portfolio/upload", response_model=PortfolioUploadResponse)
async def upload_portfolio(
    file: UploadFile = File(...),
    _auth: None = Depends(require_auth),
) -> PortfolioUploadResponse:
    rows = parse_portfolio_csv(await file.read())
    portfolio_id = await asyncio.to_thread(
        SQLiteClient().create_portfolio, file.filename or "Uploaded Portfolio", rows
    )
    total = sum(float(row.get("market_value") or 0.0) for row in rows)
    tickers = [str(row["ticker"]).upper() for row in rows]
    return PortfolioUploadResponse(
        portfolio_id=portfolio_id,
        name=file.filename or "Uploaded Portfolio",
        holdings_count=len(rows),
        total_value=total,
        tickers=tickers,
        missing_cik=[],
        status="ready",
    )


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def start_analysis(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    _auth: None = Depends(require_auth),
) -> AnalyzeResponse:
    db = SQLiteClient()
    job_id = await asyncio.to_thread(
        db.create_job,
        request.portfolio_id,
        request.analysis_type,
        request.question,
    )
    background_tasks.add_task(run_job, job_id, request)
    return AnalyzeResponse(
        job_id=job_id,
        portfolio_id=request.portfolio_id,
        status="queued",
        created_at=utc_now(),
    )


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    row = await asyncio.to_thread(SQLiteClient().get_job, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    duration = None
    if row.get("started_at") and row.get("completed_at"):
        started = datetime.fromisoformat(row["started_at"])
        completed = datetime.fromisoformat(row["completed_at"])
        duration = (completed - started).total_seconds()
    return JobStatusResponse(
        job_id=row["id"],
        portfolio_id=row["portfolio_id"],
        status=row["status"],
        created_at=row["created_at"],
        stage=row["stage"],
        progress=float(row["progress"] or 0.0),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        error=row["error"],
        duration_seconds=duration,
        citation_pass_rate=row["citation_pass_rate"],
        findings_count=row["findings_count"],
    )


@app.get("/api/documents/{ticker}", response_model=DocumentsResponse)
async def list_documents(ticker: str) -> DocumentsResponse:
    documents = await asyncio.to_thread(SQLiteClient().list_documents, ticker.upper())
    return DocumentsResponse(ticker=ticker.upper(), documents=documents)


@app.get("/api/findings/{portfolio_id}", response_model=FindingsResponse)
async def get_findings(portfolio_id: str) -> FindingsResponse:
    """Return analysis findings from the cached results_json — never re-runs the graph."""
    db = SQLiteClient()
    job = await asyncio.to_thread(db.latest_job_for_portfolio, portfolio_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No analysis job found for this portfolio.")

    if job.get("status") not in ("completed", "failed"):
        raise HTTPException(
            status_code=202,
            detail=f"Analysis is still in progress (stage: {job.get('stage', 'unknown')}).",
        )

    results_json = await asyncio.to_thread(db.load_results, job["id"])
    if not results_json:
        raise HTTPException(
            status_code=404,
            detail="Analysis completed but no results were stored. Re-run the analysis.",
        )

    state = AnalysisState.model_validate_json(results_json)
    return _build_findings_response(
        portfolio_id=portfolio_id,
        job_id=job["id"],
        analyzed_at=job.get("completed_at") or utc_now(),
        state=state,
    )


@app.get("/api/diff/{ticker}", response_model=DiffResponse)
async def get_diff(
    ticker: str,
    section: str = "Item 1A",
    year_a: str = "",
    year_b: str = "",
    filing_type: str = "10-K",
) -> DiffResponse:
    db = SQLiteClient()
    chunks = await asyncio.to_thread(
        db.recent_chunks,
        ticker.upper(),
        [filing_type],
        f"{year_a}-01-01" if year_a else None,
        f"{year_b}-12-31" if year_b else None,
        [section],
        12,
    )
    changes: list[DiffChange] = []
    if len(chunks) >= 2:
        old = chunks[-1]
        new = chunks[0]
        changes.append(
            DiffChange(
                change_type="intensified_language" if old.text != new.text else "boilerplate",
                materiality="medium",
                confidence=0.35,
                summary="Diff endpoint found comparable filing chunks. Run full analysis for LLM classification.",
                old_text=old.text,
                new_text=new.text,
                old_citation_anchor=old.citation_anchor,
                new_citation_anchor=new.citation_anchor,
                old_source_url=old.source_url,
                new_source_url=new.source_url,
            )
        )
    return DiffResponse(
        ticker=ticker.upper(),
        section=section,
        filing_type=filing_type,
        year_a=year_a,
        year_b=year_b,
        changes=changes,
    )


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    _auth: None = Depends(require_auth),
) -> StreamingResponse:
    async def events() -> Any:
        yield ChatStageEvent(stage="planning").model_dump_json() + "\n\n"
        state = await analyze(
            AnalysisState(
                user_id="demo",
                portfolio_id=request.portfolio_id,
                question=request.question,
            )
        )
        yield ChatStageEvent(stage="complete").model_dump_json() + "\n\n"
        text = (
            state.memo.executive_summary
            if state.memo
            else state.error or "No answer available."
        )
        yield ChatTokenEvent(text=text).model_dump_json() + "\n\n"
        yield ChatDoneEvent(citation_pass_rate=state.citation_pass_rate or 0.0).model_dump_json() + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/benchmark/metrics", response_model=BenchmarkMetricsResponse)
async def benchmark_metrics() -> BenchmarkMetricsResponse:
    empty_model = ModelMetrics(
        count=0,
        avg_input_tokens=0,
        avg_output_tokens=0,
        avg_time_to_first_token_ms=0,
        avg_total_latency_ms=0,
        avg_tokens_per_second=0,
    )
    # These are truthful placeholders until this endpoint aggregates live
    # Gateway /metrics output. Do not present zero values as measured results.
    recent_requests = RecentRequests.model_validate(
        {
            "fincontext-reasoner": empty_model,
            "fincontext-planner": empty_model,
            "embedding": EmbeddingMetrics(count=0, avg_batch_size=0, avg_latency_ms=0),
            "reranker": RerankerMetrics(count=0, avg_candidates=0, avg_latency_ms=0),
        }
    )
    return BenchmarkMetricsResponse(
        provider_info=ProviderInfo(
            provider="nvidia-nim",
            base_url=os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            status="configured" if os.getenv("NIM_API_KEY") else "missing_nim_api_key",
        ),
        recent_requests=recent_requests,
        benchmark_scenarios=BenchmarkScenarios(
            single_10k_analysis_seconds=0.0,
            five_stock_portfolio_seconds=0.0,
            interactive_qa_seconds=0.0,
        ),
    )
