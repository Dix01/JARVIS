"""Web search + fetch — JARVIS OS edition.

Tools return *structured JSON strings* prefixed with `__JARVIS_MEDIA__` so the
orchestrator's emit-hook can lift them into a `media` event for the Media Bay.

Providers:
  duckduckgo  — no key needed (default)
  brave       — BRAVE_API_KEY
  tavily      — TAVILY_API_KEY
  serpapi     — SERPAPI_API_KEY
"""
from __future__ import annotations

import html
import json
import os
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import httpx

from ..core.permissions import Permission
from .base import PluginInfo, tool

MEDIA_PREFIX = "__JARVIS_MEDIA__"


def _media(kind: str, items: list[dict], summary: str = "") -> str:
    """Encode a media payload that the orchestrator emit-hook will pluck out."""
    payload = {"kind": kind, "items": items, "summary": summary}
    return MEDIA_PREFIX + json.dumps(payload, ensure_ascii=False)


def register(registry):
    cfg = registry.cfg
    toggle = cfg.plugins.get("web_tools")
    provider = (toggle.provider if toggle else None) or "duckduckgo"

    @tool(
        name="web_search",
        description=(
            "Search the web for fresh facts, news, docs, or any text-based query. "
            "Results are rendered as clickable cards in the Media Bay AUTOMATICALLY. "
            "Always call this before answering questions about current events, "
            "products, people, prices, releases, or anything time-sensitive."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 6},
            },
            "required": ["query"],
        },
        preview=lambda a: f"web search: {a.get('query','')}",
    )
    async def web_search(query: str, max_results: int = 6) -> str:
        # Route news-y queries into a dedicated news kind so the UI can
        # surface them in their own NEWS panel separate from generic web
        # results. Falls back to plain web search if Google News empty.
        is_news = _is_news_query(query)
        try:
            items: list[dict] = []
            if is_news:
                items = await _google_news(query, max_results)
            if not items:
                items = await _do_search(provider, query, max_results)
                is_news = False  # fell back to web — render as search
        except Exception as e:  # noqa: BLE001
            return f"web search failed ({provider}): {e}"
        if not items:
            return f"web search ({provider}): no results for '{query}'"
        # Plain text fallback (for the model's tool-loop)
        text_lines = [f"Found {len(items)} results for '{query}':"]
        for i, r in enumerate(items, 1):
            text_lines.append(f"{i}. {r.get('title','(no title)')} — {r.get('url','')}")
            if r.get("snippet"):
                text_lines.append(f"   {r['snippet']}")
        return _media("news" if is_news else "search", items, "\n".join(text_lines))

    @tool(
        name="image_search",
        description=(
            "Search the web for IMAGES. Results render as a thumbnail grid in the "
            "Media Bay; click to view full size. Use whenever the user asks for "
            "pictures, photos, logos, diagrams, screenshots, or anything visual."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 12},
            },
            "required": ["query"],
        },
        preview=lambda a: f"image search: {a.get('query','')}",
    )
    async def image_search(query: str, max_results: int = 12) -> str:
        try:
            items = await _ddg_images(query, max_results)
        except Exception as e:  # noqa: BLE001
            return f"image search failed: {e}"
        if not items:
            return f"image search: no results for '{query}'"
        return _media("images", items, f"{len(items)} images for '{query}'")

    @tool(
        name="video_search",
        description=(
            "Search YouTube for VIDEOS. Results render as embedded players in the "
            "Media Bay — playable inline without leaving JARVIS. Use for tutorials, "
            "trailers, music, lectures, or any 'show me a video of X' request."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 6},
            },
            "required": ["query"],
        },
        preview=lambda a: f"video search: {a.get('query','')}",
    )
    async def video_search(query: str, max_results: int = 6) -> str:
        try:
            items = await _yt_search(query, max_results)
        except Exception as e:  # noqa: BLE001
            return f"video search failed: {e}"
        if not items:
            return f"video search: no results for '{query}'"
        return _media("videos", items, f"{len(items)} videos for '{query}'")

    @tool(
        name="open_inline",
        description=(
            "Embed a web page directly inside the Media Bay iframe — never opens a "
            "real browser window. Pass an absolute URL. Use whenever the user says "
            "'open / show me / pull up <site>'."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "url":   {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["url"],
        },
        preview=lambda a: f"embed inline: {a.get('url','')}",
    )
    async def open_inline(url: str, title: str = "") -> str:
        u = url.strip()
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        item = {
            "url": u,
            "title": title or _host(u),
            "thumbnail": _favicon(u),
        }
        return _media("page", [item], f"Embedded: {item['title']}")

    @tool(
        name="media_show",
        description=(
            "Push an arbitrary media card (image / video / link / page) to the "
            "Media Bay. Useful for surfacing a single result without searching."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "kind":      {"type": "string", "enum": ["image", "video", "page", "search"]},
                "url":       {"type": "string"},
                "title":     {"type": "string"},
                "snippet":   {"type": "string"},
                "thumbnail": {"type": "string"},
            },
            "required": ["kind", "url"],
        },
        preview=lambda a: f"media_show: {a.get('kind','')} {a.get('url','')[:60]}",
    )
    async def media_show(kind: str, url: str, title: str = "", snippet: str = "", thumbnail: str = "") -> str:
        item = {"url": url, "title": title or _host(url), "snippet": snippet, "thumbnail": thumbnail or _favicon(url)}
        return _media(kind, [item], f"Surfaced: {item['title']}")

    @tool(
        name="webcam_show",
        description=(
            "★ PREFERRED for any 'see / look / view / show me / I want to show "
            "you' webcam intent. Opens the LIVE webcam feed inline in the Media "
            "Bay with HUD overlay. Phrases that trigger this tool: "
            "'look at what I'm holding', 'can you see me?', 'show me on camera', "
            "'open the webcam', 'turn on the camera', 'take a look', "
            "'I want you to see this', 'mirror me'. "
            "Do NOT call `webcam_snapshot` for these — that is a silent "
            "background capture, not a viewer."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "title":  {"type": "string"},
                "mirror": {"type": "boolean", "default": True},
            },
        },
        preview=lambda a: "webcam_show (live feed)",
    )
    async def webcam_show(title: str = "WEBCAM FEED", mirror: bool = True) -> str:
        item = {
            "url": "webcam://local",
            "title": title,
            "snippet": "Live feed from primary capture device.",
            "thumbnail": "",
        }
        # Pass an extra `mirror` flag through the item so the UI can read it.
        item["mirror"] = "1" if mirror else "0"  # type: ignore[assignment]
        return _media("webcam", [item], f"Webcam opened: {title}")

    @tool(
        name="web_fetch",
        description="Fetch a URL and return its readable text content (HTML stripped).",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "url":       {"type": "string"},
                "max_chars": {"type": "integer", "default": 8000},
            },
            "required": ["url"],
        },
        preview=lambda a: f"GET {a.get('url','')}",
    )
    async def web_fetch(url: str, max_chars: int = 8000) -> str:
        # Use a realistic browser UA + standard accept headers. Many sites
        # (Cloudflare, Akamai, etc.) 403 anything that smells like a bot.
        # Don't raise on 4xx/5xx — return a soft error string so multi-fetch
        # callers (deep research) continue with the next URL instead of
        # bombing the whole tool chain.
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as c:
                r = await c.get(url)
            if r.status_code >= 400:
                return f"[web_fetch: HTTP {r.status_code} for {url} — site blocked the fetch]"
            text = _html_to_text(r.text)
            return text[:max_chars] if text else f"[web_fetch: empty body for {url}]"
        except httpx.HTTPError as e:
            return f"[web_fetch: network error for {url}: {e}]"

    registry.add_pending("web_tools")
    registry.register_plugin(PluginInfo(
        name="web_tools",
        description=f"In-app web search, images, videos, page embedding (provider: {provider}).",
        permissions_needed=[Permission.SAFE],
    ))


