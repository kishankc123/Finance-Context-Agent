"""CLI orchestration for pre-demo SEC filing ingestion.

This script connects the ingestion worker pieces in order: EDGAR discovery,
HTML parsing, paragraph/table chunking, Gateway embedding calls, SQLite writes,
and Qdrant vector upserts. It is intentionally a one-shot pre-demo tool, not a
live demo path or long-running service.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from worker.chunking import chunk_document
from worker.db import connect, get_existing_hashes, upsert_chunks, upsert_document
from worker.embeddings import EmbeddingClient
from worker.models import ChunkWithEmbedding, FilingRef
from worker.parsers.sec_html import parse_sec_html
from worker.sec_client import EDGARClient
from worker.vector_store import upsert_vectors


logger = logging.getLogger("fincontext.ingestion")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pre-ingest SEC filings for FinContext.")
    parser.add_argument("--tickers", required=True, help="Comma-separated ticker list.")
    parser.add_argument(
        "--filing-types",
        default="10-K,10-Q",
        help="Comma-separated filing types. Defaults to 10-K,10-Q.",
    )
    parser.add_argument("--years", type=int, default=4, help="Lookback window in years.")
    parser.add_argument(
        "--db-path",
        default=os.getenv("SQLITE_DB_PATH", "../../fincontext.db"),
        help="SQLite DB path.",
    )
    parser.add_argument(
        "--qdrant-url",
        default=os.getenv("QDRANT_URL", "http://localhost:6333"),
        help="Qdrant REST URL.",
    )
    parser.add_argument(
        "--qdrant-collection",
        default=os.getenv("QDRANT_COLLECTION", "fincontext_chunks"),
        help="Qdrant collection name.",
    )
    parser.add_argument(
        "--gateway-url",
        default=os.getenv("INFERENCE_GATEWAY_URL", "http://localhost:8080"),
        help="Inference Gateway URL.",
    )
    parser.add_argument(
        "--cache-dir",
        default=".cache/edgar",
        help="Local EDGAR cache directory.",
    )
    return parser.parse_args()


async def ingest(args: argparse.Namespace) -> None:
    _configure_logging()
    tickers = _parse_csv_arg(args.tickers)
    filing_types = _parse_csv_arg(args.filing_types)
    date_to = date.today().isoformat()
    date_from = (date.today() - timedelta(days=365 * args.years)).isoformat()

    conn = connect(args.db_path)
    try:
        async with EDGARClient(cache_dir=args.cache_dir) as edgar:
            async with EmbeddingClient(args.gateway_url) as embeddings:
                totals = {"documents": 0, "chunks": 0}
                for ticker in tickers:
                    ticker_totals = await _ingest_ticker(
                        conn,
                        edgar,
                        embeddings,
                        ticker=ticker,
                        filing_types=filing_types,
                        date_from=date_from,
                        date_to=date_to,
                        qdrant_url=args.qdrant_url,
                        qdrant_collection=args.qdrant_collection,
                    )
                    totals["documents"] += ticker_totals["documents"]
                    totals["chunks"] += ticker_totals["chunks"]
        conn.commit()
        _log("ingestion_complete", **totals)
    finally:
        conn.close()


async def _ingest_ticker(
    conn: sqlite3.Connection,
    edgar: EDGARClient,
    embeddings: EmbeddingClient,
    *,
    ticker: str,
    filing_types: list[str],
    date_from: str,
    date_to: str,
    qdrant_url: str,
    qdrant_collection: str,
) -> dict[str, int]:
    company = await edgar.get_company_record(ticker)
    cik = EDGARClient.normalize_cik(company["cik_str"])
    company_name = str(company.get("title", ""))
    _log("ticker_resolved", ticker=ticker, cik=cik, company_name=company_name)

    all_filings: list[FilingRef] = []
    for filing_type in filing_types:
        filings = await edgar.get_filings(
            ticker=ticker,
            cik=cik,
            company_name=company_name,
            filing_type=filing_type,
            from_date=date_from,
            to_date=date_to,
        )
        all_filings.extend(filings)
        _log(
            "filings_found",
            ticker=ticker,
            filing_type=filing_type,
            count=len(filings),
        )

    totals = {"documents": 0, "chunks": 0}
    for filing in sorted(all_filings, key=lambda item: item.filed_at):
        inserted_chunks = await _ingest_filing(
            conn,
            edgar,
            embeddings,
            filing=filing,
            qdrant_url=qdrant_url,
            qdrant_collection=qdrant_collection,
        )
        totals["documents"] += 1
        totals["chunks"] += inserted_chunks
    return totals


async def _ingest_filing(
    conn: sqlite3.Connection,
    edgar: EDGARClient,
    embeddings: EmbeddingClient,
    *,
    filing: FilingRef,
    qdrant_url: str,
    qdrant_collection: str,
) -> int:
    _log(
        "filing_started",
        ticker=filing.ticker,
        filing_type=filing.filing_type,
        filed_at=filing.filed_at,
        accession_number=filing.accession_number,
    )
    html = await edgar.download_filing(filing)
    document = parse_sec_html(html, filing)
    document.checksum = hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]
    chunks = chunk_document(document)
    existing_hashes = get_existing_hashes(conn, [chunk.text_hash for chunk in chunks])
    new_chunks = [chunk for chunk in chunks if chunk.text_hash not in existing_hashes]

    _log(
        "filing_parsed",
        ticker=filing.ticker,
        sections=len(document.sections),
        chunks=len(chunks),
        new_chunks=len(new_chunks),
    )
    upsert_document(conn, document)
    if not new_chunks:
        return 0

    vectors = await embeddings.embed_texts([chunk.text for chunk in new_chunks])
    embedded_chunks = [
        ChunkWithEmbedding(**chunk.model_dump(), embedding=vector)
        for chunk, vector in zip(new_chunks, vectors, strict=True)
    ]
    upsert_vectors(
        embedded_chunks,
        qdrant_url=qdrant_url,
        collection=qdrant_collection,
    )
    inserted = upsert_chunks(conn, new_chunks)
    conn.commit()
    _log(
        "filing_upserted",
        ticker=filing.ticker,
        filing_type=filing.filing_type,
        inserted_chunks=inserted,
    )
    return inserted


def _parse_csv_arg(value: str) -> list[str]:
    return [part.strip().upper() for part in value.split(",") if part.strip()]


def _configure_logging() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")


def _log(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}, sort_keys=True))


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    args = parse_args()
    try:
        asyncio.run(ingest(args))
    except Exception as exc:  # noqa: BLE001 - CLI should log actionable failures
        _configure_logging()
        _log("ingestion_failed", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
