"""Take a picture of every function of the Job Search page, on a demo copy with made-up data.

    .venv/bin/python tools/take_screenshots.py [folder]

The pictures and their index (README.md) go to the project's screenshots folder unless another
folder is named.

Everything shown is invented: the person, the employers, the addresses and the figures. The
script makes two throwaway databases of its own on this computer's PostgreSQL and drops them
again (yours is never opened), works in a temporary folder (so your settings and templates are
not touched), sends nothing, calls no paid service and runs no real `jsa` task: a stand-in
prints lines. Before it replaces the old pictures it reads the words of every new one, and
stops with an error if any looks like a real address, a phone number, a folder on this
computer, a key, or the name of this computer's user.

Needs the project's Python environment, Playwright's Chromium (`playwright install chromium`)
and PostgreSQL's createdb and dropdb.
"""
import atexit
import getpass
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from jobagent import db, mailer, tailor, web
from jobagent.actions import add_hr_contacts
from jobagent.backup import make_backup
from jobagent.config import AgentConfig, Settings
from jobagent.models import JobPosting, MatchResult

PROJECT = Path(__file__).resolve().parents[1]
OUT = (Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "screenshots").resolve()
NAMES = [f"jobsearch_pictures_{os.getpid()}", f"jobsearch_pictures_{os.getpid()}_empty"]
WORK = Path(tempfile.mkdtemp(prefix="jobsearch-pictures-"))


def _clean_up():
    os.chdir(PROJECT)
    shutil.rmtree(WORK, ignore_errors=True)
    for name in NAMES:
        subprocess.run(["dropdb", "--if-exists", "--force", name], capture_output=True)


atexit.register(_clean_up)
for name in NAMES:  # two databases of this script's own, dropped again at the end
    subprocess.run(["createdb", name], check=True)
DB, EMPTY = (f"postgresql://localhost/{name}" for name in NAMES)
os.chdir(WORK)  # the demo settings and templates are written here, never over your own
HERE = Path.cwd()
SHOTS = HERE / "pictures"  # they move to OUT only once every one of them has been taken and checked
SHOTS.mkdir()
mailer.send_messages = lambda *a, **k: None  # nothing can leave this computer, whatever is clicked

# ---------------------------------------------------------------- the demo copy
CV = HERE / "Alex_Morgan_Java_Engineer.pdf"
CV.write_bytes(b"%PDF-1.4 demo")
(HERE / "email_template.txt").write_text(
    "Subject: [Job Title] | 8+ yrs Java, Spring Boot\n\nDear [Recruiter Name or Hiring Team],\n\n"
    "I am a Senior Java Engineer with over 8 years of experience, applying for the [Job Title] position at [Company].\n\n"
    "**Key skills:** [4-6 skills from the posting that I have]\n\n**Relevant experience:**\n- Built the order and billing services of a large retailer\n"
    "- Cut page load time from 4 seconds to 1\n- Led a team of four through a move to the cloud\n\nBased in India. Ready to relocate. Available to join immediately.\n\n"
    "My CV is attached. I would be glad to discuss the role on a short call.\n\nBest regards,\nAlex Morgan\n")
(HERE / "cover_letter_template.txt").write_text(
    "Dear [Recruiter Name or Hiring Team],\n\nI am writing to apply for the [Job Title] position at [Company].\n\n"
    "[Two sentences on why my experience fits this posting]\n\nYours sincerely,\nAlex Morgan\n")
(HERE / "general_email_template.txt").write_text(
    "Subject: Senior Java Engineer, 8+ years | open to roles at [Company]\n\nDear Hiring Team,\n\n"
    "I am a Senior Java Engineer with over 8 years of experience and would like to be considered for current or upcoming openings.\n\n"
    "My CV is attached.\n\nBest regards,\nAlex Morgan\n")
SITES = [("Naukri - Java backend", "generic"), ("Bayt - Java", "generic"), ("Cutshort - Java", "generic"), ("Hirist - Java", "generic"),
         ("Wellfound - Java India", "generic"), ("Amazon", "greenhouse"), ("Microsoft", "greenhouse"), ("Okta", "greenhouse"),
         ("Careem", "greenhouse"), ("Tabby", "greenhouse"), ("Razorpay", "greenhouse"), ("Stripe", "greenhouse")]
CONFIG = HERE / "config.yaml"
CONFIG.write_text(
    "search:\n  roles: [Senior Java Engineer, Backend Engineer]\n  locations: [India, UAE, Saudi Arabia, Qatar]\n"
    "  include_title_keywords: [java, backend, software engineer, full stack, platform engineer]\n"
    "  exclude_title_keywords: [intern, sales]\n  max_age_days: 14\n  min_salary_lpa: 20\n"
    f"outreach:\n  resume_path: {CV}\n  notice_period: immediately\n  follow_up_days: 6\n  check_replies: true\n  email: alex.morgan@example.com\n"
    "  phone: '+971 50 000 0000'\n  linkedin_url: https://www.linkedin.com/in/example\n  current_salary: 18 LPA\n  expected_salary: 24 LPA\nsources:\n"
    + "".join(f"  - {{kind: generic, name: {n!r}, urls: ['https://example.com/{i}'], max_detail_pages: 10{', enabled: false' if n.startswith('Bayt') else ''}{', browser: browserbase' if n.startswith('Naukri') else ''}}}\n"
              if kind == "generic" else f"  - {{kind: greenhouse, name: {n!r}, board: {n.lower()!r}}}\n" for i, (n, kind) in enumerate(SITES)))
over = HERE / "config.overrides.yaml"
if over.exists():
    over.unlink()
cfg = AgentConfig.load(CONFIG)

SKILLS = ["Kafka", "AWS", "Kubernetes", "Docker", "React", "Oracle PL/SQL", "Angular", "Terraform", "Elasticsearch", "Redis", "GraphQL", "Azure"]
DESC = ("We are hiring a {t}.\n\nYou will build Java 17 and Spring Boot services, REST APIs, Kafka pipelines and PostgreSQL schemas "
        "for a product used by millions of people.\n\nRequirements:\n- 5+ years of Java\n- Microservices and REST\n- AWS or Azure\n- Good SQL\n\n"
        "What we offer:\n- Relocation support\n- Health cover for the family\n- 30 days of leave")
BODY = ("Dear Hiring Team,\n\nI am a Senior Java Engineer with over 8 years of experience, applying for the {t} position at {co}.\n\n"
        "**Key skills:** Java 17, Spring Boot, Microservices, REST APIs, PostgreSQL, Kafka\n\n**Relevant experience:**\n"
        "- Built the order and billing services of a large retailer\n- Cut page load time from 4 seconds to 1\n- Led a team of four through a move to the cloud\n\n"
        "Based in India. Ready to relocate. Available to join immediately.\n\nMy CV is attached. I would be glad to discuss the role on a short call.\n\n"
        "Best regards,\nAlex Morgan\n[LinkedIn](https://www.linkedin.com/in/example/)")
