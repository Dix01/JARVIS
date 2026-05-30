"""OPTIONAL: Calendar integration scaffold.

By default uses a local JSON file as a simple calendar so JARVIS can manage
reminders without external accounts. Future-proof: drop in Google Calendar
or Outlook by replacing the storage backend.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from ..core.permissions import Permission
from .base import PluginInfo, tool


def register(registry):
    cfg = registry.cfg
    cal_path: Path = cfg.abs_path("data/calendar.json")
    cal_path.parent.mkdir(parents=True, exist_ok=True)

    def _load() -> list[dict]:
        if not cal_path.exists():
            return []
        try:
            return json.loads(cal_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _save(events: list[dict]) -> None:
        cal_path.write_text(json.dumps(events, indent=2), encoding="utf-8")

    @tool(
        name="add_event",
        description="Add a calendar event. Time is a free-form string (e.g. '2026-06-01 14:00').",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "when": {"type": "string"},
                "notes": {"type": "string", "default": ""},
            },
            "required": ["title", "when"],
        },
        preview=lambda a: f"add event '{a.get('title')}' @ {a.get('when')}",
    )
    def add_event(title: str, when: str, notes: str = "") -> str:
        events = _load()
        events.append({
            "id": uuid.uuid4().hex[:8],
            "title": title,
            "when": when,
            "notes": notes,
            "created_at": time.time(),
        })
        _save(events)
        return f"event added: {title} @ {when}"

    @tool(
        name="list_events",
        description="List stored calendar events.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    def list_events() -> str:
        events = _load()
        if not events:
            return "(no events)"
        return "\n".join(f"[{e['id']}] {e['when']} — {e['title']}" + (f" ({e['notes']})" if e['notes'] else "") for e in events)

    @tool(
        name="remove_event",
        description="Remove an event by id.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
        preview=lambda a: f"remove event {a.get('id')}",
    )
    def remove_event(id: str) -> str:
        events = _load()
        new = [e for e in events if e["id"] != id]
        if len(new) == len(events):
            return f"no event with id {id}"
        _save(new)
        return f"removed {id}"

    registry.add_pending("calendar_optional")
    registry.register_plugin(PluginInfo(
        name="calendar_optional",
        description="OPTIONAL local JSON calendar.",
        permissions_needed=[Permission.CAUTION],
    ))
