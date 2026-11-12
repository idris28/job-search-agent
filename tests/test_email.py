from types import SimpleNamespace

from jobagent import cli, db
from jobagent.browser import PageContent
from jobagent.config import OutreachPrefs, Settings
from jobagent.models import (JobPosting, RecruiterEmail, RecruiterReview, TemplateEmail,
                             unfilled_placeholders)
from jobagent.report import email_body_html, emails_html

from conftest import TEST_DB


class EmailLLM:
    model = "fake"

    def __init__(self):
        self.calls = []
        self.researched = []
        self.reviews = []
        self.revised = []

    def research_email_content(self, roles, country, max_searches=4):
        self.researched.append(country)
        return "- UAE recruiters expect visa status and notice period (https://example.ae/tips)"

    def review_email(self, email, job_text, resume, country):
        # First draft scores 6, the revision scores 9.
        score = 9 if email.subject.endswith("v2") else 6
        self.reviews.append(score)
        return RecruiterReview(first_impression="Clear Java fit", score=score, would_reply=score >= 8,
                               strengths=["quantified"], issues=[] if score >= 8 else ["no notice period"],
                               rewrite_instructions=[] if score >= 8 else ["add notice period"])

    def recruiter_email(self, resume, job_text, live, notes=None, outreach=None,
                        previous=None, review=None, template=None):
        assert template is None  # no email_template.txt where this test runs
        self.calls.append((job_text, live, notes))
        if review is not None:
            self.revised.append(review.issues)
        closed = live is not None and "no longer accepting" in live
        return RecruiterEmail(
            still_open=not closed, recruiter_name="Sara" if live else None,
            contact_email="jobs@acme.ae" if live else None,
            company_hook="payments platform", subject="Senior Java Engineer | 6 yrs"
            + (" v2" if review is not None else ""),
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
    monkeypatch.chdir(tmp_path)  # away from the repo's email_template.txt: built-in format
    out = tmp_path / "emails"
    args = SimpleNamespace(job_ids=[], limit=10, no_browse=False, no_research=False, no_review=False,
                           gmail_drafts=False, send=False, general=False, config=str(tmp_path / "missing.yaml"), out=str(out))
    cli.cmd_email(args, Settings(database_url=TEST_DB))

    md = (tmp_path / "emails.md").read_text()
    html = (tmp_path / "emails.html").read_text()
    assert html.count('class="job"') == 2 and "Looks closed" in html and "Still open" in html
    assert "&lt;on Bayt&gt;" in html  # model text is escaped
    assert "Copy email" in html and "Follow-up" in html and "example.ae/tips" in html
    assert "Recruiter review 9/10" in html
    # Guidance researched once per country, not per job; each draft reviewed then revised once.
    assert llm.researched == ["UAE"] and all(n for _, _, n in llm.calls)
    assert llm.reviews == [6, 9, 6, 9] and llm.revised == [["no notice period"]] * 2
    assert "\u2022 Shipped 15+ REST APIs" in md
    assert md.count("**Subject:**") == 2 and "jobs@acme.ae" in md
    assert "LOOKS CLOSED" in md and "still open" in md
    rows = conn.execute("SELECT outreach_subject, posting_open, contact_email, company_research, "
                        "follow_up_body, review_score FROM applications ORDER BY job_id").fetchall()
    assert all(r["company_research"] and r["follow_up_body"] for r in rows)
    assert [r["review_score"] for r in rows] == [9, 9]
    assert [r["posting_open"] for r in rows] == [True, False]
    assert all(r["outreach_subject"] for r in rows)
    assert all(live for _, live, _ in llm.calls)


# --- the user's own template ----------------------------------------------------

TEMPLATE = """Dear Hiring Team,

My name is [Your Name], and I'm applying for the [Job Title] position at [Company Name].

Best regards,
[Your Full Name]
[LinkedIn Profile]"""


def filled(body):
    return TemplateEmail(still_open=True, recruiter_name=None, contact_email=None,
                         subject="Java Engineer | 6 yrs", body=body,
                         follow_up_subject="Re: Java Engineer | 6 yrs",
                         follow_up_body="Dear Hiring Team,\n\nFollowing up on my application.")


class TemplateLLM:
    """Has no research or review methods: with a template, jsa email must not call them."""

    model = "fake"

    def __init__(self):
        self.templates = []

    def recruiter_email(self, resume, job_text, live, notes=None, outreach=None,
                        previous=None, review=None, template=None):
        assert notes is None and previous is None and review is None
        self.templates.append(template)
        # The LinkedIn line is left unfilled on purpose.
        return filled("Dear Hiring Team,\n\nMy name is Alex Morgan, and I'm applying for the "
                      "Java Engineer position at Acme <UAE>.\n\nBest regards,\nAlex Morgan\n"
                      "[LinkedIn Profile]")


def test_email_fills_the_users_template(conn, monkeypatch, tmp_path):
    pid = db.save_profile(conn, "Alex", "resume text", {})
    jid, _ = db.upsert_job(conn, JobPosting(title="Java Engineer", company="Acme <UAE>",
                                            url="https://x/1", location="Dubai"), None, None)
    db.set_application_status(conn, pid, jid, "shortlisted")
    (tmp_path / "email_template.txt").write_text(TEMPLATE)
    monkeypatch.chdir(tmp_path)  # the template is picked up from where jsa runs
    llm = TemplateLLM()
    monkeypatch.setattr(cli, "_llm", lambda s: llm)
    args = SimpleNamespace(job_ids=[], limit=10, no_browse=True, no_research=False, no_review=False,
                           gmail_drafts=False, send=False, general=False,
                           config=str(tmp_path / "missing.yaml"), out=str(tmp_path / "emails"))
    cli.cmd_email(args, Settings(database_url=TEST_DB))

    assert llm.templates == [TEMPLATE]  # one draft call for the job, nothing else
    md = (tmp_path / "emails.md").read_text()
    html = (tmp_path / "emails.html").read_text()
    assert "applying for the Java Engineer position at Acme <UAE>." in md
    assert "position at Acme &lt;UAE&gt;.</p>" in html
    assert "<p>Best regards,<br>Alex Morgan<br>[LinkedIn Profile]</p>" in html
    assert "Fill in before sending: [LinkedIn Profile]" in html
    assert "**Fill in before sending:** [LinkedIn Profile]" in md
    assert "<p>Dear Hiring Team,</p><p>Following up on my application.</p>" in html
    saved = conn.execute("SELECT outreach_body FROM applications").fetchone()["outreach_body"]
    assert saved.startswith("Dear Hiring Team,") and saved.endswith("[LinkedIn Profile]")


def test_template_email_preview_keeps_paragraphs_and_line_breaks():
    e = filled("Dear Hiring Team,\n\nI build <Java> services.\n\n\nBest regards,\nAlex Morgan\n+91 1\n")
    assert email_body_html(e) == ("<p>Dear Hiring Team,</p><p>I build &lt;Java&gt; services.</p>"
                                  "<p>Best regards,<br>Alex Morgan<br>+91 1</p>")
    assert e.plain_text().endswith("+91 1")
    linked = filled("Best regards,\nAlex\n[LinkedIn](https://www.linkedin.com/in/x-1/)")
    assert email_body_html(linked) == ('<p>Best regards,<br>Alex<br>'
                                       '<a href="https://www.linkedin.com/in/x-1/">LinkedIn</a></p>')
    assert unfilled_placeholders(linked.body) == []  # a link is not an unfilled blank
    bold = filled("**Key skills:** Java, Spring Boot\n\n**Relevant experience:**\n- Shipped 15+ APIs")
    assert email_body_html(bold) == ("<p><b>Key skills:</b> Java, Spring Boot</p>"
                                     "<p><b>Relevant experience:</b><br>- Shipped 15+ APIs</p>")


def test_preview_page_leaves_out_an_unnamed_company_and_a_link_that_is_not_a_web_address():
    e = filled("Dear Hiring Team,\n\nI build Java services.")

    def item(**job):
        return {"job": {"id": 7, "title": "Java Developer", "location": "Doha, Qatar", **job}, "email": e,
                "status": "open", "research": None, "review": None, "unfilled": []}
    named = emails_html([item(company="Careem", url="https://example.com/j/7")], title="Emails")
    assert "<h2>Java Developer</h2>" in named and "<span>Careem</span>" in named
    assert '<a href="https://example.com/j/7">View posting</a>' in named
    # "Copy email" copies this element's own HTML, so it must hold the email and nothing else.
    assert '<div class="mail" id="b0"><p>Dear Hiring Team,</p><p>I build Java services.</p></div>' in named
    unnamed = emails_html([item(company="Unknown", url="general:hr@x.example")], title="Emails")
    assert "Unknown" not in unnamed and "View posting" not in unnamed and "general:" not in unnamed


def test_unfilled_placeholders():
    assert unfilled_placeholders("Dear [Company Name], the [Job Title] role at [Company Name]") \
        == ["[Company Name]", "[Job Title]"]
    described = "[4 or 5 areas of my experience that matter most for this job]"
    assert unfilled_placeholders(f"My experience includes {described}.") == [described]
    assert unfilled_placeholders("6+ years (Java) at IBM, see note [1] and []") == []


def test_template_file_setting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert OutreachPrefs().template() is None  # no file: built-in format
    assert OutreachPrefs().cover_letter_template() is None
    (tmp_path / "cover_letter_template.txt").write_text("Dear Hiring Manager,\n[Job Title]\n")
    assert OutreachPrefs().cover_letter_template() == "Dear Hiring Manager,\n[Job Title]"
    assert OutreachPrefs(cover_letter_template_file="").cover_letter_template() is None
    (tmp_path / "email_template.txt").write_text("Dear [Company Name],\n\n")
    assert OutreachPrefs().template() == "Dear [Company Name],"
    assert OutreachPrefs(template_file="").template() is None  # switched off in config.yaml
    assert OutreachPrefs(template_file="other.txt").template() is None


def test_send_emails_only_ready_drafts_and_never_twice(conn, monkeypatch, tmp_path):
    pid = db.save_profile(conn, "Alex", "resume text", {})
    for i in (1, 2):  # job 2's live page says it is closed
        jid, _ = db.upsert_job(conn, JobPosting(title=f"Java Engineer {i}", company="Acme",
                                                url=f"https://x/{i}", location="Dubai"), None, None)
        db.set_application_status(conn, pid, jid, "shortlisted")
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF fake")
    (tmp_path / "config.yaml").write_text(f"outreach: {{research: false, review: false, resume_path: {cv}}}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_llm", lambda s: EmailLLM())
    monkeypatch.setattr("jobagent.browser.LazyBrowser", FakeLazy)
    sent = []
    monkeypatch.setattr("jobagent.mailer.send_messages",
                        lambda addr, pw, msgs: sent.extend(m["To"] for m in msgs) or len(msgs))
    settings = Settings(database_url=TEST_DB, gmail_address="me@gmail.com", gmail_app_password="p")
    args = SimpleNamespace(job_ids=[], limit=10, no_browse=False, no_research=False, no_review=False,
                           gmail_drafts=False, send=True, general=False, config=str(tmp_path / "config.yaml"),
                           out=str(tmp_path / "emails"))
    cli.cmd_email(args, settings)
    assert sent == ["jobs@acme.ae"]  # the open job only
    statuses = [r["status"] for r in conn.execute("SELECT status FROM applications ORDER BY job_id")]
    assert statuses == ["applied", "shortlisted"]

    args.job_ids = [1, 2]
    cli.cmd_email(args, settings)  # a second run must not email job 1 again
    assert sent == ["jobs@acme.ae"]


def test_cover_letter_command_uses_the_template_and_flags_blanks(conn, monkeypatch, tmp_path, capsys):
    pid = db.save_profile(conn, "Alex", "resume text", {})
    jid, _ = db.upsert_job(conn, JobPosting(title="Java Engineer", company="Acme", url="https://x/1",
                                            location="Dubai"), None, None)
    (tmp_path / "cover_letter_template.txt").write_text("Dear Hiring Manager,\n[Job Title] at [Company Name]")
    monkeypatch.chdir(tmp_path)
    seen = []

    class CoverLLM:
        model = "fake"

        def cover_letter(self, resume, job_text, template=None, outreach=None):
            seen.append(template)
            return "Dear Hiring Manager,\nJava Engineer at [Company Name]"  # one blank left unfilled

    monkeypatch.setattr(cli, "_llm", lambda s: CoverLLM())
    args = cli.build_parser().parse_args(["cover-letter", str(jid), "--config", str(tmp_path / "missing.yaml")])
    cli.cmd_cover_letter(args, Settings(database_url=TEST_DB))
    out = capsys.readouterr().out
    assert seen == ["Dear Hiring Manager,\n[Job Title] at [Company Name]"]
    assert "your template (cover_letter_template.txt)" in out and "Fill in before using: [Company Name]" in out
    assert db.get_application(conn, pid, jid)["cover_letter"].startswith("Dear Hiring Manager,")


def test_a_company_the_posting_does_not_name_is_left_out_and_flagged(conn, monkeypatch, tmp_path):
    from jobagent.models import NOT_NAMED, company_named, names_missing_company

    assert [company_named(c) for c in ("Unknown", "Confidential Company", "", "N/A", "Not disclosed")] == [False] * 5
    assert all(company_named(c) for c in ("Acme", "ECS ME LLC", "The Emirates Group", "Company 2 Technologies"))
    assert names_missing_company("the Java Developer position at Unknown.", "Unknown")
    assert not names_missing_company("the Java Developer position.", "Unknown")
    assert not names_missing_company("an unknown-size team at Acme", "Acme")

    pid = db.save_profile(conn, "Alex", "resume text", {})
    jid, _ = db.upsert_job(conn, JobPosting(title="Java Developer", company="Unknown", url="pasted:1",
                                            location="Dubai"), None, None)
    db.set_application_status(conn, pid, jid, "shortlisted")
    (tmp_path / "email_template.txt").write_text(TEMPLATE)
    monkeypatch.chdir(tmp_path)
    seen = []

    class UnnamedLLM:
        model = "fake"

        def recruiter_email(self, resume, job_text, live, notes=None, outreach=None,
                            previous=None, review=None, template=None):
            seen.append(job_text)
            return filled("Dear Hiring Team,\n\nI am applying for the Java Developer position at Unknown.")

    monkeypatch.setattr(cli, "_llm", lambda s: UnnamedLLM())
    args = SimpleNamespace(job_ids=[], limit=10, no_browse=True, no_research=False, no_review=False,
                           gmail_drafts=False, send=False, general=False,
                           config=str(tmp_path / "missing.yaml"), out=str(tmp_path / "emails"))
    cli.cmd_email(args, Settings(database_url=TEST_DB))
    assert f"Company: {NOT_NAMED}" in seen[0] and "Unknown" not in seen[0]  # the writer is told, not shown a stand-in
    assert '**Fill in before sending:** company name ("Unknown" is not a real name)' in (tmp_path / "emails.md").read_text()
    assert "Fill in before sending: company name" in (tmp_path / "emails.html").read_text()


# --- general applications: an HR address with no posting ---------------------------------

HR_LIST = """1- Careers@Example.sa
Acme Gulf, hr@acme.com
3- Hr@alesayi_motors.com
careers@example.sa
jobs@example.sa
recruiter.sample@gmail.com
not an address at all
"""


def test_hr_addresses_become_general_applications(conn):
    from jobagent.actions import add_hr_contacts
    from jobagent.config import AgentConfig

    pid = db.save_profile(conn, "Alex", "resume text", {})
    r = add_hr_contacts(conn, AgentConfig(), HR_LIST, None)
    assert [(a["email"], a["company"], a["country"]) for a in r["added"]] == [
        ("careers@example.sa", "example.sa (name not given)", "Saudi Arabia"),  # country from the ending
        ("hr@acme.com", "Acme Gulf", None),
        ("recruiter.sample@gmail.com", "recruiter.sample@gmail.com (name not given)", None)]
    assert [why for _, why in r["skipped"]] == [
        "not a valid email address", "repeated in this list",
        "another address for this employer is already on your list", "not a valid email address"]
    rows = db.dashboard_rows(conn, pid)
    assert {x["status"] for x in rows} == {"shortlisted"} and all(x["score"] is None for x in rows)
    assert {x["contact_email"] for x in rows} == {a["email"] for a in r["added"]}
    assert all(x["url"].startswith("general:") and x["posted_at"] is None for x in rows)

    again = add_hr_contacts(conn, AgentConfig(), "careers@example.sa\nnew@other.ae", "UAE")
    assert [a["email"] for a in again["added"]] == ["new@other.ae"] and again["added"][0]["country"] == "UAE"
    assert again["skipped"] == [("careers@example.sa", "already on your list")]


def test_general_applications_use_their_own_template(conn, monkeypatch, tmp_path):
    from jobagent.actions import add_hr_contacts
    from jobagent.config import AgentConfig

    pid = db.save_profile(conn, "Alex", "resume text", {})
    add_hr_contacts(conn, AgentConfig(), "Acme Gulf, hr@acme.sa", None)
    jid, _ = db.upsert_job(conn, JobPosting(title="Java Engineer", company="Beta", url="https://x/1",
                                            location="Dubai"), None, None)
    db.set_application_status(conn, pid, jid, "shortlisted")
    (tmp_path / "email_template.txt").write_text(TEMPLATE)
    monkeypatch.chdir(tmp_path)
    used = {}

    class GeneralLLM:
        model = "fake"

        def recruiter_email(self, resume, job_text, live, notes=None, outreach=None,
                            previous=None, review=None, template=None):
            used["general" if "GENERAL APPLICATION" in job_text else "posting"] = template
            return filled("Dear Hiring Team,\n\nHello.")

    monkeypatch.setattr(cli, "_llm", lambda s: GeneralLLM())
    args = SimpleNamespace(job_ids=[], limit=10, no_browse=True, no_research=False, no_review=False,
                           gmail_drafts=False, send=False, general=False,
                           config=str(tmp_path / "missing.yaml"), out=str(tmp_path / "emails"))
    cli.cmd_email(args, Settings(database_url=TEST_DB))
    assert used == {"posting": TEMPLATE}  # no general template here: that draft is skipped, not mis-written

    (tmp_path / "general_email_template.txt").write_text("Dear Hiring Team,\n\nOpenings at [Company Name]?")
    cli.cmd_email(args, Settings(database_url=TEST_DB))
    assert used == {"posting": TEMPLATE, "general": "Dear Hiring Team,\n\nOpenings at [Company Name]?"}
    drafted = conn.execute("SELECT a.contact_email, a.outreach_subject FROM applications a JOIN jobs j ON j.id = a.job_id"
                           " WHERE j.url LIKE 'general:%'").fetchone()
    assert drafted["contact_email"] == "hr@acme.sa" and drafted["outreach_subject"]  # the typed address is kept


def test_general_applications_share_one_written_email(conn, monkeypatch, tmp_path):
    from jobagent.actions import add_hr_contacts
    from jobagent.config import AgentConfig

    db.save_profile(conn, "Alex", "resume text", {})
    add_hr_contacts(conn, AgentConfig(), "Acme Gulf, hr@acme.sa\nBeta & Sons, jobs@beta.sa\ncareers@gamma.sa", "Saudi Arabia")
    add_hr_contacts(conn, AgentConfig(), "Delta Dubai, hr@delta.ae", "UAE")
    (tmp_path / "general_email_template.txt").write_text("Dear Hiring Team,\n\nOpenings at [Company Name]?")
    monkeypatch.chdir(tmp_path)
    calls = []

    class OnceLLM:
        model = "fake"

        def recruiter_email(self, resume, job_text, live, notes=None, outreach=None,
                            previous=None, review=None, template=None):
            company = job_text.splitlines()[1].removeprefix("Company: ")
            calls.append(company)
            where = "" if company.startswith("(") else f" at {company}"
            return TemplateEmail(still_open=True, recruiter_name=None, contact_email=None,
                                 subject="Software Engineer | 6 yrs", body=f"Dear Hiring Team,\n\nAny openings{where}?",
                                 follow_up_subject="Re: Software Engineer | 6 yrs",
                                 follow_up_body=f"Dear Hiring Team,\n\nFollowing up{where}.")

    monkeypatch.setattr(cli, "_llm", lambda s: OnceLLM())
    args = SimpleNamespace(job_ids=[], limit=10, no_browse=True, no_research=False, no_review=False,
                           gmail_drafts=False, send=False, general=False,
                           config=str(tmp_path / "missing.yaml"), out=str(tmp_path / "emails"))
    cli.cmd_email(args, Settings(database_url=TEST_DB))
    # One call per country for named employers, one for the employer with no name: 3 calls, 4 emails.
    assert sorted(calls) == ["(not named in the posting)", "Zentrovia Holdings", "Zentrovia Holdings"]
    drafts = {r["company"]: (r["outreach_body"], r["follow_up_body"], r["contact_email"]) for r in conn.execute(
        "SELECT j.company, a.outreach_body, a.follow_up_body, a.contact_email FROM applications a JOIN jobs j ON j.id = a.job_id")}
    assert drafts["Acme Gulf"] == ("Dear Hiring Team,\n\nAny openings at Acme Gulf?", "Dear Hiring Team,\n\nFollowing up at Acme Gulf.", "hr@acme.sa")
    assert drafts["Beta & Sons"][0].endswith("at Beta & Sons?") and drafts["Delta Dubai"][0].endswith("at Delta Dubai?")
    assert drafts["gamma.sa (name not given)"][0] == "Dear Hiring Team,\n\nAny openings?"
    assert not any("Zentrovia" in body + follow for body, follow, _ in drafts.values())
