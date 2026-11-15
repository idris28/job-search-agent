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


class Answer:
    def __init__(self, status, headers=None):
        self.status, self.headers = status, headers or {}


class AnsweringPage:
    """A page that loads: the site's answer, then what the page shows."""

    def __init__(self, status, title, text, links=(), headers=None):
        self.url, self.answer = "https://x/jobs", Answer(status, headers)
        self.shows = {"title": title, "text": text, "links": [{"href": f"https://x/{n}", "text": f"job {n}"} for n in range(len(links) or 0)] if not links
                      else [{"href": h, "text": "job"} for h in links]}

    def goto(self, url, **kw):
        return self.answer

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js):
        return self.shows


DENIED = 'Access Denied You don\'t have permission to access "http://www.example.com/java-jobs?" on this server. Reference #18.f1cc517.1794744689.4000c05f'
CHECK = ("www.example.com Performing security verification This website uses a security service to protect against malicious bots. "
         "This page is displayed while the website verifies you are not a bot. Ray ID: a5ae28ef3d5e40db")
MANY = [f"https://x/job/{n}" for n in range(30)]


@pytest.mark.parametrize("page, why", [
    # the three answers real job boards gave the browser on this Mac
    (AnsweringPage(403, "Access Denied", DENIED, headers={"server": "AkamaiGHost"}), 'error 403, "Access Denied"'),
    (AnsweringPage(403, "Just a moment...", CHECK, ["https://x/a", "https://x/b"], {"server": "cloudflare", "cf-mitigated": "challenge"}),
     'a "verify you are not a bot" check'),
    (AnsweringPage(429, "", "Too many requests"), "error 429"),
    # a check page served as if it were an ordinary page
    (AnsweringPage(200, "Just a moment...", CHECK, ["https://x/a", "https://x/b"]), 'a bot check: "just a moment"'),
])
def test_a_refusal_page_is_reported_as_a_refusal_and_never_read_as_a_page(page, why):
    with pytest.raises(SiteRefused) as e:
        PlaywrightBrowser(page).fetch("https://x/jobs")
    assert str(e.value) == f"the site refused this browser when it asked for https://x/jobs ({why}). Job sites often do this to automated browsers"


@pytest.mark.parametrize("page", [
    AnsweringPage(200, "Java jobs", "Senior Java Engineer\nBackend Engineer\n" * 40, MANY),
    # a posting may well mention a check of its own; that is not the site refusing
    AnsweringPage(200, "Security Engineer", "You will run the security check for new releases and verify that you are meeting the standard. " * 30, MANY),
    AnsweringPage(200, "Short posting", "Java developer wanted. Access denied errors in our gateway are yours to fix. " * 30, ["https://x/a"]),
    AnsweringPage(404, "Not found", "This job is no longer available."),  # gone, not refused
    AnsweringPage(None, "Java jobs", "Senior Java Engineer", MANY),
])
def test_an_ordinary_page_is_still_read(page):
    got = PlaywrightBrowser(page).fetch("https://x/jobs")
    assert got.title == page.shows["title"] and got.text == page.shows["text"]


def test_a_site_that_drops_the_connection_is_reported_as_refusing_the_browser():
    page = FailingPage("Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://x/jobs\nCall log:\n  - navigating")
    with pytest.raises(SiteRefused) as e:
        PlaywrightBrowser(page).fetch("https://x/jobs")
    assert str(e.value) == ("the site closed the connection when this browser asked for https://x/jobs "
                            "(ERR_HTTP2_PROTOCOL_ERROR). Job sites often do this to automated browsers")
    assert page.url.startswith("chrome-error://")  # the next fetch on this page is still safe


class Counted:
    """Stands in for a lazy browser: remembers which kind it is and what it was asked for."""

    def __init__(self, settings):
        self.kind, self.asked, self.closed, self.minutes_used, self.sessions_opened = settings.browser, [], False, 0.0, 0

    def fetch(self, url, *, wait_ms=2500):
        self.asked.append(url)
        self.minutes_used += 1.5
        self.sessions_opened = 1
        return PageContent(url, self.kind, "", [])

    def close(self):
        self.closed = True


def test_each_job_board_gets_the_browser_it_names_and_none_is_opened_unasked():
    made = []
    browsers = bmod.Browsers(Settings(browser="local"), make=lambda s: made.append(Counted(s)) or made[-1])
    assert made == [] and browsers.minutes_used == 0  # nothing starts until a board needs it

    assert browsers.of("").fetch("https://cutshort/jobs").title == "local"  # a board that names none: the one in .env
    assert browsers.fetch("https://hirist/jobs").title == "local"
    assert [b.kind for b in made] == ["local"]  # still no Browserbase session, so none of its time is spent

    assert browsers.of("browserbase").fetch("https://naukri/jobs").title == "browserbase"
    assert browsers.of("browserbase") is browsers.of("browserbase") and [b.kind for b in made] == ["local", "browserbase"]
    assert (browsers.minutes("browserbase"), browsers.minutes("local"), browsers.minutes_used) == (1.5, 3.0, 4.5)
    assert browsers.sessions_opened == 2
    browsers.close()
    assert all(b.closed for b in made)

    # With Browserbase as the usual browser, a board can still name this Mac.
    made.clear()
    usual_hosted = bmod.Browsers(Settings(browser="browserbase"), make=lambda s: made.append(Counted(s)) or made[-1])
    assert usual_hosted.of("").kind == "browserbase" and usual_hosted.of("local").kind == "local"


def test_browserbase_that_will_not_start_says_so_in_plain_words(monkeypatch):
    import sys
    import types

    class Sessions:
        def create(self, **kw):
            raise RuntimeError("Error code: 402 - {'message': 'Browser minutes limit reached'}\nmore detail")

    fake = types.ModuleType("browserbase")
    fake.Browserbase = lambda api_key: types.SimpleNamespace(sessions=Sessions())
    monkeypatch.setitem(sys.modules, "browserbase", fake)
    with pytest.raises(bmod.BrowserUnavailable) as e:
        with bmod.open_browser(Settings(browser="browserbase", browserbase_api_key="k")):
            pass
    assert str(e.value) == ("Browserbase would not start a browser (Error code: 402 - {'message': 'Browser minutes limit reached'}). "
                            "Its browser time for this month may be used up")
