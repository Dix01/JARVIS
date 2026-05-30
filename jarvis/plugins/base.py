"""Plugin / tool definitions.

A plugin is a Python module in this package that exposes a `register(registry)`
function. Inside, it adds `Tool` objects to the registry — usually built via
the `@tool(...)` decorator.

Each Tool:
  - has a JSON-schema-typed parameter spec
  - declares a Permission level
  - optionally provides a `preview` to display in the confirmation modal
  - has an async-or-sync handler

The orchestrator never calls the handler directly — it goes through
`Tool.invoke(args)` so all calls become awaitable.
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..core.permissions import Permission

ToolHandler = Callable[..., Any | Awaitable[Any]]
PreviewFn = Callable[[dict[str, Any]], str]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    permission: Permission = Permission.SAFE
    preview_fn: PreviewFn | None = None
    plugin: str = ""

    def preview(self, args: dict[str, Any]) -> str:
        if self.preview_fn:
            try:
                return self.preview_fn(args)
            except Exception:  # noqa: BLE001
                pass
        # default preview: name + truncated arg dump
        snippet = ", ".join(f"{k}={_short(v)}" for k, v in (args or {}).items())
        return f"{self.name}({snippet})"

    async def invoke(self, args: dict[str, Any]) -> Any:
        result = self.handler(**(args or {}))
        if inspect.isawaitable(result):
            return await result
        return result


@dataclass
class PluginInfo:
    name: str
    description: str
    permissions_needed: list[Permission] = field(default_factory=list)
    enabled: bool = True


def _short(v: Any, n: int = 80) -> str:
    s = repr(v)
    return s if len(s) <= n else s[: n - 3] + "..."


# Module-level registration used by @tool decorator
_PENDING: list[Tool] = []


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any] | None = None,
    permission: Permission = Permission.SAFE,
    preview: PreviewFn | None = None,
):
    """Decorator that converts a function into a `Tool`. Plugins call
    `registry.add_pending(<plugin_name>)` after defining their @tool funcs
    to claim everything in the pending list for that plugin.
    """

    def deco(fn: ToolHandler) -> ToolHandler:
        t = Tool(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            handler=fn,
            permission=permission,
            preview_fn=preview,
        )
        _PENDING.append(t)
        # Return the raw function so other tools in the same plugin can call it
        # directly. The Tool object is captured in _PENDING and harvested by
        # `registry.add_pending(plugin_name)`.
        fn._tool = t  # type: ignore[attr-defined]
        return fn

    return deco


def consume_pending(plugin_name: str) -> list[Tool]:
    """Plugins call this in their `register()` to grab tools they defined."""
    global _PENDING
    items = list(_PENDING)
    _PENDING = []
    for t in items:
        t.plugin = plugin_name
    return items
