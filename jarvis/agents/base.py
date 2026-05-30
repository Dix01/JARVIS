"""Agent base class.

An Agent is a *persona* the orchestrator can switch to. It supplies:
  - a `name`
  - a `description` shown in the UI
  - a system-prompt addendum that biases the brain toward its domain
  - an optional `tool_allowlist` restricting which tools are exposed

Agents are lightweight by design — the heavy lifting still happens in the
orchestrator's brain/tool loop. This keeps the architecture composable
without duplicating the inference plumbing per agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Agent:
    name: str
    description: str
    system_prompt: str = ""
    tool_allowlist: list[str] = field(default_factory=list)  # empty = all tools

    def applies_to(self, tool_name: str) -> bool:
        if not self.tool_allowlist:
            return True
        return tool_name in self.tool_allowlist


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def add(self, a: Agent) -> None:
        self._agents[a.name] = a

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def list(self) -> list[Agent]:
        return list(self._agents.values())

    def names(self) -> list[str]:
        return list(self._agents.keys())
