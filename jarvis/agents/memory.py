from .base import Agent


class MemoryAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            name="memory",
            description="Curates JARVIS' long-term memory: prefs, notes, paths, fixes.",
            system_prompt=(
                "You are the MEMORY agent. Read prefs and notes before answering. "
                "When the user shares a fact worth keeping (preference, path, fix), "
                "use remember / add_note / set_path / add_fix. Search memory before "
                "asking for info you might already have."
            ),
            tool_allowlist=[
                "remember", "recall", "forget", "list_prefs",
                "add_note", "list_notes", "search_memory",
                "set_path", "get_path", "list_paths",
                "record_tool", "list_tools",
                "add_fix", "lookup_fix",
                "top_commands",
            ],
        )
