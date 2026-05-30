from .base import Agent


class ExecutorAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            name="executor",
            description="Runs an approved plan step-by-step, reporting results.",
            system_prompt=(
                "You are the EXECUTOR. Carry out the plan exactly. "
                "Use one tool per turn, then summarise the outcome of that step "
                "in one short line. Stop and ask the user if any step fails "
                "twice or requires destructive action you cannot infer consent for."
            ),
        )
