from .base import Agent


class VisionAgent(Agent):
    """OPTIONAL — disabled by default. Enable the vision_tools_optional plugin first."""

    def __init__(self) -> None:
        super().__init__(
            name="vision",
            description="OPTIONAL: screenshot / OCR / webcam analysis.",
            system_prompt=(
                "You are the VISION agent. Only act when the user explicitly asks "
                "for screen or camera input. Always describe what you intend to capture "
                "and request confirmation. Never auto-capture in the background."
            ),
            tool_allowlist=[
                "screenshot", "ocr_image", "screen_ocr",
                "webcam_status", "webcam_snapshot",
            ],
        )
