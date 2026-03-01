import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote_plus

import aiohttp

from .base import BaseTool

logger = logging.getLogger(__name__)

# User-agent for plain HTTP requests
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


async def _fetch_text(url: str, timeout: int = 20) -> str:
    """Fetch a URL and return cleaned plain text."""
    async with aiohttp.ClientSession(headers={"User-Agent": UA}) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            ct = resp.headers.get("Content-Type", "")
            raw = await resp.text(errors="replace")
    # Strip HTML tags
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _duckduckgo_search(query: str, max_results: int = 8) -> str:
    """Search DuckDuckGo using the HTML endpoint (no API key needed)."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        from bs4 import BeautifulSoup
        async with aiohttp.ClientSession(headers={"User-Agent": UA}) as session:
            async with session.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                html = await resp.text(errors="replace")
        soup = BeautifulSoup(html, "lxml")
        results = []
        for result in soup.select(".result")[:max_results]:
            title_el = result.select_one(".result__a")
            snippet_el = result.select_one(".result__snippet")
            if title_el:
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                results.append(f"**{title}**\n{href}\n{snippet}")
        return "\n\n".join(results) if results else "No search results found."
    except Exception as e:
        return f"Search failed: {e}"


class BrowserTool(BaseTool):
    name = "browser"
    description = (
        "Browse the web and search for information. "
        "Actions: search_web, get_page_content, screenshot_page (requires Playwright), "
        "fill_and_submit_form (requires Playwright)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search_web", "get_page_content", "screenshot_page", "fill_and_submit_form"],
                "description": "Browser action to perform.",
            },
            "query": {"type": "string", "description": "Search query (for search_web)."},
            "url": {"type": "string", "description": "URL to load (for get_page_content / screenshot_page)."},
            "max_results": {"type": "integer", "description": "Max search results. Default 8."},
            "form_data": {
                "type": "object",
                "description": "Dict of {CSS_selector: value} for form filling.",
            },
            "submit_selector": {"type": "string", "description": "CSS selector of submit button."},
        },
        "required": ["action"],
    }

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright_available = self._check_playwright()

    @staticmethod
    def _check_playwright() -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")
        try:
            if action == "search_web":
                query = kwargs.get("query", "")
                max_results = int(kwargs.get("max_results", 8))
                return await _duckduckgo_search(query, max_results)

            elif action == "get_page_content":
                url = kwargs.get("url", "")
                if not url:
                    return "URL is required."
                text = await _fetch_text(url)
                return text[:6000] if len(text) > 6000 else text

            elif action == "screenshot_page":
                if not self._playwright_available:
                    return "Playwright not installed. Run: playwright install chromium"
                return await self._screenshot(kwargs.get("url", ""))

            elif action == "fill_and_submit_form":
                if not self._playwright_available:
                    return "Playwright not installed. Run: playwright install chromium"
                return await self._fill_form(
                    kwargs.get("url", ""),
                    kwargs.get("form_data", {}),
                    kwargs.get("submit_selector", ""),
                )
            else:
                return f"Unknown browser action: {action}"
        except Exception as e:
            logger.error("Browser tool error", exc_info=True)
            return f"Browser error: {e}"

    async def _screenshot(self, url: str) -> str:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self._headless)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            path = f"/tmp/screenshot_{hash(url) & 0xFFFFFF}.png"
            await page.screenshot(path=path, full_page=False)
            await browser.close()
        return f"Screenshot saved to {path}"

    async def _fill_form(self, url: str, form_data: dict, submit_selector: str) -> str:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self._headless)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            for selector, value in form_data.items():
                await page.fill(selector, str(value))
            if submit_selector:
                await page.click(submit_selector)
                await page.wait_for_load_state("networkidle", timeout=10000)
            content = await page.content()
            await browser.close()
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "lxml")
            text = soup.get_text(separator="\n", strip=True)
        except Exception:
            text = re.sub(r"<[^>]+>", " ", content)
        return text[:4000]
