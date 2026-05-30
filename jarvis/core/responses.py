"""Deterministic JARVIS replies for core identity and status prompts."""
from __future__ import annotations

import re
import platform

from ..config import Config


_GREETING_RE = re.compile(
    r"^\s*(?:hey|hello|hi|sup|yo|good\s+(?:morning|afternoon|evening)|"
    r"hey\s+there|hi\s+there)[\s,!.?]*(?:jarvis)?[\s,!.?]*$",
    re.IGNORECASE,
)
_IDENTITY_RE = re.compile(
    r"\b(?:who are you|what are you|identify yourself|your name)\b",
    re.IGNORECASE,
)
_MODEL_RE = re.compile(
    r"\b(?:which|what)\s+model\b|\bmodel\s+are\s+you\b|\busing\s+model\b",
    re.IGNORECASE,
)
_CYBER_ABUSE_RE = re.compile(
    r"\b(?:hack|ddos|doxx|steal\s+password|break\s+into|malware|ransomware|"
    r"keylogger|phish|phishing|take\s+over\s+(?:an?\s+)?account)\b",
    re.IGNORECASE,
)
_OS_RE = re.compile(
    r"\b(?:which|what)\s+(?:operating\s+system|os)\b|\bwhat\s+am\s+i\s+running\b|\bmy\s+os\b",
    re.IGNORECASE,
)


def core_reply(user_text: str, cfg: Config) -> str | None:
    text = (user_text or "").strip()
    if not text:
        return None

    if _GREETING_RE.search(text) or (
        re.search(r"^\s*(?:hey|hello|hi|sup|yo)\b", text, re.IGNORECASE)
        and len(text) <= 48
    ):
        return "Online, sir. Systems are nominal. What shall we tackle?"

    if _IDENTITY_RE.search(text):
        return (
            "I am J.A.R.V.I.S., your local desktop intelligence system: "
            "voice, diagnostics, tools, memory, and mission support under one roof."
        )

    if _MODEL_RE.search(text):
        return (
            f"I am running `{cfg.model.model}` through the `{cfg.model.provider}` "
            f"adapter at `{cfg.model.endpoint}`, sir."
        )

    if _OS_RE.search(text):
        return (
            f"You are on {platform.system()} {platform.release()} "
            f"({platform.version()}), host `{platform.node()}`, sir."
        )

    if _CYBER_ABUSE_RE.search(text):
        return (
            "I cannot help attack, harass, or compromise someone, sir. "
            "I can help with defensive security, authorized testing, account recovery, "
            "or hardening your own systems."
        )

    return None
