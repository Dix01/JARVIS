"""Embedding client for semantic memory.

Calls an OpenAI-compatible ``/embeddings`` endpoint. By default it reuses the
main model endpoint; set ``ultimate.embed_endpoint`` to point at a dedicated
embeddings server (e.g. a local Ollama/LM-Studio instance serving
``nomic-embed-text``).

Every call degrades gracefully: on any failure it returns ``None`` and the
caller falls back to keyword memory. After a hard failure the client backs
off for a short window instead of hammering a dead endpoint on every turn.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ..config import Config

log = logging.getLogger("jarvis.embeddings")

_RETRY_BACKOFF_S = 90.0


class EmbeddingClient:
    def __init__(self, cfg: Config):
        u = cfg.ultimate
        base = (u.embed_endpoint or cfg.model.endpoint).rstrip("/")
        self.url = base + "/embeddings"
        self.model = u.embed_model
        self.api_key = cfg.model.api_key
        self._client = httpx.AsyncClient(timeout=30)
        self._dim: int | None = None
        self._disabled_until: float = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def dim(self) -> int | None:
        return self._dim

    @property
    def available(self) -> bool:
        return time.time() >= self._disabled_until

    async def embed(self, text: str) -> list[float] | None:
        vecs = await self.embed_batch([text])
        return vecs[0] if vecs else None

    async def embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        texts = [t for t in texts if t and t.strip()]
        if not texts or not self.available:
            return None

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {"model": self.model, "input": texts}

        try:
            resp = await self._client.post(self.url, json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            self._disabled_until = time.time() + _RETRY_BACKOFF_S
            log.warning(
                "embeddings unavailable (%s) — semantic memory falls back to "
                "keyword search; retry in %ds", e, int(_RETRY_BACKOFF_S),
            )
            return None

        try:
            data = resp.json()
            items = data.get("data") or []
            vecs = [it.get("embedding") for it in items if it.get("embedding")]
        except Exception as e:  # noqa: BLE001
            log.warning("malformed embeddings response: %s", e)
            return None

        if not vecs:
            return None
        self._dim = len(vecs[0])
        return vecs
