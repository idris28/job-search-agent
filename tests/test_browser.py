from contextlib import contextmanager

import pytest

from jobagent import browser as bmod
from jobagent.browser import LazyBrowser, PageContent, PlaywrightBrowser, SiteRefused
from jobagent.config import Settings

SESSION_ENDED = "Page.goto: Target page, context or browser has been closed"


class Dying:
    """First session serves one page then dies; later sessions work."""

    def __init__(self, n):
        self.n, self.calls = n, 0

    def fetch(self, url, wait_ms=0):
        self.calls += 1
        if self.n == 1 and self.calls > 1:
            raise RuntimeError(SESSION_ENDED)
        return PageContent(url, "t", f"session {self.n}", [])


def test_reopens_dead_session(monkeypatch):
    opened = []

    @contextmanager
    def fake_open(settings):
        b = Dying(len(opened) + 1)
        opened.append(b)
        yield b

    monkeypatch.setattr(bmod, "open_browser", fake_open)
    lb = LazyBrowser(Settings())
    assert lb.fetch("a").text == "session 1"
    assert lb.fetch("b").text == "session 2"   # died, reopened, retried
    assert lb.sessions_opened == 2
    lb.close()


def test_other_errors_propagate(monkeypatch):
    class Bad:
        def fetch(self, url, wait_ms=0):
            raise ValueError("net::ERR_NAME_NOT_RESOLVED")

    @contextmanager
    def fake_open(settings):
        yield Bad()

    monkeypatch.setattr(bmod, "open_browser", fake_open)
    with pytest.raises(ValueError):
        LazyBrowser(Settings()).fetch("a")


def test_gives_up_when_the_new_session_ends_too(monkeypatch):
    class Dead:
        def fetch(self, url, wait_ms=0):
            raise RuntimeError(SESSION_ENDED)

    @contextmanager
    def fake_open(settings):
        yield Dead()

    monkeypatch.setattr(bmod, "open_browser", fake_open)
    lb = LazyBrowser(Settings())
    with pytest.raises(RuntimeError, match="has been closed"):
        lb.fetch("a")
    assert lb.sessions_opened == 2   # reopened once, then the error is reported


class FailingPage:
    """goto always fails; Chromium's error page shows up after `error_page_after` waits."""

    url = "https://x/previous"

    def __init__(self, error, error_page_after=3):
        self.error, self.error_page_after, self.waits = error, error_page_after, 0

    def goto(self, url, **kw):
        raise RuntimeError(self.error)

    def wait_for_timeout(self, ms):
        self.waits += 1
        if self.waits == self.error_page_after:
            self.url = "chrome-error://chromewebdata/"


def test_failed_load_waits_for_the_error_page_before_reporting():
    # Otherwise the error page lands during the next fetch and cancels it.
    page = FailingPage("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://x/jobs")
    with pytest.raises(RuntimeError, match="ERR_NAME_NOT_RESOLVED"):
        PlaywrightBrowser(page).fetch("https://x/jobs")
    assert page.waits == 3 and page.url.startswith("chrome-error://")


def test_other_load_failures_are_reported_at_once():
    page = FailingPage("Page.goto: Timeout 45000ms exceeded.")
    with pytest.raises(RuntimeError, match="Timeout"):
        PlaywrightBrowser(page).fetch("https://x/jobs")
    assert page.waits == 0


def test_a_site_that_drops_the_connection_is_reported_as_refusing_the_browser():
    page = FailingPage("Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://x/jobs\nCall log:\n  - navigating")
    with pytest.raises(SiteRefused) as e:
        PlaywrightBrowser(page).fetch("https://x/jobs")
    assert str(e.value) == ("the site closed the connection when this browser asked for https://x/jobs "
                            "(ERR_HTTP2_PROTOCOL_ERROR). Job sites often do this to automated browsers")
    assert page.url.startswith("chrome-error://")  # the next fetch on this page is still safe
