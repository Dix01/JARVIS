"""WebSocket bridge — concurrent edition.

The previous version awaited `_stream_brain(...)` inline inside the receive
loop. That meant *while* the brain was streaming, the receive loop was
blocked. When the orchestrator yielded a CONFIRMATION event and awaited the
user's reply, the websocket could no longer receive `confirm` messages —
classic deadlock.

This version runs the brain as a background task and keeps the receive
loop hot, so confirmation replies (and cancellations) flow through
immediately. Each chat also cancels any in-flight chat.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..core.events import Event, EventKind
from ..core.orchestrator import UNINTERRUPTIBLE_TOOLS

log = logging.getLogger("jarvis.ws")

CONFIRM_TIMEOUT_S = 90  # auto-deny after this long if user never answers

HELP_TEXT = (
    "Slash commands:\n"
    "  /help                show this\n"
    "  /reset               wipe conversation history\n"
    "  /cancel              cancel in-flight task\n"
    "  /agent <name>        switch agent persona\n"
    "  /agents              list agents\n"
    "  /tools               list available tools\n"
    "  /image-model [id]    list or select local image model\n"
    "  /protocols           show JARVIS operating profile\n"
    "  /memory <query>      search local memory\n"
    "  /mission <path>      pin a project as the current focus\n"
    "  /cleanslate          Iron-Man style: wipe everything\n"
)


async def websocket_endpoint(ws: WebSocket) -> None:
    # Guard accept — if the browser dropped before the handshake finished,
    # `accept()` raises immediately. Without this guard the receive loop
    # below would crash with "WebSocket is not connected. Need to call
    # accept first." (see the ws_error trace from 2026-05-26 16:56:57).
    try:
        await ws.accept()
    except Exception as e:  # noqa: BLE001
        log.info("ws accept aborted by client: %s", e)
        return
    state = ws.app.state
    orchestrator = state.orchestrator
    memory = state.memory
    agents = state.agents
    cfg = state.cfg

    # Pending confirmation futures keyed by short id.
    pending: dict[str, asyncio.Future] = {}
    # The single in-flight brain task (None if idle).
    brain_task: asyncio.Task | None = None
    # Lock so two `chat` messages can't race the task swap.
    swap_lock = asyncio.Lock()
    send_lock = asyncio.Lock()  # uvicorn complains if two coros write concurrently

    async def safe_send(msg: dict) -> None:
        async with send_lock:
            try:
                await ws.send_json(msg)
            except Exception:  # noqa: BLE001
                # connection dying — swallow; outer loop will tear down.
                pass

    await safe_send({
        "type": "info",
        "text": f"{cfg.A.name} online — {cfg.model.provider}/{cfg.model.model}",
    })

    async def cancel_running(reason: str = "superseded") -> None:
        nonlocal brain_task
        # Resolve any dangling confirmations as deny so the brain stops awaiting.
        for fut in list(pending.values()):
            if not fut.done():
                fut.set_result(False)
        pending.clear()
        if brain_task and not brain_task.done():
            brain_task.cancel()
            try:
                await brain_task
            except (asyncio.CancelledError, Exception):
                # Cancelled is expected; other exceptions logged but never
                # re-raised — we are tearing down by design.
                pass
            await safe_send({"type": "info", "text": f"task cancelled ({reason})"})
        brain_task = None

    async def run_brain(text: str, attachments: list | None = None) -> None:
        try:
            async for ev in orchestrator.handle_user_message(text, attachments=attachments):
                await _emit_event(safe_send, ev, pending)
        except asyncio.CancelledError:
            # Best-effort notify — connection may already be dead. Do NOT
            # re-raise: callers (`await brain_task`) won't expect a
            # CancelledError to escape from a routine teardown.
            await safe_send({"type": "info", "text": "task cancelled"})
            await safe_send({"type": "done"})
        except Exception as e:  # noqa: BLE001
            log.exception("brain error")
            await safe_send({"type": "error", "text": str(e)})
            await safe_send({"type": "done"})

    try:
        while True:
            # State guard — if the client closed during `accept()` or between
            # frames, `receive_json` raises a generic RuntimeError that pollutes
            # the logs. Check first; break cleanly if disconnected.
            if ws.application_state != WebSocketState.CONNECTED:
                log.info("ws no longer connected (state=%s) — closing loop", ws.application_state)
                break
            try:
                msg = await ws.receive_json()
            except WebSocketDisconnect:
                raise
            except RuntimeError as e:
                # Starlette raises this when the socket closed before receive.
                if "WebSocket is not connected" in str(e) or "disconnect" in str(e).lower():
                    log.info("ws closed mid-receive: %s", e)
                    break
                raise
            mtype = msg.get("type")

            if mtype == "ping":
                await safe_send({"type": "pong"})

            elif mtype == "confirm":
                rid = msg.get("id")
                fut = pending.pop(rid, None)
                if fut and not fut.done():
                    fut.set_result(bool(msg.get("approved")))

            elif mtype == "agent":
                name = msg.get("name", "")
                agent = agents.get(name)
                if agent:
                    orchestrator.set_agent(agent)
                    await safe_send({"type": "info", "text": f"agent active: {name}"})
                else:
                    await safe_send({"type": "error", "text": f"no such agent: {name}"})

            elif mtype == "cancel":
                await cancel_running("user request")

            elif mtype == "command":
                line = (msg.get("command") or "").strip()
                await _handle_command(safe_send, line, orchestrator, memory, agents, cfg, cancel_running)

            elif mtype == "chat":
                text = (msg.get("text") or "").strip()
                attachments = msg.get("attachments") or None
                if not text and not attachments:
                    continue
                if text.startswith("/"):
                    await _handle_command(safe_send, text, orchestrator, memory, agents, cfg, cancel_running)
                    continue

                async with swap_lock:
                    if brain_task and not brain_task.done():
                        busy = getattr(orchestrator, "busy_tool", None)
                        if busy in UNINTERRUPTIBLE_TOOLS:
                            # Heavy work in progress (image / 3D gen). Tossing it
                            # mid-load wastes ~30s of GPU + disk I/O, so refuse
                            # the new chat instead of cancelling.
                            await safe_send({
                                "type": "info",
                                "text": f"{busy} in progress — finish then I'll take the next one, sir.",
                            })
                            continue
                        await cancel_running("new request")
                    await safe_send({"type": "user", "text": text, "attachments": attachments})
                    brain_task = asyncio.create_task(run_brain(text, attachments))

            else:
                await safe_send({"type": "error", "text": f"unknown msg type: {mtype}"})

    except WebSocketDisconnect:
        log.info("ws client disconnected")
    except asyncio.CancelledError:
        # Receive-loop itself got cancelled (server shutdown). Just unwind.
        log.info("ws task cancelled")
    except Exception as e:  # noqa: BLE001
        log.exception("ws error")
        try:
            await safe_send({"type": "error", "text": str(e)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        # Always tear down the running task on disconnect.
        if brain_task and not brain_task.done():
            brain_task.cancel()
            try:
                await brain_task
            except (asyncio.CancelledError, Exception):
                # CancelledError is BaseException, not Exception — must list
                # it explicitly. Swallow either; connection is going away.
                pass


async def _handle_command(send, line: str, orchestrator, memory, agents, cfg, cancel_running) -> None:
    parts = line[1:].split(None, 1) if line.startswith("/") else line.split(None, 1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "help":
        await send({"type": "assistant", "text": HELP_TEXT})
    elif cmd == "reset":
        orchestrator.reset()
        await send({"type": "info", "text": "conversation history reset"})
    elif cmd == "cancel":
        await cancel_running("user /cancel")
    elif cmd == "cleanslate":
        orchestrator.reset()
        await send({
            "type": "assistant",
            "text": "Clean Slate Protocol executed, sir. Conversation history purged.",
        })
    elif cmd == "agents":
        rows = "\n".join(f"- **{a.name}** — {a.description}" for a in agents.list())
        await send({"type": "assistant", "text": "**Agents**\n" + rows})
    elif cmd == "agent":
        if arg.lower() in {"", "jarvis", "default", "base"}:
            orchestrator.set_agent(None)
            await send({"type": "info", "text": "agent active: jarvis"})
            return
        agent = agents.get(arg)
        if agent:
            orchestrator.set_agent(agent)
            await send({"type": "info", "text": f"agent active: {arg}"})
        else:
            await send({"type": "error", "text": f"no such agent: {arg}"})
    elif cmd == "tools":
        rows = "\n".join(f"- `{t.name}` ({t.permission.value}) — {t.description}" for t in orchestrator.registry.all_tools())
        await send({"type": "assistant", "text": "**Tools**\n" + rows})
    elif cmd in {"image-model", "imagemodel", "imgmodel"}:
        from ..plugins.media_generation import list_image_models, select_image_model
        if not arg:
            state = list_image_models(cfg)
            rows = "\n".join(
                f"- `{m['key']}`{' (selected)' if m['key'] == state['selected'] else ''}: "
                f"{m['label']} - {'downloaded' if m['downloaded'] else 'not downloaded'}"
                for m in state["models"]
            )
            await send({"type": "assistant", "text": "**Image models**\n" + rows})
        else:
            try:
                result = select_image_model(cfg, arg)
                await send({"type": "info", "text": f"image model selected: {result['selected']}"})
            except Exception as e:  # noqa: BLE001
                await send({"type": "error", "text": f"image model selection failed: {e}"})
    elif cmd == "protocols":
        text = (
            "**JARVIS protocols**\n"
            "- Persona: concise British systems assistant; calm, dry, protective.\n"
            f"- Model: `{cfg.model.provider}/{cfg.model.model}`.\n"
            f"- Tools: `{len(orchestrator.registry.all_tools())}` active under `{cfg.permissions.mode}` permissions.\n"
            "- Voice: prefers British male voices, especially Ryan/George/Daniel-class voices.\n"
            "- Safety: asks before destructive operations and refuses reckless commands."
        )
        await send({"type": "assistant", "text": text})
    elif cmd == "memory":
        hits = memory.search(arg, limit=20) if arg else []
        if hits:
            rows = "\n".join(f"- [{h['kind']}] **{h['title']}**: {h['body']}" for h in hits)
            await send({"type": "assistant", "text": "**memory matches**\n" + rows})
        else:
            await send({"type": "info", "text": "no memory matches" if arg else "usage: /memory <query>"})
    elif cmd == "mission":
        from pathlib import Path as _P
        if not arg:
            await send({"type": "info", "text": f"mission: {cfg.mission.project_path or '(none)'}"})
        else:
            p = _P(arg).expanduser().resolve()
            if p.exists():
                cfg.mission.enabled = True
                cfg.mission.project_path = str(p)
                memory.set_path("mission", str(p), "project")
                await send({"type": "info", "text": f"mission locked: {p}"})
            else:
                await send({"type": "error", "text": f"path not found: {p}"})
    else:
        await send({"type": "error", "text": f"unknown command: /{cmd} — try /help"})


async def _emit_event(send, ev: Event, pending: dict[str, asyncio.Future]) -> None:
    # Wrap the underlying send so every outbound message produced by this
    # event automatically picks up the swarm tags (subagent grouping). We
    # MUST capture the original `send` in a different name before shadowing
    # — otherwise tagged_send's closure captures itself and recurses
    # infinitely the first time it's called.
    swarm_id = ev.swarm_id
    swarm_label = ev.swarm_label
    raw_send = send

    async def tagged_send(msg: dict) -> None:
        if swarm_id:
            msg.setdefault("swarm_id", swarm_id)
            if swarm_label:
                msg.setdefault("swarm_label", swarm_label)
        await raw_send(msg)

    send = tagged_send  # shadow within this function only

    if ev.kind is EventKind.ASSISTANT:
        await send({"type": "assistant", "text": ev.text})
    elif ev.kind is EventKind.STREAM_BEGIN:
        await send({"type": "stream_begin"})
    elif ev.kind is EventKind.STREAM_DELTA:
        await send({"type": "stream_delta", "text": ev.text})
    elif ev.kind is EventKind.STREAM_END:
        await send({"type": "stream_end"})
    elif ev.kind is EventKind.THINKING:
        await send({"type": "thinking"})
    elif ev.kind is EventKind.TOOL_PROPOSED:
        await send({
            "type": "tool_proposed",
            "tool": ev.payload.get("tool"),
            "permission": ev.payload.get("permission"),
            "args": ev.payload.get("args", {}),
            "preview": ev.text,
        })
    elif ev.kind is EventKind.TOOL_RESULT:
        await send({
            "type": "tool_result",
            "tool": ev.payload.get("tool"),
            "ok": bool(ev.payload.get("ok")),
            "duration_s": ev.payload.get("duration_s"),
            "text": ev.text,
        })
    elif ev.kind is EventKind.TASK_START:
        await send({"type": "task_start", "text": ev.text})
    elif ev.kind is EventKind.TASK_PROGRESS:
        await send({"type": "task_progress", "text": ev.text, "tool": ev.payload.get("tool")})
    elif ev.kind is EventKind.TASK_END:
        await send({"type": "task_end", "text": ev.text, "ok": bool(ev.payload.get("ok", True))})
    elif ev.kind is EventKind.CONFIRMATION:
        if ev.confirm_req and ev.confirm_future:
            rid = uuid.uuid4().hex[:8]
            pending[rid] = ev.confirm_future
            await send({
                "type": "confirm_request",
                "id": rid,
                "tool": ev.confirm_req.tool,
                "permission": ev.confirm_req.permission.value,
                "preview": ev.confirm_req.preview,
                "args": ev.confirm_req.args,
            })
            # Belt-and-braces timeout so a forgotten dialog never hangs the
            # orchestrator forever. Auto-deny after CONFIRM_TIMEOUT_S.
            async def _timeout(fut: asyncio.Future, rid: str) -> None:
                try:
                    await asyncio.sleep(CONFIRM_TIMEOUT_S)
                    if not fut.done():
                        fut.set_result(False)
                        pending.pop(rid, None)
                        await send({"type": "info", "text": "confirmation timeout — auto-denied"})
                except asyncio.CancelledError:
                    pass
            asyncio.create_task(_timeout(ev.confirm_future, rid))
    elif ev.kind is EventKind.MEDIA:
        msg = {"type": "media"}
        msg.update(ev.payload or {})
        if ev.text and "summary" not in msg:
            msg["summary"] = ev.text
        await send(msg)
    elif ev.kind is EventKind.PLAN:
        await send({"type": "plan", "text": ev.text, "steps": ev.payload.get("steps", [])})
    elif ev.kind is EventKind.SUGGESTIONS:
        await send({"type": "suggestions", "items": ev.payload.get("items", [])})
    elif ev.kind is EventKind.ERROR:
        await send({"type": "error", "text": ev.text})
    elif ev.kind is EventKind.INFO:
        await send({"type": "info", "text": ev.text})
    elif ev.kind is EventKind.DONE:
        await send({"type": "done"})
