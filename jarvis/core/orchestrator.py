"""Orchestrator: drives the chat <-> tool loop.

Owns the LLM brain, plugin registry, permission manager, conversation history,
and the event stream consumed by the UI.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, AsyncIterator, TYPE_CHECKING

import json

if TYPE_CHECKING:
    from .semantic_memory import SemanticMemory

from ..agents.base import Agent
from ..config import Config
from ..plugins.base import Tool
from ..plugins.registry import PluginRegistry
from .brain import BrainReply, LLMBrain, ToolCall
from .events import Event, EventKind
from .task_progress import set_reporter
from .hooks import HookRegistry
from .intent_router import IntentMatch, classify as classify_intent, classify_multi
from .logger import ActionLog
from .memory import Memory
from .permissions import (
    Decision,
    Permission,
    PermissionManager,
    PermissionRequest,
)
from .responses import core_reply
from .style import clean_assistant_text, is_malformed_reply

MEDIA_PREFIX = "__JARVIS_MEDIA__"

log = logging.getLogger("jarvis.orchestrator")

MAX_TOOL_HOPS = 10

# Phrases that indicate the model is *promising* an action without doing it.
# When matched in a text-only assistant reply (no tool calls in the same hop),
# the orchestrator injects one nudge to force follow-through.
PROMISE_RE = re.compile(
    r"\b(?:"
    r"i(?:'|\s*a)?ll\s+(?:try|run|attempt|check|look|do|fix|see|verify|analyze|search|launch|open|test|investigate|diagnose|capture|find|pull|grab|create|build|write|generate|fetch)|"
    r"let\s+me\s+(?:try|run|check|look|verify|see|analyze|search|investigate|diagnose|capture|fetch|test)|"
    r"standing\s+by|one\s+moment|attempting\s+(?:to|another)|"
    r"i'?m\s+(?:going\s+to|about\s+to)|"
    r"shall\s+i\s+(?:try|run|attempt|check|do|fix|see|verify|analyze|search|test)|"
    r"i\s+will\s+now|i'?ll\s+now|running\s+diagnostic"
    r")\b",
    re.IGNORECASE,
)
PROMISE_FOLLOWUP_LIMIT = 1   # at most one auto-nudge per user turn


# Tools whose work is too expensive to throw away when a new chat arrives.
# The WS layer holds new chats until these finish instead of cancelling.
UNINTERRUPTIBLE_TOOLS = frozenset({
    "image_generate",
    "image_to_3d",
    "text_to_3d",
})


class Orchestrator:
    def __init__(
        self,
        cfg: Config,
        brain: LLMBrain,
        registry: PluginRegistry,
        memory: Memory,
        permissions: PermissionManager,
        actions: ActionLog,
        hooks: HookRegistry | None = None,
        semantic: "SemanticMemory | None" = None,
    ):
        self.cfg = cfg
        self.brain = brain
        self.registry = registry
        self.memory = memory
        self.permissions = permissions
        self.actions = actions
        self.hooks = hooks or HookRegistry()
        self.semantic = semantic
        # Long-term memories recalled for the current user turn. Rebuilt each
        # turn and injected into the system prompt by _system_prompt().
        self._recalled: list[dict] = []
        # Rolling summary of compacted older turns (long-session memory).
        self._running_summary: str = ""
        # Plan for the current complex task (autonomous planning). Set per
        # turn, injected into the system prompt to anchor multi-step execution.
        self._current_plan: str = ""
        self._history: list[dict] = []
        self._active_agent: Agent | None = None
        # Name of the tool currently running, or None when idle. Used by the
        # WS layer to decide whether a new chat message should cancel the
        # in-flight task. Heavy tools (image_generate, image_to_3d,
        # text_to_3d) protect their work via UNINTERRUPTIBLE_TOOLS below.
        self.busy_tool: str | None = None

        # Default emit-hook: lift tool results carrying a __JARVIS_MEDIA__
        # JSON payload into a proper MEDIA event. This is what makes
        # web_search / image_search / video_search render inline.
        self.hooks.add_emit(self._media_emit_hook)

    async def _media_emit_hook(self, tool: str, args: dict, ok: bool, result):
        if not ok or not isinstance(result, str) or not result.startswith(MEDIA_PREFIX):
            return []
        try:
            payload = json.loads(result[len(MEDIA_PREFIX):])
        except Exception:
            return []
        payload["tool"] = tool
        payload["args"] = args
        return [Event(EventKind.MEDIA, text=payload.get("summary", ""), payload=payload)]

    # ------------------------------------------------------------------
    def _system_prompt(self) -> str:
        persona = self.cfg.A.persona.strip()
        runtime = (
            "Runtime context: "
            f"provider={self.cfg.model.provider}; "
            f"model={self.cfg.model.model}; "
            f"image_model={getattr(getattr(self.cfg, 'image_model', None), 'selected', 'flux2-klein')}; "
            f"tools={len(self.registry.all_tools())}; "
            f"permission_mode={self.cfg.permissions.mode}."
        )
        persona = "\n\n".join([persona, runtime])
        if self._active_agent and self._active_agent.system_prompt:
            persona = "\n\n".join(
                [
                    persona,
                    f"Current operating mode: {self._active_agent.name}.",
                    self._active_agent.system_prompt.strip(),
                ]
            )
        if self._running_summary:
            persona = "\n\n".join([
                persona,
                "Summary of earlier conversation (older turns were compacted "
                "to save context):\n" + self._running_summary,
            ])
        if self._current_plan:
            persona = "\n\n".join([
                persona,
                "Your plan for the current task (execute it step by step, "
                "calling the named tools; adapt if a step proves wrong):\n"
                + self._current_plan,
            ])
        mem_block = self._recalled_block()
        if mem_block:
            persona = "\n\n".join([persona, mem_block])
        tools_doc = self.registry.documentation()
        return self.brain.build_system_prompt(persona, tools_doc)

    def _recalled_block(self) -> str:
        """Render recalled long-term memories as a system-prompt section."""
        if not self._recalled:
            return ""
        lines = [
            "Relevant long-term memory (recalled for this turn — trust the "
            "live conversation if anything here conflicts):",
        ]
        for m in self._recalled:
            kind = m.get("kind", "fact")
            lines.append(f"- [{kind}] {m.get('text', '').strip()}")
        return "\n".join(lines)

    def _ultimate_on(self, feature: str) -> bool:
        u = getattr(self.cfg, "ultimate", None)
        if u is None or not u.enabled or self.semantic is None:
            return False
        return bool(getattr(u, feature, False))

    async def _recall_for(self, user_text: str) -> list[dict]:
        if not self._ultimate_on("semantic_memory"):
            return []
        try:
            return await self.semantic.recall(user_text)
        except Exception:  # noqa: BLE001
            log.exception("semantic recall failed")
            return []

    async def _maybe_compact_history(self) -> int:
        """Fold older turns into a rolling summary once history grows past the
        configured trigger. Keeps recent turns verbatim. Returns the number of
        messages folded (0 if no compaction happened). Best-effort + gated."""
        u = getattr(self.cfg, "ultimate", None)
        if u is None or not u.enabled or not u.context_compaction:
            return 0
        trigger = max(8, u.compaction_trigger_messages)
        keep = max(4, u.compaction_keep_recent)
        if len(self._history) <= trigger:
            return 0

        # Find a clean exchange boundary at/above the keep window: a real user
        # turn (not a tool result / internal nudge). Cutting there avoids
        # orphaning a tool-result whose tool_call lived in the folded head.
        cut: int | None = None
        for i in range(len(self._history) - keep, 0, -1):
            m = self._history[i]
            content = m.get("content", "")
            if (
                m.get("role") == "user"
                and "tool_call_id" not in m
                and not (isinstance(content, str) and content.startswith("<tool_result"))
                and not (isinstance(content, str) and content.startswith("(internal protocol"))
            ):
                cut = i
                break
        if cut is None or cut < 6:
            return 0

        head = self._history[:cut]
        try:
            summary = await self._summarize(head)
        except Exception:  # noqa: BLE001
            log.exception("history compaction failed")
            return 0
        if not summary:
            return 0

        self._running_summary = summary
        self._history = self._history[cut:]
        log.info(
            "compacted %d msgs into running summary (%d chars); %d kept verbatim",
            len(head), len(summary), len(self._history),
        )
        return len(head)

    async def _summarize(self, msgs: list[dict]) -> str:
        excerpt = _serialize_history(msgs)
        prior = (
            f"Existing notes:\n{self._running_summary}\n\n" if self._running_summary else ""
        )
        prompt = [
            {
                "role": "system",
                "content": (
                    "You compress conversation logs into durable notes. Output "
                    "4-8 terse bullet points capturing: decisions made, facts and "
                    "preferences learned about the user, tasks completed, and open "
                    "threads still in progress. No preamble, no fluff — bullets only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{prior}New excerpt to fold in:\n{excerpt}\n\n"
                    "Return the updated consolidated notes."
                ),
            },
        ]
        reply = await self.brain.chat(prompt)
        return clean_assistant_text(reply.text)

    async def _maybe_plan(self, user_text: str) -> str:
        """For a sufficiently complex request, draft a short execution plan
        before touching tools. Returns the plan text (anchored into the system
        prompt for this turn) or "" when planning is off / the task is trivial.
        Best-effort: any failure returns "" and execution proceeds unplanned."""
        u = getattr(self.cfg, "ultimate", None)
        if u is None or not u.enabled or not u.autonomous_planning:
            return ""
        if len((user_text or "").strip()) < max(20, u.plan_min_chars):
            return ""
        prompt = [
            {
                "role": "system",
                "content": (
                    "You are the planning stage of an autonomous assistant that "
                    "has tools. Draft a SHORT plan for the user's request: 2-6 "
                    "numbered steps, each naming the tool to use (if any) and the "
                    "concrete input. No preamble, no final answer — steps only. "
                    "If the request is trivial and needs no tools, reply exactly "
                    "NONE."
                ),
            },
            {"role": "user", "content": user_text.strip()},
        ]
        try:
            reply = await self.brain.chat(prompt)
        except Exception:  # noqa: BLE001
            log.exception("planning failed")
            return ""
        plan = clean_assistant_text(reply.text).strip()
        if not plan or plan.upper().startswith("NONE") or len(plan) < 12:
            return ""
        return plan

    async def _reflect(self, user_text: str, final_text: str) -> str | None:
        """After a planned task finishes, verify completion ONCE. Returns a
        one-line next-action string if work remains, else None. Best-effort."""
        if not self._current_plan:
            return None
        prompt = [
            {
                "role": "system",
                "content": (
                    "You verify whether an assistant fully completed a task. "
                    "Given the user's request, the plan, and the assistant's "
                    "final answer, decide if every step was genuinely carried "
                    "out. If complete, reply exactly DONE. If not, reply with a "
                    "SINGLE sentence naming the one concrete next tool action "
                    "needed. No other output."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User request:\n{user_text.strip()}\n\n"
                    f"Plan:\n{self._current_plan}\n\n"
                    f"Final answer given:\n{final_text.strip()}"
                ),
            },
        ]
        try:
            reply = await self.brain.chat(prompt)
        except Exception:  # noqa: BLE001
            log.exception("reflection failed")
            return None
        verdict = clean_assistant_text(reply.text).strip()
        if not verdict or verdict.upper().startswith("DONE"):
            return None
        return verdict[:300]

    async def _suggest(self, user_text: str, final_text: str) -> list[str]:
        """Propose 2-3 short next-step follow-ups the user might want next.
        Returns [] when suggestions are off, the reply is trivial, or on any
        failure. Surfaced as clickable chips by the UI."""
        u = getattr(self.cfg, "ultimate", None)
        if u is None or not u.enabled or not u.proactive_suggestions:
            return []
        if len((final_text or "").strip()) < 40:
            return []
        prompt = [
            {
                "role": "system",
                "content": (
                    "You propose what the user might want to do NEXT, given the "
                    "exchange. Output 2-3 suggestions, one per line, each a short "
                    "imperative the user could click to send (max 7 words, no "
                    "numbering, no punctuation at the end). They must be natural "
                    "follow-ups, not restatements. If nothing useful, output NONE."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User asked:\n{user_text.strip()}\n\n"
                    f"You answered:\n{final_text.strip()}\n\n"
                    "Suggested next steps:"
                ),
            },
        ]
        try:
            reply = await self.brain.chat(prompt)
        except Exception:  # noqa: BLE001
            log.exception("suggestion generation failed")
            return []
        raw = clean_assistant_text(reply.text).strip()
        if not raw or raw.upper().startswith("NONE"):
            return []
        out: list[str] = []
        for line in raw.splitlines():
            s = re.sub(r"^(?:\d+[.)]\s*|[-*•]\s*)", "", line.strip()).strip(" .\t\"'")
            if 2 < len(s) <= 60:
                out.append(s)
        return out[:3]

    async def _auto_remember(self, user_text: str) -> None:
        if not self._ultimate_on("semantic_memory") or not self.cfg.ultimate.auto_remember:
            return
        fact = _extract_durable_fact(user_text)
        if fact is None:
            return
        kind, text = fact
        try:
            wrote = await self.semantic.remember(text, kind=kind, meta={"source": "auto"})
            if wrote:
                log.info("auto-remembered [%s] %s", kind, text[:80])
        except Exception:  # noqa: BLE001
            log.exception("auto-remember failed")

    def reset(self) -> None:
        self._history.clear()

    def set_agent(self, agent: Agent | None) -> None:
        self._active_agent = agent

    def build_messages(self, user_text: str) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt()}
        ]
        msgs.extend(self._history)
        msgs.append({"role": "user", "content": user_text})
        return msgs

    # ------------------------------------------------------------------
    async def handle_user_message(
        self,
        user_text: str,
        attachments: list[dict] | None = None,
    ) -> AsyncIterator[Event]:
        self.memory.append_message("user", user_text)
        user_msg: dict = {"role": "user", "content": user_text}
        if attachments:
            user_msg["attachments"] = attachments
        self._history.append(user_msg)
        # Clear any plan from a previous turn so it can't leak into the
        # immediate / intent fast-paths (which never re-plan).
        self._current_plan = ""

        # Capture durable self-disclosure ("my name is…", "I prefer…") into
        # long-term semantic memory. Gated + best-effort.
        await self._auto_remember(user_text)

        immediate = core_reply(user_text, self.cfg)
        if immediate:
            self._history.append({"role": "assistant", "content": immediate})
            self.memory.append_message("assistant", immediate)
            yield Event(EventKind.ASSISTANT, text=immediate)
            yield Event(EventKind.DONE)
            return

        # Multi-intent fast-path — a COMPOUND request ("1: … 2: … 3: …", or
        # newline / semicolon separated) that decomposes into 2+ deterministic
        # intents is fanned out through the swarm runner. No LLM round-trip,
        # so EVERY command runs (not just the first regex match). This is the
        # fix for "I gave 3 commands but only the image generated".
        multi = classify_multi(user_text)
        if multi is not None:
            from .swarm import SwarmTask, run_swarm
            tasks = [
                SwarmTask(label=m.name, tool=m.tool_call.name, args=m.tool_call.args)
                for m in multi
            ]
            yield Event(
                EventKind.INFO,
                text=f"multi-intent: {len(tasks)} commands → swarm",
            )
            async for ev in run_swarm(self, tasks):
                yield ev
            final = f"Ran {len(tasks)} requests in parallel, sir."
            self._history.append({"role": "assistant", "content": final})
            self.memory.append_message("assistant", final)
            yield Event(EventKind.ASSISTANT, text=final)
            yield Event(EventKind.DONE)
            return

        # Deterministic intent routing — high-confidence search / FS /
        # browser / agent intents fire here BEFORE the LLM ever sees them.
        # This is what prevents the regression where "populate latest news
        # on X" gets answered by `browser_open` instead of `web_search`.
        intent = classify_intent(user_text)
        if intent is not None:
            yield Event(
                EventKind.INFO,
                text=f"intent: {intent.name} → {intent.tool_call.name}",
            )
            async for ev in self._handle_intent(intent):
                yield ev
            return

        # Fold older turns into a rolling summary once history grows long, so
        # deep sessions don't blow the context window. Gated + best-effort.
        folded = await self._maybe_compact_history()
        if folded:
            yield Event(
                EventKind.INFO,
                text=f"compacted {folded} older messages into memory",
            )

        # Recall relevant long-term memory for the reasoning path only — the
        # immediate/intent paths above never touch the LLM prompt.
        self._recalled = await self._recall_for(user_text)

        # Autonomous planning: for a complex request, draft a plan first and
        # surface it to the UI. The plan is injected into the system prompt so
        # the hop loop executes against it. Gated + best-effort.
        self._current_plan = await self._maybe_plan(user_text)
        if self._current_plan:
            yield Event(
                EventKind.PLAN,
                text=self._current_plan,
                payload={"steps": _plan_steps(self._current_plan)},
            )

        hop = 0
        promise_followups = 0
        reflections = 0
        while hop < MAX_TOOL_HOPS:
            hop += 1
            yield Event(EventKind.THINKING, text="thinking...")

            messages: list[dict] = [
                {"role": "system", "content": self._system_prompt()}
            ]
            messages.extend(self._history)

            # Stream this hop. Bridge sync on_delta callback → async event
            # yield via a queue so consumers see token-by-token output.
            delta_queue: asyncio.Queue = asyncio.Queue()
            done_marker = object()

            def _on_delta(piece: str) -> None:
                try:
                    delta_queue.put_nowait(piece)
                except Exception:  # noqa: BLE001
                    pass

            stream_task = asyncio.create_task(
                self.brain.chat_stream(
                    messages,
                    tool_schemas=self.registry.schemas(),
                    on_delta=_on_delta,
                )
            )

            stream_began = False
            get_task: asyncio.Task | None = None
            try:
                while True:
                    # Race: next delta vs stream completion.
                    get_task = asyncio.create_task(delta_queue.get())
                    done, _ = await asyncio.wait(
                        {get_task, stream_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if get_task in done:
                        piece = get_task.result()
                        if not stream_began:
                            stream_began = True
                            yield Event(EventKind.STREAM_BEGIN)
                        yield Event(EventKind.STREAM_DELTA, text=piece)
                    else:
                        get_task.cancel()
                        # Await the cancel so the Queue.get() task is properly
                        # cleaned up — otherwise the GC logs
                        # "Task was destroyed but it is pending" on shutdown.
                        try:
                            await get_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        # Drain any pending deltas before exiting.
                        while not delta_queue.empty():
                            piece = delta_queue.get_nowait()
                            if not stream_began:
                                stream_began = True
                                yield Event(EventKind.STREAM_BEGIN)
                            yield Event(EventKind.STREAM_DELTA, text=piece)
                        break
                reply: BrainReply = stream_task.result()
            except asyncio.CancelledError:
                # Cancel + drain BOTH child tasks so neither leaks as
                # "pending Task destroyed" warnings on GC.
                stream_task.cancel()
                try:
                    await stream_task
                except (asyncio.CancelledError, Exception):
                    pass
                if get_task is not None and not get_task.done():
                    get_task.cancel()
                    try:
                        await get_task
                    except (asyncio.CancelledError, Exception):
                        pass
                raise
            finally:
                if stream_began:
                    yield Event(EventKind.STREAM_END)

            assistant_text = clean_assistant_text(reply.text)
            if not reply.tool_calls and is_malformed_reply(assistant_text, user_text):
                reply, assistant_text = await self._repair_malformed_reply(
                    messages=messages,
                    reply=reply,
                    user_text=user_text,
                )

            if assistant_text and not reply.tool_calls:
                # FOLLOW-THROUGH GUARD: did the model promise an action
                # without calling any tool? Inject ONE nudge to force
                # execution, then re-run the loop. Cap at PROMISE_FOLLOWUP_LIMIT
                # so we never spin forever.
                if (
                    promise_followups < PROMISE_FOLLOWUP_LIMIT
                    and PROMISE_RE.search(assistant_text)
                ):
                    promise_followups += 1
                    self._history.append({"role": "assistant", "content": reply.raw or assistant_text})
                    self.memory.append_message("assistant", assistant_text)
                    # Surface the announcement to the UI (replace streamed partial
                    # with cleaned text), then nudge the model to follow through.
                    yield Event(EventKind.ASSISTANT, text=assistant_text)
                    self._history.append({
                        "role": "user",
                        "content": (
                            "(internal protocol — not from the user) "
                            "You just announced an action ('I'll …' / 'Standing by' / "
                            "'Let me check' / etc.) without executing. Follow through "
                            "NOW: call the appropriate tool to perform the action you "
                            "just promised. Do not respond with words alone."
                        ),
                    })
                    continue  # next hop

                self._history.append({"role": "assistant", "content": reply.raw or assistant_text})
                self.memory.append_message("assistant", assistant_text)
                yield Event(EventKind.ASSISTANT, text=assistant_text)

                # Self-reflection: for a planned task, verify completion ONCE.
                # If a concrete step still remains, inject it and keep going;
                # otherwise close the turn. Capped so it can never spin.
                if self._current_plan and reflections < 1:
                    reflections += 1
                    next_action = await self._reflect(user_text, assistant_text)
                    if next_action:
                        yield Event(EventKind.INFO, text="verifying plan completion")
                        self._history.append({
                            "role": "user",
                            "content": (
                                "(internal protocol — not from the user) "
                                "Self-check on your own plan: the task is not yet "
                                f"complete. Next concrete action: {next_action} "
                                "Execute it now by calling the appropriate tool. "
                                "Do not reply with words alone."
                            ),
                        })
                        continue  # next hop

                chips = await self._suggest(user_text, assistant_text)
                if chips:
                    yield Event(EventKind.SUGGESTIONS, payload={"items": chips})
                yield Event(EventKind.DONE)
                return

            # Native tool calls: append assistant turn with proper tool_calls
            # array so the next round can match tool_call_id → tool result.
            if any(tc.call_id for tc in reply.tool_calls):
                self._history.append({
                    "role": "assistant",
                    "content": reply.raw or assistant_text or "",
                    "tool_calls": [
                        {
                            "id": tc.call_id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.args, ensure_ascii=False),
                            },
                        }
                        for tc in reply.tool_calls if tc.call_id
                    ],
                })
            else:
                self._history.append({"role": "assistant", "content": reply.raw or assistant_text})

            if not reply.tool_calls:
                fallback = (
                    "I am online, sir, but the local model returned no usable text. "
                    "Give me the order once more and I will re-run it cleanly."
                )
                self._history.append({"role": "assistant", "content": fallback})
                self.memory.append_message("assistant", fallback)
                yield Event(EventKind.ASSISTANT, text=fallback)
                yield Event(EventKind.DONE)
                return

            for tc in reply.tool_calls:
                async for ev in self._invoke_tool(tc):
                    yield ev

        yield Event(
            EventKind.ERROR,
            text=f"Tool loop exceeded {MAX_TOOL_HOPS} hops. Stopping.",
        )
        yield Event(EventKind.DONE)

    async def _repair_malformed_reply(
        self,
        messages: list[dict[str, str]],
        reply: BrainReply,
        user_text: str,
    ) -> tuple[BrainReply, str]:
        repair_messages = [
            *messages,
            {"role": "assistant", "content": reply.raw or reply.text or ""},
            {
                "role": "user",
                "content": (
                    "Protocol correction: your previous answer was empty, echoed, "
                    "or malformed. Answer the user's latest message directly now "
                    "in JARVIS mode. No hidden reasoning. One to three polished "
                    "sentences unless the user asked for detail."
                ),
            },
        ]
        repaired = await self.brain.chat(
            repair_messages, tool_schemas=self.registry.schemas()
        )
        repaired_text = clean_assistant_text(repaired.text)
        if repaired.tool_calls or not is_malformed_reply(repaired_text, user_text):
            return repaired, repaired_text
        return reply, clean_assistant_text(reply.text)

    async def _handle_intent(self, intent: IntentMatch) -> AsyncIterator[Event]:
        """Execute a router-classified intent end-to-end.

        Runs the matched tool, surfaces tool/media events, then closes the
        turn with the intent's final prefix. The model is bypassed entirely
        — guaranteeing deterministic routing for high-confidence inputs.
        """
        # Fallback shim: web_search → browser_search if the structured tool
        # is somehow not registered (shouldn't happen in normal setups).
        tc = intent.tool_call
        if self.registry.get(tc.name) is None:
            fallback = {
                "web_search": "browser_search",
                "image_search": "web_search",
                "video_search": "web_search",
                "memory_galaxy": "search_memory",
                "webcam_see": "webcam_snapshot",
                "open_inline": "browser_open",
            }.get(tc.name)
            if fallback and self.registry.get(fallback):
                log.warning("intent tool '%s' missing, falling back to '%s'", tc.name, fallback)
                tc = ToolCall(fallback, tc.args, tc.raw, tc.call_id)

        result_text = ""
        async for ev in self._invoke_tool(tc):
            if ev.kind is EventKind.TOOL_RESULT:
                result_text = ev.text
            yield ev

        final = intent.final_prefix
        if result_text and intent.name not in {"web_search", "image_search", "video_search", "memory_galaxy", "webcam_see", "open_inline", "image_generate", "text_to_3d", "image_to_3d"}:
            # For media intents the result is already rendered as a card in
            # the Media Bay — appending a wall of text below it is noise.
            # For everything else the result IS the substance.
            final = f"{final}\n{result_text}"
        self._history.append({"role": "assistant", "content": final})
        self.memory.append_message("assistant", final)
        yield Event(EventKind.ASSISTANT, text=final)
        yield Event(EventKind.DONE)

    # ------------------------------------------------------------------
    async def _invoke_tool(self, tc: ToolCall) -> AsyncIterator[Event]:
        tool: Tool | None = self.registry.get(tc.name)
        if tool is None:
            yield Event(
                EventKind.TOOL_RESULT,
                text=f"unknown tool: {tc.name}",
                payload={"tool": tc.name, "ok": False},
            )
            self._history.append(
                {
                    "role": "user",
                    "content": f"<tool_result name=\"{tc.name}\" ok=\"false\">"
                               f"unknown tool</tool_result>",
                }
            )
            return

        preview = tool.preview(tc.args)
        req = PermissionRequest(
            tool=tool.name, args=tc.args, permission=tool.permission, preview=preview
        )

        yield Event(
            EventKind.TOOL_PROPOSED,
            text=preview,
            payload={"tool": tool.name, "permission": tool.permission.value, "args": tc.args},
        )

        decision = self.permissions.evaluate(req)
        if decision is Decision.ASK:
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            yield Event(
                EventKind.CONFIRMATION,
                text=preview,
                confirm_req=req,
                confirm_future=fut,
            )
            try:
                approved = await fut
            except asyncio.CancelledError:
                approved = False
            if not approved:
                decision = Decision.DENY
            else:
                decision = Decision.ALLOW

        if decision is Decision.DENY:
            denial = f"Denied by policy or user: {tool.name}"
            self.actions.record("denied", tool=tool.name, args=tc.args, preview=preview)
            yield Event(
                EventKind.TOOL_RESULT,
                text=denial,
                payload={"tool": tool.name, "ok": False, "denied": True},
            )
            self._history.append(
                {
                    "role": "user",
                    "content": f"<tool_result name=\"{tool.name}\" ok=\"false\">"
                               f"{denial}</tool_result>",
                }
            )
            return

        yield Event(EventKind.TASK_START, text=f"{tool.name}: {preview}")
        t0 = time.perf_counter()

        # Wire a thread-safe progress reporter so tools can push mid-task
        # status updates back to the UI while running in an executor thread.
        loop = asyncio.get_running_loop()
        prog_q: asyncio.Queue = asyncio.Queue()

        def _progress_report(msg: str) -> None:
            loop.call_soon_threadsafe(prog_q.put_nowait, msg)

        set_reporter(_progress_report)

        self.busy_tool = tool.name
        try:
            # PRE hook can mutate args or veto with PermissionError
            args_after_pre = await self.hooks.run_pre(tool.name, tc.args)

            # Run the tool as an async task so we can concurrently drain the
            # progress queue and emit TASK_PROGRESS events in real-time.
            tool_task = asyncio.ensure_future(tool.invoke(args_after_pre))
            get_task: asyncio.Task | None = None
            while not tool_task.done():
                if get_task is None or get_task.done():
                    get_task = asyncio.ensure_future(prog_q.get())
                done_set, _ = await asyncio.wait(
                    {tool_task, get_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if get_task in done_set:
                    prog_msg = get_task.result()
                    get_task = None
                    yield Event(EventKind.TASK_PROGRESS, text=prog_msg, payload={"tool": tool.name})
            if get_task is not None and not get_task.done():
                get_task.cancel()
                try:
                    await get_task
                except (asyncio.CancelledError, Exception):
                    pass
            # Drain any remaining progress messages flushed before task finished
            while not prog_q.empty():
                yield Event(EventKind.TASK_PROGRESS, text=prog_q.get_nowait(), payload={"tool": tool.name})

            result = tool_task.result()  # re-raises if tool raised
            # POST hook can mutate result
            result = await self.hooks.run_post(tool.name, args_after_pre, True, result)
            ok = True
            err: str | None = None
        except PermissionError as e:
            result = f"hook denied: {e}"
            ok = False
            err = result
            log.info("tool '%s' blocked by pre-hook: %s", tool.name, e)
        except Exception as e:  # noqa: BLE001
            result = f"{type(e).__name__}: {e}"
            ok = False
            err = result
            log.exception("tool '%s' failed", tool.name)
        finally:
            set_reporter(lambda _: None)  # clear reporter so stale threads don't leak
            self.busy_tool = None

        dt = time.perf_counter() - t0
        self.actions.record(
            "ran" if ok else "failed",
            tool=tool.name,
            args=tc.args,
            ok=ok,
            duration_s=round(dt, 3),
            error=err,
            preview=preview,
        )

        result_text = result if isinstance(result, str) else _to_str(result)

        yield Event(EventKind.TASK_END, text=tool.name, payload={"ok": ok, "duration_s": dt})

        # EMIT hooks: lift media payloads into proper MEDIA events
        for ev in await self.hooks.run_emit(tool.name, tc.args, ok, result_text):
            yield ev

        # Strip the MEDIA prefix from the text we show in the tool feed +
        # the text we hand back to the model — keep the readable summary only.
        display_text = result_text
        history_text = result_text
        if isinstance(result_text, str) and result_text.startswith(MEDIA_PREFIX):
            try:
                payload = json.loads(result_text[len(MEDIA_PREFIX):])
                display_text = payload.get("summary") or display_text
                history_text = payload.get("summary") or history_text
            except Exception:
                pass

        yield Event(
            EventKind.TOOL_RESULT,
            text=display_text,
            payload={"tool": tool.name, "ok": ok, "duration_s": dt},
        )

        # Append a proper tool-result message. With native tool calling we use
        # role="tool" + tool_call_id; otherwise we keep the legacy XML marker
        # that ReAct models expect.
        if tc.call_id:
            self._history.append({
                "role": "tool",
                "tool_call_id": tc.call_id,
                "name": tool.name,
                "content": history_text,
            })
        else:
            marker = (
                f"<tool_result name=\"{tool.name}\" ok=\"{str(ok).lower()}\">"
                f"{history_text}</tool_result>"
            )
            self._history.append({"role": "user", "content": marker})


def _to_str(x: Any) -> str:
    try:
        import json as _json
        return _json.dumps(x, default=str, ensure_ascii=False)
    except Exception:
        return str(x)


def _plan_steps(plan: str) -> list[str]:
    """Split a numbered/bulleted plan into individual step strings for the UI
    checklist. Falls back to non-empty lines if no list markers are found."""
    steps: list[str] = []
    for line in (plan or "").splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^(?:\d+[.)]\s*|[-*•]\s*)", "", s).strip()
        if s:
            steps.append(s)
    return steps[:8]


def _serialize_history(msgs: list[dict]) -> str:
    """Flatten history messages into a plain transcript for summarization.

    Handles string content, multimodal content lists (keeps text parts only),
    and appends the names of any tools the assistant called so the summary can
    note what work was done."""
    lines: list[str] = []
    for m in msgs:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            parts = [
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            text = " ".join(t for t in parts if t)
        else:
            text = str(content or "")
        tool_calls = m.get("tool_calls") or []
        if tool_calls:
            names = ", ".join(
                tc.get("function", {}).get("name", "?")
                for tc in tool_calls
                if isinstance(tc, dict)
            )
            if names:
                text = (text + f" [called: {names}]").strip()
        text = text.strip()
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


# ── Durable-fact extraction for auto-remember ──────────────────────────────
# Tight patterns: capture self-disclosure worth keeping across sessions
# without hoarding every casual "I'm not sure" line.
_REMEMBER_RE = re.compile(
    r"\b(?:remember|note|don'?t forget|keep in mind)\b(?:\s+that)?\s+(.+)",
    re.IGNORECASE,
)
_PREF_RE = re.compile(
    r"\bi\s+(?:really\s+)?(?:prefer|like|love|hate|dislike|don'?t\s+like|"
    r"can'?t\s+stand|enjoy)\b|\bmy\s+favou?rite\b",
    re.IGNORECASE,
)
_IDENTITY_RE = re.compile(
    r"\b(?:"
    r"my name is|call me|i am called|i'?m called|"
    r"i live in|i'?m from|i was born|"
    r"i work (?:at|as|for|on)|i'?m working on|"
    r"i'?m a |i am a |i'?m an |i am an |"
    r"i use |i'?m using |"
    r"my (?:email|phone|timezone|birthday|address|github|handle|username|"
    r"company|team|role|job|setup|machine|gpu|os|stack) is"
    r")\b",
    re.IGNORECASE,
)


def _extract_durable_fact(user_text: str) -> tuple[str, str] | None:
    """Return (kind, text) if the message contains a durable fact worth
    remembering, else None. `kind` ∈ {fact, preference}."""
    t = (user_text or "").strip()
    if len(t) < 4 or len(t) > 400:
        return None
    m = _REMEMBER_RE.search(t)
    if m and m.group(1).strip():
        return ("fact", m.group(1).strip()[:300])
    if _PREF_RE.search(t):
        return ("preference", t[:300])
    if _IDENTITY_RE.search(t):
        return ("fact", t[:300])
    return None
