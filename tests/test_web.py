"""The local web app: the page, its JSON API, and running commands as tasks."""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from jobagent import cli, db, scheduler, web
from jobagent.config import AgentConfig, OutreachPrefs, Settings
from jobagent.models import JobPosting, MatchResult

from conftest import TEST_DB


def match(score, pay=None):
    return MatchResult(score=score, verdict="good", summary="Good fit", matched_skills=["Java"],
                       missing_skills=["Kafka"], red_flags=[], salary_estimate=pay)


class Page:
    """A running server and a small client for it."""

    def __init__(self, settings=None, cfg=None):
        self.server = web.serve(settings or Settings(database_url=TEST_DB), cfg or AgentConfig(), 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def call(self, path, body=None, *, token=None, headers=None, raw=None):
        h = {"X-Token": self.server.token if token is None else token, **(headers or {})}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, data=data, headers=h)) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            text = e.read()
            return e.code, json.loads(text) if text.startswith(b"{") else {}

    def wait(self):
        for _ in range(100):
            task = self.call("/api/task?since=0")[1]["task"]
            if not task["running"]:
                return task
            time.sleep(0.05)
        raise AssertionError("the task did not finish")

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def page(conn):
    p = Page()
    yield p
    p.close()


def seed(conn, title="Java <Dev>", score=88):
    pid = (db.active_profile(conn) or {}).get("id") or db.save_profile(conn, "Alex", "resume", {})
    jid, _ = db.upsert_job(conn, JobPosting(title=title, company="Acme", url=f"https://x/{title}", location="Dubai",
                                            description="Build services.",
                                            posted_at=datetime.now(timezone.utc) - timedelta(hours=3)), None, None)
    db.save_match(conn, pid, jid, None, match(score, "AED 20k (estimate)"), "m", "h")
    db.set_application_status(conn, pid, jid, "shortlisted")
    return pid, jid


def test_page_and_api_need_the_token_and_a_local_host(conn, page):
    html = urllib.request.urlopen(page.base + "/").read().decode()
    assert page.server.token in html and "__TOKEN__" not in html and "Find new jobs" in html
    assert page.call("/api/state", token="wrong")[0] == 403
    assert page.call("/api/status", {"job_id": 1, "status": "applied"}, token="wrong")[0] == 403
    assert page.call("/api/state", headers={"Host": "evil.example"})[0] == 403  # DNS rebinding
    assert page.call("/api/nothing")[0] == 404


