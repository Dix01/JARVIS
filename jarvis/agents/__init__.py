from .base import Agent, AgentRegistry
from .planner import PlannerAgent
from .executor import ExecutorAgent
from .research import ResearchAgent
from .code import CodeAgent
from .file import FileAgent
from .system import SystemAgent
from .memory import MemoryAgent
from .vision import VisionAgent
from .voice import VoiceAgent

__all__ = [
    "Agent",
    "AgentRegistry",
    "PlannerAgent",
    "ExecutorAgent",
    "ResearchAgent",
    "CodeAgent",
    "FileAgent",
    "SystemAgent",
    "MemoryAgent",
    "VisionAgent",
    "VoiceAgent",
]


def build_default_registry(cfg) -> AgentRegistry:
    """Construct the agent registry honoring the per-agent enable flags."""
    reg = AgentRegistry()
    candidates: list[Agent] = [
        PlannerAgent(),
        ExecutorAgent(),
        ResearchAgent(),
        CodeAgent(),
        FileAgent(),
        SystemAgent(),
        MemoryAgent(),
        VisionAgent(),
        VoiceAgent(),
    ]
    for a in candidates:
        toggle = cfg.agents.get(a.name)
        if toggle is not None and not toggle.enabled:
            continue
        reg.add(a)
    return reg
