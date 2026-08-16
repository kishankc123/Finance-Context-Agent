"""Local, free embedding + reranker service.

Stands in for a hosted embedding/reranker backend so the Inference Gateway's
EMBEDDING_URL / RERANKER_URL routes have something real to call, without
needing a paid API. Wraps sentence-transformers models and exposes the same
contract the Gateway/agent-api clients already expect:

- POST /v1/embeddings  -> {"data": [{"index": i, "embedding": [...]}]}
- POST /v1/rerank      -> {"results": [{"index": i, "relevance_score": f}]}
- GET  /health
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import CrossEncoder, SentenceTransformer

EMBEDDING_MODEL_ID = os.getenv("EMBEDDING_MODEL_ID", "BAAI/bge-large-en-v1.5")
RERANKER_MODEL_ID = os.getenv("RERANKER_MODEL_ID", "BAAI/bge-reranker-large")

app = FastAPI(title="FinContext Local Embedding/Reranker Service")

_embedder: SentenceTransformer | None = None
_reranker: CrossEncoder | None = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBEDDING_MODEL_ID)
    return _embedder


def get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(RERANKER_MODEL_ID)
    return _reranker


class EmbeddingsRequest(BaseModel):
    input: list[str]
    model: str | None = None


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_n: int | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/embeddings")
def embeddings(request: EmbeddingsRequest) -> dict:
    vectors = get_embedder().encode(request.input, normalize_embeddings=True)
    return {
        "data": [
            {"index": i, "embedding": vector.tolist()}
            for i, vector in enumerate(vectors)
        ]
    }


@app.post("/v1/rerank")
def rerank(request: RerankRequest) -> dict:
    if not request.documents:
        return {"results": []}
    pairs = [(request.query, doc) for doc in request.documents]
    scores = get_reranker().predict(pairs)
    ranked = sorted(
        range(len(request.documents)), key=lambda i: scores[i], reverse=True
    )
    top_n = request.top_n or len(ranked)
    return {
        "results": [
            {"index": i, "relevance_score": float(scores[i])}
            for i in ranked[:top_n]
        ]
    }
