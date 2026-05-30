"""File-system helpers: safe paths, automatic backups, dir scanning."""
from __future__ import annotations

import fnmatch
import os
import shutil
import time
from pathlib import Path


def expand(p: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(p)))).resolve()


def backup_path(target: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    safe = target.name + "." + ts + ".bak"
    return backup_dir / safe


def backup_file(target: Path, backup_dir: Path) -> Path | None:
    if not target.exists() or not target.is_file():
        return None
    dst = backup_path(target, backup_dir)
    shutil.copy2(target, dst)
    return dst


def prune_backups(backup_dir: Path, keep: int = 50) -> None:
    if not backup_dir.exists():
        return
    files = sorted(backup_dir.glob("*.bak"), key=lambda p: p.stat().st_mtime)
    for old in files[:-keep] if keep > 0 else files:
        try:
            old.unlink()
        except OSError:
            pass


def list_dir(path: Path, glob: str = "*", recursive: bool = False) -> list[Path]:
    if recursive:
        return list(path.rglob(glob))
    return list(path.glob(glob))


def is_ignored(path: Path, patterns: list[str]) -> bool:
    s = str(path).replace("\\", "/")
    return any(fnmatch.fnmatch(s, pat) for pat in patterns)


def read_text(path: Path, max_bytes: int = 1_000_000) -> str:
    data = path.read_bytes()
    if len(data) > max_bytes:
        return data[:max_bytes].decode("utf-8", errors="replace") + f"\n... [truncated, {len(data)} bytes total]"
    return data.decode("utf-8", errors="replace")


def write_text(path: Path, content: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return len(content)


def search_in_files(root: Path, query: str, ignore: list[str], max_hits: int = 100) -> list[dict]:
    out: list[dict] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if is_ignored(p, ignore):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if query in text:
            for i, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    out.append({"path": str(p), "line": i, "text": line.strip()[:200]})
                    if len(out) >= max_hits:
                        return out
    return out
