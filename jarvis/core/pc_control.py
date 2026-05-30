"""Deterministic PC-control command routing.

This catches common local-machine operations before the LLM can turn them into
questions. The LLM is useful for reasoning; it should not be needed to create a
folder on the user's Desktop.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .brain import ToolCall


@dataclass(frozen=True)
class DirectCommand:
    tool_call: ToolCall
    final_prefix: str


_CREATE_FOLDER_RE = re.compile(
    r"\b(?:create|make|new)\s+(?:a\s+)?(?:folder|directory)\b(?P<body>.*)",
    re.IGNORECASE,
)
_LIST_DESKTOP_RE = re.compile(
    r"\b(?:list|show|what(?:'s|\s+is))\b.*\b(?:desktop|desktop\s+files)\b",
    re.IGNORECASE,
)
_SYSTEM_STATUS_RE = re.compile(
    r"\b(?:system\s+status|pc\s+status|computer\s+status|diagnostics|how\s+is\s+(?:my\s+)?pc)\b",
    re.IGNORECASE,
)
_RUN_PS_RE = re.compile(
    r"^\s*(?:run|execute)\s+(?:powershell|ps)\s*:?\s*(?P<command>.+)",
    re.IGNORECASE | re.DOTALL,
)
_RUN_CMD_RE = re.compile(
    r"^\s*(?:run|execute)\s+(?:command|cmd|shell)\s*:?\s*(?P<command>.+)",
    re.IGNORECASE | re.DOTALL,
)
_OPEN_BROWSER_RE = re.compile(
    r"^\s*(?:open|go\s+to|navigate\s+to)\s+(?:my\s+)?(?:browser\s+(?:to\s+)?)?(?P<target>.+)",
    re.IGNORECASE | re.DOTALL,
)
_SCREENSHOT_BROWSER_RE = re.compile(
    r"\b(?:screenshot|screen\s+shot|capture)\b.*\b(?:browser|page|website)\b",
    re.IGNORECASE,
)
_AGENT_BACKEND_RE = re.compile(
    r"^\s*(?P<prefix>"
    r"(?:use|ask|run|delegate(?:\s+to)?)\s+"
    r"(?:claude(?:\s+code)?|codex|opencode|open\s+code|agent\s+backend|backend)\s+"
    r"(?:to\s+)?"
    r"|"
    r"(?:run|work|keep\s+going)\s+until\s+"
    r"(?:you\s+)?(?:accomplish|finish|complete)\s+"
    r"(?:the\s+)?(?:goal|task)\s*:?\s*"
    r")(?P<goal>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_FOLDER_NAME_RE = re.compile(
    r"\b(?:called|named|name(?:d)?\s+it|folder\s+called|folder\s+named)\s+"
    r"(?P<name>[^.?!,;]+)",
    re.IGNORECASE,
)


def desktop_path() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def direct_pc_command(user_text: str) -> DirectCommand | None:
    text = (user_text or "").strip()
    if not text:
        return None

    folder = _parse_create_folder(text)
    if folder:
        return DirectCommand(
            tool_call=ToolCall("mkdir", {"path": str(folder)}),
            final_prefix="Created the folder, sir.",
        )

    if _LIST_DESKTOP_RE.search(text):
        return DirectCommand(
            tool_call=ToolCall("list_dir", {"path": str(desktop_path()), "glob": "*", "recursive": False}),
            final_prefix="Desktop scan complete, sir.",
        )

    if _SYSTEM_STATUS_RE.search(text):
        return DirectCommand(
            tool_call=ToolCall("system_status", {}),
            final_prefix="System status, sir.",
        )

    if _SCREENSHOT_BROWSER_RE.search(text):
        return DirectCommand(
            tool_call=ToolCall("browser_screenshot", {"full_page": False}),
            final_prefix="Browser screenshot captured, sir.",
        )

    agent_match = _AGENT_BACKEND_RE.search(text)
    if agent_match:
        goal = agent_match.group("goal").strip()
        if goal:
            return DirectCommand(
                tool_call=ToolCall(
                    "agent_backend_run",
                    {
                        "goal": goal,
                        "backend": _backend_from_prefix(agent_match.group("prefix")),
                        "cwd": str(Path.cwd()),
                        "max_turns": 20,
                        "timeout": 1800,
                    },
                ),
                final_prefix="Agent backend run complete, sir.",
            )

    open_match = _OPEN_BROWSER_RE.search(text)
    if open_match and _looks_like_browser_target(open_match.group("target")):
        return DirectCommand(
            tool_call=ToolCall("browser_open", {"url": open_match.group("target").strip()}),
            final_prefix="Browser navigation complete, sir.",
        )

    ps_match = _RUN_PS_RE.search(text)
    if ps_match:
        return DirectCommand(
            tool_call=ToolCall("run_powershell", {"command": ps_match.group("command").strip()}),
            final_prefix="PowerShell command complete, sir.",
        )

    cmd_match = _RUN_CMD_RE.search(text)
    if cmd_match:
        return DirectCommand(
            tool_call=ToolCall("run_shell", {"command": cmd_match.group("command").strip()}),
            final_prefix="Command complete, sir.",
        )

    return None


def _looks_like_browser_target(target: str) -> bool:
    t = (target or "").strip().lower()
    if not t:
        return False
    if t.startswith(("http://", "https://", "www.")):
        return True
    if "." in t and " " not in t:
        return True
    return any(word in t for word in ("website", "webpage", "google", "youtube", "github", "duckduckgo"))


def _parse_create_folder(text: str) -> Path | None:
    m = _CREATE_FOLDER_RE.search(text)
    if not m:
        return None

    body = m.group("body") or ""
    name_match = _FOLDER_NAME_RE.search(body)
    if name_match:
        folder_name = _clean_name(name_match.group("name"))
    else:
        folder_name = _clean_name(body)

    if not folder_name:
        return None

    base = desktop_path() if re.search(r"\bdesktop\b", text, re.IGNORECASE) else Path.cwd()
    return base / folder_name


def _backend_from_prefix(prefix: str) -> str:
    p = (prefix or "").lower()
    if "claude" in p:
        return "claude"
    if "codex" in p:
        return "codex"
    if "opencode" in p or "open code" in p:
        return "opencode"
    return "auto"


def _clean_name(raw: str) -> str:
    name = (raw or "").strip().strip("\"'")
    name = re.sub(r"^(?:on|in|at)\s+(?:my\s+)?desktop\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\b(?:on|in|at)\s+(?:my\s+)?desktop\b.*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip(" .")
    # Windows-forbidden filename characters.
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name[:120].strip()