def test_state_job_detail_and_quick_changes(conn, page):
    pid, jid = seed(conn)
    db.save_outreach(conn, pid, jid, subject="Java Dev | 6 yrs", body="Dear Team,\n\n**Key skills:** Java [Job Title]",
                     recruiter_name=None, contact_email="hr@acme.ae", still_open=True)
    code, st = page.call("/api/state")
    assert code == 200 and st["setup"] == {"database": "ok", "pending": [], "gmail": False,
                                           "profile": st["setup"]["profile"]}
    assert st["setup"]["profile"]["name"] == "Alex"
    assert st["counts"] == {"found": 1, "found_week": 1, "scored": 1, "shortlisted": 1, "emailed": 0,
                            "applied": 0, "due": 0}
    assert st["countries"] == [{"country": "UAE", "jobs": 1}] and st["search"]["max_age_days"] == 30
    row = st["jobs"][0]
    assert row["title"] == "Java <Dev>" and row["has_draft"] and "outreach_body" not in row

    d = page.call(f"/api/job?id={jid}")[1]
    assert d["match"]["score"] == 88 and d["job"]["description"] == "Build services."
    assert d["application"]["unfilled"] == ["[Job Title]"] and "<b>Key skills:</b>" in d["application"]["body_html"]
    assert [e["to_status"] for e in d["events"]] == ["shortlisted"]
    assert page.call("/api/job?id=99999")[1]["error"] == "That job was not found."
    conn.execute("UPDATE jobs SET company = 'Confidential Company' WHERE id = %s", (jid,))
    db.save_draft_text(conn, pid, jid, "Java Dev", "the role at Confidential Company.")
    assert page.call(f"/api/job?id={jid}")[1]["application"]["unfilled"] == ['company name ("Confidential Company" is not a real name)']
    conn.execute("UPDATE jobs SET company = 'Acme' WHERE id = %s", (jid,))

    assert page.call("/api/draft", {"job_id": jid, "subject": "", "body": "x"})[0] == 400
    assert page.call("/api/draft", {"job_id": jid, "subject": "New subject", "body": "Edited."})[1]["message"] == "Draft saved."
    assert page.call("/api/note", {"job_id": jid, "note": "Call Sara"})[0] == 200
    app = db.get_application(conn, pid, jid)
    assert (app["outreach_subject"], app["outreach_body"], app["notes"]) == ("New subject", "Edited.", "Call Sara")
    assert page.call("/api/contact", {"job_id": jid, "email": "not an address"})[0] == 400
    assert "sara@acme.ae" in page.call("/api/contact", {"job_id": jid, "email": " sara@acme.ae "})[1]["message"]
    app = db.get_application(conn, pid, jid)
    assert (app["contact_email"], app["contact_kind"], app["contact_source"]) == ("sara@acme.ae", "recruiter", None)
    assert page.call("/api/contact", {"job_id": jid, "email": ""})[1]["message"] == "Address removed."
    assert db.get_application(conn, pid, jid)["contact_email"] is None
    page.call("/api/contact", {"job_id": jid, "email": "hr@acme.ae"})
    assert "Gmail is not set up" in page.call("/api/send", {"job_id": jid})[1]["error"]
    assert page.call("/api/hr-contacts", {"text": " "})[0] == 400
    assert page.call("/api/hr-contacts", {"text": "x@y.sa", "country": "Mars"})[0] == 400
    r = page.call("/api/hr-contacts", {"text": "Gulf Tech, hr@gulftech.example\nbad line", "country": "Saudi Arabia"})[1]
    assert r["message"] == "Added 1 general application, skipped 1." and r["skipped"] == [["bad line", "not a valid email address"]]
    general = [j for j in page.call("/api/state")[1]["jobs"] if j["url"].startswith("general:")]
    assert [(j["company"], j["location"], j["contact_email"], j["score"]) for j in general] == [("Gulf Tech", "Saudi Arabia", "hr@gulftech.example", None)]
    conn.execute("DELETE FROM jobs WHERE url LIKE 'general:%'")
    assert page.call("/api/status", {"job_id": jid, "status": "nonsense"})[0] == 400
    assert page.call("/api/status", {"job_id": jid, "status": "applied"})[0] == 200
    assert db.get_application(conn, pid, jid)["status"] == "applied"
    assert page.call("/api/matches?min_score=80")[1]["jobs"][0]["application_status"] == "applied"
    assert page.call("/api/matches?min_score=95")[1]["jobs"] == []
    ins = page.call("/api/insights?days=30")[1]
    assert ins["gaps"] == [{"skill": "Kafka", "jobs": 1}] and ins["progress"]["moves"]["applied"] == 1
    digest = urllib.request.urlopen(f"{page.base}/api/digest?min_score=50&token={page.server.token}").read().decode()
    assert "Java <Dev> at Acme" in digest
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(f"{page.base}/api/digest?token=wrong")


def test_send_from_the_page_and_follow_up(conn, monkeypatch, tmp_path):
    pid, jid = seed(conn)
    db.save_outreach(conn, pid, jid, subject="Java Dev", body="Dear Team", recruiter_name=None,
                     contact_email="hr@acme.ae", still_open=True)
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF fake")
    sent = []
    monkeypatch.setattr("jobagent.mailer.send_messages", lambda a, p, msgs: sent.extend(m["To"] for m in msgs))
    page = Page(Settings(database_url=TEST_DB, gmail_address="me@gmail.com", gmail_app_password="p"),
                AgentConfig(outreach=OutreachPrefs(resume_path=str(cv))))
    try:
        assert page.call("/api/state")[1]["sends"] == {"today": 0, "cap": 10}
        assert "Email sent to hr@acme.ae." in page.call("/api/send", {"job_id": jid})[1]["message"]
        assert "already marked applied" in page.call("/api/send", {"job_id": jid})[1]["error"] and sent == ["hr@acme.ae"]
        conn.execute("UPDATE applications SET outreach_sent_at = now() - interval '9 days'")
        st = page.call("/api/state")[1]
        assert st["due"] == [jid] and st["counts"]["due"] == 1 and st["counts"]["emailed"] == 1
        assert page.call(f"/api/job?id={jid}")[1]["due"] is True
        assert page.call("/api/followup-done", {"job_id": jid})[0] == 200
        assert page.call("/api/state")[1]["due"] == []
    finally:
        page.close()


