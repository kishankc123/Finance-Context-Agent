#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


DEFAULT_COLLECTION = "fincontext_chunks"
DEFAULT_QDRANT_URL = "http://localhost:6333"
VECTOR_SIZE = 1024
PAYLOAD_INDEXES = {
    "ticker": "keyword",
    "filing_type": "keyword",
    "filed_at": "datetime",
    "section": "keyword",
}


def request_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            try:
                return json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                return {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc


def wait_for_qdrant(qdrant_url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{qdrant_url.rstrip('/')}/healthz"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            request_json("GET", health_url, timeout=2.0)
            return
        except Exception as exc:  # noqa: BLE001 - printed if startup never completes
            last_error = exc
            time.sleep(1.0)
    raise RuntimeError(f"Qdrant did not become healthy at {health_url}: {last_error}")


def create_collection(qdrant_url: str, collection: str, recreate: bool) -> None:
    base_url = qdrant_url.rstrip("/")
    collection_url = f"{base_url}/collections/{collection}"

    if recreate:
        try:
            request_json("DELETE", collection_url)
        except RuntimeError as exc:
            if "failed with 404" not in str(exc):
                raise

    request_json(
        "PUT",
        collection_url,
        {
            "vectors": {
                "size": VECTOR_SIZE,
                "distance": "Cosine",
            }
        },
    )

    for field_name, field_schema in PAYLOAD_INDEXES.items():
        request_json(
            "PUT",
            f"{collection_url}/index",
            {
                "field_name": field_name,
                "field_schema": field_schema,
            },
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the FinContext Qdrant collection and payload indexes."
    )
    parser.add_argument(
        "--qdrant-url",
        default=os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL),
        help=f"Qdrant REST URL. Defaults to QDRANT_URL or {DEFAULT_QDRANT_URL}.",
    )
    parser.add_argument(
        "--collection",
        default=os.getenv("QDRANT_COLLECTION", DEFAULT_COLLECTION),
        help=f"Collection name. Defaults to QDRANT_COLLECTION or {DEFAULT_COLLECTION}.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete the collection first. Use only before loading demo data.",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for Qdrant health before creating the collection.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        wait_for_qdrant(args.qdrant_url, args.wait_timeout)
        create_collection(args.qdrant_url, args.collection, args.recreate)
    except Exception as exc:  # noqa: BLE001 - CLI should print actionable failures
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"created collection {args.collection!r} with {VECTOR_SIZE}-dim Cosine vectors "
        f"and payload indexes: {', '.join(PAYLOAD_INDEXES)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
