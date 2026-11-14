"""Browser access. Browserbase in production, local Chromium for development.

Adapters only see `Browser.fetch(url) -> PageContent`, so they don't care which is used.
"""

from __future__ import annotations

import logging
import time
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


class SiteRefused(RuntimeError):
    """The site dropped the connection as soon as this browser asked for a page."""


# Chromium's names for a connection the server cut before sending a page. Job sites do this to
# automated browsers. Nothing here tries to get around it: the source fails, and says why.
_REFUSALS = ("ERR_HTTP2_PROTOCOL_ERROR", "ERR_CONNECTION_RESET", "ERR_CONNECTION_CLOSED", "ERR_EMPTY_RESPONSE")


class PlaywrightBrowser:
    """Wraps a Playwright page; used for both Browserbase (over CDP) and local Chromium."""

    def __init__(self, page):
        self._page = page

    def _await_error_page(self) -> None:
        """After a load fails with a network error, Chromium shows its own error page a moment
        later, and a goto issued before that lands gets cancelled by it ("interrupted by another
        navigation"). Wait for the error page so the next fetch on this page is safe."""
        for _ in range(50):  # it normally lands within ~10 ms; give up after about a second
            if self._page.url.startswith("chrome-error://"):
                return
            self._page.wait_for_timeout(20)

    def fetch(self, url: str, *, wait_ms: int = 2500) -> PageContent:
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as e:  # noqa: BLE001
            if "net::ERR" in str(e):
                self._await_error_page()
                code = next((c for c in _REFUSALS if c in str(e)), None)
                if code:
                    raise SiteRefused(f"the site closed the connection when this browser asked for {url} ({code}). "
                                      "Job sites often do this to automated browsers") from e
            raise
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

        settings.require("browserbase_api_key")
        from browserbase import Browserbase

        bb = Browserbase(api_key=settings.browserbase_api_key)
        # Project ID is optional: Browserbase uses the API key's project when it is omitted.
        params = ({"project_id": settings.browserbase_project_id}
                  if settings.browserbase_project_id else {})
        session = bb.sessions.create(**params)
        log.info("Browserbase session %s (replay: https://browserbase.com/sessions/%s)",
                 session.id, session.id)
        browser = pw.chromium.connect_over_cdp(session.connect_url)
        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            yield PlaywrightBrowser(page)
        finally:
            browser.close()  # ends the Browserbase session


def _session_ended(e: Exception) -> bool:
    """True for Playwright's error once the browser behind the page is gone, which for
    Browserbase means the session reached its timeout."""
    return type(e).__name__ == "TargetClosedError" or "has been closed" in str(e)


class LazyBrowser:
    """Opens a browser session only when a source needs one, and a new one if it ends mid-run."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._cm = None
        self._browser: Browser | None = None
        self.sessions_opened = 0
        self._seconds = 0.0          # browser time in sessions already closed
        self._opened_at: float | None = None

    def _open(self) -> Browser:
        cm = open_browser(self._settings)
        self._browser = cm.__enter__()
        self._cm = cm
        self._opened_at = time.monotonic()
        self.sessions_opened += 1
        return self._browser

    def fetch(self, url: str, *, wait_ms: int = 2500) -> PageContent:
        browser = self._browser or self._open()
        try:
            return browser.fetch(url, wait_ms=wait_ms)
        except Exception as e:  # noqa: BLE001
            if not _session_ended(e):
                raise
        # An ended session never comes back, so without a new one every remaining fetch of the
        # run would fail the same way. Retried once: if the new session ends too, give up.
        log.warning("Browser session ended mid-run; opening a new one for %s", url)
        self.close()
        return self._open().fetch(url, wait_ms=wait_ms)

    @property
    def minutes_used(self) -> float:
        """Browser session time so far in this run, which is what Browserbase bills."""
        live = time.monotonic() - self._opened_at if self._opened_at is not None else 0.0
        return (self._seconds + live) / 60

    def close(self) -> None:
        cm, self._cm, self._browser = self._cm, None, None
        if self._opened_at is not None:
            self._seconds += time.monotonic() - self._opened_at
            self._opened_at = None
        if cm is not None:
            cm.__exit__(None, None, None)
