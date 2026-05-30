"""Bridge to external agentic coding/OS backends.

Supports installed CLIs such as Claude Code, OpenCode, and Codex in their
non-interactive modes. This lets JARVIS delegate long-running implementation
goals to a dedicated agent runner while keeping the HUD as mission control.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from ..core.permissions import Permission
from .base import PluginInfo, tool


BACKENDS = {
    "claude": {
        "exe": "claude",
        "argv": lambda prompt, max_turns: ["claude", "-p", "--max-turns", str(max_turns), prompt],
        "label": "Claude Code CLI",
    },
    "opencode": {
        "exe": "opencode",
        "argv": lambda prompt, max_turns: ["opencode", "-p", prompt, "-q"],
        "label": "OpenCode CLI",
    },
    "codex": {
        "exe": "codex",
        "argv": lambda prompt, max_turns: ["codex", "exec", "--skip-git-repo-check", prompt],
        "label": "Codex CLI",
    },
}

ALIASES = {
    "claude-code": "claude",
    "claude_code": "claude",
    "claudecode": "claude",
    "open-code": "opencode",
    "open_code": "opencode",
    "openai-codex": "codex",
    "openai_codex": "codex",
}


def register(registry):
    cfg = registry.cfg

    @tool(
        name="agent_backend_status",
        description="Detect installed external agent CLIs that JARVIS can delegate goals to.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    def agent_backend_status() -> str:
        rows = []
        preferred = _preferred_backend()
        for name, meta in BACKENDS.items():
            path = shutil.which(meta["exe"])
            status = "available" if path else "missing"
            marker = " (preferred)" if preferred == name else ""
            rows.append(f"- {name}: {status}{marker} {path or ''}".rstrip())
        rows.append("")
        rows.append("Set JARVIS_AGENT_BACKEND=claude|opencode|codex to choose one.")
        return "\n".join(rows)

    @tool(
        name="agent_backend_run",
        description="Delegate a goal to an installed external agent CLI and return its output.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "backend": {"type": "string", "default": "auto"},
                "cwd": {"type": "string", "default": ""},
                "max_turns": {"type": "integer", "default": 20},
                "timeout": {"type": "integer", "default": 1800},
            },
            "required": ["goal"],
        },
        preview=lambda a: f"delegate goal to {a.get('backend','auto')}: {a.get('goal','')[:120]}",
    )
    async def agent_backend_run(
        goal: str,
        backend: str = "auto",
        cwd: str = "",
        max_turns: int = 20,
        timeout: int = 1800,
    ) -> str:
        selected = _select_backend(backend)
        if not selected:
            return (
                "No external agent backend is installed. Install one of:\n"
                "- Claude Code: npm install -g @anthropic-ai/claude-code\n"
                "- OpenCode: npm install -g opencode-ai\n"
                "- Codex CLI: npm install -g @openai/codex"
            )
        meta = BACKENDS[selected]
        command = meta["argv"](_backend_prompt(goal), max_turns)
        workdir = Path(cwd).expanduser() if cwd else cfg.project_root
        if not workdir.exists():
            return f"Working directory does not exist: {workdir}"
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workdir),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"{meta['label']} timed out after {timeout}s."
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        parts = [
            f"backend: {selected}",
            f"cwd: {workdir}",
            f"returncode: {proc.returncode}",
        ]
        if out.strip():
            parts += ["--- stdout ---", _clip(out)]
        if err.strip():
            parts += ["--- stderr ---", _clip(err)]
        return "\n".join(parts)

    # ─── Parallel-task swarm meta-tool ───────────────────────────────────
    # When the LLM sees a user request that splits cleanly into independent
    # sub-tasks (eg. "search news on X, find images of Y, generate a 3D
    # model of Z"), it can invoke this tool with a list of sub-calls and
    # JARVIS will fan them out concurrently through the orchestrator's
    # normal tool pipeline (permissions + hooks + media emit). Events from
    # each subagent are tagged with a swarm_id so the UI groups them.
    @tool(
        name="parallel_tasks",
        description=(
            "★ Run MULTIPLE independent tool calls IN PARALLEL. Use whenever "
            "the user's request decomposes into 2+ unrelated tasks "
            "(e.g. 'search news on X, get images of Y, weather in Z'). "
            "Pass a list of {label, tool, args} objects — JARVIS executes "
            "all of them at once via the swarm runner and streams their "
            "results into the Media Bay tagged per-subagent. ONE call per "
            "user request, NEVER nest. Prefer this over sequential tool "
            "calls when tasks are independent."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Short human-readable card title."},
                            "tool":  {"type": "string", "description": "Name of the tool to run."},
                            "args":  {"type": "object", "description": "Args object for the tool."},
                        },
                        "required": ["label", "tool", "args"],
                    },
                },
            },
            "required": ["tasks"],
        },
        preview=lambda a: (
            f"swarm × {len(a.get('tasks', []))}: "
            + ", ".join(t.get("label", t.get("tool", "?"))
                        for t in (a.get("tasks") or [])[:4])
        ),
    )
    async def parallel_tasks(tasks: list[dict]) -> str:
        # Lookup orchestrator lazily so the import doesn't cycle at module load.
        orch = registry.services.get("orchestrator")
        if orch is None:
            return "swarm unavailable: orchestrator not registered with plugin registry"
        from ..core.swarm import SwarmTask, run_swarm

        normalised: list[SwarmTask] = []
        for raw in tasks:
            try:
                label = str(raw.get("label") or raw.get("tool") or "subtask")[:64]
                tool_name = str(raw.get("tool", "")).strip()
                args = raw.get("args") or {}
                if not tool_name:
                    continue
                if not isinstance(args, dict):
                    continue
                normalised.append(SwarmTask(label=label, tool=tool_name, args=args))
            except Exception:  # noqa: BLE001
                continue

        if not normalised:
            return "swarm: no valid tasks parsed"

        # Drain swarm into the orchestrator's event stream via the active
        # progress reporter. parallel_tasks returns a summary; the real
        # per-task events flow via WS in real time.
        from ..core.task_progress import report as _progress
        ok = 0
        fail = 0
        lines: list[str] = []
        async for ev in run_swarm(orch, normalised):
            # Surface every swarm event back to the user via the progress
            # channel; the WS layer already routes these to the chat info
            # feed. Tool-result events become summary rows.
            if ev.text:
                _progress(ev.text)
            from ..core.events import EventKind
            if ev.kind is EventKind.TOOL_RESULT:
                if ev.payload.get("ok") is False:
                    fail += 1
                    lines.append(f"✗ {ev.swarm_label}: {ev.text[:120]}")
                else:
                    ok += 1
                    lines.append(f"✓ {ev.swarm_label}: {ev.text[:120]}")

        head = f"⌬ Swarm finished — {ok} ok, {fail} failed."
        return head + ("\n" + "\n".join(lines) if lines else "")

    registry.add_pending("agent_backend_tools")
    registry.register_plugin(PluginInfo(
        name="agent_backend_tools",
        description="Delegates goals to external agent CLIs + the parallel_tasks swarm runner.",
        permissions_needed=[Permission.SAFE, Permission.CAUTION],
    ))


def _preferred_backend() -> str:
    return _normalize_backend(os.environ.get("JARVIS_AGENT_BACKEND", "auto"))


def _select_backend(requested: str) -> str | None:
    wanted = _normalize_backend(requested or "auto")
    if wanted == "auto":
        preferred = _preferred_backend()
        if preferred in BACKENDS and shutil.which(BACKENDS[preferred]["exe"]):
            return preferred
        for name, meta in BACKENDS.items():
            if shutil.which(meta["exe"]):
                return name
        return None
    if wanted in BACKENDS and shutil.which(BACKENDS[wanted]["exe"]):
        return wanted
    return None


def _normalize_backend(name: str) -> str:
    cleaned = (name or "auto").lower().strip().replace(" ", "-")
    return ALIASES.get(cleaned, cleaned)


def _backend_prompt(goal: str) -> str:
    return (
        "You are running as the external backend for JARVIS_LOCAL on the user's Windows PC. "
        "Complete the requested goal end-to-end in the current project directory. "
        "Inspect before editing, preserve unrelated user changes, run relevant checks, "
        "and stop only when the goal is handled or a concrete blocker remains.\n\n"
        f"Goal:\n{goal.strip()}"
    )


def _clip(text: str, limit: int = 12000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [clipped, {len(text)} chars total]"
