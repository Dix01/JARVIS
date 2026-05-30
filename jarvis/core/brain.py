"""LLM brain.

Supports two providers, both via httpx:
  - "anthropic"           : POST <endpoint>/v1/messages
  - "openai_compatible"   : POST <endpoint>/chat/completions   (LM Studio, Ollama, vLLM, OpenAI)

Two tool-calling strategies:
  - native_tool_calls=True  : use the provider's tool / function-calling API
  - native_tool_calls=False : ReAct-style XML tags in plain text (works with any model)

The orchestrator does NOT see the difference — both paths return a list of
`ToolCall` objects (possibly empty) plus a final text reply.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

import httpx

from ..config import Config

log = logging.getLogger("jarvis.brain")


TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
XML_TOOL_RE = re.compile(
    r"<(?P<name>[a-zA-Z_][\w-]*)>\s*(?P<body>.*?)\s*</(?P=name)>",
    re.DOTALL,
)
THOUGHT_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    raw: str = ""              # original text (for logging)
    call_id: str | None = None # provider id when native


@dataclass
class BrainReply:
    text: str                       # cleaned final text (no tool tags)
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: str = ""                   # untouched assistant message
    finish_reason: str | None = None


REACT_INSTRUCTIONS = """\
You have access to tools. To call a tool, output a single block:

<tool_call>
{"name": "<tool_name>", "args": {<json-args>}}
</tool_call>

Never invent tags like <web_search> or <shell_command>. The only valid tool
syntax is the JSON <tool_call> block above.

