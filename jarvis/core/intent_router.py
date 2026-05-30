"""Deterministic intent router.

Sits between the user's raw utterance and the LLM. Catches high-confidence
intents (web search, image search, video search, open URL, create folder,
system status, run shell, …) and dispatches them as direct tool calls.

Why this exists
---------------
The LLM is excellent at reasoning over ambiguous prompts but unreliable at
*picking the right tool* between near-synonyms ("browser_open" vs
"web_search"). Real-world example: "populate the latest news on Elon Musk"
should always populate the Media Bay via `web_search`, never spawn a
visible browser via `browser_open`. The router enforces this contract
deterministically — the LLM is only invoked when no high-confidence
intent matches.

Architecture
------------
- `Intent` dataclass holds a name, pattern, builder, and final-reply
  prefix. Builders take the regex match and return a `ToolCall` plus the
  human-readable wrap-up the assistant will speak after the tool runs.
- Intents are ordered by precedence (most specific first). The first
  match wins.
- Each match is logged through `jarvis.intent` for diagnostics; the
  orchestrator can also surface this to the UI as an INFO event.

Adding a new intent
-------------------
1. Register an `Intent(...)` in INTENTS, ideally above any broader rule
   that might steal its trigger.
2. If the intent maps to a new tool, add it to the plugin registry first.
3. Add a fixture under `tests/intent_router_test.py` (todo: scaffold).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Pattern

from .brain import ToolCall

log = logging.getLogger("jarvis.intent")


@dataclass(frozen=True)
class IntentMatch:
    """Result of intent routing."""
    name: str                     # intent name (for logs / UI surfaces)
    tool_call: ToolCall           # tool + arguments to dispatch
    final_prefix: str             # what the assistant says after the tool returns
    raw_match: str = ""           # the substring that triggered the match


@dataclass(frozen=True)
class Intent:
    name: str
    pattern: Pattern[str]
    builder: Callable[[re.Match], IntentMatch | None]
    description: str = ""


# ────────────────────── helpers ──────────────────────

def _desktop_path() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def _clean_query(q: str) -> str:
    """Strip filler phrasing so the search engine sees a clean query."""
    q = (q or "").strip().strip(" .!?\"'")
    # Strip leading verbs and articles that aren't part of the query.
    q = re.sub(
        r"^(?:please|kindly|could\s+you|can\s+you|would\s+you|just|simply|then)\s+",
        "", q, flags=re.IGNORECASE,
    )
    q = re.sub(
        r"^(?:about|for|on|regarding|concerning|some|any|the)\s+",
        "", q, flags=re.IGNORECASE,
    )
    return q.strip()


def _looks_like_url(target: str) -> bool:
    t = (target or "").strip().lower()
    if not t:
        return False
    if t.startswith(("http://", "https://", "www.")):
        return True
    # Bare host like "anthropic.com" — only treat as URL if it has no spaces
    # AND has a dot AND has no question words.
    if "." in t and " " not in t and not re.search(r"\b(?:what|who|when|where|why|how|is|are|the)\b", t):
        return True
    # Well-known site shortcuts.
    return t in {"google", "youtube", "github", "stackoverflow", "duckduckgo", "twitter", "x", "reddit"}


# ────────────────────── pattern catalogue ──────────────────────
# Order matters: more specific patterns first.

# === Media / search intents (priority over browser_open) ===

# 1) Image search — must come BEFORE generic web search.
_IMAGE_SEARCH_RE = re.compile(
    r"\b(?:"
    r"show\s+(?:me\s+)?(?:some\s+|a\s+few\s+)?(?:pictures|photos|images|pics)\s+(?:of|for)|"
    r"find\s+(?:me\s+)?(?:some\s+|a\s+few\s+)?(?:pictures|photos|images|pics)\s+(?:of|for)|"
    r"search\s+(?:for\s+)?(?:pictures|photos|images|pics)\s+(?:of|for)|"
    r"pull\s+up\s+(?:pictures|photos|images|pics)\s+(?:of|for)|"
    r"(?:get|grab|fetch)\s+(?:me\s+)?(?:some\s+)?(?:pictures|photos|images|pics)\s+(?:of|for)|"
    r"(?:image|picture|photo)\s+search\s+(?:for|of)|"
    r"image\s+results?\s+(?:for|of)"
    r")\s+(?P<q>.+)",
    re.IGNORECASE,
)


def _build_image_search(m: re.Match) -> IntentMatch | None:
    q = _clean_query(m.group("q"))
    if not q:
        return None
    return IntentMatch(
        name="image_search",
        tool_call=ToolCall("image_search", {"query": q, "max_results": 12}),
        final_prefix=f"Image grid for “{q}”, sir.",
        raw_match=m.group(0),
    )


# 2) Video search.
_VIDEO_SEARCH_RE = re.compile(
    r"\b(?:"
    r"(?:show|find|play|get|grab|queue|pull\s+up|bring\s+up|look\s+up)\s+(?:me\s+)?(?:a\s+|some\s+)?(?:video|videos|clip|clips|footage)\s+(?:of|for|about|on)|"
    r"search\s+(?:youtube|yt)\s+(?:for\s+)?|"
    r"youtube\s+(?:search\s+)?(?:for|of)|"
    r"(?:video|youtube)\s+results?\s+(?:for|of)"
    r")\s+(?P<q>.+)",
    re.IGNORECASE,
)


def _build_video_search(m: re.Match) -> IntentMatch | None:
    q = _clean_query(m.group("q"))
    if not q:
        return None
    return IntentMatch(
        name="video_search",
        tool_call=ToolCall("video_search", {"query": q, "max_results": 8}),
        final_prefix=f"Video results for “{q}”, sir.",
        raw_match=m.group(0),
    )


# 3) Web search — broad. Includes "news/latest/headlines/populate/find/look up
#    /search/google/research". This is the CRITICAL rule that prevents the
#    regression where "populate latest news on X" opened a browser instead.
#
# Design rule: each alternative ends at a *keyword boundary*, not on
# whitespace. The outer `\s*(?P<q>.+)` absorbs any separator between the
# trigger and the query payload. This avoids the trap where a trailing
# `\s+` in an alternative + outer `\s+` together demanded TWO whitespaces.
# Each trigger must be followed by whitespace (lookahead `(?=\s)`) so that
# random text like "google.com" or "https://news.ycombinator.com" never
# fires the web-search intent — those belong to `open_browser`.
_WEB_SEARCH_RE = re.compile(
    r"\b(?:"
    # explicit search verbs
    r"search(?:\s+online|\s+the\s+web|\s+google)?(?:\s+for)?(?=\s)|"
    r"google(?:\s+for)?(?=\s)|"
    r"look\s+up(?:\s+online)?(?=\s)|"
    r"find(?:\s+me)?(?:\s+online)?(?:\s+(?:articles?|info|information|results?))?(?:\s+(?:on|about|for|regarding))?(?=\s)|"
    # "list available jobs in cairo" / "show me a list of restaurants" — lookahead
    # keeps the web-noun in the query and blocks filesystem-intent collisions.
    r"(?:list|show\s+me\s+a\s+list\s+of)\s+(?:[a-z]+\s+){0,3}?(?=(?:jobs?|vacancies|openings|listings?|restaurants?|hotels?|flights?|events?|places?|gyms?|cafes?|bars?|shops?|stores?|attractions?|activities|things\s+to\s+do)\b)|"
    # populate / pull up / show me + (latest)? news/results/etc + topic
    r"populate(?:\s+(?:the|my))?(?:\s+media\s+bay\s+with)?(?:\s+(?:latest|recent))?\s+(?:news|results|articles?|info|stories)(?:\s+(?:on|about|for|regarding))?(?=\s)|"
    r"pull\s+up(?:\s+(?:the|some))?(?:\s+(?:latest|recent))?\s+(?:news|results|articles?|info|stories)(?:\s+(?:on|about|for|regarding))?(?=\s)|"
    r"show\s+me(?:\s+(?:the|some))?(?:\s+(?:latest|recent))?\s+(?:news|results|articles?|info|stories|headlines)(?:\s+(?:on|about|for|regarding))?(?=\s)|"
    # "what's the latest on X" / "whats happening with X" / "what is happening with X"
    r"what(?:'s|s|\s+is)(?:\s+the)?\s+(?:latest|new|happening|going\s+on)(?:\s+(?:with|about|on|for|in))?(?=\s)|"
    # "research X" / "do research on X"
    r"(?:do\s+|some\s+)?research(?:\s+(?:on|about|for|regarding))?(?=\s)|"
    # bare "news/headlines about X" — last resort, requires trailing whitespace
    r"(?:(?:latest|recent|today's|todays)\s+)?(?:news|headlines)(?:\s+(?:on|about|for|regarding))?(?=\s)"
    r")\s*(?P<q>.+)",
    re.IGNORECASE,
)


def _build_web_search(m: re.Match) -> IntentMatch | None:
    q = _clean_query(m.group("q"))
    if not q:
        return None
    return IntentMatch(
        name="web_search",
        tool_call=ToolCall("web_search", {"query": q, "max_results": 8}),
        final_prefix=f"Search complete for “{q}”, sir.",
        raw_match=m.group(0),
    )


# 3b) Bare "latest news" — no topic. The topic'd web_search above requires a
# query after "news", so "pull up the latest news" / "show me the news" (clause
# end) fall through. End-anchored so a topic'd request ("...news on cairo")
# never matches here. Maps to a general headline search.
_NEWS_BARE_RE = re.compile(
    r"\b(?:"
    r"(?:populate|pull\s+up|show(?:\s+me)?|get|grab|give\s+me|bring\s+up|fetch|open)"
    r"(?:\s+(?:the|some|me))?(?:\s+(?:latest|recent|today'?s))?\s+(?:news|headlines)"
    r"|what(?:'s|s|\s+is)(?:\s+the)?\s+(?:latest\s+)?news"
    r"|(?:the\s+)?(?:latest|recent|today'?s)\s+(?:news|headlines)"
    r")\s*[.!?]*$",
    re.IGNORECASE,
)


def _build_news_bare(m: re.Match) -> IntentMatch | None:
    return IntentMatch(
        name="web_search",
        tool_call=ToolCall("web_search", {"query": "latest news today", "max_results": 8}),
        final_prefix="The latest headlines are in the Media Bay, sir.",
        raw_match=m.group(0),
    )


# 4) Embed a known URL inline (Media Bay iframe). Triggers on
#    "open inline / embed / pull up <URL>".
_OPEN_INLINE_RE = re.compile(
    r"\b(?:"
    r"(?:open|pull\s+up|embed|preview|show)\s+(?:inline|in\s+the\s+media\s+bay|in\s+media\s+bay|in\s+app)\s+(?P<u>\S+)|"
    r"embed\s+(?P<u2>\S+)"
    r")",
    re.IGNORECASE,
)


def _build_open_inline(m: re.Match) -> IntentMatch | None:
    u = (m.group("u") or m.group("u2") or "").strip()
    if not u:
        return None
    return IntentMatch(
        name="open_inline",
        tool_call=ToolCall("open_inline", {"url": u}),
        final_prefix=f"Embedded {u} in the Media Bay, sir.",
        raw_match=m.group(0),
    )


# 4a) Local image generation (must come BEFORE image_search so "generate a
#     picture of X" doesn't get routed to DuckDuckGo image search).
_IMAGE_GEN_RE = re.compile(
    r"\b(?:"
    r"(?:generate|create|make|draw|render|paint|design|produce|synthes(?:i[sz]e|e))\s+(?:me\s+)?"
    r"(?:an?\s+|some\s+)?(?:image|picture|photo|pic|artwork|illustration|render(?:ing)?|painting|drawing|logo|wallpaper|portrait)\s+"
    r"(?:of|showing|depicting|with|for|about)|"
    r"(?:ai[- ]?(?:image|art)\s+(?:of|for))|"
    r"text[- ]?to[- ]?image\s+(?:of|for)|"
    r"diffuse\s+(?:me\s+)?(?:an?\s+)?(?:image|picture)\s+of"
    r")(?=\s)(?P<q>.+)",
    re.IGNORECASE,
)


def _build_image_gen(m: re.Match) -> IntentMatch | None:
    q = _clean_query(m.group("q"))
    if not q:
        return None
    return IntentMatch(
        name="image_generate",
        tool_call=ToolCall("image_generate", {"prompt": q}),
        final_prefix=f"Image rendered for “{q}”, sir.",
        raw_match=m.group(0),
    )


# 4b) Text-to-3D generation.
_TEXT_TO_3D_RE = re.compile(
    r"\b(?:"
    r"(?:generate|create|make|render|build|produce)\s+(?:a\s+|me\s+(?:a\s+)?)?(?:3d\s+(?:model|asset|object|mesh)|hologram|three[- ]dimensional\s+model)\s+(?:of|for|from|showing)|"
    r"(?:turn|convert)\s+(?:that|this|it)?\s*into\s+(?:a\s+)?(?:3d|hologram)|"
    r"text[- ]?to[- ]?3d\s+(?:of|for)"
    r")(?=\s)(?P<q>.+)",
    re.IGNORECASE,
)


def _build_text_to_3d(m: re.Match) -> IntentMatch | None:
    q = _clean_query(m.group("q"))
    if not q:
        return None
    return IntentMatch(
        name="text_to_3d",
        tool_call=ToolCall("text_to_3d", {"prompt": q}),
        final_prefix=f"3D model generated for “{q}”, sir.",
        raw_match=m.group(0),
    )


# 5) Memory galaxy.
_MEMORY_GALAXY_RE = re.compile(
    r"\b(?:"
    r"show\s+(?:me\s+)?(?:my\s+)?memory\s+galaxy|"
    r"open\s+(?:the\s+)?(?:neural\s+)?(?:cloud|galaxy)|"
    r"visualise\s+(?:my\s+)?(?:memory|data|knowledge)|"
    r"what\s+do\s+you\s+remember\s+about\s+me"
    r")",
    re.IGNORECASE,
)


def _build_memory_galaxy(m: re.Match) -> IntentMatch | None:
    return IntentMatch(
        name="memory_galaxy",
        tool_call=ToolCall("memory_galaxy", {}),
        final_prefix="Neural cloud surfaced, sir.",
        raw_match=m.group(0),
    )


# 6) Webcam vision.
_WEBCAM_SEE_RE = re.compile(
    r"\b(?:"
    r"(?:can\s+you\s+|please\s+)?(?:see|look\s+at)\s+(?:me|what\s+i(?:'|\s+a)m\s+holding|this)|"
    r"what\s+(?:am\s+i\s+holding|do\s+you\s+see)|"
    r"take\s+a\s+look\s+at\s+(?:what\s+i(?:'|\s+a)m\s+holding|this)|"
    r"describe\s+what\s+you\s+see"
    r")",
    re.IGNORECASE,
)


def _build_webcam_see(m: re.Match) -> IntentMatch | None:
    return IntentMatch(
        name="webcam_see",
        tool_call=ToolCall("webcam_see", {}),
        final_prefix="Vision pass complete, sir.",
        raw_match=m.group(0),
    )


# === System / FS / shell intents ===

_CREATE_FOLDER_RE = re.compile(
    r"\b(?:create|make|new)\s+(?:a\s+)?(?:folder|directory)\b(?P<body>.*)",
    re.IGNORECASE,
)
_FOLDER_NAME_RE = re.compile(
    r"\b(?:called|named|name(?:d)?\s+it|folder\s+called|folder\s+named)\s+"
    r"(?P<name>[^.?!,;]+)",
    re.IGNORECASE,
)


def _build_create_folder(m: re.Match) -> IntentMatch | None:
    body = m.group("body") or ""
    text_all = m.string
    name_match = _FOLDER_NAME_RE.search(body)
    raw = (name_match.group("name") if name_match else body).strip().strip("\"'")
    raw = re.sub(r"^(?:on|in|at)\s+(?:my\s+)?desktop\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\b(?:on|in|at)\s+(?:my\s+)?desktop\b.*$", "", raw, flags=re.IGNORECASE)
    name = re.sub(r'[<>:"/\\|?*]', "_", raw).strip(" .")[:120].strip()
    if not name:
        return None
    base = _desktop_path() if re.search(r"\bdesktop\b", text_all, re.IGNORECASE) else Path.cwd()
    return IntentMatch(
        name="create_folder",
        tool_call=ToolCall("mkdir", {"path": str(base / name)}),
        final_prefix="Created the folder, sir.",
        raw_match=m.group(0),
    )


_LIST_DESKTOP_RE = re.compile(
    r"\b(?:list|show|what(?:'s|\s+is))\b.*\b(?:desktop|desktop\s+files)\b",
    re.IGNORECASE,
)


def _build_list_desktop(_m: re.Match) -> IntentMatch | None:
    return IntentMatch(
        name="list_desktop",
        tool_call=ToolCall("list_dir", {"path": str(_desktop_path()), "glob": "*", "recursive": False}),
        final_prefix="Desktop scan complete, sir.",
    )


_SYSTEM_STATUS_RE = re.compile(
    r"\b(?:system\s+status|pc\s+status|computer\s+status|diagnostics|how\s+is\s+(?:my\s+)?pc)\b",
    re.IGNORECASE,
)


def _build_system_status(_m: re.Match) -> IntentMatch | None:
    return IntentMatch(
        name="system_status",
        tool_call=ToolCall("system_status", {}),
        final_prefix="System status, sir.",
    )


_SCREENSHOT_BROWSER_RE = re.compile(
    r"\b(?:screenshot|screen\s+shot|capture)\b.*\b(?:browser|page|website)\b",
    re.IGNORECASE,
)


def _build_browser_screenshot(_m: re.Match) -> IntentMatch | None:
    return IntentMatch(
        name="browser_screenshot",
        tool_call=ToolCall("browser_screenshot", {"full_page": False}),
        final_prefix="Browser screenshot captured, sir.",
    )


_AGENT_BACKEND_RE = re.compile(
    r"^\s*(?P<prefix>"
    r"(?:use|ask|run|delegate(?:\s+to)?)\s+"
    r"(?:claude(?:\s+code)?|codex|opencode|open\s+code|agent\s+backend|backend)\s+"
    r"(?:to\s+)?"
    r"|"
    r"(?:run|work|keep\s+going)\s+until\s+"
    r"(?:you\s+)?(?:accomplish|finish|complete)\s+"
    r"(?:the\s+)?(?:goal|task)\s*:?\s*"
    r")(?P<goal>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _build_agent_backend(m: re.Match) -> IntentMatch | None:
    goal = m.group("goal").strip()
    if not goal:
        return None
    prefix = (m.group("prefix") or "").lower()
    if "claude" in prefix:
        backend = "claude"
    elif "codex" in prefix:
        backend = "codex"
    elif "opencode" in prefix or "open code" in prefix:
        backend = "opencode"
    else:
        backend = "auto"
    return IntentMatch(
        name="agent_backend",
        tool_call=ToolCall("agent_backend_run", {
            "goal": goal, "backend": backend, "cwd": str(Path.cwd()),
            "max_turns": 20, "timeout": 1800,
        }),
        final_prefix="Agent backend run complete, sir.",
    )


# === Browser navigation — LOW PRIORITY (last among URL/search). ===
# Critical: ONLY fires for explicit "open / go to / navigate to <something
# URL-shaped>". Never for "open inline" (handled above) or "open the latest
# news" (handled by web_search above).
_OPEN_BROWSER_RE = re.compile(
    r"^\s*(?:open|go\s+to|navigate\s+to|visit)\s+(?:my\s+|the\s+)?(?:browser\s+(?:to\s+)?)?(?P<target>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _build_open_browser(m: re.Match) -> IntentMatch | None:
    target = (m.group("target") or "").strip()
    if not _looks_like_url(target):
        return None
    return IntentMatch(
        name="open_browser",
        tool_call=ToolCall("browser_open", {"url": target}),
        final_prefix="Browser navigation complete, sir.",
    )


_RUN_PS_RE = re.compile(
    r"^\s*(?:run|execute)\s+(?:powershell|ps)\s*:?\s*(?P<command>.+)",
    re.IGNORECASE | re.DOTALL,
)


def _build_run_ps(m: re.Match) -> IntentMatch | None:
    return IntentMatch(
        name="run_powershell",
        tool_call=ToolCall("run_powershell", {"command": m.group("command").strip()}),
        final_prefix="PowerShell command complete, sir.",
    )


_RUN_CMD_RE = re.compile(
    r"^\s*(?:run|execute)\s+(?:command|cmd|shell)\s*:?\s*(?P<command>.+)",
    re.IGNORECASE | re.DOTALL,
)


def _build_run_cmd(m: re.Match) -> IntentMatch | None:
    return IntentMatch(
        name="run_shell",
        tool_call=ToolCall("run_shell", {"command": m.group("command").strip()}),
        final_prefix="Command complete, sir.",
    )


# ────────────────────── master ordering ──────────────────────
# First match wins. Media / search intents intentionally come BEFORE
# browser_open so "show me news about X" never opens a visible browser.

INTENTS: list[Intent] = [
    Intent("text_to_3d",         _TEXT_TO_3D_RE,         _build_text_to_3d,
           "Generate a 3D model from a text prompt."),
    Intent("image_generate",     _IMAGE_GEN_RE,          _build_image_gen,
           "Generate an image locally via FLUX.2-klein-4B."),
    Intent("image_search",       _IMAGE_SEARCH_RE,       _build_image_search,
           "Image grid for visual queries."),
    Intent("video_search",       _VIDEO_SEARCH_RE,       _build_video_search,
           "YouTube embed for video queries."),
    Intent("web_search_news",    _NEWS_BARE_RE,          _build_news_bare,
           "General latest-headlines search (no topic given)."),
    Intent("web_search",         _WEB_SEARCH_RE,         _build_web_search,
           "Web result cards in the Media Bay."),
    Intent("open_inline",        _OPEN_INLINE_RE,        _build_open_inline,
           "Embed a known URL inline."),
    Intent("memory_galaxy",      _MEMORY_GALAXY_RE,      _build_memory_galaxy,
           "Surface the neural memory cloud."),
    Intent("webcam_see",         _WEBCAM_SEE_RE,         _build_webcam_see,
           "One-shot webcam + vision analysis."),
    Intent("create_folder",      _CREATE_FOLDER_RE,      _build_create_folder,
           "Create a folder on the file system."),
    Intent("list_desktop",       _LIST_DESKTOP_RE,       _build_list_desktop,
           "List Desktop contents."),
    Intent("system_status",      _SYSTEM_STATUS_RE,      _build_system_status,
           "Live system telemetry."),
    Intent("browser_screenshot", _SCREENSHOT_BROWSER_RE, _build_browser_screenshot,
           "Screenshot of the controlled browser."),
    Intent("agent_backend",      _AGENT_BACKEND_RE,      _build_agent_backend,
           "Delegate goal to claude-code / codex / opencode."),
    Intent("open_browser",       _OPEN_BROWSER_RE,       _build_open_browser,
           "Last-resort browser navigation for explicit URL targets."),
    Intent("run_powershell",     _RUN_PS_RE,             _build_run_ps,
           "Run a PowerShell command."),
    Intent("run_shell",          _RUN_CMD_RE,            _build_run_cmd,
           "Run a generic shell command."),
]


def classify(user_text: str) -> IntentMatch | None:
    """Run the intent catalogue against `user_text`. First match wins.

    Returns the IntentMatch (or None). Always logs the result so the
    operator can diagnose tool routing.
    """
    text = (user_text or "").strip()
    if not text:
        return None
    for intent in INTENTS:
        m = intent.pattern.search(text)
        if not m:
            continue
        built = intent.builder(m)
        if built is None:
            log.debug("intent '%s' matched but builder rejected: %s", intent.name, text[:80])
            continue
        log.info(
            "intent='%s' tool='%s' args=%s match=%r",
            built.name, built.tool_call.name, built.tool_call.args, built.raw_match[:80],
        )
        return built
    log.debug("no intent matched: %s", text[:80])
    return None


# Strong segment boundaries for compound requests. Newlines, semicolons, and
# numbered/bulleted list markers always split.
_SEGMENT_SPLIT_RE = re.compile(
    r"(?:\r?\n)+|\s*;\s*|(?:^|\s)\d{1,2}[:.)]\s+|(?:^|\s)[-*•]\s+"
)
# Leftover leading list marker on a segment (e.g. "1:list" with no space after
# the colon survives the split above) — strip it so classify() sees clean text.
_LEAD_MARKER_RE = re.compile(r"^\s*(?:\d{1,2}\s*[:.)]|[-*•])\s*")

# Command verbs that mark the start of a fresh instruction.
_CMD_VERB = (
    r"(?:show|find|get|grab|give|generate|make|create|draw|render|search|"
    r"play|queue|open|populate|pull|bring|look|tell|fetch|download|display|"
    r"list|put|what'?s?|what\s+is)"
)
# Soft conjunction boundary — " and " / " then " / " and then " / "& " / ", and ".
# Split ONLY when the next clause starts with a command verb, so connective
# prose ("cats and dogs", "hotels and restaurants in cairo") is never split.
# The leading (\s+|\s*,\s*) requires a real separator so "command"/"lengthen"
# can't false-match the embedded "and"/"then".
_CONJ_SPLIT_RE = re.compile(
    rf"(?:\s+|\s*,\s*)(?:and\s+then|and|then|&)\s+(?={_CMD_VERB}\b)",
    re.IGNORECASE,
)


def _split_segments(text: str) -> list[str]:
    out: list[str] = []
    for part in _SEGMENT_SPLIT_RE.split(text):
        if not part:
            continue
        for sub in _CONJ_SPLIT_RE.split(part):
            if not sub:
                continue
            cleaned = _LEAD_MARKER_RE.sub("", sub).strip(" .\t\r\n")
            if len(cleaned) >= 3:
                out.append(cleaned)
    return out


def classify_multi(user_text: str) -> list[IntentMatch] | None:
    """Decompose a COMPOUND request into multiple deterministic intents.

    Splits on strong boundaries (newlines / numbered or bulleted markers /
    semicolons), classifies each segment independently, and returns the list
    of matches when 2+ segments resolve to an intent. Returns None for a
    single command so the caller falls back to single-intent classify().

    This is what lets "1: search jobs  2: make an image  3: find videos" fan
    out through the swarm instead of only the first matching intent firing.
    """
    text = (user_text or "").strip()
    if not text:
        return None
    segments = _split_segments(text)
    if len(segments) < 2:
        return None
    matches: list[IntentMatch] = []
    for seg in segments:
        m = classify(seg)
        if m is not None:
            matches.append(m)
    if len(matches) < 2:
        return None
    log.info(
        "multi-intent: %d segments → %d intents (%s)",
        len(segments), len(matches), ", ".join(m.name for m in matches),
    )
    return matches


def list_intents() -> list[dict]:
    """Useful for /api/intents and UI surface."""
    return [
        {"name": i.name, "pattern": i.pattern.pattern, "description": i.description}
        for i in INTENTS
    ]
