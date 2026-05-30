from .base import Agent


class FileAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            name="file",
            description="Reads, writes, searches, and reorganises files safely.",
            system_prompt=(
                "You are the FILE agent. Always check the directory layout with "
                "list_dir before mutating anything. Use write_file's automatic "
                "backup. Never delete recursively without explicit confirmation."
            ),
            tool_allowlist=[
                "list_dir", "read_file", "write_file", "append_file",
                "search_files", "mkdir", "copy", "move", "delete", "stat",
                "scan_project",
            ],
        )
