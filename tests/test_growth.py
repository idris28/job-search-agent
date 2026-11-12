import threading
import urllib.parse
import urllib.request
from types import SimpleNamespace

import httpx

from jobagent import cli, db, notifier, web
from jobagent.actions import ActionError, send_stored_draft
from jobagent.config import AgentConfig, OutreachPrefs, Settings
from jobagent.contacts import verify_contact
from jobagent.models import JobPosting, MatchResult, PastedJob

import pytest

from conftest import TEST_DB


def match(score=80, missing=(), pay=None):
    return MatchResult(score=score, verdict="good", summary="s", matched_skills=["Java"],
                       missing_skills=list(missing), red_flags=[], salary_estimate=pay)


def shortlist(conn, pid, title, company="Acme", url=None, location="Dubai", **kw):
    jid, _ = db.upsert_job(conn, JobPosting(title=title, company=company, url=url or f"https://x/{title}",
                                            location=location, **kw), None, None)
    db.set_application_status(conn, pid, jid, "shortlisted")
    return jid


def site(pages: dict):
    def handler(request):
        body = pages.get(str(request.url))
        return httpx.Response(200, text=body) if body is not None else httpx.Response(404, text="")
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- 1. finding a recruiter address ------------------------------------------------

def test_contact_is_kept_only_when_printed_on_the_companys_own_page():
    http = site({"https://www.acme.ae/careers": "Send your CV to Careers@Acme.ae today",
                 "https://www.acme.ae/contact": "Call us",
                 "https://rocketreach.co/acme": "careers@acme.ae"})
    found = {"email": "careers@acme.ae", "source_url": "https://www.acme.ae/careers", "kind": "careers"}
    assert verify_contact(found, "Acme LLC", http)[0] == found
    assert verify_contact({**found, "source_url": "https://www.acme.ae/contact"}, "Acme", http) \
        == (None, "the address is not on that page")  # a guessed address is rejected
    assert "not the company's own site" in verify_contact(
        {**found, "source_url": "https://rocketreach.co/acme"}, "Acme", http)[1]
    assert "does not look like" in verify_contact(
        {"email": "hr@other.com", "source_url": "https://blog.example.org/x", "kind": "careers"}, "Acme", http)[1]
    assert verify_contact({"email": None}, "Acme", http) == (None, "no address is published")
    assert verify_contact(None, "Acme", http)[0] is None


class ContactLLM:
    model = "fake"

    def __init__(self):
        self.asked = []

    def find_contact(self, company, location):
        self.asked.append(company)
        return {"email": "jobs@acme.ae", "source_url": "https://acme.ae/careers", "kind": "careers"} \
            if company.startswith("Acme") else {"email": "info@beta.io", "source_url": "https://beta.io/", "kind": "general"}


def test_contacts_command_stores_verified_addresses(conn, monkeypatch, capsys):
    pid = db.save_profile(conn, "Alex", "resume", {})
    a1 = shortlist(conn, pid, "Java Developer", "Acme LLC")
    a2 = shortlist(conn, pid, "Backend Engineer", "Acme")
    b = shortlist(conn, pid, "Java Developer", "Beta")
    llm = ContactLLM()
    monkeypatch.setattr(cli, "_llm", lambda s: llm)
    pages = {"https://acme.ae/careers": "jobs@acme.ae", "https://beta.io/": "write to info@beta.io"}
    client = site(pages)
    monkeypatch.setattr(httpx, "Client", lambda **kw: client)
    cli.cmd_contacts(SimpleNamespace(job_ids=[], limit=10), Settings(database_url=TEST_DB))
    assert sorted(llm.asked) == ["Acme LLC", "Beta"]  # one search per company
    apps = {jid: db.get_application(conn, pid, jid) for jid in (a1, a2, b)}
    assert apps[a1]["contact_email"] == apps[a2]["contact_email"] == "jobs@acme.ae"
    assert apps[a1]["contact_source"] == "https://acme.ae/careers" and apps[b]["contact_kind"] == "general"
    assert "Found an address for 3 of 3" in capsys.readouterr().out
    # A later draft that reads no address off the posting keeps the found one.
    db.save_outreach(conn, pid, a1, subject="s", body="b", recruiter_name=None, contact_email=None, still_open=True)
    assert db.get_application(conn, pid, a1)["contact_email"] == "jobs@acme.ae"


# --- 5. salary estimate ------------------------------------------------------------------

def test_salary_estimate_is_stored_and_listed(conn):
    pid = db.save_profile(conn, "Alex", "resume", {})
    jid = shortlist(conn, pid, "Java Developer")
    db.save_match(conn, pid, jid, None, match(pay="18-26 LPA (estimate)"), "m", "h")
    assert db.top_matches(conn, pid)[0]["salary_estimate"] == "18-26 LPA (estimate)"
    assert db.dashboard_rows(conn, pid)[0]["salary_estimate"] == "18-26 LPA (estimate)"
    assert MatchResult(score=1, verdict="poor", summary="s", matched_skills=[], missing_skills=[],
                       red_flags=[]).salary_estimate is None  # optional for the model


# --- 9 and 10. skill gaps and progress ------------------------------------------------------

def test_skill_gaps_counts_the_most_missed_skills(conn, capsys):
    pid = db.save_profile(conn, "Alex", "resume", {})
    for i, missing in enumerate((["Kafka", "Kubernetes"], ["kafka"], ["Kafka ", "AWS"], ["Go"])):
        jid = shortlist(conn, pid, f"Job {i}")
        db.save_match(conn, pid, jid, None, match(40 if i == 3 else 80, missing), "m", f"h{i}")
    total, rows = db.skill_gaps(conn, pid, 30, 50, 10)
    assert total == 3 and (rows[0]["skill"].strip().lower(), rows[0]["jobs"]) == ("kafka", 3)
    assert "Go" not in [r["skill"] for r in rows]  # the low-scoring job is not counted
    cli.cmd_gaps(SimpleNamespace(days=30, min_score=50, limit=10), Settings(database_url=TEST_DB))
    assert "3 jobs  100%" in capsys.readouterr().out