def test_a_database_that_is_behind_is_reported_and_updated_from_the_page(conn, page):
    conn.execute("DELETE FROM schema_migrations WHERE name = '006_contacts_salary.sql'")
    st = page.call("/api/state")[1]
    assert st["setup"]["database"] == "behind" and st["setup"]["pending"] == ["006_contacts_salary.sql"]
    assert "needs an update" in page.call("/api/matches")[1]["error"]
    seen = []
    page.server.runner.command = lambda argv: seen.append(argv) or [sys.executable, "-c", "print('Applied')"]
    assert page.call("/api/task", {"action": "migrate"})[1]["task"]["label"] == "Update the database"
    assert page.wait()["exit_code"] == 0 and seen == [["migrate"]]


def test_tasks_run_one_at_a_time_show_output_and_can_be_stopped(conn, page):
    runner, seen = page.server.runner, []
    script = "import sys,time\nprint('one', flush=True)\nprint('args', *sys.argv[1:], flush=True)\ntime.sleep(float(sys.argv[1]) if sys.argv[1:2] == ['30'] else 0)"
    runner.command = lambda argv: seen.append(argv) or [sys.executable, "-c", script, *argv]

    assert page.call("/api/task", {"action": "rm -rf"})[1]["error"] == "That action is not known."
    assert page.call("/api/task", {"action": "run", "source": "Not a site"})[0] == 400
    assert page.call("/api/task", {"action": "email", "job_ids": ["1; rm"]})[0] == 400  # ids must be numbers

    task = page.call("/api/task", {"action": "email", "job_ids": [7, 9], "check_live": False})[1]["task"]
    assert task["running"] and task["label"] == "Draft emails"
    done = page.wait()
    assert done["exit_code"] == 0 and done["lines"][0] == "one" and done["last"].startswith("args email 7 9")
    assert seen[-1] == ["email", "7", "9", "--limit", "10", "--no-browse"]
    assert page.call("/api/task?since=1")[1]["task"]["lines"] == done["lines"][1:]

    for body, argv in (({"action": "run", "no_score": True}, ["run", "--no-score"]),
                       ({"action": "send", "job_ids": [3]}, ["send", "3"]),
                       ({"action": "gmail-drafts", "job_ids": [3], "general": True}, ["send", "3", "--gmail-drafts", "--general"]),
                       ({"action": "contacts"}, ["contacts"]), ({"action": "followups"}, ["followups", "--send"]),
                       ({"action": "cover-letter", "job_ids": [5]}, ["cover-letter", "5"]),
                       ({"action": "daily"}, ["daily"]), ({"action": "dedupe"}, ["dedupe", "--apply"])):
        assert page.call("/api/task", body)[0] == 200
        page.wait()
        assert seen[-1] == argv

    # A task carries the name of the button that starts it, so the page says one thing throughout.
    assert page.call("/api/task", {"action": "contacts"})[1]["task"]["label"] == "Look for addresses"
    page.wait()
    added = page.call("/api/task", {"action": "add", "text": "Hiring a Java dev", "url": "https://x/post"})[1]
    assert added["task"]["label"] == "Add a job from a post"
    page.wait()
    assert seen[-1][0] == "add" and seen[-1][2:] == ["--url", "https://x/post"]
    import os
    for _ in range(40):  # the pasted text is removed once the task ends
        if not os.path.exists(seen[-1][1]):
            break
        time.sleep(0.05)
    assert not os.path.exists(seen[-1][1])

    assert page.call("/api/profile", raw=b"resume text", headers={"X-Filename": "cv.exe"})[0] == 400
    assert page.call("/api/profile", raw=b"resume text", headers={"X-Filename": "My%20CV.txt"})[0] == 200
    page.wait()
    assert seen[-1][:2] == ["profile", "import"] and seen[-1][2].endswith(".txt")

    runner.command = lambda argv: [sys.executable, "-c", script, "30"]
    page.call("/api/task", {"action": "run"})
    assert "still running" in page.call("/api/task", {"action": "daily"})[1]["error"]
    assert page.call("/api/task/stop", {})[1] == {"stopped": True}
    stopped = page.wait()
    assert stopped["stopped"] and stopped["exit_code"] != 0

    # Stop always stops: a task that ignores the request is ended after a short wait.
    stubborn = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('up', flush=True)\ntime.sleep(30)"
    runner.command, runner.grace_seconds = lambda argv: [sys.executable, "-c", stubborn], 0.2
    page.call("/api/task", {"action": "run"})
    for _ in range(100):
        if page.call("/api/task?since=0")[1]["task"]["lines"]:
            break
        time.sleep(0.05)
    assert page.call("/api/task/stop", {})[1] == {"stopped": True}
    assert page.wait()["exit_code"] == -9


