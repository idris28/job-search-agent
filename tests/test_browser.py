from contextlib import contextmanager

import pytest

from jobagent import browser as bmod
from jobagent.browser import LazyBrowser, PageContent
from jobagent.config import Settings


class Dying:
    """First session serves one page then dies; later sessions work."""

    def __init__(self, n):
        self.n, self.calls = n, 0

    def fetch(self, url, wait_ms=0):
        self.calls += 1
        if self.n == 1 and self.calls > 1:
            raise RuntimeError("Page.goto: Target page, context or browser has been closed")
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
