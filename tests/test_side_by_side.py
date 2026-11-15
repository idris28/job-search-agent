"""Company career sites are read several at the same time; job boards one after another."""

import threading
import time

import httpx
import pytest

from jobagent import db, pipeline
from jobagent.browser import PageContent
from jobagent.config import AgentConfig, MatchingPrefs, SearchPrefs, SourceConfig
from jobagent.pipeline import run_agent

from conftest import FakeBrowser, FakeLLM

NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]


def site(name, n=1):
    return {"jobs": [{"id": f"{name}-{i}", "title": f"Java Engineer at {name} {i}", "absolute_url": f"https://gh/{name}/{i}",
                      "location": {"name": "Dubai"}, "content": "Build Java services. " * 20} for i in range(n)]}


def slow_sites(delay, broken=(), slowest=None):
    """Six company sites that each take `delay` seconds to answer."""
    seen = []

    def handler(request: httpx.Request):
        name = request.url.path.split("/")[3].capitalize()  # /v1/boards/<name>/jobs
        seen.append((name, threading.current_thread().name))
        time.sleep(delay * (4 if name == slowest else 1))
        if name in broken:
            return httpx.Response(500, json={"error": "down"})
        return httpx.Response(200, json=site(name))

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def cfg(extra=()):
    return AgentConfig(search=SearchPrefs(locations=["Dubai"], include_title_keywords=["java"]),
                       matching=MatchingPrefs(shortlist_min_score=75, concurrency=1),
                       sources=[*extra, *(SourceConfig(kind="greenhouse", name=n, board=n.lower()) for n in NAMES)])


def messages(conn):
    return [r["message"] for r in conn.execute("SELECT message FROM run_events ORDER BY id").fetchall()]


def test_company_sites_are_read_side_by_side_and_stored_in_the_order_of_the_settings(conn):
    db.save_profile(conn, "Alex", "resume", {})
    http, seen = slow_sites(0.4, slowest="Alpha")  # the first one in the settings is the slowest
    llm = FakeLLM()
    started = time.monotonic()
    s = run_agent(conn, cfg(), llm, FakeBrowser({}), http=http)
    took = time.monotonic() - started

    assert (s.status, s.found, s.scored) == ("succeeded", 6, 6)
    assert took < 2.6  # one after another it would be 0.4 x 9 = 3.6 seconds before any scoring
    assert len({thread for _, thread in seen}) > 1 and all(t.startswith("site") for _, t in seen)
    # Whichever answered first, what is stored and scored keeps the order of the settings.
    said = messages(conn)
    assert [m.split(":")[0] for m in said if "jobs (" in m] == NAMES
    assert llm.scored_titles == [f"Java Engineer at {n} 0" for n in NAMES]
    assert any(m.startswith("6 sites read in ") for m in said)


def test_one_site_that_fails_does_not_hold_up_or_spoil_the_others(conn):
    db.save_profile(conn, "Alex", "resume", {})
    http, _ = slow_sites(0.05, broken={"Echo", "Bravo"})
    s = run_agent(conn, cfg(), FakeLLM(), FakeBrowser({}), http=http)
    assert (s.status, s.found) == ("partial", 4)
    assert list(s.source_errors) == ["Bravo", "Echo"]  # named in the order of the settings, not of failing
    assert db.list_runs(conn)[0]["error"] == "2 sites could not be read: Bravo, Echo"


def test_only_the_search_itself_writes_to_the_database(conn, monkeypatch):
    db.save_profile(conn, "Alex", "resume", {})
    writers = set()
    for name in ("upsert_job", "log_event", "upsert_source"):
        real = getattr(db, name)
        monkeypatch.setattr(db, name, lambda *a, _real=real, **kw: (writers.add(threading.current_thread().name), _real(*a, **kw))[1])
    http, seen = slow_sites(0.05)
    run_agent(conn, cfg(), FakeLLM(), FakeBrowser({}), http=http)
    assert writers == {threading.current_thread().name} and len({t for _, t in seen}) > 1


def test_job_boards_are_still_read_one_after_another_while_the_company_sites_come_in(conn):
    db.save_profile(conn, "Alex", "resume", {})
    board = "https://board.example.com/java-jobs"
    order = []

    class Recording(FakeBrowser):
        def fetch(self, url, *, wait_ms=0):
            order.append(threading.current_thread().name)
            return super().fetch(url, wait_ms=wait_ms)

    browser = Recording({board: PageContent(board, "Jobs", "nothing today", [])})
    http, seen = slow_sites(0.05)
    s = run_agent(conn, cfg(extra=[SourceConfig(kind="generic", name="Board", urls=[board], max_detail_pages=0)]),
                  FakeLLM(listings=[]), browser, http=http)
    assert order == [threading.current_thread().name]  # the browser is only ever used by the search itself
    assert s.found == 6 and [m.split(":")[0] for m in messages(conn) if "jobs (" in m] == ["Board", *NAMES]


def test_a_stopped_search_does_not_wait_for_sites_still_being_read(conn):
    db.save_profile(conn, "Alex", "resume", {})
    board = "https://board.example.com/java-jobs"

    class Stopping(FakeBrowser):
        def fetch(self, url, *, wait_ms=0):
            time.sleep(0.2)
            raise KeyboardInterrupt  # the Stop button, while the company sites are still answering

    http, _ = slow_sites(1.5)
    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        run_agent(conn, cfg(extra=[SourceConfig(kind="generic", name="Board", urls=[board])]), FakeLLM(), Stopping({}), http=http)
    assert time.monotonic() - started < 1.2  # it did not sit out the 1.5 seconds
    run = db.list_runs(conn)[0]
    assert run["status"] == "partial" and run["error"].startswith("Stopped before it finished")
    time.sleep(1.6)  # let the stand-in sites finish answering before the next test wipes the database


def test_a_single_site_search_reads_just_that_site(conn):
    db.save_profile(conn, "Alex", "resume", {})
    http, seen = slow_sites(0.01)
    s = run_agent(conn, cfg(), FakeLLM(), FakeBrowser({}), http=http, only_source="Delta")
    assert [n for n, _ in seen] == ["Delta"] and s.found == 1
    assert not any("sites read in" in m for m in messages(conn))
    assert pipeline.SITES_AT_ONCE >= 2
