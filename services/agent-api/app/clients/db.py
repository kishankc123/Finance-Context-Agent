"""SQLite-backed persistence helpers for portfolios, filings, and jobs.

This client opens the configured SQLite database and provides read/write
helpers for portfolio holdings, chunk and document lookup, full-text search,
portfolio creation, and analysis job tracking.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from fincontext_schemas import ChunkRow, DocumentSummary, Holding, HoldingRow


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteClient:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv("SQLITE_DB_PATH", "./fincontext.db")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def load_holdings(self, portfolio_id: str) -> list[Holding]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM holdings
                WHERE portfolio_id = ?
                ORDER BY COALESCE(weight, 0) DESC, market_value DESC
                """,
                (portfolio_id,),
            ).fetchall()
        total = sum(float(row["market_value"] or 0.0) for row in rows) or 1.0
        holdings: list[Holding] = []
        for row in rows:
            weight = row["weight"] if row["weight"] is not None else float(row["market_value"] or 0.0) / total
            holdings.append(
                Holding(
                    ticker=str(row["ticker"]).upper(),
                    name=row["company_name"] or str(row["ticker"]).upper(),
                    weight=float(weight or 0.0),
                    sector=row["sector"] or "Unknown",
                    shares=float(row["shares"] or 0.0),
                    avg_cost=float(row["cost_basis"] or 0.0),
                )
            )
        return holdings

    def bm25_search(
        self,
        query: str,
        ticker: str,
        filing_types: list[str],
        date_start: str | None,
        date_end: str | None,
        sections: list[str],
        limit: int = 50,
    ) -> list[tuple[ChunkRow, float]]:
        # Quote each token as a literal phrase so bare words that collide with
        # FTS5 operators (AND, OR, NOT, NEAR) are matched as text, not parsed
        # as boolean syntax. Join with OR (not the default implicit AND) so a
        # chunk only needs to contain some of the query's words, not all of
        # them -- a full natural-language question ANDed together almost
        # never matches any single paragraph-sized chunk. bm25() ranking
        # (see ORDER BY below) still surfaces the best-matching rows first.
        fts_query = " OR ".join(f'"{token}"' for token in query.split() if token)
        where = ["chunks_fts MATCH ?", "c.ticker = ?"]
        params: list[Any] = [fts_query, ticker]
        if filing_types:
            where.append(f"c.filing_type IN ({','.join('?' for _ in filing_types)})")
            params.extend(filing_types)
        if date_start:
            where.append("c.filed_at >= ?")
            params.append(date_start)
        if date_end:
            where.append("c.filed_at <= ?")
            params.append(date_end)
        if sections:
            where.append(f"c.section IN ({','.join('?' for _ in sections)})")
            params.extend(sections)
        params.append(limit)
        sql = f"""
            SELECT c.*, bm25(chunks_fts) AS bm25_score
            FROM chunks_fts
            JOIN chunks c ON c.rowid = chunks_fts.rowid
            WHERE {' AND '.join(where)}
            ORDER BY bm25_score
            LIMIT ?
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
        return [(ChunkRow.model_validate(dict(row)), float(row["bm25_score"])) for row in rows]

    def recent_chunks(
        self,
        ticker: str,
        filing_types: list[str],
        date_start: str | None,
        date_end: str | None,
        sections: list[str],
        limit: int = 50,
    ) -> list[ChunkRow]:
        where = ["ticker = ?"]
        params: list[Any] = [ticker]
        if filing_types:
            where.append(f"filing_type IN ({','.join('?' for _ in filing_types)})")
            params.extend(filing_types)
        if date_start:
            where.append("filed_at >= ?")
            params.append(date_start)
        if date_end:
            where.append("filed_at <= ?")
            params.append(date_end)
        if sections:
            where.append(f"section IN ({','.join('?' for _ in sections)})")
            params.extend(sections)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM chunks WHERE {' AND '.join(where)} ORDER BY filed_at DESC, chunk_index ASC LIMIT ?",
                params,
            ).fetchall()
        return [ChunkRow.model_validate(dict(row)) for row in rows]

    def list_documents(self, ticker: str) -> list[DocumentSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.*, COUNT(c.id) AS chunks_indexed
                FROM documents d
                LEFT JOIN chunks c ON c.document_id = d.id
                WHERE d.ticker = ?
                GROUP BY d.id
                ORDER BY d.filed_at DESC
                """,
                (ticker.upper(),),
            ).fetchall()
        documents: list[DocumentSummary] = []
        for row in rows:
            sections = json.loads(row["sections_parsed"] or "[]")
            documents.append(
                DocumentSummary(
                    document_id=row["id"],
                    filing_type=row["filing_type"],
                    filed_at=row["filed_at"] or "",
                    accession_number=row["accession_number"],
                    source_url=row["source_url"],
                    sections_parsed=sections,
                    chunks_indexed=int(row["chunks_indexed"] or 0),
                )
            )
        return documents

    def create_portfolio(self, name: str, holdings: list[dict[str, Any]]) -> str:
        portfolio_id = str(uuid.uuid4())
        created_at = utc_now()
        total = sum(float(row.get("market_value") or 0.0) for row in holdings) or 1.0
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO portfolios (id, name, created_at) VALUES (?, ?, ?)",
                (portfolio_id, name, created_at),
            )
            for row in holdings:
                market_value = float(row.get("market_value") or 0.0)
                conn.execute(
                    """
                    INSERT INTO holdings (
                        id, portfolio_id, ticker, shares, market_value, cost_basis,
                        sector, weight, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        portfolio_id,
                        str(row["ticker"]).upper(),
                        float(row.get("shares") or 0.0),
                        market_value,
                        float(row.get("cost_basis") or 0.0),
                        row.get("sector"),
                        market_value / total,
                        created_at,
                    ),
                )
        return portfolio_id

    def create_job(self, portfolio_id: str, job_type: str, question: str | None) -> str:
        job_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO analysis_jobs (id, portfolio_id, job_type, status, progress, question, created_at)
                VALUES (?, ?, ?, 'queued', 0.0, ?, ?)
                """,
                (job_id, portfolio_id, job_type, question, utc_now()),
            )
        return job_id

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        keys = list(fields)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE analysis_jobs SET {', '.join(f'{key} = ?' for key in keys)} WHERE id = ?",
                [fields[key] for key in keys] + [job_id],
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def latest_job_for_portfolio(self, portfolio_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_jobs WHERE portfolio_id = ? ORDER BY created_at DESC LIMIT 1",
                (portfolio_id,),
            ).fetchone()
        return dict(row) if row else None

    def store_results(self, job_id: str, results_json: str) -> None:
        """Persist serialized AnalysisState JSON so findings can be read back without re-running the graph."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE analysis_jobs SET results_json = ? WHERE id = ?",
                (results_json, job_id),
            )

    def load_results(self, job_id: str) -> str | None:
        """Return the stored results_json for a job, or None if not yet cached."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT results_json FROM analysis_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return row["results_json"]
