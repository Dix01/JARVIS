from .base import Agent


class PlannerAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            name="planner",
            description="Breaks complex requests into ordered, concrete steps.",
            system_prompt=(
                "Right now you are the PLANNER. Do not execute. "
                "Produce a numbered plan with 3–8 steps. Each step names "
                "the tool you would use (if any) and the exact inputs. "
                "End with a one-line summary of the goal. Be concise."
            ),
            tool_allowlist=[],  # planning uses no tools; pure reasoning
        )
