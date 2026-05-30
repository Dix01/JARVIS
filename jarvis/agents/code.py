from .base import Agent


class CodeAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            name="code",
            description="Writes, runs, debugs, and iterates on code.",
            system_prompt=(
                "You are the CODE agent. Plan briefly, then write code with "
                "write_file, run it with run_python / run_node / run_python_file, "
                "inspect stderr, fix issues, retry. Stop when the program runs "
                "clean OR you have reached the retry cap; explain the final state."
            ),
            tool_allowlist=[
                "write_file", "read_file", "append_file", "list_dir", "search_files",
                "run_python", "run_python_file", "run_node",
                "pip_install", "npm_install",
                "scan_project", "code_debug_loop",
                "add_fix", "lookup_fix",
            ],
        )
