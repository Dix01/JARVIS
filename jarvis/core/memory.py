"""Local memory store backed by SQLite.

Tables:
  preferences        — key/value user prefs
  project_notes      — free-form notes tied to a project path
  frequent_commands  — commands the user runs often
  past_fixes         — error text -> fix that worked
  known_paths        — labeled important paths
  installed_tools    — tools/libs JARVIS knows are installed
  conversations     — recent chat history (rolling)
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from ..config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS project_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    note TEXT NOT NULL,
    tags TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS frequent_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL UNIQUE,
    uses INTEGER NOT NULL DEFAULT 1,
    last_used REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS past_fixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_signature TEXT NOT NULL,
    fix TEXT NOT NULL,
    context TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS known_paths (
    label TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    kind TEXT
);
CREATE TABLE IF NOT EXISTS installed_tools (
    name TEXT PRIMARY KEY,
    version TEXT,
    notes TEXT,
    detected_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_created ON conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_notes_project ON project_notes(project);
"""


class Memory:
    def __init__(self, cfg: Config):
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

    # ---- preferences ----
    def set_pref(self, key: str, value: Any) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO preferences(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value), time.time()),
            )

    def get_pref(self, key: str, default: Any = None) -> Any:
        with self._conn() as c:
            row = c.execute(
                "SELECT value FROM preferences WHERE key=?", (key,)
            ).fetchone()
            return json.loads(row["value"]) if row else default

    def all_prefs(self) -> dict[str, Any]:
        with self._conn() as c:
            rows = c.execute("SELECT key,value FROM preferences").fetchall()
            return {r["key"]: json.loads(r["value"]) for r in rows}

    # ---- project notes ----
    def add_note(self, project: str, note: str, tags: Iterable[str] = ()) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO project_notes(project,note,tags,created_at) VALUES(?,?,?,?)",
                (project, note, ",".join(tags), time.time()),
            )
            return cur.lastrowid

    def notes(self, project: str | None = None) -> list[dict]:
        with self._conn() as c:
            if project:
                rows = c.execute(
                    "SELECT * FROM project_notes WHERE project=? ORDER BY created_at DESC",
                    (project,),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM project_notes ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    # ---- frequent commands ----
    def bump_command(self, command: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO frequent_commands(command,uses,last_used) VALUES(?,1,?) "
                "ON CONFLICT(command) DO UPDATE SET uses=uses+1, last_used=excluded.last_used",
                (command, time.time()),
            )

    def top_commands(self, limit: int = 10) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM frequent_commands ORDER BY uses DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ---- past fixes ----
    def add_fix(self, signature: str, fix: str, context: str = "") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO past_fixes(error_signature,fix,context,created_at) VALUES(?,?,?,?)",
                (signature, fix, context, time.time()),
            )

    def lookup_fix(self, signature: str) -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM past_fixes WHERE error_signature LIKE ? "
                "ORDER BY created_at DESC LIMIT 1",
                (f"%{signature[:120]}%",),
            ).fetchone()
            return dict(row) if row else None

    # ---- known paths ----
    def set_path(self, label: str, path: str, kind: str = "") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO known_paths(label,path,kind) VALUES(?,?,?) "
                "ON CONFLICT(label) DO UPDATE SET path=excluded.path, kind=excluded.kind",
                (label, path, kind),
            )

    def get_path(self, label: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT path FROM known_paths WHERE label=?", (label,)).fetchone()
            return row["path"] if row else None

    def list_paths(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM known_paths ORDER BY label").fetchall()
            return [dict(r) for r in rows]

    # ---- installed tools ----
    def record_tool(self, name: str, version: str = "", notes: str = "") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO installed_tools(name,version,notes,detected_at) VALUES(?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET version=excluded.version, notes=excluded.notes, detected_at=excluded.detected_at",
                (name, version, notes, time.time()),
            )

    def list_tools(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM installed_tools ORDER BY name").fetchall()
            return [dict(r) for r in rows]

    # ---- conversations (rolling chat history) ----
    def append_message(self, role: str, content: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO conversations(role,content,created_at) VALUES(?,?,?)",
                (role, content, time.time()),
            )

    def recent_messages(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return list(reversed([dict(r) for r in rows]))

    # ---- search ----
    def search(self, query: str, limit: int = 20) -> list[dict]:
        q = f"%{query}%"
        hits: list[dict] = []
        with self._conn() as c:
            for row in c.execute(
                "SELECT 'preference' AS kind, key AS title, value AS body, updated_at AS ts "
                "FROM preferences WHERE key LIKE ? OR value LIKE ? LIMIT ?",
                (q, q, limit),
            ):
                hits.append(dict(row))
            for row in c.execute(
                "SELECT 'note' AS kind, project AS title, note AS body, created_at AS ts "
                "FROM project_notes WHERE note LIKE ? OR project LIKE ? LIMIT ?",
                (q, q, limit),
            ):
                hits.append(dict(row))
            for row in c.execute(
                "SELECT 'fix' AS kind, error_signature AS title, fix AS body, created_at AS ts "
                "FROM past_fixes WHERE error_signature LIKE ? OR fix LIKE ? LIMIT ?",
                (q, q, limit),
            ):
                hits.append(dict(row))
            for row in c.execute(
                "SELECT 'path' AS kind, label AS title, path AS body, 0 AS ts "
                "FROM known_paths WHERE label LIKE ? OR path LIKE ? LIMIT ?",
                (q, q, limit),
            ):
                hits.append(dict(row))
        return hits

    def delete(self, kind: str, identifier: str) -> bool:
        tables = {
            "preference": ("preferences", "key"),
            "note": ("project_notes", "id"),
            "fix": ("past_fixes", "id"),
            "path": ("known_paths", "label"),
            "tool": ("installed_tools", "name"),
        }
        if kind not in tables:
            return False
        table, col = tables[kind]
        with self._conn() as c:
            cur = c.execute(f"DELETE FROM {table} WHERE {col}=?", (identifier,))
            return cur.rowcount > 0