FOLLOW = "Dear Hiring Team,\n\nI am following up on my application for the {t} position, sent last week. I remain very interested and can join immediately.\n\nBest regards,\nAlex Morgan"
CV_TEXT = {  # the CV written for the first job; every line of it is invented
    "headline": "Senior Java Engineer, 8 years",
    "summary": "Senior Java Engineer with 8 years of building Java and Spring Boot services for products used by millions of people: "
               "order and billing services, REST APIs, Kafka pipelines and PostgreSQL schemas. Led a team of four through a move to the cloud.",
    "skills": ["Java 17", "Spring Boot", "Microservices", "REST APIs", "Kafka", "PostgreSQL", "AWS", "Docker"],
    "experience": [
        {"employer": "Harbor Retail Group", "title": "Senior Java Engineer", "dates": "Mar 2021 - Present", "location": "Pune, India",
         "bullets": ["Built the order and billing services in Java 17 and Spring Boot, used by millions of shoppers",
                     "Cut page load time from 4 seconds to 1", "Led a team of four through a move to the cloud"]},
        {"employer": "Cedar Software", "title": "Java Developer", "dates": "Jul 2017 - Feb 2021", "location": "Ahmedabad, India",
         "bullets": ["Wrote REST APIs and PostgreSQL schemas for a billing product", "Moved nightly jobs to Kafka pipelines"]}],
    "education": ["B.E. Computer Engineering, 2017"], "other": []}
JOBS = [  # title, company, place, score, hours since posted, status, site. Every employer is invented.
    ("Senior Technical Software Engineer (Java, Spring Boot, Microservices)", "Skyline Aviation Group", "Dubai, UAE", 91, 5, "shortlisted", "Naukri - Java backend"),
    ("Sr. Full Stack Java Developer | Immediate Joiners | Hybrid", "Harbor Business Services", "Ahmedabad, Gujarat, India", 88, 20, "shortlisted", "Naukri - Java backend"),
    ("Software Engineer, Payments", "Northwind Payments", "Riyadh, Saudi Arabia", 84, 30, "shortlisted", "Tabby"),
    ("Java Developer (Spring Boot)", "Cedar Labs", "Ahmedabad, India", 82, 50, "shortlisted", "Hirist - Java"),
    ("Backend Engineer, AI Platform", "Lumen AI", "Bengaluru, India", 79, 70, "shortlisted", "Wellfound - Java India"),
    ("Lead Java Engineer", "Riverbank Mobility", "Dubai, UAE", 77, 100, "applied", "Careem"),
    ("Java Microservices Engineer", "Souq Lane", "Riyadh, Saudi Arabia", 86, 200, "applied", "Naukri - Java backend"),
    ("Senior Software Engineer", "Postbox APIs", "Bengaluru, India", 80, 150, "interviewing", "Cutshort - Java"),
    ("Java Engineer", "Saffron Kitchens", "Dubai, UAE", 76, 160, "skipped", "Cutshort - Java"),
    ("Platform Engineer", "Quartz Pay", "Bengaluru, India", 68, 40, None, "Razorpay"),
    ("Full Stack Engineer", "Zenith Suite", "Chennai, India", 55, 90, None, "Hirist - Java"),
    ("Java Support Analyst", "Gulf Data Systems", "Doha, Qatar", 41, 110, None, "Naukri - Java backend"),
    ("Staff Software Engineer, Identity", "Keystone Identity", "Bengaluru, India", 83, 26, "shortlisted", "Okta"),
    ("Software Development Engineer II", "Atlas Commerce", "Hyderabad, India", 81, 34, "shortlisted", "Amazon"),
    ("Senior Backend Engineer, Checkout", "Ledgerline", "Bengaluru, India", 78, 44, "shortlisted", "Stripe"),
    ("Software Engineer 2", "Brightsoft", "Hyderabad, India", 75, 60, "shortlisted", "Microsoft"),
    ("Senior Java Developer", "Blue Dune Airways", "Doha, Qatar", 85, 240, "applied", "Naukri - Java backend"),
    ("Backend Engineer", "Oasis Pay", "Riyadh, Saudi Arabia", 79, 300, "applied", "Cutshort - Java"),
    ("Java Developer", "Marina Bank Tech", "Dubai, UAE", 74, 330, "rejected", "Naukri - Java backend"),
    ("Principal Software Engineer", "Voyage Stays", "Remote, India", 72, 80, None, "Wellfound - Java India"),
    ("Senior Software Engineer, Platform", "Riverbank Mobility", "Dubai, UAE", 87, 400, "offer", "Careem"),
    ("Java Backend Developer", "Pine Technologies", "Pune, India", 71, 18, None, "Cutshort - Java"),
    ("Software Engineer, Risk", "Northwind Payments", "Dubai, UAE", 73, 52, None, "Tabby"),
    ("Senior Java Engineer", "Crescent Bank Tech", "Dubai, UAE", 80, 500, "interviewing", "Naukri - Java backend"),
]


