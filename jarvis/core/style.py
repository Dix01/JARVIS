"""Reply-quality helpers for the JARVIS persona.

These are deliberately small guardrails around local models. They do not try to
rewrite good answers; they only catch empty, echoed, or visibly malformed text.
"""
from __future__ import annotations

import re
import string


_MALFORMED_PATTERNS = [
    re.compile(r"^\(?no reply from model\)?\.?$", re.IGNORECASE),
    re.compile(r"^thinking process:", re.IGNORECASE),
    re.compile(r"^all there is said\.?$", re.IGNORECASE),
    re.compile(r"^there is that\.?$", re.IGNORECASE),
]

_ODD_TAIL_RE = re.compile(
    r"(?:\n|\s)+(?:All there is said|There is that|"
    r"Else, let me know what needs doing|Can we get some work done)\.?\s*$",
    re.IGNORECASE,
)


def clean_assistant_text(text: str) -> str:
    """Remove known local-model artifacts while preserving the answer."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    cleaned = _ODD_TAIL_RE.sub("", cleaned)
    return cleaned.strip()


def is_malformed_reply(text: str, user_text: str = "") -> bool:
    """Return true when a reply should be retried before reaching the UI."""
    cleaned = clean_assistant_text(text)
    if not cleaned:
        return True
    if len(cleaned) < 3:
        return True
    if any(pattern.search(cleaned) for pattern in _MALFORMED_PATTERNS):
        return True
    if _normalise(cleaned) == _normalise(user_text):
        return True
    return False


def _normalise(text: str) -> str:
    lowered = (text or "").lower().strip()
    return lowered.translate(str.maketrans("", "", string.punctuation + string.whitespace))
