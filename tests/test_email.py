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
        self.researched = []

    def research_company(self, company, title, location, max_searches=4):
        self.researched.append(company)
        return "- Acme launched a payments platform in 2026 (https://acme.ae/news)"

    def recruiter_email(self, resume, job_text, live, notes=None, outreach=None):
        self.calls.append((job_text, live, notes))
        closed = live is not None and "no longer accepting" in live
        return RecruiterEmail(
            still_open=not closed, recruiter_name="Sara" if live else None,
            contact_email="jobs@acme.ae" if live else None,
            company_hook="payments platform launch", subject="Senior Java Engineer | 6 yrs",
            greeting="Hi Sara,", opener="I saw the role <on Bayt>.",
            bullets=["Shipped 15+ REST APIs", "Cut build time 67%", "Raised coverage to 50%"],
            logistics="Based in Ahmedabad, open to relocating.", call_to_action="15-minute call?",
            signature=["Alex Morgan", "+91-0000000000"], follow_up_subject="Re: Senior Java Engineer",
            follow_up_body="Following up...")


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
    out = tmp_path / "emails"
    args = SimpleNamespace(job_ids=[], limit=10, no_browse=False, no_research=False,
                           config=str(tmp_path / "missing.yaml"), out=str(out))
    cli.cmd_email(args, Settings(database_url=TEST_DB))

    md = (tmp_path / "emails.md").read_text()
    html = (tmp_path / "emails.html").read_text()
    assert html.count('class="card"') == 2 and "Looks closed" in html and "Still open" in html
    assert "&lt;on Bayt&gt;" in html  # model text is escaped
    assert "Copy email" in html and "Follow-up" in html and "acme.ae/news" in html
    assert llm.researched == ["Acme", "Acme"] and all(n for _, _, n in llm.calls)
    assert "\u2022 Shipped 15+ REST APIs" in md
    assert md.count("**Subject:**") == 2 and "jobs@acme.ae" in md
    assert "LOOKS CLOSED" in md and "still open" in md
    rows = conn.execute("SELECT outreach_subject, posting_open, contact_email, company_research, "
                        "follow_up_body FROM applications ORDER BY job_id").fetchall()
    assert all(r["company_research"] and r["follow_up_body"] for r in rows)
    assert [r["posting_open"] for r in rows] == [True, False]
    assert all(r["outreach_subject"] for r in rows)
    assert all(live for _, live, _ in llm.calls)