def seed(conn):
    conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    db.migrate(conn)
    pid = db.save_profile(conn, "Alex Morgan", "resume", {"name": "Alex Morgan"})
    now = datetime.now(timezone.utc)
    site = {n: db.upsert_source(conn, kind, n, f"https://example.com/{i}", {"max_detail_pages": 10}) for i, (n, kind) in enumerate(SITES)}
    ids = []
    for i, (t, co, loc, sc, hrs, st, s) in enumerate(JOBS):
        p = JobPosting(title=t, company=co, url=f"https://example.com/jobs/{i}", location=loc, description=DESC.format(t=t),
                       posted_at=now - timedelta(hours=hrs))
        jid, _ = db.upsert_job(conn, p, site[s], None)
        gaps = [SKILLS[k] for k in range(len(SKILLS)) if (i * 7 + k * k) % (k + 2) == 0][:4]
        flags = ["Banking experience is asked for", "Salary not stated"] if i % 3 == 0 else []
        db.save_match(conn, pid, jid, None, MatchResult(
            score=sc, verdict="strong" if sc >= 85 else "good" if sc >= 70 else "stretch",
            summary=f"Eight years of Java and Spring Boot line up with this {t} role. The stack and seniority match, and "
                    f"{loc.split(', ')[-1]} is one of your places.",
            matched_skills=["Java 17", "Spring Boot", "REST APIs", "Microservices", "PostgreSQL"], missing_skills=gaps, red_flags=flags,
            salary_estimate="AED 18-24k a month (estimate)" if "UAE" in loc else "24-32 LPA (estimate)"), "claude-sonnet-5-5", p.content_hash)
        if st:
            db.set_application_status(conn, pid, jid, "shortlisted", "auto: high match score", history_only=True)
            if st != "shortlisted":
                db.set_application_status(conn, pid, jid, "applied" if st in ("interviewing", "offer", "rejected") else st,
                                          "set on the web page", history_only=True)
            if st in ("interviewing", "offer", "rejected"):
                db.set_application_status(conn, pid, jid, "interviewing" if st == "offer" else st, "set on the web page", history_only=True)
            if st == "offer":
                db.set_application_status(conn, pid, jid, "offer", "set on the web page", history_only=True)
        ids.append(jid)

    def write(k, to, kind="recruiter"):
        t, co = JOBS[k][0], JOBS[k][1]
        db.save_outreach(conn, pid, ids[k], subject=f"{t.split(' (')[0].split(' |')[0]} | 8 yrs Java, Spring Boot", body=BODY.format(t=t.split(' (')[0], co=co),
                         recruiter_name=None, contact_email=to, still_open=True,
                         follow_up_subject=f"Re: {t.split(' (')[0].split(' |')[0]} | 8 yrs Java, Spring Boot", follow_up_body=FOLLOW.format(t=t.split(' (')[0]))
        if to:
            db.save_contact(conn, pid, ids[k], to, f"https://example.com/careers/{k}", kind)

    write(0, "careers@skylineaviation.example")
    write(1, "hr@harborbusiness.example")
    write(2, None)
    write(12, "info@keystoneidentity.example", "general")
    for k, to, days in ((5, "talent@riverbankmobility.example", 2), (6, "jobs@souqlane.example", 8), (7, "hiring@postboxapis.example", 12),
                        (16, "recruitment@bluedune.example", 4), (17, "people@oasispay.example", 9)):
        write(k, to)
        conn.execute("UPDATE applications SET outreach_sent_at = now() - make_interval(days => %s) WHERE job_id = %s", (days, ids[k]))
    conn.execute("UPDATE applications SET follow_up_sent_at = now() - interval '5 days' WHERE job_id = %s", (ids[7],))
    db.save_replies(conn, pid, [ids[16], ids[17]], {  # what a look in Gmail found: one answer, one address that refused the email
        ids[16]: {"kind": "reply", "at": now - timedelta(days=1), "subject": "Re: Senior Java Developer | 8 yrs Java, Spring Boot"},
        ids[17]: {"kind": "bounced", "at": now - timedelta(days=9) + timedelta(minutes=5), "subject": "Delivery Status Notification (Failure)"}})
    db.set_note(conn, pid, ids[7], "Call with Priya (recruiter) on Thursday at 4pm. She asked about notice period and Kafka.")
    db.save_cover_letter(conn, pid, ids[0], "Dear Hiring Team,\n\nI am writing to apply for the Senior Technical Software Engineer position at Skyline Aviation Group.\n\n"
                         "For eight years I have built Java and Spring Boot services, most recently the order and billing services of a large retailer. "
                         "Your posting asks for microservices at scale and a move to Dubai, both of which suit me.\n\nYours sincerely,\nAlex Morgan")

    db.save_answers(conn, pid, ids[0], {
        "why_this_role": "The posting asks for Java 17 and Spring Boot services used by millions of people, which is the work I have done for eight years. "
                         "A move to Dubai suits me, and the relocation support makes it practical.",
        "why_you": "I have built and run the order and billing services of a large retailer in Java and Spring Boot, with REST APIs, Kafka and PostgreSQL. "
                   "I led a team of four through a move to the cloud, so I can take ownership from the first week.",
        "about_you": "I am a senior Java engineer with eight years of experience building backend services. Most of my work has been Spring Boot "
                     "microservices and REST APIs on PostgreSQL. I am based in India, ready to relocate, and can join immediately.",
        "key_skills": "Java 17, Spring Boot, Microservices, REST APIs, PostgreSQL, Kafka",
        "experience": "Java: 8 years\nSpring Boot: 6 years\nPostgreSQL: 5 years"})

    # a CV written for the first job, checked against the resume, and not yet attached to its email
    cv_file = tailor.file_for(str(HERE / "resumes"), ids[0], "Alex Morgan", "Alex_Morgan_Java_Engineer.pdf")
    tailor.write_pdf(tailor.page_html("Alex Morgan", ["alex.morgan@example.com", "+971 50 000 0000", "Pune, India"], CV_TEXT), cv_file)
    db.save_tailored_cv(conn, pid, ids[0], {"cv": CV_TEXT, "file": str(cv_file), "attach": False, "written_at": now.isoformat(), "notes": [
        "Left out, because your resume does not name it: Kubernetes",
        'Left out a line at Harbor Retail Group, because your resume does not give the figure 40: "Cut cloud costs by 40%."']})
    db.save_prep(conn, pid, ids[7], {
        "technical": [{"question": "How does Spring Boot decide which beans to create?", "points": ["Auto-configuration and its conditions", "The starters used in the order service"]},
                      {"question": "How would you keep a Kafka consumer from handling a message twice?", "points": ["Offsets are committed after the work is done", "The billing service checks an order id before it writes"]},
                      {"question": "A REST call is slow under load. Where do you look first?", "points": ["Page load cut from 4 seconds to 1: the query plan, then the cache", "Connection pool size and timeouts"]},
                      {"question": "When would you choose PostgreSQL over a document store?", "points": ["Orders and payments need transactions", "Five years of PostgreSQL schemas"]}],
        "experience": [{"question": "Tell me about a move to the cloud that you led.", "points": ["Team of four", "Moved the order and billing services one at a time", "No downtime on the day"]},
                       {"question": "Why do you want to move now?", "points": ["Ready to relocate", "Looking for a product used by millions of people"]}],
        "ask_them": ["How is the team split between new work and support?", "What does the first month look like for this role?", "How are services released, and how often?"],
        "revise": ["AWS: the posting asks for it and your resume shows little. Cover EC2, S3, IAM and how a service is deployed",
                   "Kafka: consumer groups, offsets and delivery guarantees"]})

    # a post pasted by hand: something of yours, so it can be deleted
    post = JobPosting(title="Java Developer", company="Harbor Tech Systems", url="pasted:demo0001", location="Dubai, UAE", posted_at=now,
                      description="WE ARE HIRING | JAVA DEVELOPER\nLocation: Dubai, UAE. Experience: 5+ years.\nJava, Spring Boot, Microservices, Kafka.\n\n"
                                  "Send applications to: jobs@harbortech.example")
    pasted, _ = db.upsert_job(conn, post, None, None)
    db.save_match(conn, pid, pasted, None, MatchResult(score=84, verdict="good", summary="A Java and Spring Boot role in Dubai asking for five years; you have eight.",
                                                       matched_skills=["Java", "Spring Boot", "Microservices"], missing_skills=["Kafka"], red_flags=[]),
                  "claude-sonnet-5-5", post.content_hash)
    db.set_application_status(conn, pid, pasted, "shortlisted", "added from pasted text", history_only=True)
    db.save_contact(conn, pid, pasted, "jobs@harbortech.example", None, "recruiter")

    # HR addresses with no posting: two already written to, for the In progress list
    added = add_hr_contacts(conn, cfg, "Sandstone Systems, hr@sandstonesystems.example\nPalm Grove Clinics, careers@palmgroveclinics.example", "UAE")["added"]
    for n, a in enumerate(added):
        jid = a["job_id"] if isinstance(a, dict) else a
        row = db.get_application(conn, pid, jid)
        db.save_outreach(conn, pid, jid, subject="Senior Java Engineer, 8+ years | open to roles", body=BODY.format(t="Senior Java Engineer", co="your company"),
                         recruiter_name=None, contact_email=row["contact_email"], still_open=True)
        db.save_contact(conn, pid, jid, row["contact_email"], None, row["contact_kind"] or "hr")
        db.set_application_status(conn, pid, jid, "applied", f"emailed {row['contact_email']}", history_only=True)
        conn.execute("UPDATE applications SET outreach_sent_at = now() - make_interval(days => %s) WHERE job_id = %s", (n + 1, jid))

    # the same job stored twice, for the Duplicate jobs card
    twin, _ = db.upsert_job(conn, JobPosting(title="Zz placeholder", company="Zz", url="https://example.com/jobs/twin", location="Dubai, UAE",
                                             description=DESC.format(t="Java Engineer"), posted_at=now - timedelta(hours=170)), site["Naukri - Java backend"], None)
    conn.execute("UPDATE jobs SET title = 'Java Engineer (Dubai)', company = 'Saffron Kitchens FZ LLC', match_key = (SELECT match_key FROM jobs WHERE id = %s) WHERE id = %s",
                 (ids[8], twin))

    # found by a search but not scored yet
    for n, t in enumerate(["Senior Software Engineer, Workflows", "Backend Engineer, Directory", "Software Engineer, Platform", "Senior Backend Engineer, Auth"]):
        db.upsert_job(conn, JobPosting(title=t, company="Keystone Identity", url=f"https://example.com/keystone/{n}", location="Bengaluru, India",
                                       description=DESC.format(t=t), posted_at=now - timedelta(hours=6 + n)), site["Okta"], None)

    def spent(main, quick):
        return {"cost": round(main + quick, 2), "usage": {"claude-sonnet-5-5": {"cost": main}, "claude-haiku-5-5": {"cost": quick}}}

    for n, (days, status, stats, why) in enumerate((
            (3, "succeeded", {"found": 5412, "new": 36, "scored": 36, "tokens": 248900, **spent(0.31, 0.02)}, None),
            (2, "partial", {"found": 7960, "new": 97, "scored": 90, "tokens": 489300, **spent(0.62, 0.04)}, "1 site could not be read: Wellfound - Java India"),
            (1, "partial", {"found": 3204, "new": 8, "scored": 8, "tokens": 52700, **spent(0.07, 0.01)}, "1 site could not be read: Wellfound - Java India"),
            (0, "succeeded", {"found": 7415, "new": 29, "scored": 27, "tokens": 231600, **spent(0.29, 0.02)}, None))):
        rid = db.start_run(conn, pid, {})
        for name, sid in site.items():  # what each search wrote down about each site: one keeps failing, one has gone quiet
            if name.startswith("Bayt"):
                continue
            if name.startswith("Wellfound") and n:
                db.log_event(conn, rid, f"{name}: failed: the site refused this browser (error 403)", level="error", source_id=sid)
            else:
                found = 0 if name.startswith("Hirist") and n else 12 + 7 * len(name)
                db.log_event(conn, rid, f"{name}: {found} jobs ({(n + len(name)) % 6 if found else 0} new)", source_id=sid)
        db.finish_run(conn, rid, status=status, stats=stats, error=why)
        conn.execute("UPDATE runs SET started_at = now() - make_interval(days => %s, mins => 40), finished_at = now() - make_interval(days => %s, mins => 29) WHERE id = %s",
                     (days, days, rid))
    return pid, ids, pasted


