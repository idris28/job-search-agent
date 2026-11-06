from types import SimpleNamespace

from jobagent import cli, db
from jobagent.browser import PageContent
from jobagent.config import Settings
from jobagent.models import JobPosting, RecruiterEmail

from conftest import TEST_DB


class EmailLLM:
    model = "fake"

    def __init__(self):
        self.calls = []

    def recruiter_email(self, resume, job_text, live):
        self.calls.append((job_text, live))
        closed = live is not None and "no longer accepting" in live
        return RecruiterEmail(still_open=not closed, recruiter_name="Sara" if live else None,
                              contact_email="jobs@acme.ae" if live else None,
                              key_requirements=["Java"], subject="Senior Java Engineer - 6 yrs",
                              body="Hi Sara,\n...")


class FakeLazy:
    def __init__(self, settings):
        pass

    def fetch(self, url, wait_ms=0):
        if url.endswith("/2"):
            return PageContent(url, "", "This job is no longer accepting applications", [])
        return PageContent(url, "", "Senior Java Engineer. Contact Sara at jobs@acme.ae", [])

    def close(self):
        pass


def test_email_shortlisted(conn, monkeypatch, tmp_path):
    pid = db.save_profile(conn, "Alex", "resume text", {})
    for i in (1, 2):
        jid, _ = db.upsert_job(conn, JobPosting(title=f"Java Engineer {i}", company="Acme",
                                                url=f"https://x/{i}", location="Dubai"), None, None)
        db.set_application_status(conn, pid, jid, "shortlisted")
    llm = EmailLLM()
    monkeypatch.setattr(cli, "_llm", lambda s: llm)
    monkeypatch.setattr("jobagent.browser.LazyBrowser", FakeLazy)
    out = tmp_path / "emails.md"
    args = SimpleNamespace(job_ids=[], limit=10, no_browse=False, out=str(out))
    cli.cmd_email(args, Settings(database_url=TEST_DB))

    md = out.read_text()
    assert md.count("**Subject:**") == 2 and "jobs@acme.ae" in md
    assert "LOOKS CLOSED" in md and "still open" in md
    rows = conn.execute("SELECT outreach_subject, posting_open, contact_email FROM applications "
                        "ORDER BY job_id").fetchall()
    assert [r["posting_open"] for r in rows] == [True, False]
    assert all(r["outreach_subject"] for r in rows)
    assert all(live for _, live in llm.calls)
