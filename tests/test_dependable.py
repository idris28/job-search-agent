import plistlib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobagent import cli, db, scheduler, web
from jobagent.config import AgentConfig, ConfigError, MatchingPrefs, OutreachPrefs, ResumeVariant, SearchPrefs, Settings, SourceConfig
from jobagent.models import JobPosting, MatchResult, company_key, title_key
from jobagent.pipeline import run_agent

from conftest import TEST_DB, FakeBrowser, FakeLLM, mock_http
from test_email import EmailLLM, FakeLazy


# --- 9. the same job on two boards ----------------------------------------------

def test_title_and_company_keys():
    assert title_key("Sr. Java Developer - Dubai", "Dubai, UAE") == title_key("Senior Java Developer")
    assert title_key("Java Backend Developer") == title_key("Backend Java Developer (Urgent Hiring)")
    assert title_key("Java Developer") != title_key("Java Developer II")
    assert title_key("Java Developer") != title_key("Senior Java Developer")
    assert company_key("Acme Technologies Pvt. Ltd.") == company_key("Acme Technologies")
    assert company_key("Acme") != company_key("Acme Labs")


def test_same_job_from_another_board_is_stored_once(conn):
    a, new_a = db.upsert_job(conn, JobPosting(title="Senior Java Developer", company="Acme Pvt Ltd",
                                              url="https://naukri/1", location="Dubai"), None, None)
    b, new_b = db.upsert_job(conn, JobPosting(title="Sr. Java Developer - Dubai", company="Acme",
                                              url="https://bayt/9", location="Dubai, UAE",
                                              description="Full text from the second board"), None, None)
    assert (new_a, new_b) == (True, False) and a == b
    assert db.get_job(conn, a)["description"] == "Full text from the second board"  # gap filled in
    other, new_other = db.upsert_job(conn, JobPosting(title="Senior Java Developer", company="Acme",
                                                      url="https://x/2", location="Pune, India"), None, None)
    assert new_other and other != a  # same title in another country is a different job
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 2


def test_merged_listing_is_not_scored_twice(conn):
    db.save_profile(conn, "Alex", "resume", {})
    gh = lambda title: {"jobs": [{"id": 1, "title": title, "absolute_url": "https://gh/1",
                                  "location": {"name": "Dubai"}, "content": title}]}
    cfg = AgentConfig(sources=[SourceConfig(kind="greenhouse", name="A", board="a"),
                               SourceConfig(kind="greenhouse", name="B", board="b")])
    http = mock_http({"boards-api.greenhouse.io/v1/boards/a/jobs": gh("Senior Java Developer"),
                      "boards-api.greenhouse.io/v1/boards/b/jobs": gh("Sr. Java Developer")})
    for scfg in cfg.sources:
        scfg.company = "Acme"
    llm = FakeLLM()
    s = run_agent(conn, cfg, llm, FakeBrowser({}), http=http)
    assert (s.found, s.new, s.scored) == (2, 1, 1) and len(llm.scored_titles) == 1
    s2 = run_agent(conn, cfg, FakeLLM(), FakeBrowser({}), http=http)
    assert s2.scored == 0 and s2.skipped_unchanged == 2  # neither wording is scored again


# --- 7. spending limits ------------------------------------------------------------

def many_jobs(n):
    return mock_http({"boards-api.greenhouse.io/v1/boards/acme/jobs": {"jobs": [
        {"id": i, "title": f"Java Engineer {i}", "absolute_url": f"https://gh/{i}",
         "location": {"name": "Dubai"}, "content": "x"} for i in range(n)]}})


def test_run_stops_scoring_at_the_token_limit(conn):
    db.save_profile(conn, "Alex", "resume", {})
    cfg = AgentConfig(matching=MatchingPrefs(max_tokens_per_run=150, concurrency=1),
                      sources=[SourceConfig(kind="greenhouse", name="Acme", board="acme")])
    s = run_agent(conn, cfg, FakeLLM(), FakeBrowser({}), http=many_jobs(8))  # 100 tokens per score
    assert "token limit reached" in s.stopped and s.status == "partial"
    assert s.scored == 2 and s.tokens == 200  # one batch over the limit, then it stops
    assert db.list_runs(conn)[0]["status"] == "partial"


def test_run_stops_collecting_at_the_browser_time_limit(conn):
    db.save_profile(conn, "Alex", "resume", {})
    browser = FakeBrowser({})
    browser.minutes_used = 12.0
    cfg = AgentConfig(matching=MatchingPrefs(max_browser_minutes_per_run=10),
                      sources=[SourceConfig(kind="greenhouse", name="Acme", board="acme")])
    s = run_agent(conn, cfg, FakeLLM(), browser, http=many_jobs(3))
    assert "browser time limit reached" in s.stopped and s.found == 0


# --- 6 and 8. sending, the daily cap and follow-ups ---------------------------------

