"""A job board's list gives a title, a company and a place. The job's own page is opened once,
and until it has been opened the job is not scored."""

from jobagent import db
from jobagent.browser import PageContent
from jobagent.config import AgentConfig, MatchingPrefs, SearchPrefs, Settings, SourceConfig
from jobagent.models import JobPosting, MatchResult
from jobagent.pipeline import run_agent, unread_jobs, waiting_jobs
from jobagent.sources import SourceContext, build_source

from conftest import TEST_DB, FakeBrowser, FakeLLM, mock_http

BOARD = "https://board.example.com/java-jobs"
TITLES = ["Senior Java Engineer", "Java Backend Developer", "Java Developer"]
LINKS = [{"href": f"https://board.example.com/jobs/{i + 1}", "text": t} for i, t in enumerate(TITLES)]
LISTED = [{"title": t, "url": LINKS[i]["href"], "company": "Acme", "location": "Dubai"} for i, t in enumerate(TITLES)]
TEXT = "We build payment services in Java 21 and Spring Boot, with Kafka and PostgreSQL, for banks across the Gulf. " * 3


def job_page(i):
    return PageContent(LINKS[i]["href"], "", f"{TITLES[i]}. {TEXT}", [])


def board(listed=3, pages=(0, 1, 2)):
    return FakeBrowser({BOARD: PageContent(BOARD, "Jobs", "\n".join(TITLES[:listed]), LINKS[:listed]),
                        **{LINKS[i]["href"]: job_page(i) for i in pages}})


def cfg(read_per_search=1):
    return AgentConfig(search=SearchPrefs(locations=["Dubai"], include_title_keywords=["java"]),
                       matching=MatchingPrefs(shortlist_min_score=75),
                       sources=[SourceConfig(kind="generic", name="Board", urls=[BOARD], max_detail_pages=read_per_search)])


def opened(browser):
    """The job pages opened, as their numbers; the list page itself is left out."""
    return [int(u.rsplit("/", 1)[1]) for u in browser.visited if u != BOARD]


def test_a_job_is_scored_only_after_its_own_page_was_read_and_each_page_is_opened_once(conn):
    pid = db.save_profile(conn, "Alex", "resume", {})
    llm = FakeLLM(listings=LISTED, scores={"Senior Java Engineer": 90})

    first = board()
    s = run_agent(conn, cfg(), llm, first, http=mock_http({}))
    assert opened(first) == [1] and llm.scored_titles == ["Senior Java Engineer"]
    assert (s.found, s.scored, s.unread, s.shortlisted, s.status) == (3, 1, 2, 1, "succeeded")
    assert waiting_jobs(conn, cfg(), pid) == []  # the other two wait to be read, not to be scored
    assert unread_jobs(conn, cfg()) == 2
    assert {r["title"] for r in db.top_matches(conn, pid, min_score=0)} == {"Senior Java Engineer"}
    said = [r["message"] for r in conn.execute("SELECT message FROM run_events ORDER BY id").fetchall()]
    assert "Board: 2 jobs wait for a later search to read their page" in said

    second = board()
    s = run_agent(conn, cfg(), llm, second, http=mock_http({}))
    assert opened(second) == [2]  # the page read last time is not opened again
    assert llm.scored_titles == ["Senior Java Engineer", "Java Backend Developer"]
    assert (s.scored, s.skipped_unchanged, s.unread, s.new) == (1, 1, 1, 0)

    third = board()
    s = run_agent(conn, cfg(), llm, third, http=mock_http({}))
    assert opened(third) == [3] and (s.scored, s.skipped_unchanged, s.unread) == (1, 2, 0)
    assert unread_jobs(conn, cfg()) == 0

    fourth = board()
    s = run_agent(conn, cfg(), llm, fourth, http=mock_http({}))
    assert opened(fourth) == [] and (s.scored, s.skipped_unchanged, s.unread) == (0, 3, 0)
    assert len(llm.scored_titles) == 3  # three jobs, three scorings, however many searches
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 3


