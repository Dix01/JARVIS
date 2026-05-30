from .base import Agent


class SystemAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            name="system",
            description="Reports PC health and helps diagnose performance issues.",
            system_prompt=(
                "You are the SYSTEM agent. Read system_status, list_processes, "
                "network_info, battery, disk_usage, gpu_info — combine them into "
                "a short situational brief. Suggest concrete actions when something "
                "looks off (high CPU/RAM/disk). Never kill processes without confirmation."
            ),
            tool_allowlist=[
                "system_status", "list_processes", "network_info",
                "battery", "gpu_info", "disk_usage", "kill_process",
                "which", "env_var",
            ],
        )
