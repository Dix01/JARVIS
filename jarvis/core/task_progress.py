"""Thread-safe progress reporting for long-running tool invocations.

Tools running in asyncio executor threads can call `report(msg)` to push
progress text back to the orchestrator, which emits it as a TASK_PROGRESS
event visible in the chat dialogue.

Usage (from a tool or plugin):
    from ..core.task_progress import report
    report("Loading model weights… 60%")
"""
from __future__ import annotations

import contextvars
from typing import Callable, Optional

# ContextVar is propagated to asyncio.run_in_executor threads automatically
# (Python 3.7+ copies the current context into child tasks/threads).
_reporter: contextvars.ContextVar[Optional[Callable[[str], None]]] = \
    contextvars.ContextVar("jarvis_progress_reporter", default=None)


def set_reporter(fn: Callable[[str], None]) -> None:
    """Called by the orchestrator before invoking a tool. Sets the reporter
    function that tools can use to push progress messages."""
    _reporter.set(fn)


def report(msg: str) -> None:
    """Call from any thread (including executor threads) to push a progress
    update. Safe to call even if no reporter is active (silently ignored)."""
    fn = _reporter.get(None)
    if fn is not None:
        try:
            fn(msg)
        except Exception:  # noqa: BLE001
            pass