After you receive the tool result (as a user message), you may call another
tool or write a final reply to the user. Do NOT wrap your final reply in
<tool_call>. Only emit one tool_call per turn. Think briefly inside
<thinking>...</thinking> if you need to plan; that block will be hidden
from the user. Keep replies short and concrete.
"""


class LLMBrain:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.mc = cfg.model
        self._client = httpx.AsyncClient(timeout=self.mc.request_timeout_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    def build_system_prompt(self, persona: str, tools_doc: str) -> str:
        parts = [persona.strip()]
        if not self.mc.native_tool_calls:
            parts.append(REACT_INSTRUCTIONS)
        if tools_doc:
            parts.append("Available tools:\n" + tools_doc)
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    async def chat(
        self,
        messages: list[dict[str, str]],
        tool_schemas: list[dict] | None = None,
    ) -> BrainReply:
        provider = self.mc.provider
        if provider == "anthropic":
            return await self._chat_anthropic(messages, tool_schemas or [])
        return await self._chat_openai_compatible(messages, tool_schemas or [])

    async def chat_stream(
        self,
        messages: list[dict],
        tool_schemas: list[dict] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> BrainReply:
        """Streaming chat — invokes `on_delta(text_chunk)` for each token.

        Tool-call arguments are accumulated transparently. Returns the same
        `BrainReply` shape as `chat()` once the stream finishes.

        Falls back to non-stream on Anthropic provider or when the server
        returns a non-stream response.
        """
        if self.mc.provider == "anthropic":
            # Anthropic streaming wired separately; non-stream path still works.
            return await self._chat_anthropic(messages, tool_schemas or [])
        return await self._chat_openai_compatible_stream(messages, tool_schemas or [], on_delta)

    # ------------------------------------------------------------------
    async def _chat_openai_compatible(
        self,
        messages: list[dict[str, str]],
        tool_schemas: list[dict],
    ) -> BrainReply:
        url = self.mc.endpoint.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.mc.api_key:
            headers["Authorization"] = f"Bearer {self.mc.api_key}"
        # OpenRouter requires these headers for proper routing.
        if "openrouter.ai" in self.mc.endpoint:
            headers["HTTP-Referer"] = "http://localhost:7341"
            headers["X-Title"] = "JARVIS_LOCAL"

        norm_msgs = _normalise_messages(messages)

        payload: dict[str, Any] = {
            "model": self.mc.model,
            "messages": norm_msgs,
            "temperature": self.mc.temperature,
            "max_tokens": self.mc.max_tokens,
            "stream": False,
            "frequency_penalty": self.mc.frequency_penalty,
            "presence_penalty":  self.mc.presence_penalty,
        }
        if self.mc.reasoning_effort not in (None, "none", ""):
            payload["reasoning_effort"] = self.mc.reasoning_effort
        if self.mc.native_tool_calls and tool_schemas:
            payload["tools"] = [
                {"type": "function", "function": s} for s in tool_schemas
            ]

        try:
            resp = await self._client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500] if e.response else ""
            log.error("LLM HTTP %s: %s — %s", e.response.status_code, e, body)
            return BrainReply(text=f"[brain error] HTTP {e.response.status_code}: {body}", raw=str(e))
        except httpx.HTTPError as e:
            log.error("LLM HTTP error: %s", e)
            return BrainReply(text=f"[brain error] {e}", raw=str(e))

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        raw_text: str = msg.get("content") or ""
        finish = choice.get("finish_reason")

        tool_calls: list[ToolCall] = []

        # native tool calls (OpenAI style)
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(
                    name=fn.get("name", ""),
                    args=args,
                    raw=json.dumps(fn),
                    call_id=tc.get("id"),
                )
            )

        # ReAct fallback parse
        if not tool_calls:
            tool_calls = _parse_react_tool_calls(raw_text)

        clean_text = _strip_artifacts(raw_text)
        return BrainReply(text=clean_text, tool_calls=tool_calls, raw=raw_text, finish_reason=finish)

    # ------------------------------------------------------------------
    async def _chat_openai_compatible_stream(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict],
        on_delta: Callable[[str], None] | None = None,
    ) -> BrainReply:
        url = self.mc.endpoint.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.mc.api_key:
            headers["Authorization"] = f"Bearer {self.mc.api_key}"
        if "openrouter.ai" in self.mc.endpoint:
            headers["HTTP-Referer"] = "http://localhost:7341"
            headers["X-Title"] = "JARVIS_LOCAL"

        norm_msgs = _normalise_messages(messages)
        payload: dict[str, Any] = {
            "model": self.mc.model,
            "messages": norm_msgs,
            "temperature": self.mc.temperature,
            "max_tokens": self.mc.max_tokens,
            "stream": True,
            "frequency_penalty": self.mc.frequency_penalty,
            "presence_penalty":  self.mc.presence_penalty,
        }
        if self.mc.reasoning_effort not in (None, "none", ""):
            payload["reasoning_effort"] = self.mc.reasoning_effort
        if self.mc.native_tool_calls and tool_schemas:
            payload["tools"] = [{"type": "function", "function": s} for s in tool_schemas]

        text_parts: list[str] = []
        # Accumulate streaming tool_calls keyed by index.
        tc_acc: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        loop_truncated = False

        try:
            async with self._client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")[:500]
                    log.error("LLM stream HTTP %s: %s", resp.status_code, body)
                    return BrainReply(text=f"[brain error] HTTP {resp.status_code}: {body}", raw=body)
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta", {}) or {}
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    # Text delta
                    piece = delta.get("content")
                    if piece:
                        text_parts.append(piece)
                        if on_delta:
                            try:
                                on_delta(piece)
                            except Exception:  # noqa: BLE001
                                pass
                        # Loop watchdog: abort if we detect ≥3-fold back-to-back
                        # repetition in the last 240 chars.
                        cut = _detect_repetition_loop("".join(text_parts))
                        if cut is not None:
                            loop_truncated = True
                            full = "".join(text_parts)
                            text_parts = [full[:cut]]
                            finish_reason = finish_reason or "repetition_loop"
                            log.warning("stream aborted: repetition loop at offset %d", cut)
                            break
                    # Tool call deltas
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = tc_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["args"] += fn["arguments"]
        except httpx.HTTPError as e:
            log.error("LLM stream HTTP error: %s", e)
            return BrainReply(text=f"[brain error] {e}", raw=str(e))

        if loop_truncated and on_delta:
            # Tell the consumer we cut. Optional — the UI already has the text.
            try:
                on_delta("")  # marker no-op
            except Exception:
                pass

        raw_text = "".join(text_parts)
        tool_calls: list[ToolCall] = []
        for idx in sorted(tc_acc.keys()):
            slot = tc_acc[idx]
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(
                name=slot["name"],
                args=args,
                raw=json.dumps(slot),
                call_id=slot["id"] or None,
            ))

        # ReAct fallback if no native tool calls came through
        if not tool_calls:
            tool_calls = _parse_react_tool_calls(raw_text)

        return BrainReply(
            text=_strip_artifacts(raw_text),
            tool_calls=tool_calls,
            raw=raw_text,
            finish_reason=finish_reason,
        )

    # ------------------------------------------------------------------
    async def _chat_anthropic(
        self,
        messages: list[dict[str, str]],
        tool_schemas: list[dict],
    ) -> BrainReply:
        url = self.mc.endpoint.rstrip("/") + "/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.mc.api_key:
            headers["x-api-key"] = self.mc.api_key

        # Anthropic separates system message from messages
        system_text = ""
        conv: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "system":
                system_text += ("\n" if system_text else "") + m["content"]
            else:
                conv.append({"role": m["role"], "content": m["content"]})

        payload: dict[str, Any] = {
            "model": self.mc.model,
            "system": system_text,
            "messages": conv,
            "max_tokens": self.mc.max_tokens,
            "temperature": self.mc.temperature,
        }
        if self.mc.native_tool_calls and tool_schemas:
            payload["tools"] = [
                {
                    "name": s["name"],
                    "description": s.get("description", ""),
                    "input_schema": s.get("parameters", {"type": "object"}),
                }
                for s in tool_schemas
            ]

        try:
            resp = await self._client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            log.error("Anthropic HTTP error: %s", e)
            return BrainReply(text=f"[brain error] {e}", raw=str(e))

        data = resp.json()
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            t = block.get("type")
            if t == "text":
                text_parts.append(block.get("text", ""))
            elif t == "tool_use":
                tool_calls.append(
                    ToolCall(
                        name=block.get("name", ""),
                        args=block.get("input", {}) or {},
                        raw=json.dumps(block),
                        call_id=block.get("id"),
                    )
                )

        raw_text = "".join(text_parts)
        if not tool_calls:
            tool_calls = _parse_react_tool_calls(raw_text)

        return BrainReply(
            text=_strip_artifacts(raw_text),
            tool_calls=tool_calls,
            raw=raw_text,
            finish_reason=data.get("stop_reason"),
        )


def _detect_repetition_loop(text: str) -> int | None:
    """Return the cut index (keep text[:cut]) if back-to-back repetition is
    detected in the last 240 chars, else None.

    Examples that trigger:
      "it appears you are holding, it appears you are holding, it appears you are holding"
      "abc abc abc abc"
    """
    # Frequency-count detector. Strict back-to-back matching misses real
    # loops because the last repetition is often truncated mid-phrase
    # ("X, X, X, X" — last X has no trailing punctuation). Instead, count
    # how many times each candidate substring from early-in-the-tail
    # appears anywhere in the tail. ≥4 → loop.
    n = len(text)
    if n < 60:
        return None
    tail = text[-400:]
    base = n - len(tail)
    # Try medium-length probes first; tighter probes catch shorter loops.
    for size in (40, 30, 24, 20, 17, 14):
        if size * 4 > len(tail):
            continue
        # Sample candidate segs from the first ~120 chars of the tail in
        # 5-char steps. Anything that repeats 4+ times anywhere in tail
        # is a clear degenerate loop.
        for start in range(0, min(120, len(tail) - size * 3), 5):
            seg = tail[start:start + size]
            if not seg.strip():
                continue
            tokens = seg.split()
            if len(tokens) < 2 or sum(len(t) for t in tokens) < 8:
                continue
            if tail.count(seg) >= 4:
                # Keep first instance — cut right after it ends.
                first = tail.find(seg)
                return base + first + size


def _normalise_messages(messages: list[dict]) -> list[dict[str, Any]]:
    """Pass through `tool_calls`, `tool_call_id`, `name`, and multimodal
    `content` arrays (text + image_url parts) so multi-hop and vision both
    work with strict OpenAI-compatible servers (Ollama, vLLM, OpenAI)."""
    out: list[dict[str, Any]] = []
    for m in messages:
        entry: dict[str, Any] = {"role": m.get("role", "user")}
        if "content" in m:
            entry["content"] = m["content"]
        # If caller attached images, lift into OpenAI multimodal format.
        attach = m.get("attachments") or []
        if attach:
            parts: list[dict[str, Any]] = []
            if isinstance(entry.get("content"), str) and entry["content"]:
                parts.append({"type": "text", "text": entry["content"]})
            for a in attach:
                if not isinstance(a, dict):
                    continue
                if a.get("type") == "image" and a.get("data_url"):
                    parts.append({"type": "image_url", "image_url": {"url": a["data_url"]}})
            if parts:
                entry["content"] = parts
        for k in ("tool_calls", "tool_call_id", "name"):
            if k in m:
                entry[k] = m[k]
        out.append(entry)
    return out


def _parse_react_tool_calls(text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for m in TOOL_CALL_RE.finditer(text or ""):
        payload = m.group(1).strip()
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        name = obj.get("name") or obj.get("tool")
        args = obj.get("args") or obj.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        if name:
            calls.append(ToolCall(name=name, args=args, raw=m.group(0)))
    if calls:
        return calls

    for m in XML_TOOL_RE.finditer(text or ""):
        name = m.group("name").strip()
        if name.lower() in {"thinking", "tool_call"}:
            continue
        body = m.group("body").strip()
        args: dict[str, Any]
        try:
            parsed = json.loads(body)
            args = parsed if isinstance(parsed, dict) else {"_raw": parsed}
        except json.JSONDecodeError:
            args = _args_from_legacy_tool_tag(name, body)
        calls.append(ToolCall(name=name, args=args, raw=m.group(0)))
    return calls


def _args_from_legacy_tool_tag(name: str, body: str) -> dict[str, Any]:
    if name == "web_search":
        return {"query": body, "max_results": 5}
    if name == "web_fetch":
        return {"url": body}
    if name in {"read_file", "list_dir", "scan_project"}:
        return {"path": body}
    if name in {"shell", "run_shell", "shell_command"}:
        return {"command": body}
    return {"_raw": body}


def _strip_artifacts(text: str) -> str:
    if not text:
        return ""
    text = TOOL_CALL_RE.sub("", text)
    text = XML_TOOL_RE.sub(
        lambda m: "" if m.group("name").lower() != "thinking" else m.group(0),
        text,
    )
    text = THOUGHT_RE.sub("", text)
    return text.strip()
