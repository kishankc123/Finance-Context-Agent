"""Hybrid retrieval pipeline for SEC filing evidence chunks.

This module turns a retrieval plan into citation-ready evidence by combining
SQLite BM25 search, Qdrant vector search, reciprocal rank fusion, reranking,
and section-diversity filtering before returning the top filing chunks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fincontext_schemas import EvidenceChunk, RetrievalPlan

from app.clients.db import SQLiteClient
from app.clients.gateway import InferenceGatewayClient
from app.clients.qdrant import QdrantSearchClient


@dataclass(frozen=True)
class RankedChunk:
    chunk: EvidenceChunk
    score: float


def to_evidence_chunk(row: object, score: float = 0.0) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=getattr(row, "id"),
        document_id=getattr(row, "document_id"),
        ticker=getattr(row, "ticker"),
        filing_type=getattr(row, "filing_type"),
        filed_at=getattr(row, "filed_at"),
        section=getattr(row, "section"),
        item_label=getattr(row, "item_label") or getattr(row, "section"),
        text=getattr(row, "text"),
        citation_anchor=getattr(row, "citation_anchor"),
        source_url=getattr(row, "source_url") or "",
        chunk_index=int(getattr(row, "chunk_index")),
        rerank_score=float(score),
    )


def reciprocal_rank_fusion(
    bm25_results: list[tuple[object, float]],
    vector_results: list[tuple[object, float]],
    k: int = 60,
) -> list[RankedChunk]:
    scores: dict[str, float] = {}
    chunks: dict[str, object] = {}
    for rank, (chunk, _score) in enumerate(bm25_results):
        chunk_id = getattr(chunk, "id")
        chunks[chunk_id] = chunk
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, (chunk, _score) in enumerate(vector_results):
        chunk_id = getattr(chunk, "id")
        chunks[chunk_id] = chunk
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return [
        RankedChunk(to_evidence_chunk(chunks[chunk_id], score), score)
        for chunk_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]


def apply_section_diversity(
    chunks: list[EvidenceChunk],
    max_per_section_per_ticker: int = 3,
    max_per_section_per_date: int = 2,
    limit: int = 12,
) -> list[EvidenceChunk]:
    # Two-level cap: (ticker, section) bounds the overall budget per section,
    # while (ticker, section, filed_at) stops one filing period's near-duplicate
    # boilerplate language from consuming the whole budget and crowding out
    # older periods the disclosure-drift diff step needs to compare against.
    counts: dict[tuple[str, str], int] = {}
    date_counts: dict[tuple[str, str, str], int] = {}
    selected: list[EvidenceChunk] = []
    for chunk in chunks:
        key = (chunk.ticker, chunk.section)
        date_key = (chunk.ticker, chunk.section, chunk.filed_at)
        if counts.get(key, 0) >= max_per_section_per_ticker:
            continue
        if date_counts.get(date_key, 0) >= max_per_section_per_date:
            continue
        selected.append(chunk)
        counts[key] = counts.get(key, 0) + 1
        date_counts[date_key] = date_counts.get(date_key, 0) + 1
        if len(selected) >= limit:
            break
    return selected


async def hybrid_retrieve(
    plan: RetrievalPlan,
    db: SQLiteClient | None = None,
    gateway: InferenceGatewayClient | None = None,
    qdrant: QdrantSearchClient | None = None,
    per_source_limit: int = 50,
    rerank_top_n: int = 20,
    final_limit: int = 12,
) -> list[EvidenceChunk]:
    db = db or SQLiteClient()
    gateway = gateway or InferenceGatewayClient()
    qdrant = qdrant or QdrantSearchClient()
    query = " ".join([plan.query, *plan.bm25_keywords]).strip() or plan.query

    async def retrieve_for_ticker(ticker: str) -> list[RankedChunk]:
        bm25_task = asyncio.to_thread(
            db.bm25_search,
            query,
            ticker,
            plan.filing_types,
            plan.date_range_start,
            plan.date_range_end,
            plan.sections,
            per_source_limit,
        )
        try:
            embedding = await gateway.embed(query)
            vector_task = qdrant.search(
                embedding,
                ticker,
                plan.filing_types,
                plan.date_range_start,
                plan.date_range_end,
                plan.sections,
                per_source_limit,
            )
            bm25_results, vector_results = await asyncio.gather(bm25_task, vector_task)
        except Exception:
            bm25_results = await bm25_task
            vector_results = []

        if not bm25_results and not vector_results:
            fallback = await asyncio.to_thread(
                db.recent_chunks,
                ticker,
                plan.filing_types,
                plan.date_range_start,
                plan.date_range_end,
                plan.sections,
                per_source_limit,
            )
            bm25_results = [(chunk, 0.0) for chunk in fallback]
        return reciprocal_rank_fusion(bm25_results, vector_results)

    ticker_results = await asyncio.gather(
        *(retrieve_for_ticker(ticker) for ticker in plan.target_tickers)
    )
    merged = [item for per_ticker in ticker_results for item in per_ticker]
    merged.sort(key=lambda item: item.score, reverse=True)
    candidates = [item.chunk for item in merged[:rerank_top_n]]

    try:
        reranked = await gateway.rerank(query, [chunk.text for chunk in candidates], rerank_top_n)
        ordered: list[EvidenceChunk] = []
        for index, score in reranked:
            if 0 <= index < len(candidates):
                ordered.append(candidates[index].model_copy(update={"rerank_score": score}))
        seen = {chunk.chunk_id for chunk in ordered}
        ordered.extend(chunk for chunk in candidates if chunk.chunk_id not in seen)
    except Exception:
        ordered = candidates

    return apply_section_diversity(ordered, limit=final_limit)
