import subprocess
import sys
import time

import pytest

from jobagent import db
from jobagent.config import AgentConfig, MatchingPrefs, SearchPrefs, SourceConfig
from jobagent.models import JobPosting, MatchResult
from jobagent.pipeline import run_agent

from conftest import TEST_DB, FakeBrowser, FakeLLM, mock_http


def gh(*jobs):
    return {"jobs": [{"id": i, "title": t, "absolute_url": f"https://gh/{i}",
                      "location": {"name": loc}, "content": f"desc {t}"}
                     for i, (t, loc) in enumerate(jobs)]}


def make_cfg(**match):
    return AgentConfig(
        search=SearchPrefs(locations=["Dubai", "India"], include_title_keywords=["java", "backend"]),
        matching=MatchingPrefs(shortlist_min_score=75, **match),
        sources=[SourceConfig(kind="greenhouse", name="Acme", board="acme"),
                 SourceConfig(kind="greenhouse", name="Broken", board="broken")],
    )


def test_full_run(conn):
    db.save_profile(conn, "Alex", "resume", {"primary_skills": ["Java"]})
    http = mock_http({"boards-api.greenhouse.io/v1/boards/acme/jobs": gh(
        ("Senior Java Engineer", "Dubai"),
        ("Backend Engineer", "Pune, India"),
        ("Java Engineer", "Berlin"),          # filtered: location
        ("Designer", "Dubai"),                # filtered: title
        ("Backend Engineer II", "Dubai"),     # scoring error
    )})
    llm = FakeLLM(scores={"Senior Java Engineer": 90, "Backend Engineer": 60,
                          "Backend Engineer II": "boom"})
    s = run_agent(conn, make_cfg(), llm, FakeBrowser({}), http=http)

    assert s.status == "partial" and "Broken" in s.source_errors
    assert (s.found, s.new, s.filtered, s.scored, s.shortlisted) == (5, 5, 2, 2, 1)
    pid = db.active_profile(conn)["id"]
    top = db.top_matches(conn, pid, min_score=0)
    assert [r["title"] for r in top] == ["Senior Java Engineer", "Backend Engineer"]
    assert top[0]["application_status"] == "shortlisted"
    run = db.list_runs(conn)[0]
    assert run["status"] == "partial" and run["jobs_scored"] == 2 and run["tokens_used"] == 200

    # Second run: nothing changed -> no re-scoring, nothing new, status not overridden.
    db.set_application_status(conn, pid, top[0]["job_id"], "applied", "sent CV")
    llm2 = FakeLLM(scores={"Backend Engineer II": 80})
    s2 = run_agent(conn, make_cfg(), llm2, FakeBrowser({}), http=http, only_source="Acme")
    assert s2.status == "succeeded" and s2.new == 0
    assert llm2.scored_titles == ["Backend Engineer II"]  # only the one that failed before
    assert s2.skipped_unchanged == 2
    statuses = {r["title"]: r["status"] for r in db.list_applications(conn, pid)}
    assert statuses == {"Senior Java Engineer": "applied", "Backend Engineer II": "shortlisted"}
    events = conn.execute("SELECT to_status FROM application_events ORDER BY id").fetchall()
    assert [e["to_status"] for e in events] == ["shortlisted", "applied", "shortlisted"]


def test_score_cap(conn):
    db.save_profile(conn, "Alex", "resume", {})
    http = mock_http({"boards-api.greenhouse.io/v1/boards/acme/jobs":
                      gh(*[(f"Java Engineer {i}", "Dubai") for i in range(5)])})
    llm = FakeLLM()
    s = run_agent(conn, make_cfg(max_jobs_to_score=2), llm, FakeBrowser({}), http=http,
                  only_source="Acme")
    assert s.scored == 2 and len(llm.scored_titles) == 2


def test_migrate_idempotent(conn):
    assert db.migrate(conn) == []


class StoppedAt(FakeLLM):
    """Scores jobs until it reaches one title, where the search is stopped, as Stop or Ctrl-C does."""

    def __init__(self, title, **kw):
        super().__init__(**kw)
        self.title = title

    def score_job(self, profile, prefs, job):
        if job.title == self.title:
            raise KeyboardInterrupt
        return super().score_job(profile, prefs, job)


def run_locks(conn):
    return conn.execute("SELECT count(*) AS n FROM pg_locks WHERE locktype = 'advisory' AND classid = %s",
                        (db._RUN_LOCK,)).fetchone()["n"]