def test_a_job_scored_on_its_title_alone_is_scored_again_once_its_page_is_read(conn):
    pid = db.save_profile(conn, "Alex", "resume", {})
    source = db.upsert_source(conn, "generic", "Board", BOARD, {"max_detail_pages": 1})
    unread = JobPosting(title=TITLES[2], company="Acme", url=LINKS[2]["href"], location="Dubai")
    jid, _ = db.upsert_job(conn, unread, source, None)  # listed by an earlier search, page never opened
    db.save_match(conn, pid, jid, None, MatchResult(score=55, verdict="stretch", summary="Title only.", matched_skills=[],
                                                    missing_skills=[], red_flags=[]), "m", unread.content_hash)

    # It has dropped off the list page, but it was listed recently, so its page is still read.
    llm, browser = FakeLLM(listings=LISTED[:1], scores={"Java Developer": 88}), board(listed=1)
    s = run_agent(conn, cfg(read_per_search=5), llm, browser, http=mock_http({}))
    assert opened(browser) == [1, 3] and sorted(llm.scored_titles) == ["Java Developer", "Senior Java Engineer"]
    assert (s.scored, s.shortlisted, s.unread) == (2, 1, 0)
    row = conn.execute("SELECT score, summary FROM job_matches WHERE job_id = %s", (jid,)).fetchone()
    assert row == {"score": 88, "summary": "fit 88"}
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 2  # the same job, not a second copy


def test_a_board_that_lists_nothing_is_not_asked_for_more_pages(conn):
    db.save_profile(conn, "Alex", "resume", {})
    source = db.upsert_source(conn, "generic", "Board", BOARD, {"max_detail_pages": 5})
    db.upsert_job(conn, JobPosting(title=TITLES[0], company="Acme", url=LINKS[0]["href"], location="Dubai"), source, None)
    browser = FakeBrowser({BOARD: PageContent(BOARD, "Jobs", "Please verify you are human", [])})
    s = run_agent(conn, cfg(read_per_search=5), FakeLLM(listings=[]), browser, http=mock_http({}))
    assert browser.visited == [BOARD] and (s.found, s.scored, s.unread) == (0, 0, 0)


def test_pages_go_to_jobs_the_rules_would_keep_and_a_page_that_fails_is_tried_again(conn):
    db.save_profile(conn, "Alex", "resume", {})
    listed = [{"title": "Sales Manager", "url": LINKS[0]["href"], "company": "Acme", "location": "Dubai"}, *LISTED[1:]]
    llm = FakeLLM(listings=listed)
    browser = FakeBrowser({BOARD: PageContent(BOARD, "Jobs", "jobs", LINKS), LINKS[1]["href"]: RuntimeError("timeout"),
                           LINKS[2]["href"]: job_page(2)})
    s = run_agent(conn, cfg(read_per_search=2), llm, browser, http=mock_http({}))
    assert opened(browser) == [2, 3]  # no page is spent on the sales job: the title rule drops it anyway
    assert llm.scored_titles == ["Java Developer"] and (s.filtered, s.unread, s.status) == (1, 1, "succeeded")

    again = FakeBrowser({BOARD: PageContent(BOARD, "Jobs", "jobs", LINKS), LINKS[1]["href"]: job_page(1)})
    s = run_agent(conn, cfg(read_per_search=2), llm, again, http=mock_http({}))
    assert opened(again) == [2] and llm.scored_titles == ["Java Developer", "Java Backend Developer"] and s.unread == 0


