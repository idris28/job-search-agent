"""A CV written for one job: the resume's own facts, what the posting asks for first. What the
model writes is checked against the resume, and the job's email carries it only when asked."""

import json
import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from jobagent import cli, db, tailor
from jobagent.actions import ActionError, stored_draft_message
from jobagent.config import AgentConfig, OutreachPrefs, Settings
from jobagent.llm import TAILORED_RESUME_INSTRUCTIONS
from jobagent.models import JobPosting, ResumeJob, TailoredResume

from conftest import TEST_DB
from test_web import Page

RESUME = """Alex Morgan
Senior Java Engineer
Pune, India

Skills: Java 17, Spring Boot, Kafka, PostgreSQL, REST APIs, Docker, CI/CD

Experience
Northwind Payments, Pune. Senior Java Engineer. Mar 2019 - Present
- Built payment services in Java 17 and Spring Boot that handle 1,200 requests a second.
- Cut the nightly settlement run from 4 hours to 35 minutes with Kafka.
Lakeside Systems, Pune. Java Developer. Jul 2016 - Feb 2019
- Wrote REST APIs for a billing product used by 40 clients.

Education
B.E. Computer Engineering, Western State University, 2016
"""

WRITTEN = TailoredResume(
    headline="Senior Java Engineer, 8 years",
    summary="Senior Java Engineer with 8 years building payment services in Java 17 and Spring Boot.",
    skills=["Kafka", "Spring Boot", "Java 17", "Kubernetes", "REST API", "kafka"],
    experience=[
        ResumeJob(employer="Northwind Payments", title="Senior Java Engineer", dates="Mar 2019 - Present", location="Pune",
                  bullets=["Cut the nightly settlement run from 4 hours to 35 minutes with Kafka.",
                           "Built payment services that handle 5,000 requests a second.",
                           "Built payment services in Java 17 and Spring Boot that handle 1200 requests a second."]),
        ResumeJob(employer="Lakeside Systems", title="Lead Developer", dates="Jul 2015 - Feb 2019", location="Pune",
                  bullets=["Wrote REST APIs for a billing product used by 40 clients."]),
        ResumeJob(employer="Globex Bank", title="Java Engineer", dates="2014 - 2015", location="", bullets=["Built services."]),
    ],
    education=["B.E. Computer Engineering, Western State University, 2016", "M.Sc. Distributed Systems, Harbour Institute"],
    other=[])


def test_what_the_resume_does_not_say_is_taken_out_and_named():
    cv, notes = tailor.check(WRITTEN, RESUME, years=8.0)
    assert cv["skills"] == ["Kafka", "Spring Boot", "Java 17", "REST API"]  # a plural more or less is the same skill; no skill twice
    assert [j["employer"] for j in cv["experience"]] == ["Northwind Payments", "Lakeside Systems"]
    assert cv["experience"][0]["bullets"] == ["Cut the nightly settlement run from 4 hours to 35 minutes with Kafka.",
                                               "Built payment services in Java 17 and Spring Boot that handle 1200 requests a second."]
    assert cv["education"] == ["B.E. Computer Engineering, Western State University, 2016"] and cv["other"] == []
    assert cv["headline"] == "Senior Java Engineer, 8 years"  # the years worked out at import may be stated
    assert notes == [
        "Left out, because your resume does not name it: Kubernetes",
        'Left out a line at Northwind Payments, because your resume does not give the figure 5000: '
        '"Built payment services that handle 5,000 requests a second."',
        'Check the job title "Lead Developer" at Lakeside Systems: your resume words it differently',
        'Check the dates "Jul 2015 - Feb 2019" at Lakeside Systems: your resume gives other ones',
        'Left out the job at "Globex Bank", because your resume does not name that employer',
        'Left out under Education, because your resume does not say it: "M.Sc. Distributed Systems, Harbour Institute"',
    ]

    exact = TailoredResume(headline="Senior Java Engineer", summary="Builds payment services in Java 17.", skills=["Java 17"],
                           experience=[WRITTEN.experience[0].model_copy(update={"bullets": ["Cut the nightly settlement run from 4 hours to 35 minutes with Kafka."]})],
                           education=[], other=[])
    assert tailor.check(exact, RESUME)[1] == []  # nothing to say about a CV that keeps to the resume
    assert "Check the headline: your resume does not give the figure 8" in tailor.check(WRITTEN, RESUME)[1]  # no years given


def test_the_page_is_one_plain_column_under_the_usual_headings():
    cv, _ = tailor.check(WRITTEN, RESUME, years=8.0)
    cv["summary"] = "Builds <fast> services & APIs."
    page = tailor.page_html("Alex Morgan", ["alex@example.com", "+00 00000 00000"], cv)
    order = [page.index(h) for h in ("<h1>Alex Morgan</h1>", "Senior Java Engineer, 8 years", "alex@example.com | +00 00000 00000",
                                     "<h2>Summary</h2>", "<h2>Skills</h2>", "<h2>Experience</h2>", "<h2>Education</h2>")]
    assert order == sorted(order) and "<h2>Additional information</h2>" not in page  # an empty part has no heading
    assert "Builds &lt;fast&gt; services &amp; APIs." in page and "<img" not in page and "<table" not in page
    assert "<b>Senior Java Engineer</b><span>Mar 2019 - Present</span>" in page and "Kafka, Spring Boot, Java 17, REST API" in page


