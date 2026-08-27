"""Async client for the inference gateway service.

This client centralizes calls to the gateway's health check, JSON and text
chat completions, embeddings, and reranking endpoints so the agent code can
talk to model services through one HTTP abstraction.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx


class InferenceGatewayClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("INFERENCE_GATEWAY_URL", "http://localhost:8080")).rstrip("/")
        self.timeout = timeout
        self._client = client

    async def __aenter__(self) -> "InferenceGatewayClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def health(self) -> dict[str, Any]:
        response = await self.client.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str = "fincontext-planner",
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        response = await self.client.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            return content
        return json.loads(content)

    async def chat_text(
        self,
        messages: list[dict[str, str]],
        model: str = "fincontext-reasoner",
        temperature: float = 0.2,
        max_tokens: int = 2500,
    ) -> str:
        response = await self.client.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"])

    async def embed(self, text: str) -> list[float]:
        response = await self.client.post(
            f"{self.base_url}/v1/embeddings",
            json={"input": [text]},
        )
        response.raise_for_status()
        payload = response.json()
        return list(payload["data"][0]["embedding"])

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> list[tuple[int, float]]:
        if not documents:
            return []
        response = await self.client.post(
            f"{self.base_url}/v1/rerank",
            json={"query": query, "documents": documents, "top_n": top_n},
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", payload)
        ranked: list[tuple[int, float]] = []
        for item in results:
            index = item.get("index", item.get("document_index"))
            score = item.get("relevance_score", item.get("score", 0.0))
            if index is not None:
                ranked.append((int(index), float(score)))
        return ranked