conn = db.connect(DB)
pid, ids, pasted = seed(conn)
make_backup(DB, folder=str(HERE / "backups"), keep=7, repo=None)

SLOW = ("import time\nfor line in ['Naukri - Java backend: 24 listings on the search page', 'Naukri - Java backend: 24 jobs (6 new)', "
        "'Cutshort - Java: 50 listings on the search page', 'Cutshort - Java: 50 jobs (12 new)', 'Okta: 310 jobs (0 new)', 'Amazon: kept 52 jobs that fit your rules', "
        "'Quick check (claude-haiku-5-5): 3 of 30 jobs ruled out', 'Scoring 27 jobs', 'Run #5: succeeded. 7415 jobs found, 29 new, 27 scored, 4 shortlisted']:\n"
        "    print(line, flush=True); time.sleep(1.3)")
QUICK = "import time\nprint('Working', flush=True)\ntime.sleep(0.6)\nprint('Done', flush=True)"


def serve(url):
    s = web.serve(Settings(database_url=url, llm_provider="anthropic", llm_model="claude-sonnet-5-5", anthropic_api_key="demo", browser="local", browserbase_api_key="demo",
                           gmail_address="alex.morgan@example.com", gmail_app_password="demo"), cfg, 0, config_path=str(CONFIG))
    s.runner.command = lambda argv: [sys.executable, "-u", "-c", SLOW if argv[0] == "run" and "--source" not in argv else QUICK]
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"


# ---------------------------------------------------------------- the pictures
index, group, words = [], [""], {}