def test_the_file_has_its_own_folder_and_a_name_a_recruiter_should_see(tmp_path):
    assert tailor.file_for(str(tmp_path), 7, "Alex Morgan") == (tmp_path / "job-7" / "Alex_Morgan_Resume.pdf").resolve()
    assert tailor.file_for(str(tmp_path), 7, "Alex Morgan", "Alex_Morgan_Java.pdf").name == "Alex_Morgan_Java.pdf"
    assert tailor.file_for(str(tmp_path), 7, "Alex Morgan", "../../elsewhere/cv.pdf").parent.name == "job-7"  # never outside its folder
    assert tailor.file_for(str(tmp_path), 7, "", "notes.txt").name == "My_Resume.pdf"


def test_a_real_pdf_is_made(tmp_path):
    cv, _ = tailor.check(WRITTEN, RESUME, years=8.0)
    file = tmp_path / "job-1" / "Alex_Morgan_Resume.pdf"
    try:
        tailor.write_pdf(tailor.page_html("Alex Morgan", ["alex@example.com"], cv), file)
    except RuntimeError as e:
        pytest.skip(str(e))
    assert file.read_bytes().startswith(b"%PDF") and file.stat().st_size > 2000


def job(conn, name="Alex Morgan"):
    pid = db.save_profile(conn, name, RESUME, {"years_experience": 8.0, "current_location": "Pune, India"})
    jid, _ = db.upsert_job(conn, JobPosting(title="Java Engineer", company="Acme", url="https://jobs.example.com/1", location="Dubai",
                                            description="Payment services in Java, Spring Boot and Kafka."), None, None)
    db.set_application_status(conn, pid, jid, "shortlisted")
    return pid, jid


def write_cv(conn, monkeypatch, tmp_path, jid, **outreach):
    """Run the command with a stand-in model and a stand-in for the browser that prints the PDF."""
    asked, pages = [], []
    monkeypatch.setattr(cli, "_llm", lambda s: SimpleNamespace(tailored_resume=lambda resume, text: asked.append((resume, text)) or WRITTEN))
    monkeypatch.setattr(tailor, "write_pdf", lambda page, path: (pages.append(page), path.parent.mkdir(parents=True, exist_ok=True),
                                                                 path.write_bytes(b"%PDF-1.4 stand-in")))
    config = tmp_path / "config.yaml"
    config.write_text(json.dumps({"outreach": {"tailored_folder": str(tmp_path / "resumes"), **outreach}}))
    cli.cmd_cv(SimpleNamespace(job_id=jid, config=str(config)), Settings(database_url=TEST_DB, gmail_address="alex@example.com"))
    return asked, pages


def test_the_cv_command_checks_what_was_written_and_keeps_the_file_unattached(conn, monkeypatch, tmp_path, capsys):
    pid, jid = job(conn)
    asked, pages = write_cv(conn, monkeypatch, tmp_path, jid, phone="+00 00000 00000")
    file = (tmp_path / "resumes" / f"job-{jid}" / "Alex_Morgan_Resume.pdf").resolve()
    assert file.read_bytes().startswith(b"%PDF")
    assert asked[0][0] == RESUME and asked[0][1].startswith("Title: Java Engineer")
    assert "<h1>Alex Morgan</h1>" in pages[0] and "alex@example.com | +00 00000 00000 | Pune, India" in pages[0]
    assert "Kubernetes" not in pages[0] and "Globex Bank" not in pages[0] and "5,000" not in pages[0]

    made = db.get_application(conn, pid, jid)["tailored_cv"]
    assert made["file"] == str(file) and made["attach"] is False and len(made["notes"]) == 6 and made["written_at"]
    assert made["cv"]["skills"] == ["Kafka", "Spring Boot", "Java 17", "REST API"]
    assert db.get_application(conn, pid, jid)["status"] == "shortlisted"  # writing it moves nothing
    out = capsys.readouterr().out
    assert f"CV for #{jid} (Java Engineer): {file}" in out and "! Left out, because your resume does not name it: Kubernetes" in out
    assert "carries your usual CV until you switch on" in out

    with pytest.raises(SystemExit, match="valid job id"):
        cli.cmd_cv(SimpleNamespace(job_id=999, config="none.yaml"), Settings(database_url=TEST_DB))
    monkeypatch.setattr(cli, "_llm", lambda s: SimpleNamespace(tailored_resume=lambda r, t: WRITTEN.model_copy(update={"experience": WRITTEN.experience[2:]})))
    with pytest.raises(SystemExit, match="none of its jobs could be matched to your resume"):
        cli.cmd_cv(SimpleNamespace(job_id=jid, config="none.yaml"), Settings(database_url=TEST_DB))


