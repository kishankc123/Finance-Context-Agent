"""Post-ingestion validation helpers for demo data readiness.

These checks are meant to run after a real pre-demo ingestion pass. They verify
that SQLite FTS rows are searchable, Qdrant has the expected point count,
citation anchors keep the required paragraph/table format, and loaded documents
can be summarized for manual review.
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SqliteFtsValidation:
    chunks_count: int
    fts_count: int

    @property
    def ok(self) -> bool:
        return self.chunks_count == self.fts_count

    @property
    def message(self) -> str:
        if self.ok:
            return f"SQLite FTS is in sync: {self.chunks_count} chunks"
        return (
            "SQLite FTS mismatch: "
            f"chunks={self.chunks_count}, chunks_fts={self.fts_count}"
        )


@dataclass(frozen=True)
class QdrantCountValidation:
    sqlite_chunks_count: int
    qdrant_points_count: int
    collection: str
    allowed_delta: int = 0

    @property
    def delta(self) -> int:
        return abs(self.sqlite_chunks_count - self.qdrant_points_count)

    @property
    def ok(self) -> bool:
        return self.delta <= self.allowed_delta

    @property
    def message(self) -> str:
        if self.ok:
            return (
                f"Qdrant collection {self.collection!r} is in sync: "
                f"{self.qdrant_points_count} points for {self.sqlite_chunks_count} chunks"
            )
        return (
            f"Qdrant count mismatch for {self.collection!r}: "
            f"sqlite_chunks={self.sqlite_chunks_count}, "
            f"qdrant_points={self.qdrant_points_count}, "
            f"allowed_delta={self.allowed_delta}"
        )


@dataclass(frozen=True)
class CitationAnchorIssue:
    chunk_id: str
    citation_anchor: str
    expected_format: str


@dataclass(frozen=True)
class CitationAnchorInspection:
    sampled_count: int
    invalid_anchors: list[CitationAnchorIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.invalid_anchors

    @property
    def message(self) -> str:
        if self.ok:
            return f"Citation anchors valid for {self.sampled_count} sampled chunks"
        return (
            "Citation anchor inspection failed: "
            f"{len(self.invalid_anchors)} invalid of {self.sampled_count} sampled chunks"
        )


@dataclass(frozen=True)
class IngestedDocumentSummary:
    document_id: str
    ticker: str
    filing_type: str
    filed_at: str
    sections_parsed: list[str]
    chunk_count: int


def validate_sqlite_fts(conn: sqlite3.Connection) -> SqliteFtsValidation:
    chunks_count = _scalar_count(conn, "SELECT count(*) FROM chunks")
    fts_count = _count_searchable_fts_rows(conn)
    return SqliteFtsValidation(chunks_count=chunks_count, fts_count=fts_count)


def validate_qdrant_count(
    conn: sqlite3.Connection,
    qdrant_url: str,
    collection: str = "fincontext_chunks",
    allowed_delta: int = 0,
    timeout_seconds: float = 10.0,
) -> QdrantCountValidation:
    # This comparison is the fastest way to catch partial ingestion: SQLite may
    # have chunk text even when embedding or Qdrant upsert failed mid-run.
    sqlite_chunks_count = _scalar_count(conn, "SELECT count(*) FROM chunks")
    qdrant_points_count = fetch_qdrant_point_count(
        qdrant_url=qdrant_url,
        collection=collection,
        timeout_seconds=timeout_seconds,
    )
    return QdrantCountValidation(
        sqlite_chunks_count=sqlite_chunks_count,
        qdrant_points_count=qdrant_points_count,
        collection=collection,
        allowed_delta=allowed_delta,
    )


def fetch_qdrant_point_count(
    qdrant_url: str,
    collection: str = "fincontext_chunks",
    timeout_seconds: float = 10.0,
) -> int:
    base_url = qdrant_url.rstrip("/")
    url = f"{base_url}/collections/{collection}/points/count"
    data = json.dumps({"exact": True}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Qdrant count request failed with {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Qdrant count request failed: {exc.reason}") from exc
    return parse_qdrant_count_response(payload)


def inspect_citation_anchors(
    conn: sqlite3.Connection,
    sample_size: int = 20,
) -> CitationAnchorInspection:
    rows = conn.execute(
        """
        SELECT id, ticker, filing_type, item_label, citation_anchor, is_table
        FROM chunks
        ORDER BY ticker, filing_type, filed_at, chunk_index, id
        LIMIT ?
        """,
        (sample_size,),
    ).fetchall()
    invalid: list[CitationAnchorIssue] = []
    for row in rows:
        chunk_id = str(row[0])
        ticker = str(row[1])
        filing_type = str(row[2])
        item_label = str(row[3])
        citation_anchor = str(row[4])
        is_table = bool(row[5])
        kind = "table" if is_table else "paragraph"
        expected_format = f"{ticker.upper()} {filing_type} {item_label} {kind} <N>"
        if not _valid_citation_anchor(
            citation_anchor=citation_anchor,
            ticker=ticker,
            filing_type=filing_type,
            item_label=item_label,
            kind=kind,
        ):
            invalid.append(
                CitationAnchorIssue(
                    chunk_id=chunk_id,
                    citation_anchor=citation_anchor,
                    expected_format=expected_format,
                )
            )
    return CitationAnchorInspection(sampled_count=len(rows), invalid_anchors=invalid)


def summarize_ingested_documents(
    conn: sqlite3.Connection,
    ticker: str | None = None,
) -> list[IngestedDocumentSummary]:
    filters: list[str] = []
    params: list[str] = []
    if ticker:
        filters.append("d.ticker = ?")
        params.append(ticker.upper())

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        f"""
        SELECT
            d.id,
            d.ticker,
            d.filing_type,
            d.filed_at,
            d.sections_parsed,
            count(c.id) AS chunk_count
        FROM documents d
        LEFT JOIN chunks c ON c.document_id = d.id
        {where_clause}
        GROUP BY d.id, d.ticker, d.filing_type, d.filed_at, d.sections_parsed
        ORDER BY d.ticker, d.filed_at DESC, d.filing_type
        """,
        params,
    ).fetchall()
    return [
        IngestedDocumentSummary(
            document_id=str(row[0]),
            ticker=str(row[1]),
            filing_type=str(row[2]),
            filed_at=str(row[3]),
            sections_parsed=_parse_sections_parsed(row[4]),
            chunk_count=int(row[5]),
        )
        for row in rows
    ]


def parse_qdrant_count_response(payload: str | bytes | dict[str, Any]) -> int:
    if isinstance(payload, bytes):
        parsed: dict[str, Any] = json.loads(payload.decode("utf-8"))
    elif isinstance(payload, str):
        parsed = json.loads(payload)
    else:
        parsed = payload

    result = parsed.get("result")
    if not isinstance(result, dict) or "count" not in result:
        raise ValueError("Qdrant count response is missing result.count")
    return int(result["count"])


def _valid_citation_anchor(
    *,
    citation_anchor: str,
    ticker: str,
    filing_type: str,
    item_label: str,
    kind: str,
) -> bool:
    prefix = f"{ticker.upper()} {filing_type} {item_label} {kind}"
    pattern = rf"^{re.escape(prefix)} [1-9][0-9]*$"
    return re.match(pattern, citation_anchor) is not None


def _parse_sections_parsed(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return [str(value)]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return [str(parsed)]


def _scalar_count(conn: sqlite3.Connection, query: str) -> int:
    row = conn.execute(query).fetchone()
    if row is None:
        return 0
    return int(row[0])


def _count_searchable_fts_rows(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT rowid, text FROM chunks").fetchall()
    searchable = 0
    for rowid, text in rows:
        token = _first_search_token(str(text))
        if token is None:
            continue
        matched = conn.execute(
            "SELECT 1 FROM chunks_fts WHERE chunks_fts MATCH ? AND rowid = ? LIMIT 1",
            (f'"{token}"', rowid),
        ).fetchone()
        if matched is not None:
            searchable += 1
    return searchable


def _first_search_token(text: str) -> str | None:
    match = re.search(r"[A-Za-z0-9]{3,}", text)
    if match is None:
        return None
    return match.group(0)
