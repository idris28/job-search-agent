"""Interview preparation for one job: likely questions with points for each answer, questions to
ask, and what to revise first."""

import json
import sys
from types import SimpleNamespace

import pytest

from jobagent import cli, db
from jobagent.config import Settings
from jobagent.llm import INTERVIEW_PREP_INSTRUCTIONS
from jobagent.models import InterviewPrep, PrepQuestion

from conftest import TEST_DB
from test_web import Page, seed

PREP = InterviewPrep(
    technical=[PrepQuestion(question="How does Spring Boot decide which beans to create?", points=["Auto-configuration and conditions", "The payment service at Northwind"]),
               PrepQuestion(question="How would you keep a Kafka consumer from reading a message twice?", points=["Have not used Kafka in production; the closest is RabbitMQ"])],
    experience=[PrepQuestion(question="Tell me about a service you made faster.", points=["Settlement run cut from 4 hours to 35 minutes"])],
    ask_them=["How is the team split between new work and support?"],
    revise=["Kafka: consumer groups, offsets and delivery guarantees"])


def test_the_prep_command_writes_and_keeps_it_with_the_job(conn, monkeypatch, capsys):
    pid, jid = seed(conn)
    asked = []
    monkeypatch.setattr(cli, "_llm", lambda s: SimpleNamespace(interview_prep=lambda resume, text, missing: asked.append((resume, text, missing)) or PREP))
    cli.cmd_prep(SimpleNamespace(job_id=jid), Settings(database_url=TEST_DB))
    resume, text, missing = asked[0]
    assert resume == "resume" and text.startswith("Title: Java <Dev>") and missing == db.get_match(conn, pid, jid)["missing_skills"]
    kept = db.get_application(conn, pid, jid)
    assert kept["interview_prep"] == PREP.model_dump() and kept["status"] == "shortlisted"  # writing it moves nothing
    out = capsys.readouterr().out
    assert out.index("Technical questions:") < out.index("About your work:") < out.index("Questions to ask them:") < out.index("Revise first:")
    assert "- How does Spring Boot decide which beans to create?\n    Auto-configuration and conditions" in out
    assert "- Kafka: consumer groups, offsets and delivery guarantees" in out
    with pytest.raises(SystemExit, match="valid job id"):
        cli.cmd_prep(SimpleNamespace(job_id=999), Settings(database_url=TEST_DB))


def test_what_is_sent_to_the_model_for_the_preparation():
    from test_cheaper_scoring import claude, httpx2, message

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=message(PREP.model_dump_json()))

    llm = claude(handler)
    assert llm.interview_prep("Six years of Java at a bank.", "Title: Java Engineer", ["Kafka", "AWS"]) == PREP
    body = seen[0]
    assert body["system"] == INTERVIEW_PREP_INSTRUCTIONS and "Never invent a project, an employer or a figure" in body["system"]
    resume, posting = body["messages"][0]["content"]
    assert resume["text"] == "RESUME:\nSix years of Java at a bank.\n\n" and resume["cache_control"] == {"type": "ephemeral"}
    assert posting["text"] == "JOB POSTING:\nTitle: Java Engineer\n\nSKILLS THE RESUME WAS JUDGED TO LACK:\nKafka, AWS"
    assert set(body["output_config"]["format"]["schema"]["properties"]) == {"technical", "experience", "ask_them", "revise"}
    llm.interview_prep("Six years of Java at a bank.", "Title: Java Engineer")
    assert seen[1]["messages"][0]["content"][1]["text"] == "JOB POSTING:\nTitle: Java Engineer"  # nothing judged missing: nothing said


def test_the_page_serves_the_preparation_and_starts_the_task(conn):
    pid, jid = seed(conn)
    page = Page()
    started = []
    page.server.runner.command = lambda argv: started.append(argv) or [sys.executable, "-c", "print('ok')"]
    try:
        assert page.call(f"/api/job?id={jid}")[1]["application"]["interview_prep"] is None
        code, r = page.call("/api/task", {"action": "prep", "job_ids": [jid]})
        assert code == 200 and r["task"]["label"] == f"Prepare for the interview for #{jid}" and started == [["prep", str(jid)]]
        page.wait()
        assert page.call("/api/task", {"action": "prep", "job_ids": [jid, jid]})[0] == 400  # one job at a time
        db.save_prep(conn, pid, jid, PREP.model_dump())
        assert page.call(f"/api/job?id={jid}")[1]["application"]["interview_prep"]["revise"] == ["Kafka: consumer groups, offsets and delivery guarantees"]
    finally:
        page.close()
