"""File system tools. Every write performs an automatic timestamped backup."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..core.permissions import Permission
from ..utils import files as F
from .base import PluginInfo, tool


def register(registry):
    cfg = registry.cfg
    backup_dir = cfg.abs_path(cfg.backups.dir)
    ignore = cfg.project.ignore_patterns

    @tool(
        name="list_dir",
        description="List entries in a directory. Optional glob pattern + recursive flag.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "glob": {"type": "string", "default": "*"},
                "recursive": {"type": "boolean", "default": False},
            },
            "required": ["path"],
        },
    )
    def list_dir(path: str, glob: str = "*", recursive: bool = False) -> str:
        p = F.expand(path)
        if not p.exists():
            return f"path does not exist: {p}"
        items = F.list_dir(p, glob=glob, recursive=recursive)
        lines = [f"{'D' if x.is_dir() else 'F'} {x.relative_to(p) if recursive else x.name}" for x in items]
        return "\n".join(lines[:500]) or "(empty)"

    @tool(
        name="read_file",
        description="Read a UTF-8 text file. Truncates to max_bytes.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 200000},
            },
            "required": ["path"],
        },
    )
    def read_file(path: str, max_bytes: int = 200000) -> str:
        p = F.expand(path)
        if not p.exists():
            return f"path does not exist: {p}"
        if p.is_dir():
            return f"is a directory: {p}"
        return F.read_text(p, max_bytes=max_bytes)

    @tool(
        name="write_file",
        description="Write text to a file. Backs up the existing file first. Creates parent dirs.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "backup": {"type": "boolean", "default": True},
            },
            "required": ["path", "content"],
        },
        preview=lambda a: f"write {len(a.get('content','')):,} chars -> {a.get('path','')}",
    )
    def write_file(path: str, content: str, backup: bool = True) -> str:
        p = F.expand(path)
        backed = None
        if backup and p.exists() and cfg.backups.enabled:
            backed = F.backup_file(p, backup_dir)
            F.prune_backups(backup_dir, keep=cfg.backups.keep_last)
        n = F.write_text(p, content)
        msg = f"wrote {n} chars to {p}"
        if backed:
            msg += f" (backup: {backed.name})"
        return msg

    @tool(
        name="append_file",
        description="Append text to a file. Creates the file if missing.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        preview=lambda a: f"append {len(a.get('content','')):,} chars -> {a.get('path','')}",
    )
    def append_file(path: str, content: str) -> str:
        p = F.expand(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
        return f"appended {len(content)} chars to {p}"

    @tool(
        name="search_files",
        description="Search for a substring inside files under a root directory. Honors ignore patterns.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "query": {"type": "string"},
                "max_hits": {"type": "integer", "default": 100},
            },
            "required": ["root", "query"],
        },
    )
    def search_files(root: str, query: str, max_hits: int = 100) -> str:
        r = F.expand(root)
        hits = F.search_in_files(r, query, ignore=ignore, max_hits=max_hits)
        if not hits:
            return f"no matches for '{query}' under {r}"
        return "\n".join(f"{h['path']}:{h['line']}: {h['text']}" for h in hits)

    @tool(
        name="mkdir",
        description="Create a directory (with parents).",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        preview=lambda a: f"mkdir {a.get('path','')}",
    )
    def mkdir(path: str) -> str:
        p = F.expand(path)
        p.mkdir(parents=True, exist_ok=True)
        return f"created {p}"

    @tool(
        name="copy",
        description="Copy a file or directory. Directories copy recursively.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "src": {"type": "string"},
                "dst": {"type": "string"},
            },
            "required": ["src", "dst"],
        },
        preview=lambda a: f"copy {a.get('src','')} -> {a.get('dst','')}",
    )
    def copy(src: str, dst: str) -> str:
        s, d = F.expand(src), F.expand(dst)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        return f"copied {s} -> {d}"

    @tool(
        name="move",
        description="Move/rename a file or directory.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "src": {"type": "string"},
                "dst": {"type": "string"},
            },
            "required": ["src", "dst"],
        },
        preview=lambda a: f"move {a.get('src','')} -> {a.get('dst','')}",
    )
    def move(src: str, dst: str) -> str:
        s, d = F.expand(src), F.expand(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return f"moved {s} -> {d}"

    @tool(
        name="delete",
        description="Delete a file or directory. Backed up first if it's a file. DANGEROUS.",
        permission=Permission.DANGEROUS,
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "recursive": {"type": "boolean", "default": False}},
            "required": ["path"],
        },
        preview=lambda a: f"DELETE {a.get('path','')}",
    )
    def delete(path: str, recursive: bool = False) -> str:
        p = F.expand(path)
        if not p.exists():
            return f"does not exist: {p}"
        if p.is_file():
            if cfg.backups.enabled:
                F.backup_file(p, backup_dir)
            p.unlink()
            return f"deleted file {p}"
        if recursive:
            shutil.rmtree(p)
            return f"deleted directory tree {p}"
        try:
            p.rmdir()
            return f"deleted empty directory {p}"
        except OSError as e:
            return f"refused: directory not empty (set recursive=true). {e}"

    @tool(
        name="stat",
        description="Show size, mtime, and type for a file or directory.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    def stat(path: str) -> str:
        p = F.expand(path)
        if not p.exists():
            return f"does not exist: {p}"
        st = p.stat()
        kind = "dir" if p.is_dir() else "file"
        return f"{kind} {p} | size={st.st_size} | mtime={st.st_mtime}"

    registry.add_pending("file_tools")
    registry.register_plugin(PluginInfo(
        name="file_tools",
        description="Read/write/search files with automatic backups.",
        permissions_needed=[Permission.SAFE, Permission.CAUTION, Permission.DANGEROUS],
    ))
