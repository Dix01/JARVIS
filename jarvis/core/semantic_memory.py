"""Semantic long-term memory — embeddings + cosine recall over SQLite.

Sits alongside the keyword :class:`~jarvis.core.memory.Memory` store, sharing
the same DB file. Each remembered fact is stored with its embedding vector;
recall returns the top-K facts most similar to a query. Those are injected
into the system prompt so JARVIS genuinely remembers the user across sessions
instead of only matching substrings.

Brute-force cosine over the whole table is fine here: a personal assistant
accumulates thousands of facts at most, and recall runs once per user turn.

If embeddings are unavailable the store still records facts (vector = empty)
and recall returns nothing — the orchestrator then leans on the existing
keyword :meth:`Memory.search`. Nothing breaks; it just gets less smart.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from ..config import Config
from .embeddings import EmbeddingClient

log = logging.getLogger("jarvis.semantic")

SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_memory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    text         TEXT NOT NULL,
    meta         TEXT,
    embedding    BLOB,
    dim          INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    last_recalled REAL
);
CREATE INDEX IF NOT EXISTS idx_sem_kind ON semantic_memory(kind);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sem_text ON semantic_memory(kind, text);
"""


class SemanticMemory:
    def __init__(self, cfg: Config, embedder: EmbeddingClient):
        self.cfg = cfg
        self.embedder = embedder
        self.path: Path = cfg.abs_path(cfg.memory.db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    async def remember(self, text: str, kind: str = "fact", meta: dict | None = None) -> bool:
        """Embed + persist a fact. Idempotent on (kind, text). Returns True if
        a new row was written, False if it already existed or text was empty."""
        text = (text or "").strip()
        if not text:
            return False
        vec = await self.embedder.embed(text)
        blob = _to_blob(vec) if vec else b""
        dim = len(vec) if vec else 0
        try:
            with self._conn() as c:
                cur = c.execute(
                    "INSERT OR IGNORE INTO semantic_memory(kind,text,meta,embedding,dim,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (kind, text, json.dumps(meta or {}), blob, dim, time.time()),
                )
                wrote = cur.rowcount > 0
            if wrote:
                log.debug("remembered [%s] %s", kind, text[:80])
            return wrote
        except sqlite3.Error as e:
            log.warning("remember failed: %s", e)
            return False

    async def recall(
        self, query: str, k: int | None = None, min_score: float | None = None,
    ) -> list[dict]:
        """Return up to k facts most cosine-similar to query, each with a
        ``score`` in [0,1]. Empty list if embeddings unavailable or no hits."""
        query = (query or "").strip()
        if not query:
            return []
        k = k or self.cfg.ultimate.recall_k
        min_score = self.cfg.ultimate.recall_min_score if min_score is None else min_score

        qv = await self.embedder.embed(query)
        if not qv:
            return []
        q = np.asarray(qv, dtype=np.float32)
        qn = float(np.linalg.norm(q))
        if qn == 0.0:
            return []
        q = q / qn

        rows = self._load_vectors()
        if not rows:
            return []

        scored: list[tuple[float, dict]] = []
        for row in rows:
            v = row["_vec"]
            if v is None or v.shape != q.shape:
                continue
            score = float(np.dot(q, v))  # both unit-normalised → cosine
            if score >= min_score:
                scored.append((score, row))

        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:k]
        if top:
            self._touch([r["id"] for _, r in top])
        out: list[dict] = []
        for score, row in top:
            out.append({
                "id": row["id"],
                "kind": row["kind"],
                "text": row["text"],
                "meta": row["meta"],
                "score": round(score, 4),
            })
        return out

    # ------------------------------------------------------------------
    def _load_vectors(self) -> list[dict]:
        with self._conn() as c:
            raw = c.execute(
                "SELECT id, kind, text, meta, embedding, dim FROM semantic_memory "
                "WHERE dim > 0"
            ).fetchall()
        out: list[dict] = []
        for r in raw:
            vec = _from_blob(r["embedding"], r["dim"])
            if vec is None:
                continue
            n = float(np.linalg.norm(vec))
            out.append({
                "id": r["id"],
                "kind": r["kind"],
                "text": r["text"],
                "meta": _safe_json(r["meta"]),
                "_vec": (vec / n) if n else None,
            })
        return out

    def _touch(self, ids: list[int]) -> None:
        if not ids:
            return
        now = time.time()
        with self._conn() as c:
            c.executemany(
                "UPDATE semantic_memory SET last_recalled=? WHERE id=?",
                [(now, i) for i in ids],
            )

    def count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM semantic_memory").fetchone()[0])

    def recent(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, kind, text, meta, created_at, last_recalled "
                "FROM semantic_memory ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {**dict(r), "meta": _safe_json(r["meta"])}
            for r in rows
        ]

    def forget(self, mem_id: int) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM semantic_memory WHERE id=?", (mem_id,))
            return cur.rowcount > 0


def _to_blob(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _from_blob(blob: bytes | None, dim: int) -> np.ndarray | None:
    if not blob or dim <= 0:
        return None
    try:
        arr = np.frombuffer(blob, dtype=np.float32)
        return arr if arr.shape[0] == dim else None
    except Exception:  # noqa: BLE001
        return None


def _safe_json(s: str | None) -> dict:
    if not s:
        return {}
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}
    except Exception:  # noqa: BLE001
        return {}