# ============================== providers ===================================

async def _do_search(provider: str, query: str, n: int) -> list[dict]:
    if provider == "duckduckgo": return await _ddg_text(query, n)
    if provider == "brave":      return await _brave(query, n)
    if provider == "tavily":     return await _tavily(query, n)
    if provider == "serpapi":    return await _serpapi(query, n)
    return await _ddg_text(query, n)


def _is_news_query(query: str) -> bool:
    return bool(re.search(r"\b(?:news|headlines|breaking|latest|current|recent)\b", query or "", re.IGNORECASE))


async def _google_news(query: str, n: int) -> list[dict]:
    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"},
    ) as c:
        r = await c.get(
            "https://news.google.com/rss/search",
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        )
        r.raise_for_status()

    root = ET.fromstring(r.text)
    out: list[dict] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or _host(url)).strip()
        published = _format_pub_date(item.findtext("pubDate") or "")
        if not title or not url:
            continue
        snippet = f"{source}{f' · {published}' if published else ''}"
        out.append({
            "url": url,
            "title": title,
            "snippet": snippet,
            "thumbnail": _favicon(url),
            "source": source,
        })
        if len(out) >= n:
            break
    return out


def _format_pub_date(value: str) -> str:
    try:
        dt = parsedate_to_datetime(value)
        return f"{dt:%b} {dt.day}, {dt:%Y %H:%M}"
    except Exception:
        return ""


DDG_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
    r'(?:.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>)?',
    re.DOTALL,
)


