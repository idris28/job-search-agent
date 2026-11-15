"""Ready-to-paste answers for a job site's application form. The program writes them; the person
pastes them into the site's form. Nothing is submitted."""

import json
import sys
from types import SimpleNamespace

import pytest

from jobagent import cli, db
from jobagent.actions import applicant_details
from jobagent.config import AgentConfig, OutreachPrefs, Settings
from jobagent.llm import APPLICATION_ANSWERS_INSTRUCTIONS
from jobagent.models import ANSWER_NAMES, ApplicationAnswers

from conftest import TEST_DB
from test_web import Page, seed

WRITTEN = ApplicationAnswers(
    why_this_role="The posting asks for Java services at scale, which is the work I have done for six years.",
    why_you="I have built and run Spring Boot services in production and can start at once.",
    about_you="I am a backend engineer who builds Java services.",
    key_skills="Java, Spring Boot, REST APIs",
    experience="")


class Writer:
    model = "fake"

    def __init__(self):
        self.asked = []

    def application_answers(self, resume_text, job_text):
        self.asked.append((resume_text, job_text))
        return WRITTEN


def test_the_answers_command_writes_and_keeps_them_with_the_job(conn, monkeypatch, capsys):
    pid, jid = seed(conn)
    writer = Writer()
    monkeypatch.setattr(cli, "_llm", lambda s: writer)
    cli.cmd_answers(SimpleNamespace(job_id=jid), Settings(database_url=TEST_DB))
    out = capsys.readouterr().out
    assert "Why this role:\nThe posting asks for Java services at scale" in out and "Key skills:\nJava, Spring Boot, REST APIs" in out
    assert "Experience:" not in out  # an answer the resume cannot support is left out, not guessed
    assert "Read each one before you paste it into the site's form" in out
    resume, posting = writer.asked[0]
    assert resume == "resume" and posting.startswith("Title: Java <Dev>") and "Build services." in posting
    kept = db.get_application(conn, pid, jid)
    assert kept["answers"] == WRITTEN.model_dump() and kept["status"] == "shortlisted"  # writing them moves nothing

    with pytest.raises(SystemExit, match="valid job id"):
        cli.cmd_answers(SimpleNamespace(job_id=999), Settings(database_url=TEST_DB))


def test_what_is_sent_to_the_model_for_the_answers():
    from test_cheaper_scoring import claude, httpx2, message

    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=message(WRITTEN.model_dump_json()))

    got = claude(handler).application_answers("Six years of Java at a bank.", "Title: Java Engineer")
    assert got == WRITTEN
    body = seen["body"]
    assert body["system"] == APPLICATION_ANSWERS_INSTRUCTIONS and "Never invent an employer, a number, a skill or a year" in body["system"]
    resume, posting = body["messages"][0]["content"]
    assert resume["text"] == "RESUME:\nSix years of Java at a bank.\n\n" and resume["cache_control"] == {"type": "ephemeral"}
    assert posting["text"] == "JOB POSTING:\nTitle: Java Engineer"
    assert set(body["output_config"]["format"]["schema"]["properties"]) == {k for k, _ in ANSWER_NAMES}


def test_your_own_details_are_listed_for_copying_and_only_the_ones_you_gave():
    profile = {"name": "Alex Morgan", "profile": {"current_location": "Pune, India", "years_experience": 8.0}}
    full = OutreachPrefs(email="alex@example.com", phone="+00 00000 00000", linkedin_url="https://linkedin.example/alex",
                         notice_period="30 days", current_salary="18 LPA", expected_salary="24 LPA")
    assert applicant_details(profile, full) == [
        ["Name", "Alex Morgan"], ["Email", "alex@example.com"], ["Phone", "+00 00000 00000"], ["LinkedIn", "https://linkedin.example/alex"],
        ["Where you are", "Pune, India"], ["Total experience", "8 years"], ["When you can join", "30 days"],
        ["Current salary", "18 LPA"], ["Expected salary", "24 LPA"]]
    assert applicant_details({"name": "Alex Morgan", "profile": {}}, OutreachPrefs()) == [["Name", "Alex Morgan"]]
    assert applicant_details(None, OutreachPrefs(phone="  ")) == []


def test_the_page_serves_the_answers_and_starts_the_task(conn):
    pid, jid = seed(conn)
    page = Page(cfg=AgentConfig(outreach=OutreachPrefs(phone="+00 00000 00000", expected_salary="24 LPA")))
    started = []
    page.server.runner.command = lambda argv: started.append(argv) or [sys.executable, "-c", "print('ok')"]
    try:
        detail = page.call(f"/api/job?id={jid}")[1]
        assert detail["application"]["answers"] is None
        assert detail["details"] == [["Name", "Alex"], ["Phone", "+00 00000 00000"], ["Expected salary", "24 LPA"]]

        code, r = page.call("/api/task", {"action": "answers", "job_ids": [jid]})
        assert code == 200 and r["task"]["label"] == f"Write application answers for #{jid}" and started == [["answers", str(jid)]]
        page.wait()
        assert page.call("/api/task", {"action": "answers", "job_ids": [jid, jid]})[0] == 400  # one job at a time

        db.save_answers(conn, pid, jid, WRITTEN.model_dump())
        assert page.call(f"/api/job?id={jid}")[1]["application"]["answers"]["key_skills"] == "Java, Spring Boot, REST APIs"
    finally:
        page.close()