def test_a_stopped_search_records_where_it_ended_and_keeps_what_it_saved(conn):
    pid = db.save_profile(conn, "Alex", "resume", {"primary_skills": ["Java"]})
    http = mock_http({"boards-api.greenhouse.io/v1/boards/acme/jobs": gh(
        ("Senior Java Engineer", "Dubai"), ("Backend Engineer", "Pune, India"), ("Backend Engineer II", "Dubai"))})
    llm = StoppedAt("Backend Engineer", scores={"Senior Java Engineer": 90})
    with pytest.raises(KeyboardInterrupt):
        run_agent(conn, make_cfg(concurrency=1), llm, FakeBrowser({}), http=http)

    run = db.list_runs(conn)[0]
    assert run["status"] == "partial" and run["error"] == db.STOPPED_EARLY and run["finished_at"]
    assert (run["jobs_found"], run["jobs_scored"], run["tokens_used"]) == (3, 1, 100)
    top = db.top_matches(conn, pid, min_score=0)
    assert [(r["title"], r["application_status"]) for r in top] == [("Senior Java Engineer", "shortlisted")]
    assert run_locks(conn) == 0 and db.close_dead_runs(conn) == []

    # The next search picks up the jobs the stopped one did not get to.
    after = FakeLLM()
    run_agent(conn, make_cfg(), after, FakeBrowser({}), http=http)
    assert sorted(after.scored_titles) == ["Backend Engineer", "Backend Engineer II"]


def gone(conn, run_id):
    """Wait for PostgreSQL to notice that the program holding a search's lock has closed."""
    for _ in range(100):
        if db.close_dead_runs(conn) == [run_id]:
            return True
        time.sleep(0.05)
    return False


def test_a_search_whose_program_is_gone_is_given_an_end(conn):
    pid = db.save_profile(conn, "Alex", "resume", {})
    program = db.connect(TEST_DB)  # stands for the program that runs the search
    try:
        run_id = db.start_run(program, pid, {})
        job_id, _ = db.upsert_job(program, JobPosting(title="Java Engineer", company="Acme", url="https://x/1"), None, run_id)
        db.save_match(program, pid, job_id, run_id, MatchResult(score=80, verdict="good", summary="fit", matched_skills=[],
                                                                missing_skills=[], red_flags=[]), "m", "h")
        assert db.close_dead_runs(conn) == []  # its program is alive, so it really is running
        assert db.list_runs(conn)[0]["status"] == "running"
    finally:
        program.close()  # closed without recording an end, as a crash or a forced stop does

    assert gone(conn, run_id)
    run = db.list_runs(conn)[0]
    assert run["status"] == "partial" and run["error"] == db.CLOSED_EARLY and run["finished_at"]
    assert (run["jobs_found"], run["jobs_new"], run["jobs_scored"]) == (1, 1, 1)

    # Starting the next search tidies up as well, and an ended search is never touched again.
    program = db.connect(TEST_DB)
    second = db.start_run(program, pid, {})
    program.close()
    for _ in range(100):
        if run_locks(conn) == 0:
            break
        time.sleep(0.05)
    third = db.start_run(conn, pid, {})
    status = {r["id"]: r["status"] for r in db.list_runs(conn)}
    assert status == {run_id: "partial", second: "partial", third: "running"}
    db.finish_run(conn, third, status="succeeded", stats={})
    assert db.close_dead_runs(conn) == [] and db.list_runs(conn)[0]["status"] == "succeeded"


STOPPABLE_SEARCH = """
import sys, time
sys.path.insert(0, sys.argv[1])
from jobagent import cli, db
from jobagent.pipeline import run_agent
from conftest import FakeBrowser, FakeLLM, mock_http
from test_pipeline import gh, make_cfg

class Slow(FakeLLM):
    def score_job(self, profile, prefs, job):
        print("scoring", flush=True)
        time.sleep(1)
        return super().score_job(profile, prefs, job)

cli._unwind_on_terminate()
http = mock_http({"boards-api.greenhouse.io/v1/boards/acme/jobs": gh(("Senior Java Engineer", "Dubai"), ("Backend Engineer", "Dubai"))})
try:
    run_agent(db.connect(sys.argv[2]), make_cfg(concurrency=1), Slow(), FakeBrowser({}), http=http)
except KeyboardInterrupt:
    print("stopped", flush=True)
"""


def test_the_stop_signal_reaches_a_running_search_which_records_its_end(conn):
    """The page's Stop button sends a terminate signal to the program running the search."""
    db.save_profile(conn, "Alex", "resume", {})
    tests_dir = str(__import__("pathlib").Path(__file__).parent)
    program = subprocess.Popen([sys.executable, "-c", STOPPABLE_SEARCH, tests_dir, TEST_DB], stdout=subprocess.PIPE, text=True)
    try:
        assert program.stdout.readline().strip() == "scoring"  # the search is under way
        assert db.list_runs(conn)[0]["status"] == "running" and db.close_dead_runs(conn) == []
        program.terminate()
        assert "stopped" in program.stdout.read() and program.wait(10) == 0
    finally:
        program.kill()
    run = db.list_runs(conn)[0]
    assert (run["status"], run["error"], run["jobs_found"]) == ("partial", db.STOPPED_EARLY, 2)
