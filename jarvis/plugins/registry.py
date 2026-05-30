"""Plugin discovery + tool registry."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from ..config import Config
from . import base as _base
from .base import PluginInfo, Tool

log = logging.getLogger("jarvis.plugins")


class PluginRegistry:
    def __init__(self, cfg: Config, services: dict[str, Any] | None = None):
        self.cfg = cfg
        self._tools: dict[str, Tool] = {}
        self._plugins: dict[str, PluginInfo] = {}
        # services pulled in by plugins (memory, action log, etc.)
        self.services: dict[str, Any] = services or {}

    # ------------------------------------------------------------------
    def add(self, t: Tool) -> None:
        if t.name in self._tools:
            log.warning("tool '%s' already registered, overwriting", t.name)
        self._tools[t.name] = t

    def add_pending(self, plugin_name: str) -> None:
        for t in _base.consume_pending(plugin_name):
            self.add(t)

    def register_plugin(self, info: PluginInfo) -> None:
        self._plugins[info.name] = info

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def plugins(self) -> list[PluginInfo]:
        return list(self._plugins.values())

    # ------------------------------------------------------------------
    def schemas(self) -> list[dict]:
        """JSON schemas suitable for OpenAI / Anthropic native tool calls."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools.values()
        ]

    def documentation(self) -> str:
        lines: list[str] = []
        for t in self._tools.values():
            params = t.parameters.get("properties", {}) or {}
            sig = ", ".join(params.keys())
            lines.append(f"- {t.name}({sig}): {t.description}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def load_all(self) -> None:
        """Import every plugin enabled in config and call its register()."""
        from . import (  # noqa: F401  — ensures package loaded for pkgutil
            base as _b,
        )
        pkg = importlib.import_module("jarvis.plugins")
        prefix = pkg.__name__ + "."
        for mod_info in pkgutil.iter_modules(pkg.__path__):
            modname = mod_info.name
            if modname in {"__init__", "base", "registry"}:
                continue
            toggle = self.cfg.plugins.get(modname)
            if toggle is not None and not toggle.enabled:
                log.info("plugin '%s' disabled in config", modname)
                continue
            try:
                m = importlib.import_module(prefix + modname)
            except Exception as e:  # noqa: BLE001
                log.error("failed to import plugin '%s': %s", modname, e)
                continue
            if not hasattr(m, "register"):
                log.warning("plugin '%s' has no register(registry)", modname)
                continue
            try:
                m.register(self)
                log.info("plugin '%s' loaded", modname)
            except Exception as e:  # noqa: BLE001
                log.error("plugin '%s' register() failed: %s", modname, e)
