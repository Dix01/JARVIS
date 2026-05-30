"""Visible Playwright browser control tools."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from ..core.permissions import Permission
from .base import PluginInfo, tool


class BrowserController:
    def __init__(self, cfg):
        self.cfg = cfg
        self._pw = None
        self._browser = None
        self._page = None

    async def page(self):
        if self._page and not self._page.is_closed():
            return self._page
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError(
                "playwright is not installed. Run: venv\\Scripts\\python.exe -m pip install playwright && "
                "venv\\Scripts\\python.exe -m playwright install chromium"
            ) from e

        if self._pw is None:
            self._pw = await async_playwright().start()
        if self._browser is None or not self._browser.is_connected():
            self._browser = await self._pw.chromium.launch(headless=False)
        self._page = await self._browser.new_page(viewport={"width": 1280, "height": 800})
        return self._page

    async def close(self) -> str:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
            self._page = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None
        return "browser closed"


def register(registry):
    cfg = registry.cfg
    controller = BrowserController(cfg)

    @tool(
        name="browser_open",
        description=(
            "LAST-RESORT navigation — opens a visible external Chromium "
            "window. Only use when the user EXPLICITLY says 'open browser' "
            "or 'open in browser' AND provides a concrete URL. "
            "Do NOT use for general information retrieval, news, research, "
            "search, images, or videos — those MUST go through `web_search` "
            "/ `image_search` / `video_search` so results render inside the "
            "JARVIS Media Bay. For inline embedding (no popup), use "
            "`open_inline`."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        preview=lambda a: f"open external browser -> {a.get('url','')}",
    )
    async def browser_open(url: str) -> str:
        page = await controller.page()
        target = _normalise_url(url)
        await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
        return await _page_status(page)

    @tool(
        name="browser_search",
        description=(
            "Search the web via a VISIBLE external Chromium window. Use "
            "ONLY when the user explicitly requests the visible browser. "
            "For all standard search intents prefer `web_search` (cards "
            "render in the Media Bay)."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        preview=lambda a: f"browser search for: {a.get('query','')}",
    )
    async def browser_search(query: str, max_results: int = 5) -> str:
        page = await controller.page()
        await page.goto(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}", wait_until="domcontentloaded", timeout=30_000)
        try:
            await page.wait_for_selector(".result, .results_links", timeout=10_000)
        except Exception:
            pass
        results = await _extract_results(page, max_results)
        for result in results:
            result["url"] = _decode_ddg_url(result.get("url", ""))
        if results:
            return _format_results(results, max_results)
        return await _page_status(page)

    @tool(
        name="browser_current",
        description="Return the current visible browser page title and URL.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    async def browser_current() -> str:
        page = await controller.page()
        return await _page_status(page)

    @tool(
        name="browser_page_text",
        description="Read visible text from the current browser page.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"max_chars": {"type": "integer", "default": 4000}},
        },
    )
    async def browser_page_text(max_chars: int = 4000) -> str:
        page = await controller.page()
        text = await page.locator("body").inner_text(timeout=10_000)
        return text[:max_chars]

    @tool(
        name="browser_click_text",
        description="Click visible text in the controlled browser.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        preview=lambda a: f"browser click text: {a.get('text','')}",
    )
    async def browser_click_text(text: str) -> str:
        page = await controller.page()
        await page.get_by_text(text, exact=False).first.click(timeout=10_000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        return await _page_status(page)

    @tool(
        name="browser_type",
        description="Type into the current browser page. If selector is set, fills that element; otherwise types at focus.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "selector": {"type": "string", "default": ""},
            },
            "required": ["text"],
        },
        preview=lambda a: f"browser type: {a.get('text','')[:80]}",
    )
    async def browser_type(text: str, selector: str = "") -> str:
        page = await controller.page()
        if selector:
            await page.locator(selector).fill(text, timeout=10_000)
        else:
            await page.keyboard.type(text)
        return "typed into browser"

    @tool(
        name="browser_press",
        description="Press a key in the current browser page, e.g. Enter, Escape, Control+L.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        preview=lambda a: f"browser key: {a.get('key','')}",
    )
    async def browser_press(key: str) -> str:
        page = await controller.page()
        await page.keyboard.press(key)
        return await _page_status(page)

    @tool(
        name="browser_screenshot",
        description="Save a screenshot of the current browser page and return the path.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": ""},
                "full_page": {"type": "boolean", "default": False},
            },
        },
        preview=lambda a: f"browser screenshot -> {a.get('path','data/browser_screenshots')}",
    )
    async def browser_screenshot(path: str = "", full_page: bool = False) -> str:
        page = await controller.page()
        out = Path(path) if path else cfg.abs_path("data/browser_screenshots/current.png")
        if not out.is_absolute():
            out = cfg.project_root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out), full_page=full_page)
        return f"screenshot saved: {out}"

    @tool(
        name="browser_close",
        description="Close the Playwright-controlled browser.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    async def browser_close() -> str:
        return await controller.close()

    registry.add_pending("browser_tools")
    registry.register_plugin(PluginInfo(
        name="browser_tools",
        description="Visible Playwright browser search and control.",
        permissions_needed=[Permission.SAFE, Permission.CAUTION],
    ))


def _normalise_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return "about:blank"
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        return u
    if "." in u and " " not in u:
        return "https://" + u
    return "https://duckduckgo.com/?q=" + quote_plus(u)


async def _page_status(page) -> str:
    return f"{await page.title()} | {page.url}"


async def _extract_results(page, max_results: int) -> list[dict[str, str]]:
    return await page.evaluate(
        """(maxResults) => {
          const nodes = Array.from(document.querySelectorAll(
            ".result, .results_links, article, [data-testid='result'], .web-result"
          ));
          const out = [];
          for (const node of nodes) {
            const a = node.querySelector("a.result__a[href], a[href]");
            const titleNode = node.querySelector("a.result__a, h2, h3, [data-testid='result-title-a']") || a;
            const snippetNode = node.querySelector(".result__snippet, .snippet, [data-result='snippet']");
            if (!a || !titleNode) continue;
            const href = a.href || "";
            const title = (titleNode.innerText || a.innerText || "").trim();
            const snippet = snippetNode
              ? (snippetNode.innerText || "").trim()
              : (node.innerText || "").replace(title, "").trim().split("\\n").slice(0, 4).join(" ");
            if (title && href && !out.some(r => r.url === href)) {
              out.push({ title, url: href, snippet: snippet.slice(0, 240) });
            }
            if (out.length >= maxResults) break;
          }
          return out;
        }""",
        max_results,
    )


def _decode_ddg_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return unquote(uddg[0])
    return url


def _format_results(results: list[dict[str, str]], max_n: int) -> str:
    lines: list[str] = []
    for i, r in enumerate(results[:max_n], start=1):
        lines.append(f"{i}. {r.get('title', '(no title)')}")
        lines.append(f"   {r.get('url', '')}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
    return "\n".join(lines) or "(no results)"
