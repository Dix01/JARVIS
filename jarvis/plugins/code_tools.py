"""Code execution + project intelligence.

run_python / run_node    -- one-shot script in a temp file inside the sandbox
run_python_file          -- execute a file at a real path
pip_install / npm_install
scan_project             -- summary + framework detection
"""
from __future__ import annotations

import sys
import textwrap
import uuid
from pathlib import Path

from ..core.permissions import Permission
from ..utils import files as F
from ..utils.shell import run_command
from ..utils.project import scan_project
from .base import PluginInfo, tool


def register(registry):
    cfg = registry.cfg
    sandbox = cfg.abs_path(cfg.code_execution.workdir)
    sandbox.mkdir(parents=True, exist_ok=True)
    timeout_default = cfg.code_execution.timeout_seconds

    @tool(
        name="run_python",
        description="Write a Python snippet to the sandbox and execute it with the active interpreter. Captures stdout/stderr.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "timeout": {"type": "integer", "default": timeout_default},
                "args": {"type": "string", "default": ""},
            },
            "required": ["code"],
        },
        preview=lambda a: f"python -c <{len(a.get('code',''))} chars>",
    )
    async def run_python(code: str, timeout: int = timeout_default, args: str = "") -> str:
        path = sandbox / f"snippet_{uuid.uuid4().hex[:8]}.py"
        path.write_text(textwrap.dedent(code), encoding="utf-8")
        cmd = f'"{sys.executable}" "{path}"'
        if args:
            cmd += " " + args
        res = await run_command(cmd, cwd=str(sandbox), timeout=timeout)
        return _format(res)

    @tool(
        name="run_python_file",
        description="Run an existing python file with the active interpreter.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "args": {"type": "string", "default": ""},
                "cwd": {"type": "string", "default": ""},
                "timeout": {"type": "integer", "default": timeout_default},
            },
            "required": ["path"],
        },
        preview=lambda a: f"python {a.get('path','')} {a.get('args','')}",
    )
    async def run_python_file(path: str, args: str = "", cwd: str = "", timeout: int = timeout_default) -> str:
        p = F.expand(path)
        if not p.exists():
            return f"not found: {p}"
        cmd = f'"{sys.executable}" "{p}"'
        if args:
            cmd += " " + args
        res = await run_command(cmd, cwd=cwd or str(p.parent), timeout=timeout)
        return _format(res)

    @tool(
        name="run_node",
        description="Write a JS snippet to the sandbox and execute it with node. Requires node on PATH.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "timeout": {"type": "integer", "default": timeout_default},
            },
            "required": ["code"],
        },
        preview=lambda a: f"node -e <{len(a.get('code',''))} chars>",
    )
    async def run_node(code: str, timeout: int = timeout_default) -> str:
        path = sandbox / f"snippet_{uuid.uuid4().hex[:8]}.js"
        path.write_text(code, encoding="utf-8")
        res = await run_command(f'node "{path}"', cwd=str(sandbox), timeout=timeout)
        return _format(res)

    @tool(
        name="pip_install",
        description="Install a Python package into the active interpreter / venv.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "package": {"type": "string", "description": "name (and optional version specifier)"},
            },
            "required": ["package"],
        },
        preview=lambda a: f"pip install {a.get('package','')}",
    )
    async def pip_install(package: str) -> str:
        cmd = f'"{sys.executable}" -m pip install {package}'
        res = await run_command(cmd, cwd=str(cfg.project_root), timeout=300)
        return _format(res)

    @tool(
        name="npm_install",
        description="Run `npm install` in a directory (optionally one package).",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "cwd": {"type": "string"},
                "package": {"type": "string", "default": ""},
                "dev": {"type": "boolean", "default": False},
            },
            "required": ["cwd"],
        },
        preview=lambda a: f"npm install {a.get('package','')} in {a.get('cwd','')}",
    )
    async def npm_install(cwd: str, package: str = "", dev: bool = False) -> str:
        cmd = "npm install"
        if package:
            cmd += " " + package
            if dev:
                cmd += " --save-dev"
        res = await run_command(cmd, cwd=str(F.expand(cwd)), timeout=600)
        return _format(res)

    @tool(
        name="scan_project",
        description="Walk a project directory and summarise file counts, frameworks, and entrypoints.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    def scan_project_tool(path: str) -> str:
        root = F.expand(path)
        if not root.exists() or not root.is_dir():
            return f"not a directory: {root}"
        summary = scan_project(root, ignore=cfg.project.ignore_patterns)
        return summary.to_markdown()

    @tool(
        name="code_debug_loop",
        description=(
            "Run a Python snippet up to `max_retries` times. After each failure the "
            "stderr is returned to the model with the original code as the user "
            "message; the model is expected to call `code_debug_loop` again with a "
            "fixed snippet. Use this when you want JARVIS to iterate."
        ),
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "language": {"type": "string", "enum": ["python", "node"], "default": "python"},
                "timeout": {"type": "integer", "default": timeout_default},
            },
            "required": ["code"],
        },
        preview=lambda a: f"debug {a.get('language','python')} snippet ({len(a.get('code',''))} chars)",
    )
    async def code_debug_loop(code: str, language: str = "python", timeout: int = timeout_default) -> str:
        if language == "python":
            return await run_python(code, timeout=timeout)
        if language == "node":
            return await run_node(code, timeout=timeout)
        return f"unsupported language: {language}"

    registry.add_pending("code_tools")
    registry.register_plugin(PluginInfo(
        name="code_tools",
        description="Run Python/Node snippets, install packages, scan projects.",
        permissions_needed=[Permission.CAUTION],
    ))


def _format(res) -> str:
    lines = [
        f"$ {res.cmd}",
        f"cwd: {res.cwd}",
        f"returncode: {res.returncode}",
    ]
    if res.timed_out:
        lines.append("TIMED OUT")
    if res.stdout:
        lines.append("--- stdout ---")
        lines.append(res.stdout if len(res.stdout) < 4000 else res.stdout[:4000] + "\n[clipped]")
    if res.stderr:
        lines.append("--- stderr ---")
        lines.append(res.stderr if len(res.stderr) < 4000 else res.stderr[:4000] + "\n[clipped]")
    return "\n".join(lines)