def test_progress_summarises_the_week(conn, capsys):
    pid = db.save_profile(conn, "Alex", "resume", {})
    a, b, c = (shortlist(conn, pid, t) for t in ("Job A", "Job B", "Job C"))
    db.set_application_status(conn, pid, a, "applied")
    db.mark_outreach_sent(conn, pid, a)
    db.set_application_status(conn, pid, a, "interviewing")
    db.set_application_status(conn, pid, b, "skipped")
    p = db.progress(conn, pid, 7)
    assert p["moves"] == {"shortlisted": 3, "applied": 1, "interviewing": 1, "skipped": 1}
    assert (p["mail"]["sent"], p["mail"]["emailed_ever"], p["mail"]["answered_ever"]) == (1, 1, 1)
    assert p["sources"][0]["source"] == "added by hand" and p["sources"][0]["found"] == 3
    cli.cmd_progress(SimpleNamespace(days=7), Settings(database_url=TEST_DB))
    out = capsys.readouterr().out
    assert "Reply rate: 1 of 1" in out and "Still on your shortlist: 1" in out


# --- 12. notifications -----------------------------------------------------------------------

def test_notification_goes_to_telegram_when_set_up():
    sent = []

    def handler(request):
        sent.append((str(request.url), request.read().decode()))
        return httpx.Response(200, json={"ok": True})

    s = Settings(telegram_bot_token="T0KEN", telegram_chat_id="42")
    rows = [{"score": 91, "title": "Java Developer", "company": "Acme", "location": "Dubai", "url": "https://x/1"}]
    how = notifier.notify(s, "1 strong new job match(es)", notifier.strong_match_lines(rows),
                          http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert how == "telegram" and sent[0][0] == "https://api.telegram.org/botT0KEN/sendMessage"
    assert '"chat_id":"42"' in sent[0][1].replace(" ", "") and "Java Developer at Acme" in sent[0][1]
    assert notifier.notify(Settings(), "t", ["x"]) == ""  # nothing set up: silently skipped


def test_only_jobs_at_the_notify_score_are_announced(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(notifier, "notify", lambda settings, title, lines, **kw: calls.append((title, lines)) or "telegram")
    rows = [{"score": 90, "title": "A", "company": "X", "location": None, "url": "u"},
            {"score": 80, "title": "B", "company": "Y", "location": None, "url": "u"}]
    cli._notify_strong(Settings(), AgentConfig(), rows)
    assert calls[0][0] == "1 strong new job match(es)" and len(calls[0][1]) == 1
    assert "by telegram about 1 job(s) scoring 85 or more" in capsys.readouterr().out


# --- 13. duplicates already stored -----------------------------------------------------------

def test_dedupe_merges_copies_and_keeps_scores_and_status(conn, capsys):
    pid = db.save_profile(conn, "Alex", "resume", {})
    first = shortlist(conn, pid, "Senior Java Developer", "Acme", url="https://a/1")
    db.save_match(conn, pid, first, None, match(), "m", "h1")
    # A copy stored before cross-board matching existed: same job, its own row.
    conn.execute("""INSERT INTO jobs (fingerprint, url, title, company, location, description, match_key)
                    SELECT 'older-copy', 'https://b/9', 'Sr. Java Developer', 'Acme LLC', location,
                           'Full text', match_key FROM jobs WHERE id = %s""", (first,))
    copy = conn.execute("SELECT id FROM jobs WHERE fingerprint = 'older-copy'").fetchone()["id"]
    db.set_application_status(conn, pid, copy, "applied")
    other = shortlist(conn, pid, "Data Engineer", "Acme")

    cli.cmd_dedupe(SimpleNamespace(apply=False), Settings(database_url=TEST_DB))
    assert "Nothing was changed" in capsys.readouterr().out
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 3

    cli.cmd_dedupe(SimpleNamespace(apply=True), Settings(database_url=TEST_DB))
    assert "Merged 1 duplicate row(s)" in capsys.readouterr().out
    left = [r["id"] for r in conn.execute("SELECT id FROM jobs ORDER BY id")]
    assert left == [copy, other] if copy < other else sorted([copy, other])  # the applied copy is kept
    kept = db.get_application(conn, pid, copy)
    assert kept["status"] == "applied"
    assert db.existing_match_hash(conn, pid, copy) == "h1"  # the score moved over
    assert db.duplicate_groups(conn) == []


def test_general_inbox_is_not_emailed_without_saying_so(conn, tmp_path):
    pid = db.save_profile(conn, "Alex", "resume", {})
    jid = shortlist(conn, pid, "Java Developer")
    db.save_outreach(conn, pid, jid, subject="s", body="b", recruiter_name=None, contact_email=None, still_open=True)
    db.save_contact(conn, pid, jid, "info@acme.ae", "https://acme.ae/", "general")
    settings = Settings(database_url=TEST_DB, gmail_address="me@gmail.com", gmail_app_password="p")
    with pytest.raises(ActionError, match="general inbox"):
        send_stored_draft(conn, settings, OutreachPrefs(resume_path=str(tmp_path / "cv.pdf")), pid, jid)


def test_parser_has_the_growth_commands():
    p = cli.build_parser()
    for argv in (["contacts"], ["contacts", "5", "--limit", "3"], ["gaps"], ["progress", "--days", "30"],
                 ["dedupe"], ["dedupe", "--apply"], ["notify-test"], ["email", "--general"]):
        assert p.parse_args(argv).fn