def section(name):
    group[0] = name


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    server, base = serve(DB)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()

    def settle(ms=450):
        page.wait_for_timeout(ms)

    def shot(name, title, text, *, target=None, upto=None, clip=None, full=False, pad=0, keep_messages=False):
        file = f"{len(index) + 1:02d}-{name}.png"
        if not keep_messages:
            page.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")
        tidy_paths()
        words[file] = page.evaluate("() => document.body.innerText + '\\n' + [...document.querySelectorAll('input,textarea')].filter(e => e.offsetParent !== null).map(e => e.value + ' ' + (e.placeholder || '')).join('\\n')")
        if target is not None:
            box, end = target.bounding_box(), (upto or target).bounding_box()
            left, right = min(box["x"], end["x"]), max(box["x"] + box["width"], end["x"] + end["width"])
            clip = {"x": max(0, left - pad), "y": max(0, box["y"] - pad), "width": right - left + 2 * pad,
                    "height": end["y"] + end["height"] - box["y"] + 2 * pad}
        page.screenshot(path=str(SHOTS / file), clip=clip, full_page=full)
        index.append((group[0], file, title, text))
        print("  ", file)

    def tall(height=3400):
        page.set_viewport_size({"width": 1440, "height": height})
        settle(300)

    def normal():
        page.set_viewport_size({"width": 1440, "height": 900})
        settle(300)

    def go(view):
        page.evaluate(f"showView('{view}')")
        settle()

    def open_job(jid):
        page.evaluate(f"openJob({jid})")
        expect(page.locator("#detail h2")).to_be_visible()
        settle(600)

    def close_job():
        page.evaluate("closeDrawer(true)")
        settle(300)

    def tidy_paths():  # the demo copy lives in a long temporary folder: show a plain one instead
        page.evaluate("""(prefix) => { const w = document.createTreeWalker(document.querySelector('#page'), NodeFilter.SHOW_TEXT); let n;
            while ((n = w.nextNode())) if (n.nodeValue.includes(prefix)) n.nodeValue = n.nodeValue.split(prefix).join('/Users/you/job-search-agent'); }""", str(HERE))

    def top():
        page.evaluate("window.scrollTo(0, 0)")
        settle(250)

    def ask_no():
        page.locator('#ask [value="no"]').click()
        settle(250)

    page.goto(base + "/")
    expect(page.locator("#vsub")).not_to_have_text("Starting up")
    page.evaluate("document.fonts.ready")
    page.wait_for_function("S.live === true")
    settle(900)

    # ---- the screen at a glance
    section("The screen at a glance")
    shot("shortlist", "Shortlist: the home screen", "The menu on the left, the six numbers across the top, the filter bar and table of shortlisted jobs, the pipeline and top matches on the right.")
    shot("menu-and-actions", "The menu and its actions", "The seven screens with their counts, then the one-click actions that work from any screen.", target=page.locator("#sidebar"))
    shot("numbers", "The six numbers", "How many jobs are at each stage. Clicking one opens those jobs. The line under Scored says how many still wait.", target=page.locator("#stats"), pad=8)
    tall(1700)
    shot("next-steps", "Where the jobs are, and Next steps", "Scored jobs by country, and what is worth doing next, each with its button.", target=page.locator(".pair"), pad=8)
    shot("pipeline", "Pipeline and Top matches", "One mark per job on your lists, coloured by stage, and your best-scoring jobs.", target=page.locator("aside.side"), pad=8)
    normal()
    top()
    page.keyboard.press("Control+k")
    expect(page.locator("#palette")).to_be_visible()
    settle()
    shot("all-actions", "All actions (Cmd-K)", "A searchable list of every action and screen.")
    page.fill("#pq", "send")
    settle(250)
    shot("all-actions-search", "All actions, searched", "Type a few letters, then press Enter.")
    page.keyboard.press("Escape")
    page.locator("#th-light").click()
    settle(500)
    shot("light-look", "The light look", "Light and Dark at the bottom of the menu switch the look.")
    page.locator("#th-dark").click()
    settle(300)

    # ---- finding jobs
    section("Finding jobs")
    page.locator('.split [data-act="run-menu"]').click()
    settle(300)
    shot("find-new-jobs-menu", "The arrow beside Find new jobs", "Search every site, collect only, score waiting jobs, the morning routine, or search one site.", clip={"x": 760, "y": 0, "width": 680, "height": 420})
    page.keyboard.press("Escape")
    page.locator("#vtitle").click()
    page.locator('.split > [data-act="run"]').click()
    expect(page.locator("#live b")).to_have_text("Find new jobs")
    page.wait_for_timeout(3200)
    shot("search-running", "A search running", "A line moves under the numbers it is working on, and the strip under them shows the latest message, with Show output and Stop.", clip={"x": 248, "y": 0, "width": 1192, "height": 330})
    page.locator('#live [data-view="activity"]').click()
    settle(700)
    shot("activity-running", "Activity while a task runs", "Everything the task has reported so far, updating as it happens, above the list of past searches.")
    page.locator('#live [data-act="stop"]').click()
    settle(300)
    shot("stop-a-task", "Stopping a task", "Stop asks first. What the task already saved is kept.")
    ask_no()
    expect(page.locator("#live b")).to_have_text("Find new jobs: done", timeout=20000)
    settle(500)
    shot("activity-finished", "Activity: the last task and past searches", "The finished task's full output, and each past search with its result, counts, AI tokens, what the AI calls cost and, when it was only partly finished, why.", full=True)
    go("shortlist")
    shot("search-finished", "A finished task", "The strip says done and the lists refresh by themselves.", clip={"x": 248, "y": 0, "width": 1192, "height": 330})
    page.locator('#live [data-act="dismiss"]').click()
    page.locator('.head [data-act="add"]').click()
    page.fill("#addtext", "WE ARE HIRING | SENIOR JAVA DEVELOPER\nLocation: Dubai, UAE\nExperience: 5+ years\n\nJava, Spring Boot, Microservices, Kafka, Docker\n\nInterested candidates, share your CV at: careers@acmegulf.example")
    page.fill("#addurl", "https://www.linkedin.com/posts/example")
    settle(300)
    shot("add-from-a-post", "Add from a post", "Paste a LinkedIn post, a WhatsApp message or an email. The role, company and address are read from it, and the job is scored and shortlisted. Only have a picture of the post? Paste it, drop it on the box, or choose it, and its text is written into the box for you to check.")
    page.locator('#adddlg [data-act="close-add"]').click()

    # ---- HR addresses
    section("General applications: HR addresses")
    page.locator('.sidebar [data-act="hr"]').click()
    page.fill("#hrtext", "Dune Freight, recruitment@dunefreight.example\nKestrel Software, hr@kestrelsoftware.example\nthis line has no address\nhr@sandstonesystems.example")
    page.select_option("#hrcountry", "UAE")
    settle(300)
    shot("add-hr-addresses", "Add HR addresses", "One address per line, with the employer's name before it if you know it.")
    page.locator('#hrdlg [data-act="hr-go"]').click()
    expect(page.locator("#hrresult")).to_contain_text("Added 2")
    settle(400)
    shot("add-hr-addresses-result", "What was added and what was left out", "Each address becomes a general application on the shortlist. A line with no address, or one already on your list, is listed with the reason and stays in the box.")
    page.locator('#hrdlg [data-act="close-hr"]').click()
    settle(300)
    page.select_option("#f-extra", "general")
    settle(400)
    shot("general-applications-shortlist", "General applications on the shortlist", "Choose General applications in the Next step filter. Each row shows the employer and the address.")
    page.select_option("#f-extra", "")

    # ---- the table
    section("The table")
    tall(1700)
    page.select_option("#f-country", "UAE")
    page.select_option("#f-score", "80")
    settle(400)
    shot("table-filters", "Filters", "Country, score, how recently it was posted, and next step. The count beside the title says how many match.", target=page.locator("#fbar"), upto=page.locator("section.tcard"), pad=8)
    page.select_option("#f-country", "")
    page.select_option("#f-score", "0")
    page.fill("#tq", "bengaluru")
    settle(400)
    shot("table-search", "Search jobs", "Looks at the title, company, location and email address.", target=page.locator("#fbar"), upto=page.locator("section.tcard"), pad=8)
    page.fill("#tq", "")
    page.locator('th[data-sort="score"]').click()
    page.locator('th[data-sort="score"]').click()
    settle(400)
    shot("table-sorted", "Sorting", "Click a column heading to sort, again to reverse, a third time to go back to newest first.", target=page.locator("#fbar"), upto=page.locator("section.tcard"), pad=8)
    page.locator('th[data-sort="score"]').click()
    page.locator('#tfoot [aria-label="Next page"]').click()
    settle(400)
    shot("table-pages", "Pages", "Eight jobs show per page. The buttons under the table move between pages.", target=page.locator("section.tcard"), pad=8)
    page.fill("#tq", "no such job")
    settle(400)
    shot("table-nothing-matches", "When nothing matches", "Clear the filters brings every job back.", target=page.locator("#fbar"), upto=page.locator("section.tcard"), pad=8)
    page.locator('#tbody [data-act="clear"]').click()
    settle(300)
    normal()
    top()

    # ---- a job, opened
    section("A job, opened")
    open_job(ids[0])
    shot("job-opened", "A job, opened", "Clicking a row slides in a panel from the right. Esc, the X or a click outside closes it; the arrows or J and K move to the next job.")
    tall()
    panel = page.locator("#detail")
    blocks = panel.locator(".block")
    shot("job-top", "Top of the panel", "Title, company, place, age, pay and score. Apply on the job site opens the posting; the next buttons record what happened; Other status has the rest.",
         clip={"x": 768, "y": 0, "width": 672, "height": blocks.nth(0).bounding_box()["y"] + blocks.nth(0).bounding_box()["height"] + 8})
    shot("job-email-ready", "The email, ready to send", "The email is a sheet of paper: To, Subject and the text, all editable. Save draft keeps your edits; Send email sends it after asking.", target=blocks.nth(1), pad=8)
    panel.locator('[data-act="sheet"][data-to="preview"]').click()
    settle(400)
    shot("job-email-preview", "Preview", "Preview shows the email as the recruiter will see it. Edit brings the text back.", target=blocks.nth(1), pad=8)
    panel.locator('[data-act="sheet"][data-to="edit"]').click()
    shot("job-cover-letter", "Cover letter", "For sites that ask for one. Copy puts it on the clipboard; Write it again makes a new one.", target=blocks.nth(2), pad=8)
    shot("job-application-answers", "Answers for the application form", "Your own details and short answers written for this job, each with a Copy button, to paste into the site's form yourself. Nothing is submitted for you.",
         target=blocks.nth(3), pad=8)
    shot("job-cv", "CV for this job", "Your resume arranged for this posting: the same facts, with what this job asks for first. It is checked against your resume, and what "
         "your resume does not say is taken out and listed. Open the PDF to read it; the switch attaches it to this job's email in place of your usual CV.",
         target=panel.locator("#cvblock"), pad=8)
    shot("job-interview-prep-empty", "Interview preparation, before it is written", "Prepare for the interview writes likely questions for this job.", target=panel.locator("#prepblock"), pad=8)
    block = lambda name: panel.locator(f'.block:has(h3:text-is("{name}"))')  # noqa: E731
    panel.locator("details summary", has_text="Full job description").click()
    settle(300)
    shot("job-description", "Notes, history and the full job description", "Your own notes, every status change and email with its date, and the original posting text.",
         clip={"x": 768, "y": block("Notes").bounding_box()["y"] - 8, "width": 672,
               "height": blocks.last.bounding_box()["y"] + blocks.last.bounding_box()["height"] - block("Notes").bounding_box()["y"] + 24})
    normal()
    panel.locator('[data-act="send-one"]').click()
    settle(300)
    shot("send-email-question", "Send email asks first", "The question names the address. Only Send email in this box sends it.")
    ask_no()
    close_job()

    open_job(ids[3])
    tall()
    shot("job-no-draft", "A job with no draft yet", "Draft the email writes one from your template and resume.", target=page.locator("#detail .block").nth(1), pad=8)
    normal()
    close_job()
    open_job(ids[2])
    tall()
    shot("job-no-address", "A draft with no address", "The line under the buttons says why there is no Send email. Type an address and Save address, or Look for one.", target=page.locator("#detail .block").nth(1), pad=8)
    normal()
    close_job()
    go("progress")
    open_job(ids[5])
    tall()
    shot("job-top-applied", "A job you applied to", "Once a job is applied, the buttons record what happened next: Got an interview, Rejected, and later Got an offer.",
         clip={"x": 768, "y": 0, "width": 672, "height": page.locator("#detail .block").nth(0).bounding_box()["y"] - 8})
    shot("job-email-sent", "An email that already went", "The round mark is the day it was sent. Send again writes to the same address once more, after asking.", target=page.locator("#detail .block").nth(1), pad=8)
    normal()
    page.locator('#detail [data-act="send-again"]').click()
    settle(300)
    shot("send-again-question", "Send again asks first", "It names the day the first email went and the address. Send ready emails never writes to the same job twice; only this does.")
    ask_no()
    close_job()
    open_job(ids[6])
    tall()
    page.locator("#detail details[open] summary").first.scroll_into_view_if_needed()
    shot("job-follow-up-due", "A follow-up that is due", "The stored follow-up text sits under the email. I followed up myself records one you sent by hand.", target=page.locator("#detail .block").nth(1), pad=8)
    normal()
    close_job()
    open_job(ids[7])
    tall()
    page.locator("#prepblock details.pq").first.locator("summary").click()
    settle(300)
    shot("job-interview-prep", "Interview preparation", "What to revise first, likely technical questions and questions about your work, each with points for the answer from your resume "
         "(click a question to see them), and questions to ask them.", target=page.locator("#prepblock"), pad=8)
    notes, history = (page.locator(f'#detail .block:has(h3:text-is("{name}"))') for name in ("Notes", "History"))
    shot("job-notes-history", "Notes and history", "Notes are yours alone. History lists every status change and email with its date.",
         clip={"x": 768, "y": notes.bounding_box()["y"] - 8, "width": 672,
               "height": history.bounding_box()["y"] + history.bounding_box()["height"] - notes.bounding_box()["y"] + 24})
    normal()
    page.fill("#note", "Call with Priya (recruiter) on Thursday at 4pm. She asked about notice period and Kafka. She will call again next week.")
    page.locator('#detail [data-act="save-note"]').click()
    expect(page.locator(".toast").filter(has_text="Note saved").first).to_be_visible()
    shot("message", "A message after an action", "A short message at the bottom right confirms what was done, or says what went wrong and what to do.",
         clip={"x": 1040, "y": 780, "width": 400, "height": 120}, keep_messages=True)
    page.wait_for_function("S.dirty === false")
    settle(700)
    page.fill("#note", "She will call again next week")
    page.keyboard.press("Escape")
    expect(page.locator("#ask")).to_be_visible()
    settle(300)
    shot("unsaved-changes-question", "Leaving with unsaved changes", "The page asks before it throws away something you typed.")
    page.locator("#ask button.primary").click()
    settle(300)
    go("shortlist")
    open_job(ids[0])
    page.evaluate(f"S.applyPending = {{ id: {ids[0]}, title: 'Senior Technical Software Engineer', company: 'Skyline Aviation Group' }}; void askApplied()")
    expect(page.locator("#ask")).to_be_visible()
    settle(300)
    shot("did-you-apply", "After Apply on the job site", "The posting opens in a new tab. When you come back, the page asks whether you applied, and Yes moves the job to In progress.")
    ask_no()
    close_job()
    open_job(pasted)
    settle(300)
    page.locator('#detail [data-act="delete"]').click()
    settle(300)
    shot("delete-entry-question", "Delete entry", "Only something you added yourself, and have not emailed, can be deleted. It asks first.")
    ask_no()
    close_job()

    sheet = ctx.new_page()
    sheet.set_viewport_size({"width": 794, "height": 760})
    sheet.set_content(tailor.page_html("Alex Morgan", ["alex.morgan@example.com", "+971 50 000 0000", "Pune, India"], CV_TEXT).replace("<body>", '<body style="padding:14mm 16mm">'))
    file = f"{len(index) + 1:02d}-cv-for-one-job.png"
    words[file] = sheet.evaluate("() => document.body.innerText")
    sheet.screenshot(path=str(SHOTS / file))
    index.append((group[0], file, "The CV that was written", "One plain column under the usual headings, as a PDF. It is kept in the resumes folder, in a folder of its own for each job."))
    print("  ", file)
    sheet.close()

    # ---- sending
    section("Sending emails")
    page.locator('#toolbar [data-act="send-all"]').click()
    expect(page.locator("#ask")).to_be_visible()
    settle(300)
    shot("send-ready-emails-question", "Send ready emails", "Sends every email that has both a draft and an address, after asking, within the daily limit.")
    ask_no()
    shot("shortlist-toolbar", "The Shortlist buttons", "Draft emails, Look for addresses, Save drafts to Gmail and Send ready emails, each with how many jobs it applies to.", target=page.locator(".tcard .ttl"), pad=8)

    # ---- the other screens
    section("The other screens")
    go("progress")
    shot("in-progress", "In progress", "Jobs you applied to, interviews and offers. The round mark at the end of a row is the day you emailed. With Look in Gmail for replies "
         "switched on, a job a recruiter answered says Replied, and one whose address refused the email says Not delivered.")
    open_job(ids[16])
    tall()
    shot("job-reply", "A reply found in Gmail", "The panel says when the reply came and its subject line. Read it in Gmail, then record what happened. Only the sender, the date and "
         "the subject line are read, and nothing in Gmail is changed.", target=page.locator("#detail .block").nth(1), pad=8)
    normal()
    close_job()
    page.select_option("#f-extra", "general")
    settle(400)
    shot("in-progress-general", "In progress: General applications", "The HR addresses you wrote to, each with its address and the day.", target=page.locator("section.tcard"), pad=8)
    page.select_option("#f-extra", "aside")
    settle(400)
    shot("in-progress-set-aside", "In progress: Set aside", "Jobs you skipped and rejections.", target=page.locator("section.tcard"), pad=8)
    go("followups")
    shot("follow-ups", "Follow-ups", "Emails with no reply after the number of days you set. A job that was answered, or whose address refused the email, is not followed up. "
         "Check for replies looks in Gmail now; it shows only when that is switched on in Settings.")
    page.locator('#toolbar [data-act="followups"]').click()
    expect(page.locator("#ask")).to_be_visible()
    settle(300)
    shot("send-follow-ups-question", "Send follow-ups", "The stored follow-up text goes to each recruiter who has not replied, after asking.")
    ask_no()
    go("matches")
    expect(page.locator("#tbody")).not_to_contain_text("Loading")
    page.select_option("#f-score", "0")
    settle(400)
    shot("all-matches", "All matches", "Every scored job, not only the shortlist. Download digest saves the best ones as a file.")
    go("insights")
    expect(page.locator("#page")).not_to_contain_text("Loading")
    settle(900)
    shot("insights", "Insights", "Your last seven days, the skills postings ask for most that your resume lacks, and which sites deliver.", full=True)

    # ---- settings
    section("Settings")
    go("settings")
    expect(page.locator('[data-cfg="search.max_age_days"]')).to_be_visible()
    settle(600)
    tidy_paths()
    shot("settings", "Settings, the whole screen", "Setup, the morning routine, duplicate jobs, your templates, what is searched and the limits, the job sites, saving a job from your browser, backups, and stopping the program.", full=True)
    card = lambda name: page.locator(f'#page section:has(h2:text-is("{name}"))')  # noqa: E731
    tall(4200)
    tidy_paths()
    shot("settings-setup", "Setup", "A green dot for what is ready, red for what is missing, grey for something optional. Keys and passwords stay in the .env file and are never shown.", target=card("Setup"), pad=8)
    shot("settings-every-morning", "Every morning", "Pick a time and click Run every morning; the Mac then runs the morning routine daily while it is awake.", target=card("Every morning"), pad=8)
    shot("settings-duplicate-jobs", "Duplicate jobs", "If the same job is stored twice, Merge folds the copies together and keeps your score and status.", target=card("Duplicate jobs"), pad=8)
    shot("settings-templates-email", "Your templates: Email", "The wording used for every recruiter email. Text in [square brackets] is filled in for each job.", target=card("Your templates"), pad=8)
    page.locator('[data-act="tpl-show"][data-to="ctpl"]').click()
    settle(300)
    shot("settings-templates-cover-letter", "Your templates: Cover letter", "The buttons at the top right switch between the email, general email and cover letter templates.", target=card("Your templates"), pad=8)
    page.locator('[data-act="tpl-show"][data-to="tpl"]').click()
    page.fill('[data-cfg="search.max_age_days"]', "7")
    page.fill('[data-cfg="matching.prescreen_model"]', "claude-haiku-5-5")
    page.locator('[data-act="cfg-save"]').click()
    expect(page.locator('[data-act="cfg-reset"]')).to_be_visible()
    settle(500)
    shot("settings-search-and-limits", "Search and limits", "What is searched for and the limits. A value that differs from config.yaml is marked changed; Go back to config.yaml drops your changes.", target=card("Search and limits"), pad=8)
    page.locator('label.sw:has(input[data-site="Stripe"])').click()
    expect(page.locator("#sitecount")).to_have_text("10 of 12 on")
    page.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")
    settle(400)
    shot("settings-sites", "Sites", "A job board can be given its own browser, so Browserbase time goes only to the boards that refuse the browser on this Mac. Below, one switch per job site: a site that is off is skipped by every search. "
         "A site whose last search failed, or that has listed no job in its last three searches, is marked.", target=card("Sites"), pad=8)
    page.locator('[data-act="sites-ill"]').click()
    settle(300)
    shot("settings-sites-problems", "Sites with a problem", "The button lists only the sites that are on but have failed or gone quiet. Switch these off turns them all off at once, after asking; "
         "hover over a mark to see why.", target=card("Sites"), pad=8)
    page.locator('[data-act="sites-ill"]').click()
    shot("settings-save-from-browser", "Save a job from your browser", "Drag the button to your bookmarks bar once. Then, on any job page or LinkedIn post in your own browser, click the bookmark: "
         "Job Search opens with the post filled in, and nothing is added until you choose Add the job.", target=card("Save a job from your browser"), pad=8)
    shot("settings-backups", "Backups", "Back up now copies the whole database into the backups folder. The morning routine also makes one each day.", target=card("Backups"), pad=8)
    normal()
    page.locator('[data-act="quit"]').scroll_into_view_if_needed()
    page.locator('[data-act="quit"]').click()
    settle(300)
    shot("stop-job-search-question", "Stop Job Search", "Stops the program completely, after asking. Double-click Job Search to start it again.")
    ask_no()

    # ---- a narrow window
    section("On a narrow window")
    page.set_viewport_size({"width": 390, "height": 844})
    go("shortlist")
    top()
    settle(500)
    shot("narrow-shortlist", "A narrow window", "The same screens on a phone-sized window.")
    page.locator(".menu-btn").click()
    settle(600)
    shot("narrow-menu", "The menu on a narrow window", "It opens from the button with three lines at the top left.")
    page.locator(".menuscrim").click(position={"x": 370, "y": 400})
    settle(400)
    open_job(ids[0])
    shot("narrow-job", "A job on a narrow window", "The panel fills the window.")
    close_job()
    page.close()

    # ---- when something is missing
    section("When something is missing")
    c2 = db.connect(EMPTY)
    c2.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    db.migrate(c2)
    empty, base2 = serve(EMPTY)
    page = ctx.new_page()
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(base2 + "/")
    expect(page.locator("#notices")).to_contain_text("Import your resume")
    settle(700)
    shot("first-run-no-resume", "Before the first search", "With no resume imported, the page says so at the top and offers the button. Nothing else starts until then.")
    db.save_profile(c2, "Alex Morgan", "resume", {})
    c2.execute("DELETE FROM schema_migrations WHERE name = (SELECT max(name) FROM schema_migrations)")
    page.reload()
    expect(page.locator("#notices")).to_contain_text("The database needs")
    settle(700)
    shot("database-needs-an-update", "After an update of the program", "When new features need a change to the database, a bar at the top offers Update the database.")
    c2.close()
    gone = web.serve(Settings(database_url="postgresql://localhost:1/nowhere"), cfg, 0)
    threading.Thread(target=gone.serve_forever, daemon=True).start()
    page.goto(f"http://127.0.0.1:{gone.server_address[1]}/")
    expect(page.locator("#notices")).to_contain_text("The database is not answering")
    settle(700)
    shot("database-not-answering", "When PostgreSQL is not running", "The page says the database is not answering. Start PostgreSQL, then reload.")
    page.close()
    ctx.close()
    browser.close()
    for s in (server, empty, gone):
        s.runner.stop()
        s.feed.close()
        s.shutdown()
        s.server_close()
