"""Permission tiers, denylist, and confirmation contracts.

Every tool declares a `Permission` level. The orchestrator consults the
PermissionManager before executing — which may auto-approve, ask the UI,
or hard-refuse based on the configured mode plus the denylist.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..config import Config


class Permission(str, Enum):
    SAFE = "safe"            # read-only, observation
    CAUTION = "caution"      # mutates local state — files, shell, packages
    DANGEROUS = "dangerous"  # destructive / system-wide / network upload / spending


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class PermissionRequest:
    tool: str
    args: dict[str, Any]
    permission: Permission
    preview: str
    reason: str = ""


@dataclass
class PermissionResult:
    decision: Decision
    user_reason: str = ""


class PermissionManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.mode = cfg.permissions.mode
        # Each entry is (raw_string, optional_compiled_regex). If the user's
        # pattern is not valid regex (e.g. contains Windows backslashes) we
        # fall back to case-insensitive substring matching.
        self._deny: list[tuple[str, re.Pattern | None]] = []
        for raw in cfg.permissions.denylist:
            compiled: re.Pattern | None
            try:
                compiled = re.compile(raw, re.IGNORECASE)
            except re.error:
                compiled = None
            self._deny.append((raw, compiled))

    def is_denylisted(self, text: str) -> str | None:
        """Return matching pattern if `text` hits the denylist, else None."""
        if not text:
            return None
        haystack = text.lower()
        for raw, compiled in self._deny:
            if compiled is not None:
                if compiled.search(text):
                    return raw
            else:
                if raw.lower() in haystack:
                    return raw
        return None

    def evaluate(self, req: PermissionRequest) -> Decision:
        denied = self.is_denylisted(req.preview)
        if denied:
            return Decision.DENY

        # bypass: trust everything except the denylist. User-requested.
        if self.mode == "bypass":
            return Decision.ALLOW

        if req.permission is Permission.SAFE:
            return Decision.ALLOW

        if self.mode == "auto":
            if req.permission is Permission.CAUTION:
                return Decision.ALLOW
            return Decision.ASK  # DANGEROUS always asks
        if self.mode == "safe":
            if req.permission is Permission.CAUTION:
                return Decision.ASK
            return Decision.DENY  # DANGEROUS refused outside explicit override
        # confirm (default)
        return Decision.ASK
