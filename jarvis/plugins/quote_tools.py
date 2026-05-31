"""Simple inspirational quote tools."""
from __future__ import annotations

from datetime import date

from ..core.permissions import Permission
from .base import PluginInfo, tool

QUOTES: tuple[str, ...] = (
    "The best way to predict the future is to invent it. -- Alan Kay",
    "Programs must be written for people to read. -- Harold Abelson",
    "Simplicity is prerequisite for reliability. -- Edsger W. Dijkstra",
    "Make it work, make it right, make it fast. -- Kent Beck",
    "The most damaging phrase is: we've always done it this way. -- Grace Hopper",
    "First, solve the problem. Then, write the code. -- John Johnson",
    "Talk is cheap. Show me the code. -- Linus Torvalds",
)


def _quote_for_day(day: date) -> str:
    return QUOTES[day.toordinal() % len(QUOTES)]


def register(registry):
    @tool(
        name="daily_quote",
        description="Return a deterministic inspirational quote for today.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    def daily_quote() -> str:
        return _quote_for_day(date.today())

    registry.add_pending("quote_tools")
    registry.register_plugin(
        PluginInfo(
            name="quote_tools",
            description="Read-only quote-of-the-day helper.",
            permissions_needed=[Permission.SAFE],
        )
    )
