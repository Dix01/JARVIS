"""Concurrent multi-task execution — the JARVIS swarm runner.

A "swarm" runs a list of independent ToolCall requests in parallel through
the same orchestrator pipeline (permissions, hooks, media emit). Events
emitted by each branch are tagged with a stable `swarm_id` + human label
so the UI can route them to per-subtask cards.

Use cases:
  • "Search news on cairo, get me images of pyramids, and check the weather"
  • Compound reports — multiple web searches fanned out simultaneously
  • Anything where the LLM can decompose a request into independent units

The runner is invoked by the `parallel_tasks` meta-tool registered in
agent_backend_tools. It does NOT decompose tasks itself — the LLM produces
the list. This keeps swarm behaviour predictable and tool-safe.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, TYPE_CHECKING

from .events import Event, EventKind

if TYPE_CHECKING:
    from .orchestrator import Orchestrator
    # Imported lazily inside functions to avoid a circular import at module
    # load time (orchestrator imports swarm too).

log = logging.getLogger("jarvis.swarm")


@dataclass
class SwarmTask:
    label: str           # short human-readable name for the UI card
    tool: str            # tool name to run
    args: dict           # tool args


async def run_swarm(
    orchestrator: "Orchestrator",
    tasks: list[SwarmTask],
    *,
    max_concurrency: int = 4,
) -> AsyncIterator[Event]:
    """Fan out `tasks` through orchestrator._invoke_tool in parallel.

    Yields events from every subtask interleaved in arrival order. Each
    event is stamped with the subtask's swarm_id + label. A final
    aggregated INFO event reports per-task ok/fail.

    Concurrency capped at `max_concurrency` to avoid lock contention on
    GPU-heavy tools (FLUX/SF3D serialize via the VRAM manager anyway).
    """
    from .orchestrator import ToolCall  # local import — avoids cycle

    if not tasks:
        yield Event(EventKind.INFO, text="swarm: no tasks supplied")
        return

    swarm_run_id = uuid.uuid4().hex[:8]
    log.info("swarm %s: dispatching %d tasks", swarm_run_id, len(tasks))

    # Announce the swarm so the frontend can pre-create cards in order.
    yield Event(
        EventKind.INFO,
        text=f"⌬ Swarm dispatched: {len(tasks)} parallel tasks",
        payload={
            "swarm": True,
            "swarm_run_id": swarm_run_id,
            "tasks": [{"id": f"{swarm_run_id}:{i}", "label": t.label, "tool": t.tool}
                      for i, t in enumerate(tasks)],
        },
    )

    sem = asyncio.Semaphore(max_concurrency)
    # Shared queue so all subagents can shove events at the main loop
    # interleaved. None is the per-branch sentinel for "branch done".
    out: asyncio.Queue = asyncio.Queue()

    async def _run_one(idx: int, task: SwarmTask) -> tuple[int, bool, str]:
        sid = f"{swarm_run_id}:{idx}"
        async with sem:
            tc = ToolCall(name=task.tool, args=task.args, raw="", call_id=sid)
            ok = True
            last_result = ""
            try:
                async for ev in orchestrator._invoke_tool(tc):
                    # Tag every event with the swarm subagent id.
                    ev.swarm_id = sid
                    ev.swarm_label = task.label
                    if ev.kind is EventKind.TOOL_RESULT:
                        last_result = ev.text
                        if ev.payload and ev.payload.get("ok") is False:
                            ok = False
                    await out.put(ev)
            except Exception as e:  # noqa: BLE001
                log.exception("swarm %s task %d failed", swarm_run_id, idx)
                await out.put(Event(
                    EventKind.ERROR,
                    text=f"{task.label}: {type(e).__name__}: {e}",
                    swarm_id=sid,
                    swarm_label=task.label,
                ))
                ok = False
                last_result = str(e)
            await out.put(None)  # sentinel: this branch done
            return idx, ok, last_result

    # Kick off every branch immediately.
    runners = [asyncio.create_task(_run_one(i, t)) for i, t in enumerate(tasks)]
    pending_branches = len(tasks)

    try:
        # Drain the multiplexed event queue until every branch reports done.
        while pending_branches > 0:
            item = await out.get()
            if item is None:
                pending_branches -= 1
                continue
            yield item

        results = await asyncio.gather(*runners, return_exceptions=True)
        summary_lines: list[str] = []
        for r in results:
            if isinstance(r, BaseException):
                summary_lines.append(f"✗ swarm task crashed: {r}")
                continue
            idx, ok, res = r
            mark = "✓" if ok else "✗"
            label = tasks[idx].label
            summary_lines.append(f"{mark} [{label}] {res[:120]}")

        log.info("swarm %s: complete", swarm_run_id)
        yield Event(
            EventKind.INFO,
            text="⌬ Swarm complete:\n" + "\n".join(summary_lines),
            payload={"swarm": True, "swarm_run_id": swarm_run_id, "summary": summary_lines},
        )
    finally:
        # If the consumer abandons us mid-drain (barge-in / new request cancels
        # the brain task), cancel any still-running branches so they don't leak
        # as orphaned tasks ("Task was destroyed but it is pending!").
        for r in runners:
            if not r.done():
                r.cancel()
