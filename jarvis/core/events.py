"""Event types emitted by the orchestrator to the UI."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .permissions import PermissionRequest


class EventKind(str, Enum):
    INFO = "info"
    THINKING = "thinking"
    ASSISTANT = "assistant"
    USER = "user"
    TOOL_PROPOSED = "tool_proposed"
    TOOL_RESULT = "tool_result"
    CONFIRMATION = "confirmation"
    TASK_START = "task_start"
    TASK_END = "task_end"
    TASK_PROGRESS = "task_progress"   # mid-task progress update from a tool
    ERROR = "error"
    DONE = "done"
    MEDIA = "media"  # structured media payload → renders inline in Media Bay
    PLAN = "plan"    # autonomous plan for a complex task → renders as a checklist
    SUGGESTIONS = "suggestions"  # proactive next-step chips after a turn
    STREAM_DELTA = "stream_delta"  # incremental assistant token chunk
    STREAM_BEGIN = "stream_begin"  # marks start of a new streamed assistant turn
    STREAM_END = "stream_end"      # marks end of a streamed assistant turn


@dataclass
class Event:
    kind: EventKind
    text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    confirm_req: PermissionRequest | None = None
    confirm_future: asyncio.Future | None = None
    # When this event was produced by a swarm subagent, set to that
    # subagent's stable id so the frontend can group / route events to the
    # correct card. None for normal single-agent events.
    swarm_id: str | None = None
    swarm_label: str | None = None