def test_activity_does_not_list_a_cut_off_search_as_running(conn, page):
    pid = db.save_profile(conn, "Alex", "resume", {})
    program = db.connect(TEST_DB)  # the program running a search
    run_id = db.start_run(program, pid, {})
    runs = lambda: page.call("/api/insights?days=30")[1]["runs"]  # noqa: E731
    assert [(r["id"], r["status"]) for r in runs()] == [(run_id, "running")]
    program.close()  # cut off before it could record an end
    for _ in range(100):
        if runs()[0]["status"] != "running":
            break
        time.sleep(0.05)
    assert (runs()[0]["status"], runs()[0]["error"]) == ("partial", db.CLOSED_EARLY)


def test_settings_schedule_and_template(conn, page, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(scheduler, "info", lambda: {"installed": False})
    monkeypatch.setattr(scheduler, "install", lambda folder, h, m: calls.append((h, m)))
    monkeypatch.setattr(scheduler, "remove", lambda: calls.append("remove") or True)
    s = page.call("/api/settings")[1]
    assert s["schedule"] == {"installed": False} and s["gmail"]["ready"] is False and s["template"]["found"] is False
    assert "gmail_app_password" not in json.dumps(s) and s["limits"]["sends_per_day"] == 10

    assert "project folder" in page.call("/api/schedule", {"action": "install", "time": "07:30"})[1]["error"]
    (tmp_path / ".env").write_text("")
    (tmp_path / "config.yaml").write_text("")
    assert page.call("/api/schedule", {"action": "install", "time": "25:00"})[0] == 400
    assert "07:30" in page.call("/api/schedule", {"action": "install", "time": "07:30"})[1]["message"]
    page.call("/api/schedule", {"action": "remove"})
    assert calls == [(7, 30), "remove"]

    assert page.call("/api/template", {"text": "  "})[0] == 400
    assert page.call("/api/template", {"text": "Dear [Company Name],"})[0] == 200
    assert (tmp_path / "email_template.txt").read_text() == "Dear [Company Name],\n"
    assert page.call("/api/settings")[1]["template"]["text"] == "Dear [Company Name],\n"
    assert page.call("/api/settings")[1]["cover_template"] == {"file": "cover_letter_template.txt", "found": False, "text": ""}
    assert "cover letters" in page.call("/api/template", {"kind": "cover", "text": "Dear Hiring Manager,"})[1]["message"]
    assert (tmp_path / "cover_letter_template.txt").read_text() == "Dear Hiring Manager,\n"
    assert (tmp_path / "email_template.txt").read_text() == "Dear [Company Name],\n"  # the email one is untouched


def test_send_command_sends_saved_drafts_without_redrafting(conn, monkeypatch, tmp_path, capsys):
    pid, a = seed(conn, "Java A")
    _, b = seed(conn, "Java B")
    for jid, mail in ((a, "hr@acme.ae"), (b, None)):
        db.save_outreach(conn, pid, jid, subject="My edited subject", body="My edited text", recruiter_name=None,
                         contact_email=mail, still_open=True)
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF fake")
    (tmp_path / "config.yaml").write_text(f"outreach: {{resume_path: {cv}, send_pause_seconds: 0}}")
    sent, drafts = [], []
    monkeypatch.setattr("jobagent.mailer.send_messages", lambda ad, p, msgs: sent.extend((m["To"], m["Subject"]) for m in msgs))
    monkeypatch.setattr("jobagent.mailer.save_drafts", lambda ad, p, msgs: drafts.extend(m["To"] for m in msgs) or len(msgs))
    settings = Settings(database_url=TEST_DB, gmail_address="me@gmail.com", gmail_app_password="p")
    args = cli.build_parser().parse_args(["send", "--config", str(tmp_path / "config.yaml"), "--gmail-drafts"])
    cli.cmd_send(args, settings)
    assert drafts == ["hr@acme.ae"] and sent == []
    assert db.get_application(conn, pid, a)["status"] == "shortlisted"  # a Gmail draft is not an application
    args = cli.build_parser().parse_args(["send", "--config", str(tmp_path / "config.yaml")])
    cli.cmd_send(args, settings)
    out = capsys.readouterr().out
    assert sent == [("hr@acme.ae", "My edited subject")] and "No email address is known" in out and "Sent 1 email(s)." in out
    assert db.get_application(conn, pid, a)["status"] == "applied"
