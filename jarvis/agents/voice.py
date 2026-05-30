from .base import Agent


class VoiceAgent(Agent):
    """OPTIONAL — disabled by default. Enable voice_tools_optional plugin first."""

    def __init__(self) -> None:
        super().__init__(
            name="voice",
            description="OPTIONAL: speak text out loud / listen via microphone.",
            system_prompt=(
                "You are the VOICE agent. Use speak() to vocalise short replies. "
                "Use listen() only when explicitly asked. If no microphone is detected, "
                "fall back to text without complaining."
            ),
            tool_allowlist=["speak", "listen", "microphone_status"],
        )
