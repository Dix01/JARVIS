"""Project scanning + framework detection."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .files import is_ignored

FRAMEWORK_HINTS: list[tuple[str, str]] = [
    ("package.json", "node"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("requirements.txt", "python"),
    ("pyproject.toml", "python"),
    ("Pipfile", "python"),
    ("Cargo.toml", "rust"),
    ("go.mod", "go"),
    ("pom.xml", "java/maven"),
    ("build.gradle", "java/gradle"),
    ("composer.json", "php"),
    ("Gemfile", "ruby"),
    ("CMakeLists.txt", "cmake"),
    ("Makefile", "make"),
    ("next.config.js", "nextjs"),
    ("next.config.ts", "nextjs"),
    ("vite.config.ts", "vite"),
    ("vite.config.js", "vite"),
    ("svelte.config.js", "svelte"),
    ("nuxt.config.ts", "nuxt"),
    ("Dockerfile", "docker"),
    ("docker-compose.yml", "docker-compose"),
]


@dataclass
class ProjectSummary:
    root: str
    file_count: int = 0
    by_ext: dict[str, int] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)
    top_dirs: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    package_meta: dict[str, str] = field(default_factory=dict)

    def to_markdown(self) -> str:
        lines = [f"# Project: {self.root}"]
        if self.frameworks:
            lines.append(f"**Frameworks detected:** {', '.join(self.frameworks)}")
        lines.append(f"**Files:** {self.file_count}")
        if self.by_ext:
            top = sorted(self.by_ext.items(), key=lambda kv: -kv[1])[:10]
            lines.append("**By extension:** " + ", ".join(f"{e}({n})" for e, n in top))
        if self.top_dirs:
            lines.append("**Top-level dirs:** " + ", ".join(self.top_dirs))
        if self.entrypoints:
            lines.append("**Entrypoints:** " + ", ".join(self.entrypoints))
        if self.package_meta:
            lines.append("**Package metadata:**")
            for k, v in self.package_meta.items():
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)


def detect_frameworks(root: Path) -> list[str]:
    found: list[str] = []
    for fname, label in FRAMEWORK_HINTS:
        if (root / fname).exists():
            found.append(label)
    # Dedup preserving order
    seen: set[str] = set()
    return [x for x in found if not (x in seen or seen.add(x))]


def find_entrypoints(root: Path) -> list[str]:
    candidates: list[str] = []
    for name in [
        "main.py", "app.py", "server.py", "manage.py",
        "index.js", "index.ts", "server.js", "server.ts",
        "src/index.ts", "src/index.js", "src/main.ts", "src/main.py",
    ]:
        if (root / name).exists():
            candidates.append(name)
    return candidates


def read_package_meta(root: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            for k in ("name", "version", "description"):
                if k in data:
                    meta[k] = str(data[k])
            scripts = data.get("scripts", {})
            if isinstance(scripts, dict) and scripts:
                meta["scripts"] = ", ".join(scripts.keys())
        except Exception:  # noqa: BLE001
            pass
    pyp = root / "pyproject.toml"
    if pyp.exists():
        meta["pyproject.toml"] = "present"
    return meta


def scan_project(root: Path, ignore: list[str], max_files: int = 5000) -> ProjectSummary:
    summary = ProjectSummary(root=str(root))
    summary.frameworks = detect_frameworks(root)
    summary.entrypoints = find_entrypoints(root)
    summary.package_meta = read_package_meta(root)

    top_dirs: list[str] = []
    for child in root.iterdir():
        if child.is_dir() and not is_ignored(child, ignore):
            top_dirs.append(child.name)
    summary.top_dirs = sorted(top_dirs)[:20]

    count = 0
    for p in root.rglob("*"):
        if count >= max_files:
            break
        if not p.is_file():
            continue
        if is_ignored(p, ignore):
            continue
        count += 1
        ext = p.suffix.lower() or "(none)"
        summary.by_ext[ext] = summary.by_ext.get(ext, 0) + 1
    summary.file_count = count
    return summary
