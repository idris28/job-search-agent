from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from jobagent import cli, db
from jobagent.browser import PageContent
from jobagent.config import SearchPrefs, Settings, SourceConfig
from jobagent.filters import reject_reason
from jobagent.models import JobPosting, MatchResult, PastedJob
from jobagent.report import age
from jobagent.sources import SourceContext, build_source
from jobagent.sources.base import parse_posted

from conftest import TEST_DB, FakeBrowser, FakeLLM, mock_http

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def test_parse_posted():
    hours = lambda text: round((NOW - parse_posted(text, NOW)).total_seconds() / 3600, 2)
    assert hours("Posted: 2 days ago") == 48 and hours("1 hour ago") == 1
    assert hours("30+ days ago \u00b7 Application closes in 59 days") == 720
    assert hours("Just now") == 0 and hours("Posted today") == 0 and hours("Yesterday") == 24
    assert hours("3 weeks ago") == 504 and hours("45 minutes ago") == 0.75
    assert parse_posted("Full time, permanent", NOW) is None and parse_posted(None) is None


def test_week_old_limit_and_age_label():
    prefs = SearchPrefs(max_age_days=7)
    job = lambda text: JobPosting(title="Java Dev", company="A", url="u", posted_at=parse_posted(text, NOW))
    assert reject_reason(job("1 hour ago"), prefs, NOW) is None
    assert reject_reason(job("6 days ago"), prefs, NOW) is None
    assert "7 days" in reject_reason(job("8 days ago"), prefs, NOW)
    assert reject_reason(job("no date shown"), prefs, NOW) is None  # unknown age is not dropped
    assert age(NOW - timedelta(hours=3), NOW) == "3h" and age(NOW - timedelta(days=2), NOW) == "2d"
    assert age(None) == ""


def test_generic_source_reads_age_and_visits_newest_first():
    url = "https://board.example/jobs"
    links = [{"href": f"https://board.example/jobs/{i}", "text": f"Job {i}"} for i in (1, 2, 3)]
    browser = FakeBrowser({url: PageContent(url, "", "", links),
                           "https://board.example/jobs/2": PageContent("u", "", "Java. Posted: 5 days ago", []),
                           "https://board.example/jobs/3": PageContent("u", "", "Java", [])})
    llm = FakeLLM(listings=[
        {"title": "Old", "url": links[0]["href"], "company": None, "location": None, "posted": "9 days ago"},
        {"title": "Undated", "url": links[1]["href"], "company": None, "location": None},
        {"title": "Fresh", "url": links[2]["href"], "company": None, "location": None, "posted": "1 hour ago"},
    ])
    src = build_source(SourceConfig(kind="generic", name="Board", urls=[url], max_detail_pages=2))
    jobs = src.fetch(SourceContext(http=mock_http({}), browser=browser, llm=llm))
    assert [j.title for j in jobs] == ["Fresh", "Old", "Undated"]  # newest first, undated last
    assert browser.visited[1] == "https://board.example/jobs/3"  # detail visits start with the freshest
    assert jobs[0].posted_at > jobs[1].posted_at and jobs[2].posted_at is None


def test_newest_jobs_are_listed_first(conn):
    pid = db.save_profile(conn, "Alex", "resume", {})
    now = datetime.now(timezone.utc)
    for title, posted, score in (("Two days", now - timedelta(days=2), 95),
                                 ("One hour", now - timedelta(hours=1), 80), ("Undated", None, 99)):
        jid, _ = db.upsert_job(conn, JobPosting(title=title, company="A", url=title, posted_at=posted), None, None)
        db.save_match(conn, pid, jid, None, MatchResult(score=score, verdict="strong", summary="s",
                      matched_skills=[], missing_skills=[], red_flags=[]), "m", "h")
        db.set_application_status(conn, pid, jid, "shortlisted")
    assert [r["title"] for r in db.top_matches(conn, pid)] == ["One hour", "Two days", "Undated"]
    order = db.shortlisted_job_ids(conn, pid, 10)
    assert [db.get_job(conn, i)["title"] for i in order] == ["One hour", "Two days", "Undated"]


class PasteLLM:
    model = "fake"

    def read_pasted_job(self, text):
        assert "hiring" in text
        return PastedJob(title="Java Developer", company="Acme", location="Dubai",
                         contact_email="hr@acme.ae", description="We are hiring a Java Developer.")

    def score_job(self, profile, prefs, job):
        assert "hr@acme.ae" in job.description
        return MatchResult(score=88, verdict="strong", summary="fits", matched_skills=["Java"],
                           missing_skills=[], red_flags=[])


def test_a_post_pasted_again_after_its_email_went_says_so_and_offers_no_second_email(conn, monkeypatch, tmp_path, capsys):
    pid = db.save_profile(conn, "Alex", "resume", {})
    monkeypatch.setattr(cli, "_llm", lambda s: PasteLLM())
    args = SimpleNamespace(file=None, url=None, config=str(tmp_path / "missing.yaml"))
    post = lambda: "We are hiring! Send CV to hr@acme.ae"  # noqa: E731
    cli.cmd_add(args, Settings(database_url=TEST_DB), read=post)
    assert "Next: jsa email 1" in capsys.readouterr().out

    cli.cmd_add(args, Settings(database_url=TEST_DB), read=post)  # again, before anything was sent
    out = capsys.readouterr().out
    assert "Updated job #1" in out and "Next: jsa email 1" in out and "added this post before" not in out

    db.set_application_status(conn, pid, 1, "applied")
    db.mark_outreach_sent(conn, pid, 1)
    cli.cmd_add(args, Settings(database_url=TEST_DB), read=post)
    out = capsys.readouterr().out
    assert "Updated job #1" in out and "You added this post before, on " in out
    assert "Its email went to hr@acme.ae on " in out and "so nothing is sent again. Its follow-up is due from " in out
    assert "Next:" not in out and "--send" not in out
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 1
    assert db.get_application(conn, pid, 1)["status"] == "applied"  # pasting it again does not move it back


def test_add_job_from_pasted_post(conn, monkeypatch, tmp_path, capsys):
    pid = db.save_profile(conn, "Alex", "resume", {})
    monkeypatch.setattr(cli, "_llm", lambda s: PasteLLM())
    args = SimpleNamespace(file=None, url=None, config=str(tmp_path / "missing.yaml"))
    cli.cmd_add(args, Settings(database_url=TEST_DB), read=lambda: "We are hiring! Send CV to hr@acme.ae")
    out = capsys.readouterr().out
    assert "Added job #1: Java Developer at Acme" in out and "hr@acme.ae" in out and "88" in out
    job = db.get_job(conn, 1)
    assert job["url"].startswith("pasted:") and job["posted_at"] is not None
    assert "Send applications to: hr@acme.ae" in job["description"]
    assert db.shortlisted_job_ids(conn, pid, 10) == [1]
