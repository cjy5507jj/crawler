"""Shared Playwright wrapper for SPA-rendered sources.

Local-only dependency: install via `pip install playwright && playwright install chromium`.
The function is lazy-imported so non-Playwright callers (CI, tests) still work.
"""

from __future__ import annotations

from typing import Iterable

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


def render_html(
    url: str,
    *,
    wait_for_selector: str | None = None,
    wait_until: str = "networkidle",
    timeout_ms: int = 30_000,
    extra_wait_ms: int = 0,
    locale: str = "ko-KR",
    user_agent: str = DEFAULT_UA,
    cookies: Iterable[dict] | None = None,
) -> str:
    """Render `url` in headless Chromium and return the final HTML."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright not installed. Run:\n"
            "  pip install playwright && playwright install chromium"
        ) from e

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=user_agent, locale=locale)
        if cookies:
            context.add_cookies(list(cookies))
        page = context.new_page()
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            if wait_for_selector:
                page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
            if extra_wait_ms:
                page.wait_for_timeout(extra_wait_ms)
            return page.content()
        finally:
            context.close()
            browser.close()