def send_setup(conn, monkeypatch, tmp_path, jobs=2, extra=""):
    pid = db.save_profile(conn, "Alex", "resume text", {})
    for i in range(1, jobs + 1):
        jid, _ = db.upsert_job(conn, JobPosting(title=f"Java Engineer {i}", company=f"Acme{i}",
                                                url=f"https://x/{i}0", location="Dubai"), None, None)
        db.set_application_status(conn, pid, jid, "shortlisted")
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF fake")
    (tmp_path / "config.yaml").write_text(
        f"outreach: {{research: false, review: false, resume_path: {cv}, send_pause_seconds: 0{extra}}}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_llm", lambda s: EmailLLM())
    monkeypatch.setattr("jobagent.browser.LazyBrowser", FakeLazy)
    sent = []
    monkeypatch.setattr("jobagent.mailer.send_messages",
                        lambda addr, pw, msgs: sent.extend((m["To"], m["Subject"]) for m in msgs) or len(msgs))
    settings = Settings(database_url=TEST_DB, gmail_address="me@gmail.com", gmail_app_password="p")
    args = SimpleNamespace(job_ids=[], limit=10, no_browse=False, no_research=False, no_review=False,
                           gmail_drafts=False, send=True, general=False, config=str(tmp_path / "config.yaml"),
                           out=str(tmp_path / "emails"))
    return pid, sent, settings, args


def test_send_stops_at_the_daily_cap(conn, monkeypatch, tmp_path, capsys):
    pid, sent, settings, args = send_setup(conn, monkeypatch, tmp_path, jobs=3, extra=", max_sends_per_day: 2")
    cli.cmd_email(args, settings)
    assert len(sent) == 2 and db.sends_today(conn, pid) == 2
    assert "daily limit of 2 emails reached" in capsys.readouterr().out
    cli.cmd_email(args, settings)  # later the same day: nothing more goes out
    assert len(sent) == 2


def test_follow_up_becomes_due_and_is_sent_once(conn, monkeypatch, tmp_path, capsys):
    pid, sent, settings, args = send_setup(conn, monkeypatch, tmp_path, jobs=1)
    cli.cmd_email(args, settings)
    assert len(sent) == 1 and db.followups_due(conn, pid, 6) == []  # sent today: not due yet
    conn.execute("UPDATE applications SET outreach_sent_at = now() - interval '7 days'")
    due = db.followups_due(conn, pid, 6)
    assert [r["contact_email"] for r in due] == ["jobs@acme.ae"]

    fargs = SimpleNamespace(send=False, done=None, config=str(tmp_path / "config.yaml"))
    cli.cmd_followups(fargs, settings)
    assert "1 follow-up(s) due today" in capsys.readouterr().out and len(sent) == 1
    fargs.send = True
    cli.cmd_followups(fargs, settings)
    assert sent[-1] == ("jobs@acme.ae", "Re: Senior Java Engineer") and len(sent) == 2
    assert db.followups_due(conn, pid, 6) == []  # never sent twice
    cli.cmd_followups(fargs, settings)
    assert len(sent) == 2 and "No follow-ups due" in capsys.readouterr().out


# --- 14. resume variants -------------------------------------------------------------

def test_resume_variant_is_chosen_by_keyword():
    prefs = OutreachPrefs(resume_path="java.pdf", resume_variants=[
        ResumeVariant(name="Java + AI", path="ai.pdf", keywords=["llm", "generative ai", "ai/ml"])])
    assert prefs.resume_for("Java Developer. Spring Boot, Kafka.") == ("default", "java.pdf")
    assert prefs.resume_for("Backend Engineer, Generative AI platform") == ("Java + AI", "ai.pdf")
    assert prefs.resume_for("Experience with LLM APIs and RAG") == ("Java + AI", "ai.pdf")
    assert prefs.resume_for("We maintain email infrastructure") == ("default", "java.pdf")  # not "ai"


# --- 10. daily schedule ---------------------------------------------------------------

def test_schedule_definition_runs_jsa_daily_from_the_project(tmp_path):
    d = plistlib.loads(scheduler.plist_bytes(tmp_path, 8, 30, python="/venv/bin/python"))
    assert d["ProgramArguments"] == ["/venv/bin/python", "-m", "jobagent.cli", "daily"]
    assert d["WorkingDirectory"] == str(tmp_path)
    assert d["StartCalendarInterval"] == {"Hour": 8, "Minute": 30}
    assert d["StandardOutPath"].endswith("digests/daily.log")


def test_parser_has_the_new_commands():
    p = cli.build_parser()
    for argv in (["followups"], ["followups", "--send"], ["daily"], ["schedule", "install", "--time", "07:30"],
                 ["schedule", "status"], ["web", "--no-open"]):
        assert p.parse_args(argv).fn


# --- the database must be up to date ---------------------------------------------------

def test_commands_refuse_an_out_of_date_database(conn):
    assert db.pending_migrations(conn) == []
    conn.execute("DELETE FROM schema_migrations WHERE name = '006_contacts_salary.sql'")
    assert db.pending_migrations(conn) == ["006_contacts_salary.sql"]
    with pytest.raises(ConfigError, match="jsa migrate"):
        cli._conn(Settings(database_url=TEST_DB))
