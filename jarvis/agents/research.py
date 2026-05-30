from .base import Agent


class ResearchAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            name="research",
            description="Searches and summarises web sources.",
            system_prompt=(
                "You are the RESEARCH agent. Prefer web_search then web_fetch "
                "to read promising pages. Quote sources with their URL. "
                "Summarise findings in tight bullets. Never invent URLs."
            ),
            tool_allowlist=["web_search", "web_fetch", "remember", "add_note", "search_memory"],
        )
