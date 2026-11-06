"""Browser access. Browserbase in production, local Chromium for development.

Adapters only see `Browser.fetch(url) -> PageContent`, so they don't care which is used.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Protocol

from .config import Settings

log = logging.getLogger(__name__)

_EXTRACT_JS = """
() => {
  const links = Array.from(document.querySelectorAll('a[href]')).map(a => ({
    href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 200)
  })).filter(l => l.href.startsWith('http') && l.text);
  return { title: document.title, text: document.body ? document.body.innerText : '', links };
}
"""


@dataclass
class PageContent:
    url: str
    title: str
    text: str
    links: list[dict] = field(default_factory=list)  # [{href, text}]


class Browser(Protocol):
    def fetch(self, url: str, *, wait_ms: int = 2500) -> PageContent: ...


class PlaywrightBrowser:
    """Wraps a Playwright page; used for both Browserbase (over CDP) and local Chromium."""

    def __init__(self, page):
        self._page = page

    def fetch(self, url: str, *, wait_ms: int = 2500) -> PageContent:
        self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        try:
            self._page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:  # noqa: BLE001 - many job sites never go fully idle
            pass
        if wait_ms:
            self._page.wait_for_timeout(wait_ms)
        data = self._page.evaluate(_EXTRACT_JS)
        return PageContent(url=self._page.url, title=data["title"], text=data["text"],
                           links=data["links"])


@contextmanager
def open_browser(settings: Settings) -> Iterator[Browser]:
    """Open one browser session for the duration of a run."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        if settings.browser == "local":
            browser = pw.chromium.launch(headless=True)
            try:
                yield PlaywrightBrowser(browser.new_page())
            finally:
                browser.close()
            return

        settings.require("browserbase_api_key", "browserbase_project_id")
        from browserbase import Browserbase

        bb = Browserbase(api_key=settings.browserbase_api_key)
        session = bb.sessions.create(project_id=settings.browserbase_project_id)
        log.info("Browserbase session %s (replay: https://browserbase.com/sessions/%s)",
                 session.id, session.id)
        browser = pw.chromium.connect_over_cdp(session.connect_url)
        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            yield PlaywrightBrowser(page)
        finally:
            browser.close()  # ends the Browserbase session


class LazyBrowser:
    """Only opens a Browserbase session if some source actually needs one."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._cm = None
        self._browser: Browser | None = None

    def fetch(self, url: str, *, wait_ms: int = 2500) -> PageContent:
        if self._browser is None:
            self._cm = open_browser(self._settings)
            self._browser = self._cm.__enter__()
        return self._browser.fetch(url, wait_ms=wait_ms)

    def close(self) -> None:
        if self._cm is not None:
            self._cm.__exit__(None, None, None)
            self._cm = self._browser = None