def test_what_is_sent_to_the_model_for_the_cv():
    from test_cheaper_scoring import claude, httpx2, message

    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=message(WRITTEN.model_dump_json()))

    assert claude(handler).tailored_resume(RESUME, "Title: Java Engineer") == WRITTEN
    body = seen["body"]
    assert body["system"] == TAILORED_RESUME_INSTRUCTIONS and "Use only facts that are in the RESUME" in body["system"]
    resume, posting = body["messages"][0]["content"]
    assert resume["text"] == f"RESUME:\n{RESUME}\n\n" and resume["cache_control"] == {"type": "ephemeral"}
    assert posting["text"] == "JOB POSTING:\nTitle: Java Engineer"
    assert set(body["output_config"]["format"]["schema"]["properties"]) == {"headline", "summary", "skills", "experience", "education", "other"}


def test_an_email_carries_the_cv_written_for_its_job_only_when_asked(conn, monkeypatch, tmp_path):
    pid, jid = job(conn)
    usual = tmp_path / "Usual_CV.pdf"
    usual.write_bytes(b"%PDF usual")
    outreach = OutreachPrefs(resume_path=str(usual))
    settings = Settings(database_url=TEST_DB, gmail_address="alex@example.com", gmail_app_password="x")
    db.save_outreach(conn, pid, jid, subject="Java Engineer", body="Dear Hiring Team,\n\nPlease find my CV attached.", recruiter_name=None,
                     contact_email="careers@acme.example", still_open=True, follow_up_subject="Re: Java Engineer", follow_up_body="Following up.")

    def attached():
        msg, to = stored_draft_message(conn, settings, outreach, pid, jid)
        return [part.get_filename() for part in msg.iter_attachments()]

    assert attached() == ["Usual_CV.pdf"]
    write_cv(conn, monkeypatch, tmp_path, jid)
    assert attached() == ["Usual_CV.pdf"]  # written, but not asked for
    made = db.get_application(conn, pid, jid)["tailored_cv"]
    db.save_tailored_cv(conn, pid, jid, {**made, "attach": True})
    assert attached() == ["Alex_Morgan_Resume.pdf"]
    (tmp_path / "resumes" / f"job-{jid}" / "Alex_Morgan_Resume.pdf").unlink()
    assert attached() == ["Usual_CV.pdf"]  # the file is gone: the usual one goes, not nothing
    usual.unlink()
    with pytest.raises(ActionError, match="CV file for 'default' was not found"):
        attached()


def test_the_page_opens_attaches_and_removes_the_cv(conn, monkeypatch, tmp_path):
    pid, jid = job(conn)
    page = Page(cfg=AgentConfig())
    started = []
    page.server.runner.command = lambda argv: started.append(argv) or [sys.executable, "-c", "print('ok')"]

    def pdf(token):
        request = urllib.request.Request(f"{page.base}/api/cv?id={jid}", headers={"X-Token": token})
        try:
            with urllib.request.urlopen(request) as r:
                return r.status, r.headers["Content-Type"], r.headers["Content-Disposition"], r.read()
        except urllib.error.HTTPError as e:
            return e.code, None, None, e.read()

    try:
        assert page.call(f"/api/job?id={jid}")[1]["application"]["cv"] is None
        assert pdf(page.server.token)[0] == 400 and page.call("/api/cv", {"job_id": jid, "attach": True})[0] == 400  # none written yet
        code, r = page.call("/api/task", {"action": "cv", "job_ids": [jid]})
        assert code == 200 and r["task"]["label"] == f"Write a CV for #{jid}" and started == [["cv", str(jid)]]
        page.wait()

        write_cv(conn, monkeypatch, tmp_path, jid)
        file = tmp_path / "resumes" / f"job-{jid}" / "Alex_Morgan_Resume.pdf"
        shown = page.call(f"/api/job?id={jid}")[1]["application"]
        assert "tailored_cv" not in shown  # the page is told about the file, not sent its whole text
        assert shown["cv"]["name"] == "Alex_Morgan_Resume.pdf" and shown["cv"]["found"] and not shown["cv"]["attach"] and len(shown["cv"]["notes"]) == 6
        assert pdf("wrong")[0] == 403
        assert pdf(page.server.token) == (200, "application/pdf", 'inline; filename="Alex_Morgan_Resume.pdf"', b"%PDF-1.4 stand-in")

        code, r = page.call("/api/cv", {"job_id": jid, "attach": True})
        assert code == 200 and r["message"] == "This job's email now carries the CV written for it."
        assert page.call(f"/api/job?id={jid}")[1]["application"]["cv"]["attach"] is True
        assert page.call("/api/cv", {"job_id": jid, "attach": False})[1]["message"] == "This job's email carries your usual CV."

        code, r = page.call("/api/cv", {"job_id": jid, "remove": True})
        assert code == 200 and not file.exists() and not file.parent.exists() and (tmp_path / "resumes").is_dir()
        assert db.get_application(conn, pid, jid)["tailored_cv"] is None and page.call(f"/api/job?id={jid}")[1]["application"]["cv"] is None
    finally:
        page.close()
