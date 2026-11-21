"""LinkedIn messages for one job's recruiter: a connection note within LinkedIn's limit and a direct
message. The person sends them; the program never signs in to LinkedIn."""

import json
import sys
from types import SimpleNamespace

import pytest

from jobagent import cli, db
from jobagent.config import Settings
from jobagent.llm import LINKEDIN_INSTRUCTIONS
from jobagent.models import NOTE_LIMIT, LinkedInMessages, fit_note

from conftest import TEST_DB
from test_web import Page, seed

NOTE = ("Hi Priya, I saw the Java Developer role at Acme. I am a Senior Java Engineer with 8 years of Java 17, "
        "Spring Boot and Kafka, and can join in 30 days. I would be glad to connect.")
MESSAGE = ("Hi Priya, I am applying for the Java Developer role at Acme. I am a Senior Java Engineer with 8 years of "
           "Java 17, Spring Boot and Kafka, and I cut a nightly settlement run from 4 hours to 35 minutes. "
           "I can join in 30 days. May I send you my CV?")


def test_a_note_is_cut_to_linkedins_limit_at_a_sentence():
    assert fit_note(NOTE) == NOTE and len(NOTE) <= NOTE_LIMIT
    long = "Hi Priya, I saw the Java Developer role. " + "I build Java services in Spring Boot every day. " * 8
    cut = fit_note(long)
    assert len(cut) <= NOTE_LIMIT and cut.endswith("every day.") and long.startswith(cut)
    words = "word " * 100
    assert fit_note(words) == ("word " * 60).strip() and len(fit_note(words)) <= NOTE_LIMIT  # no sentence end: cut at a word
    assert fit_note("  Hi,   short   note.  ") == "Hi, short note."


class Writer:
    model = "fake"

    def __init__(self, note=NOTE):
        self.note, self.asked = note, []

    def linkedin_messages(self, resume, text, recruiter, prefs):
        self.asked.append((resume, text, recruiter, prefs))
        return LinkedInMessages(note=self.note, message=MESSAGE)


def test_the_command_writes_both_and_keeps_them_with_the_job(conn, monkeypatch, tmp_path, capsys):
    pid, jid = seed(conn)
    db.save_outreach(conn, pid, jid, subject="s", body="b", recruiter_name="Priya Shah", contact_email=None, still_open=True)
    writer = Writer(note=NOTE + " and then a long tail" * 12)  # over the limit, with no later sentence end
    monkeypatch.setattr(cli, "_llm", lambda s: writer)
    config = tmp_path / "config.yaml"
    config.write_text("outreach: {notice_period: 30 days}\n")
    cli.cmd_linkedin(SimpleNamespace(job_id=jid, config=str(config)), Settings(database_url=TEST_DB))
    resume, text, recruiter, prefs = writer.asked[0]
    assert resume == "resume" and text.startswith("Title: Java <Dev>") and recruiter == "Priya Shah" and prefs == {"notice_period": "30 days"}
    kept = db.get_application(conn, pid, jid)
    assert kept["linkedin"] == {"note": NOTE, "message": MESSAGE} and kept["status"] == "shortlisted"  # cut to the limit; nothing moved
    out = capsys.readouterr().out
    assert f"Connection note ({len(NOTE)} of 300 characters):\n{NOTE}" in out and f"Message ({len(MESSAGE.split())} words):" in out
    assert "Send them yourself on LinkedIn" in out
    with pytest.raises(SystemExit, match="valid job id"):
        cli.cmd_linkedin(SimpleNamespace(job_id=999, config="none.yaml"), Settings(database_url=TEST_DB))


def test_what_is_sent_to_the_model_for_linkedin():
    from test_cheaper_scoring import claude, httpx2, message

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=message(LinkedInMessages(note=NOTE, message=MESSAGE).model_dump_json()))

    llm = claude(handler)
    assert llm.linkedin_messages("Eight years of Java.", "Title: Java Developer", "Priya Shah", {"notice_period": "30 days", "email": ""}).note == NOTE
    body = seen[0]
    assert body["system"] == LINKEDIN_INSTRUCTIONS and "At most 280 characters" in body["system"] and "Never guess a name" in body["system"]
    resume, rest = body["messages"][0]["content"]
    assert resume["text"] == "RESUME:\nEight years of Java.\n\n" and resume["cache_control"] == {"type": "ephemeral"}
    assert rest["text"] == 'RECRUITER: Priya Shah\n\nPREFERENCES:\n{"notice_period": "30 days"}\n\nJOB POSTING:\nTitle: Java Developer'
    assert set(body["output_config"]["format"]["schema"]["properties"]) == {"note", "message"}
    llm.linkedin_messages("Eight years of Java.", "Title: Java Developer")
    assert seen[1]["messages"][0]["content"][1]["text"].startswith("RECRUITER: (not named)\n\nPREFERENCES:\n(none)")


def test_the_page_serves_the_messages_and_starts_the_task(conn):
    pid, jid = seed(conn)
    page = Page()
    started = []
    page.server.runner.command = lambda argv: started.append(argv) or [sys.executable, "-c", "print('ok')"]
    try:
        assert page.call(f"/api/job?id={jid}")[1]["application"]["linkedin"] is None
        code, r = page.call("/api/task", {"action": "linkedin", "job_ids": [jid]})
        assert code == 200 and r["task"]["label"] == f"Write LinkedIn messages for #{jid}" and started == [["linkedin", str(jid)]]
        page.wait()
        assert page.call("/api/task", {"action": "linkedin", "job_ids": [jid, jid]})[0] == 400  # one job at a time
        db.save_linkedin(conn, pid, jid, {"note": NOTE, "message": MESSAGE})
        assert page.call(f"/api/job?id={jid}")[1]["application"]["linkedin"]["note"] == NOTE
    finally:
        page.close()