def test_a_board_that_refuses_the_browser_is_reported_and_not_read_as_empty(conn):
    from jobagent.browser import SiteRefused

    db.save_profile(conn, "Alex", "resume", {})
    refused = SiteRefused(f'the site refused this browser when it asked for {BOARD} (error 403, "Access Denied"). '
                          "Job sites often do this to automated browsers")

    class Counting(FakeLLM):
        pages_read = 0

        def extract_listings(self, text, links, url):
            Counting.pages_read += 1
            return super().extract_listings(text, links, url)

    s = run_agent(conn, cfg(), Counting(listings=LISTED), FakeBrowser({BOARD: refused}), http=mock_http({}))
    assert Counting.pages_read == 0  # no AI call is spent on a page that was never served
    assert (s.status, s.found, s.source_errors) == ("partial", 0, {"Board": str(refused)})
    assert db.list_runs(conn)[0]["error"] == "1 site could not be read: Board"

    # Refused on a job's own page: the board is asked for no more pages in this search.
    listing_only = FakeBrowser({BOARD: PageContent(BOARD, "Jobs", "jobs", LINKS), LINKS[0]["href"]: refused, LINKS[1]["href"]: job_page(1),
                                LINKS[2]["href"]: job_page(2)})
    s = run_agent(conn, cfg(read_per_search=3), FakeLLM(listings=LISTED), listing_only, http=mock_http({}))
    assert opened(listing_only) == [1] and (s.status, s.scored, s.unread) == ("succeeded", 0, 3)
    said = [r["message"] for r in conn.execute("SELECT message FROM run_events ORDER BY id").fetchall()]
    assert any(m.startswith("Board: the site refused this browser") and m.endswith("No more job pages are asked for in this search") for m in said)


def test_a_board_set_to_read_no_job_pages_is_scored_on_what_its_list_gives(conn):
    db.save_profile(conn, "Alex", "resume", {})
    llm, browser = FakeLLM(listings=LISTED), board(pages=())
    s = run_agent(conn, cfg(read_per_search=0), llm, browser, http=mock_http({}))
    assert opened(browser) == [] and (s.scored, s.unread) == (3, 0)  # max_detail_pages: 0 keeps the old way


def test_the_same_job_on_another_board_is_not_read_twice():
    stored = JobPosting(title="Senior Java Engineer", company="Acme", url="https://other.example.com/j/9", location="Dubai",
                        description=TEXT)
    browser, said = board(listed=2, pages=(1,)), []
    ctx = SourceContext(http=None, browser=browser, llm=FakeLLM(listings=LISTED[:2]), log=said.append,
                        recall=lambda job: stored.model_copy(update={"url": job.url}) if job.title == stored.title else None)
    jobs = build_source(SourceConfig(kind="generic", name="Board", urls=[BOARD], max_detail_pages=5)).fetch(ctx)
    assert opened(browser) == [2]
    assert [(j.title, j.url, j.is_read) for j in jobs] == [("Senior Java Engineer", LINKS[0]["href"], True),
                                                          ("Java Backend Developer", LINKS[1]["href"], True)]
    assert jobs[0].description == TEXT and not any("wait for a later search" in m for m in said)


def test_the_page_says_how_many_jobs_wait_to_be_read(conn):
    from test_web import Page

    db.save_profile(conn, "Alex", "resume", {})
    run_agent(conn, cfg(), FakeLLM(listings=LISTED), board(), http=mock_http({}))
    page = Page(Settings(database_url=TEST_DB), cfg())
    try:
        counts = page.call("/api/state")[1]["counts"]
        assert (counts["unread"], counts["waiting"], counts["scored"]) == (2, 0, 1)
    finally:
        page.close()


def test_a_search_reads_each_board_with_the_browser_that_board_names(conn):
    db.save_profile(conn, "Alex", "resume", {})
    other = "https://other.example.com/java-jobs"
    two = AgentConfig(search=SearchPrefs(locations=["Dubai"], include_title_keywords=["java"]), matching=MatchingPrefs(shortlist_min_score=75),
                      sources=[SourceConfig(kind="generic", name="Board", urls=[BOARD], max_detail_pages=1, browser="browserbase"),
                               SourceConfig(kind="generic", name="Other", urls=[other], max_detail_pages=0)])

    class Router:
        """Hands out one stand-in browser per kind, as the real one does."""

        def __init__(self):
            self.by_kind = {"browserbase": board(), "": FakeBrowser({other: PageContent(other, "Jobs", "none today", [])})}
            self.minutes_used = 0.0

        def of(self, kind=""):
            return self.by_kind[kind]

    router = Router()
    s = run_agent(conn, two, FakeLLM(listings=LISTED), router, http=mock_http({}))
    assert router.by_kind["browserbase"].visited == [BOARD, LINKS[0]["href"]]  # only the board that named it
    assert router.by_kind[""].visited == [other]
    assert s.status == "succeeded" and s.scored == 1
