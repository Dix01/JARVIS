"""Lightweight hook system (claude-agent-sdk-style).

Hooks let plugins observe / mutate the agent loop without forking the
orchestrator. Three lifecycle points are supported:

  - PRE_TOOL_USE  (tool, args) -> args | None
    Called before a tool runs. Return modified args or None to leave alone.
    Raise PermissionError("reason") to abort.

  - POST_TOOL_USE (tool, args, ok, result) -> result | None
    Called after a tool runs. Return a replacement result or None.

  - ON_TOOL_RESULT (tool, args, ok, result) -> list[Event]
    Called after a tool runs. Return zero or more Events to emit downstream
    (e.g. a `media` event derived from a JSON search result).

Hooks are pure functions (sync or async). They share an event loop with the
orchestrator. Errors in hooks are logged but never crash the loop.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

from .events import Event

log = logging.getLogger("jarvis.hooks")

PreFn  = Callable[[str, dict[str, Any]], Any | Awaitable[Any]]
PostFn = Callable[[str, dict[str, Any], bool, Any], Any | Awaitable[Any]]
EmitFn = Callable[[str, dict[str, Any], bool, Any], Iterable[Event] | Awaitable[Iterable[Event]]]


@dataclass
class HookRegistry:
    pre:  list[PreFn]  = field(default_factory=list)
    post: list[PostFn] = field(default_factory=list)
    emit: list[EmitFn] = field(default_factory=list)

    def add_pre(self, fn: PreFn) -> None:  self.pre.append(fn)
    def add_post(self, fn: PostFn) -> None: self.post.append(fn)
    def add_emit(self, fn: EmitFn) -> None: self.emit.append(fn)

    async def run_pre(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        cur = args
        for h in self.pre:
            try:
                r = h(tool, cur)
                if inspect.isawaitable(r):
                    r = await r
                if isinstance(r, dict):
                    cur = r
            except PermissionError:
                raise
            except Exception:
                log.exception("pre-tool hook failed (tool=%s)", tool)
        return cur

    async def run_post(self, tool: str, args: dict[str, Any], ok: bool, result: Any) -> Any:
        cur = result
        for h in self.post:
            try:
                r = h(tool, args, ok, cur)
                if inspect.isawaitable(r):
                    r = await r
                if r is not None:
                    cur = r
            except Exception:
                log.exception("post-tool hook failed (tool=%s)", tool)
        return cur

    async def run_emit(self, tool: str, args: dict[str, Any], ok: bool, result: Any) -> list[Event]:
        out: list[Event] = []
        for h in self.emit:
            try:
                r = h(tool, args, ok, result)
                if inspect.isawaitable(r):
                    r = await r
                if r:
                    out.extend(r)
            except Exception:
                log.exception("emit hook failed (tool=%s)", tool)
        return out