def _strip(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return " ".join(html.unescape(s).split())


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


def _favicon(url: str) -> str:
    h = _host(url)
    if not h:
        return ""
    return f"https://www.google.com/s2/favicons?sz=64&domain={quote(h)}"


async def _ddg_text(query: str, n: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        r = await c.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
    out: list[dict] = []
    for m in DDG_RESULT_RE.finditer(r.text):
        url = m.group(1)
        if url.startswith("//duckduckgo.com/l/"):
            mu = re.search(r"uddg=([^&]+)", url)
            if mu:
                from urllib.parse import unquote
                url = unquote(mu.group(1))
        out.append({
            "url": url,
            "title": _strip(m.group(2)),
            "snippet": _strip(m.group(3) or ""),
            "thumbnail": _favicon(url),
            "source": _host(url),
        })
        if len(out) >= n:
            break
    return out


async def _ddg_images(query: str, n: int) -> list[dict]:
    """DuckDuckGo image search via the unofficial JSON endpoint."""
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as c:
        # First request hits a vqd token.
        r = await c.get("https://duckduckgo.com/", params={"q": query})
        m = re.search(r'vqd=([\d-]+)', r.text) or re.search(r'vqd="([^"]+)"', r.text)
        if not m:
            return []
        vqd = m.group(1)
        ir = await c.get(
            "https://duckduckgo.com/i.js",
            params={"l": "us-en", "o": "json", "q": query, "vqd": vqd, "p": "1"},
            headers={"Referer": "https://duckduckgo.com/"},
        )
        if ir.status_code != 200:
            return []
        try:
            data = ir.json()
        except Exception:
            return []
    items = []
    for r in (data.get("results") or [])[:n]:
        items.append({
            "url":       r.get("image"),
            "thumbnail": r.get("thumbnail") or r.get("image"),
            "title":     r.get("title", ""),
            "source":    r.get("source", ""),
            "host":      r.get("url", ""),
            "width":     r.get("width"),
            "height":    r.get("height"),
        })
    return items


async def _yt_search(query: str, n: int) -> list[dict]:
    """Scrape YouTube results page — no API key, no quota."""
    url = "https://www.youtube.com/results"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}) as c:
        r = await c.get(url, params={"search_query": query})
        r.raise_for_status()
    # Pull videoRenderer entries from ytInitialData
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    sections = (
        data.get("contents", {})
        .get("twoColumnSearchResultsRenderer", {})
        .get("primaryContents", {})
        .get("sectionListRenderer", {})
        .get("contents", [])
    )
    for s in sections:
        for item in s.get("itemSectionRenderer", {}).get("contents", []):
            vr = item.get("videoRenderer")
            if not vr:
                continue
            vid = vr.get("videoId")
            if not vid:
                continue
            title = "".join(t.get("text", "") for t in vr.get("title", {}).get("runs", []))
            chan  = "".join(t.get("text", "") for t in vr.get("ownerText", {}).get("runs", []))
            thumbs = vr.get("thumbnail", {}).get("thumbnails", [])
            duration = vr.get("lengthText", {}).get("simpleText", "")
            published = vr.get("publishedTimeText", {}).get("simpleText", "")
            views = vr.get("viewCountText", {}).get("simpleText", "")
            out.append({
                "url":         f"https://www.youtube.com/watch?v={vid}",
                "embed_url":   f"https://www.youtube.com/embed/{vid}",
                "video_id":    vid,
                "title":       title,
                "channel":     chan,
                "thumbnail":   thumbs[-1]["url"] if thumbs else "",
                "duration":    duration,
                "published":   published,
                "views":       views,
            })
            if len(out) >= n:
                return out
    return out


async def _brave(query: str, n: int) -> list[dict]:
    key = os.environ.get("BRAVE_API_KEY", "")
    if not key: raise RuntimeError("BRAVE_API_KEY missing")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": n},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        r.raise_for_status()
    data = r.json()
    return [
        {
            "title": x.get("title"), "url": x.get("url"),
            "snippet": x.get("description", ""),
            "thumbnail": (x.get("thumbnail") or {}).get("src") or _favicon(x.get("url", "")),
            "source": _host(x.get("url", "")),
        }
        for x in data.get("web", {}).get("results", [])[:n]
    ]


async def _tavily(query: str, n: int) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key: raise RuntimeError("TAVILY_API_KEY missing")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": n, "include_images": True},
        )
        r.raise_for_status()
    data = r.json()
    return [
        {
            "title": x.get("title"), "url": x.get("url"),
            "snippet": x.get("content", ""),
            "thumbnail": _favicon(x.get("url", "")),
            "source": _host(x.get("url", "")),
        }
        for x in data.get("results", [])[:n]
    ]


async def _serpapi(query: str, n: int) -> list[dict]:
    key = os.environ.get("SERPAPI_API_KEY", "")
    if not key: raise RuntimeError("SERPAPI_API_KEY missing")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://serpapi.com/search.json", params={"q": query, "api_key": key, "num": n})
        r.raise_for_status()
    data = r.json()
    return [
        {
            "title": x.get("title"), "url": x.get("link"),
            "snippet": x.get("snippet", ""),
            "thumbnail": _favicon(x.get("link", "")),
            "source": _host(x.get("link", "")),
        }
        for x in data.get("organic_results", [])[:n]
    ]


def _html_to_text(html_text: str) -> str:
    html_text = re.sub(r"<script\b[^>]*>.*?</script>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    html_text = re.sub(r"<style\b[^>]*>.*?</style>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    html_text = re.sub(r"<[^>]+>", " ", html_text)
    html_text = html.unescape(html_text)
    return re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", html_text)).strip()
