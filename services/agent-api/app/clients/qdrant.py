"""Qdrant-backed vector search helpers for filing evidence chunks.

This client checks Qdrant health, runs filtered similarity search against the
configured collection, and converts returned points into `ChunkRow` objects for
the retrieval pipeline.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from qdrant_client import AsyncQdrantClient
from fincontext_schemas import ChunkRow


class QdrantSearchClient:
    def __init__(
        self,
        url: str | None = None,
        collection: str | None = None,
    ) -> None:
        self.url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self.collection = collection or os.getenv("QDRANT_COLLECTION", "fincontext_chunks")

    async def health(self) -> dict[str, Any]:
        try:
            client = AsyncQdrantClient(url=self.url)
            collections = await client.get_collections()
            await client.close()
            return {"ok": True, "collections": len(collections.collections)}
        except Exception as exc:  # noqa: BLE001 - health endpoint reports dependency detail
            return {"ok": False, "error": str(exc)}

    async def search(
        self,
        vector: list[float],
        ticker: str,
        filing_types: list[str],
        date_start: str | None,
        date_end: str | None,
        sections: list[str],
        limit: int = 50,
    ) -> list[tuple[ChunkRow, float]]:
        return await asyncio.to_thread(
            self._search_sync,
            vector,
            ticker,
            filing_types,
            date_start,
            date_end,
            sections,
            limit,
        )

    def _search_sync(
        self,
        vector: list[float],
        ticker: str,
        filing_types: list[str],
        date_start: str | None,
        date_end: str | None,
        sections: list[str],
        limit: int,
    ) -> list[tuple[ChunkRow, float]]:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import DatetimeRange, FieldCondition, Filter, MatchAny, MatchValue
        except Exception:
            return []

        must: list[Any] = [FieldCondition(key="ticker", match=MatchValue(value=ticker))]
        if filing_types:
            must.append(FieldCondition(key="filing_type", match=MatchAny(any=filing_types)))
        if date_start or date_end:
            must.append(FieldCondition(key="filed_at", range=DatetimeRange(gte=date_start, lte=date_end)))
        if sections:
            must.append(FieldCondition(key="section", match=MatchAny(any=sections)))

        client = QdrantClient(url=self.url)
        try:
            # QdrantClient.search() was removed in qdrant-client 1.10+; the
            # replacement is query_points(), which wraps results in a
            # QueryResponse instead of returning the point list directly.
            points = client.query_points(
                collection_name=self.collection,
                query=vector,
                query_filter=Filter(must=must),
                limit=limit,
                with_payload=True,
            ).points
        except Exception:
            return []

        results: list[tuple[ChunkRow, float]] = []
        for point in points:
            payload = dict(point.payload or {})
            chunk_id = str(payload.get("chunk_id") or point.id)
            results.append(
                (
                    ChunkRow(
                        id=chunk_id,
                        document_id=str(payload.get("document_id", "")),
                        ticker=str(payload.get("ticker", ticker)),
                        filing_type=str(payload.get("filing_type", "")),
                        filed_at=str(payload.get("filed_at", "")),
                        section=str(payload.get("section", "")),
                        item_label=payload.get("item_label"),
                        section_title=payload.get("section_title"),
                        chunk_index=int(payload.get("chunk_index", 0)),
                        text=str(payload.get("text", "")),
                        text_hash=str(payload.get("text_hash", "")),
                        token_count=payload.get("token_count"),
                        citation_anchor=str(payload.get("citation_anchor", "")),
                        source_url=payload.get("source_url"),
                        is_table=1 if payload.get("is_table") else 0,
                        vector_id=chunk_id,
                        created_at="",
                    ),
                    float(point.score or 0.0),
                )
            )
        return results