conn.close()

# ---------------------------------------------------------------- the index
lines = ["# The Job Search website in pictures", "",
         "One picture for each thing the website does, in the order you would meet them. They were taken on a demo copy with made-up jobs,",
         "people, employers and addresses, so nothing here is real data, and nothing was sent or searched to make them.",
         "[WEBSITE_GUIDE.md](../WEBSITE_GUIDE.md) explains each of these in words.", ""]
last = None
for grp, file, title, text in index:
    if grp != last:
        lines += [f"## {grp}", ""]
        last = grp
    lines += [f"### {title}", "", text, "", f"![{title}]({file})", ""]
(SHOTS / "README.md").write_text("\n".join(lines) + "\n")


def looks_real(shown: dict[str, str]) -> list[str]:
    """Anything in the pictures' words that looks like a real detail. The demo copy holds none,
    so a hit means the script or the page has changed in a way that needs a look."""
    own = {p for p in re.split(r"\W+", f"{Path.home().name} {getpass.getuser()} "
                               + subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, cwd=PROJECT).stdout) if len(p) > 3}
    hints = {"recruiter@company.com", "hr@acme.sa"}  # example addresses that are part of the page itself
    checks = {
        "an email address that is not a made-up one": re.compile(r"[A-Za-z0-9._%+-]+@(?![A-Za-z0-9.-]*\.example\b)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
        "a phone number": re.compile(r"(?<!\d)(?:\+\d{1,3}[- ]?)?\d{10}(?!\d)|\+91"),
        "a folder on this computer": re.compile(r"/Users/(?!you/)|/home/(?!you/)|/private/|/var/folders"),
        "a key or password": re.compile(r"sk-ant|api[_ -]?key\s*[:=]|app password\s*[:=]|token=", re.I),
    }
    if own:
        checks["the name of this computer's user"] = re.compile(r"\b(" + "|".join(re.escape(p) for p in sorted(own)) + r")\b", re.I)
    found = []
    for file, text in shown.items():
        for what, pattern in checks.items():
            for hit in {m.group(0) for m in pattern.finditer(text)}:
                if not (what.startswith("an email") and (hit in hints or hit.endswith("@example.com"))):
                    found.append(f"{file}: {what}")
    return sorted(set(found))


problems = looks_real({**words, "README.md": (SHOTS / "README.md").read_text()})
if problems:
    sys.exit("The pictures were not replaced, because their words hold something that looks real:\n  " + "\n  ".join(problems))
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("*.png"):
    old.unlink()
for new in sorted(SHOTS.iterdir()):
    shutil.copy2(new, OUT / new.name)
print(f"{len(index)} pictures and their index are in {OUT}")
