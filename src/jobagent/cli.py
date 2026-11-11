"""Command line: `jsa <command>`. Run `jsa -h` for help."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import db
from .config import AgentConfig, ConfigError, Settings, load_dotenv
from .report import MATCH_COLS, digest_markdown, table


def _conn(settings: Settings):
    settings.require("database_url")
    return db.connect(settings.database_url)


def _llm(settings: Settings):
    from .llm import make_llm

    return make_llm(settings)


def _profile_id(conn) -> int:
    p = db.active_profile(conn)
    if not p:
        raise ConfigError("No profile yet. Run: jsa profile import <resume.pdf>")
    return p["id"]


# --- commands ---------------------------------------------------------------


def cmd_migrate(args, settings):
    with _conn(settings) as conn:
        applied = db.migrate(conn)
    print("Applied: " + ", ".join(applied) if applied else "Database is up to date.")


def cmd_profile_import(args, settings):
    from .resume import read_resume

    text = read_resume(args.resume)
    profile = _llm(settings).extract_profile(text)
    with _conn(settings) as conn:
        pid = db.save_profile(conn, profile.name, text, profile.model_dump())
    print(f"Saved profile #{pid} for {profile.name}:")
    print(json.dumps(profile.model_dump(), indent=2))


def cmd_profile_show(args, settings):
    with _conn(settings) as conn:
        p = db.active_profile(conn)
    if not p:
        print("No profile yet. Run: jsa profile import <resume.pdf>")
        return
    print(f"Profile #{p['id']} ({p['name']}), imported {p['created_at']:%Y-%m-%d}")
    print(json.dumps(p["profile"], indent=2))


def cmd_run(args, settings):
    from .browser import LazyBrowser
    from .pipeline import run_agent

    cfg = AgentConfig.load(args.config)
    llm = _llm(settings)
    browser = LazyBrowser(settings)
    try:
        with _conn(settings) as conn:
            s = run_agent(conn, cfg, llm, browser, only_source=args.source,
                          score=not args.no_score)
            print(f"\nRun #{s.run_id}: {s.status}. {s.found} jobs found, {s.new} new, "
                  f"{s.filtered} filtered out, {s.scored} scored "
                  f"({s.skipped_unchanged} unchanged, not re-scored), "
                  f"{s.shortlisted} shortlisted, {s.tokens} tokens.")
            for name, err in s.source_errors.items():
                print(f"  ! {name}: {err}")
            rows = db.top_matches(conn, _profile_id(conn), run_id=s.run_id,
                                  min_score=cfg.matching.shortlist_min_score, limit=15)
            if rows:
                print("\nTop new matches:\n" + table(rows, MATCH_COLS))
    finally:
        browser.close()


def cmd_jobs(args, settings):
    with _conn(settings) as conn:
        rows = db.top_matches(conn, _profile_id(conn), min_score=args.min_score, limit=args.limit,
                              include_status=not args.untracked)
    print(table(rows, MATCH_COLS) if rows else "No matches at that score yet.")


def cmd_show(args, settings):
    with _conn(settings) as conn:
        pid = _profile_id(conn)
        job = db.get_job(conn, args.job_id)
        if not job:
            sys.exit(f"No job {args.job_id}")
        m = conn.execute("SELECT * FROM job_matches WHERE job_id=%s AND profile_id=%s",
                         (args.job_id, pid)).fetchone()
    print(f"{job['title']} at {job['company']}\n{job['location']} · {job['remote_type']}\n{job['url']}")
    if m:
        print(f"\nScore {m['score']} ({m['verdict']}): {m['summary']}")
        print(f"Matches: {', '.join(m['matched_skills'])}")
        print(f"Gaps: {', '.join(m['missing_skills'])}")
        if m["red_flags"]:
            print(f"Red flags: {', '.join(m['red_flags'])}")
    if args.full and job["description"]:
        print("\n" + job["description"])


def cmd_status(args, settings):
    with _conn(settings) as conn:
        pid = _profile_id(conn)
        if not db.get_job(conn, args.job_id):
            sys.exit(f"No job {args.job_id}")
        db.set_application_status(conn, pid, args.job_id, args.status, args.note)
    print(f"Job {args.job_id} -> {args.status}")


def cmd_applications(args, settings):
    with _conn(settings) as conn:
        rows = db.list_applications(conn, _profile_id(conn))
    cols = [("job_id", "ID", 6), ("status", "Status", 12), ("score", "Score", 5),
            ("title", "Title", 38), ("company", "Company", 20), ("updated_at", "Updated", 16)]
    print(table(rows, cols) if rows else "No tracked applications yet.")


def cmd_cover_letter(args, settings):
    from .models import JobPosting

    with _conn(settings) as conn:
        p = db.active_profile(conn)
        job = db.get_job(conn, args.job_id)
        if not p or not job:
            sys.exit("Need an imported profile and a valid job id.")
        posting = JobPosting(**{k: job[k] for k in ("title", "company", "url", "location",
                                                     "remote_type", "description")})
        text = _llm(settings).cover_letter(p["resume_text"], posting.as_prompt_text())
        db.save_cover_letter(conn, p["id"], args.job_id, text)
    print(text)
    print("\n(Draft saved to the application record. Review and edit before sending.)")


def cmd_email(args, settings):
    """Check live postings, research each company, draft recruiter emails. Never sends."""
    from datetime import date

    from .browser import LazyBrowser
    from .models import JobPosting, unfilled_placeholders
    from .report import emails_html

    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    outreach = cfg.outreach
    template = outreach.template()
    if template:
        print(f"Email format: your template ({outreach.template_file}); "
              "web research and recruiter review are skipped")
    else:
        print("Email format: built-in"
              + (f" ({outreach.template_file} not found)" if outreach.template_file else ""))
    from .filters import country_of

    # Research and review exist to shape the wording. With a template the wording is the
    # candidate's own and fixed, so both would only add paid calls.
    research_on = outreach.research and not args.no_research and not template
    review_on = outreach.review and not args.no_review and not template
    guidance_cache: dict[str, str | None] = {}
    roles = ", ".join(cfg.search.roles) or "software engineer"
    llm = _llm(settings)
    browser = None if args.no_browse else LazyBrowser(settings)
    items: list[dict] = []
    md = [f"# Recruiter emails ({date.today():%Y-%m-%d})",
          "_Drafts only. Review, edit, and send them yourself._", ""]
    try:
        with _conn(settings) as conn:
            p = db.active_profile(conn)
            if not p:
                sys.exit("No profile yet. Run: jsa profile import <resume.pdf>")
            ids = args.job_ids or db.shortlisted_job_ids(conn, p["id"], args.limit)
            if not ids:
                sys.exit("No job ids given and nothing is shortlisted.")
            for jid in ids:
                job = db.get_job(conn, jid)
                if not job:
                    print(f"! No job {jid}, skipping")
                    continue
                print(f"#{jid} {job['title']} at {job['company']}")
                posting = JobPosting(**{k: job[k] for k in (
                    "title", "company", "url", "location", "remote_type", "description")})
                live = None
                if browser:
                    print("  checking live posting...")
                    try:
                        live = browser.fetch(job["url"], wait_ms=1500).text
                    except Exception as ex:  # noqa: BLE001
                        print(f"  ! could not open posting: {str(ex).splitlines()[0]}")
                country = country_of(job["location"])
                if research_on and country not in guidance_cache:
                    print(f"  researching what recruiters in {country} look for...")
                    try:
                        guidance_cache[country] = llm.research_email_content(
                            roles, country, outreach.max_searches)
                    except Exception as ex:  # noqa: BLE001
                        print(f"  ! research failed: {str(ex).splitlines()[0]}")
                        guidance_cache[country] = None
                notes = guidance_cache.get(country)
                print("  drafting email...")
                job_text = posting.as_prompt_text()
                e = llm.recruiter_email(p["resume_text"], job_text, live, notes, outreach,
                                        template=template)
                review = None
                if review_on:
                    for attempt in range(outreach.max_revisions + 1):
                        review = llm.review_email(e, job_text, p["resume_text"], country)
                        print(f"  recruiter review: {review.score}/10"
                              + ("" if review.score >= outreach.min_review_score
                                 or attempt == outreach.max_revisions else ", revising..."))
                        if review.score >= outreach.min_review_score or attempt == outreach.max_revisions:
                            break
                        e = llm.recruiter_email(p["resume_text"], job_text, live, notes, outreach,
                                                previous=e, review=review)
                body = e.plain_text()
                unfilled = unfilled_placeholders(f"{e.subject}\n{body}\n{e.follow_up_body}")
                if unfilled:
                    print(f"  ! fill in before sending: {', '.join(unfilled)}")
                db.save_outreach(conn, p["id"], jid, subject=e.subject, body=body,
                                 recruiter_name=e.recruiter_name, contact_email=e.contact_email,
                                 still_open=e.still_open, research=notes,
                                 follow_up_subject=e.follow_up_subject,
                                 follow_up_body=e.follow_up_body,
                                 review_score=review.score if review else None,
                                 review_notes=review.model_dump_json() if review else None)
                status = "unchecked" if live is None else ("open" if e.still_open else "closed")
                items.append({"job": job, "email": e, "status": status, "research": notes,
                              "review": review, "unfilled": unfilled})
                label = {"open": "still open", "closed": "LOOKS CLOSED - check before sending",
                         "unchecked": "live page not checked"}[status]
                md += [f"## #{jid} {job['title']} at {job['company']}",
                       f"{job['location'] or ''} · [posting]({job['url']}) · {label}",
                       f"To: {e.contact_email or '(no email on the posting - use the apply page or LinkedIn)'}"
                       + (f" · {e.recruiter_name}" if e.recruiter_name else ""),
                       (f"Recruiter review: {review.score}/10. {review.first_impression}"
                        if review else ""),
                       (f"**Fill in before sending:** {', '.join(unfilled)}" if unfilled else ""),
                       "", f"**Subject:** {e.subject}", "", "```", body, "```", "",
                       f"**Follow-up (after 5-7 days):** {e.follow_up_subject}", "", "```",
                       e.follow_up_body, "```", ""]
    finally:
        if browser:
            browser.close()
    if args.gmail_drafts:
        _save_gmail_drafts(items, settings, outreach)
    stem = Path(args.out or f"digests/emails-{date.today():%Y-%m-%d}").with_suffix("")
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".md").write_text("\n".join(md))
    stem.with_suffix(".html").write_text(
        emails_html(items, title=f"Recruiter emails · {date.today():%d %b %Y}"))
    print(f"\nWrote {len(items)} draft(s): {stem.with_suffix('.html')} (open this) "
          f"and {stem.with_suffix('.md')}")


def _save_gmail_drafts(items, settings, outreach) -> None:
    """Put each draft that has a recipient into Gmail Drafts. The user reviews and sends."""
    from .mailer import build_message, save_drafts
    from .report import email_body_html

    settings.require("gmail_address", "gmail_app_password")
    cv = Path(outreach.resume_path).expanduser() if outreach.resume_path else None
    if cv is not None and not cv.is_file():
        raise ConfigError(f"outreach.resume_path not found: {cv}")
    ready = [it for it in items
             if it["email"].contact_email and it["status"] != "closed" and not it["unfilled"]]
    for it in items:
        if it not in ready:
            why = ("no email address on the posting" if not it["email"].contact_email else
                   "posting looks closed" if it["status"] == "closed" else "unfilled placeholders")
            print(f"  no Gmail draft for #{it['job']['id']} ({why}): {it['job']['url']}")
    messages = [build_message(settings.gmail_address, it["email"].contact_email,
                              it["email"].subject, it["email"].plain_text(),
                              email_body_html(it["email"]), cv) for it in ready]
    if messages:
        n = save_drafts(settings.gmail_address, settings.gmail_app_password, messages)
        print(f"Saved {n} draft(s) to Gmail Drafts" + ("" if cv else " (no CV attached: set "
              "outreach.resume_path)") + ". Review and send them from Gmail.")


def cmd_apply_login(args, settings):
    """Open the agent's own browser so the user can sign in to Bayt themselves."""
    from .applier import BAYT_LOGIN_URL, PROFILE_DIR, user_browser

    with user_browser() as page:
        page.goto(BAYT_LOGIN_URL)
        input("A browser window is open. Sign in to Bayt there, then press Enter here... ")
    print(f"Saved. The sign-in is kept in {PROFILE_DIR} for `jsa apply`.")


def cmd_apply(args, settings):
    """Click Bayt's Easy Apply for shortlisted jobs; hand back anything that needs a person."""
    from .applier import apply_on_bayt, is_bayt, user_browser

    with _conn(settings) as conn:
        pid = _profile_id(conn)
        ids = args.job_ids or db.shortlisted_job_ids(conn, pid, args.limit)
        jobs = [j for j in (db.get_job(conn, i) for i in ids) if j]
        todo = [j for j in jobs if is_bayt(j["url"])]
        for j in jobs:
            if j not in todo:
                print(f"#{j['id']} {j['title']} at {j['company']}: not a Bayt job, apply by hand: {j['url']}")
        if not todo:
            print("No Bayt jobs to apply to.")
            return
        needs_person = []
        with user_browser() as page:
            for j in todo:
                r = apply_on_bayt(page, j["url"], dry_run=args.dry_run)
                print(f"#{j['id']} {j['title']} at {j['company']}: {r.status}"
                      + (f" ({r.detail})" if r.detail else ""))
                if r.status in ("applied", "already_applied"):
                    db.set_application_status(conn, pid, j["id"], "applied", "via Bayt Easy Apply")
                elif r.status in ("blocked", "login_needed"):
                    print("Stopping here: the site needs you. Nothing further was attempted.")
                    break
                elif r.status == "needs_you":
                    needs_person.append(j)
                    input("  Finish this application in the browser window, then press Enter... ")
        if needs_person:
            print(f"{len(needs_person)} job(s) needed your input; mark them with: jsa status <id> applied")


def cmd_digest(args, settings):
    with _conn(settings) as conn:
        rows = db.top_matches(conn, _profile_id(conn), min_score=args.min_score,
                              limit=args.limit, run_id=args.run_id)
    md = digest_markdown(rows, title=f"Job matches (score ≥ {args.min_score})")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md)
        print(f"Wrote {args.out}")
    else:
        print(md)


def cmd_runs(args, settings):
    with _conn(settings) as conn:
        rows = db.list_runs(conn, args.limit)
    cols = [("id", "Run", 5), ("status", "Status", 10), ("started_at", "Started", 19),
            ("jobs_found", "Found", 6), ("jobs_new", "New", 5), ("jobs_scored", "Scored", 6),
            ("tokens_used", "Tokens", 8), ("error", "Error", 30)]
    print(table(rows, cols) if rows else "No runs yet.")


# --- parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jsa", description="AI job search agent")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate", help="create/upgrade the database schema").set_defaults(fn=cmd_migrate)

    prof = sub.add_parser("profile", help="manage the candidate profile")
    psub = prof.add_subparsers(dest="pcmd", required=True)
    pi = psub.add_parser("import", help="parse a resume (PDF or text) into a profile")
    pi.add_argument("resume")
    pi.set_defaults(fn=cmd_profile_import)
    psub.add_parser("show").set_defaults(fn=cmd_profile_show)

    r = sub.add_parser("run", help="collect jobs from all sources and score them")
    r.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    r.add_argument("--source", help="only run the source with this name")
    r.add_argument("--no-score", action="store_true", help="collect only, skip LLM scoring")
    r.set_defaults(fn=cmd_run)

    j = sub.add_parser("jobs", help="list scored jobs, best first")
    j.add_argument("--min-score", type=int, default=70)
    j.add_argument("--limit", type=int, default=25)
    j.add_argument("--untracked", action="store_true", help="hide jobs you already acted on")
    j.set_defaults(fn=cmd_jobs)

    s = sub.add_parser("show", help="show one job and its match analysis")
    s.add_argument("job_id", type=int)
    s.add_argument("--full", action="store_true", help="include the full description")
    s.set_defaults(fn=cmd_show)

    st = sub.add_parser("status", help="set application status for a job")
    st.add_argument("job_id", type=int)
    st.add_argument("status", choices=db.APPLICATION_STATUSES)
    st.add_argument("--note")
    st.set_defaults(fn=cmd_status)

    sub.add_parser("applications", help="list tracked applications").set_defaults(fn=cmd_applications)

    cl = sub.add_parser("cover-letter", help="draft a cover letter for a job")
    cl.add_argument("job_id", type=int)
    cl.set_defaults(fn=cmd_cover_letter)

    em = sub.add_parser("email", help="check live postings and draft recruiter emails (never sends)")
    em.add_argument("job_ids", type=int, nargs="*", help="jobs to email (default: shortlisted)")
    em.add_argument("--limit", type=int, default=10, help="max shortlisted jobs when no ids given")
    em.add_argument("--no-browse", action="store_true", help="skip opening the live posting")
    em.add_argument("--no-research", action="store_true", help="skip web research on recruiter advice")
    em.add_argument("--no-review", action="store_true", help="skip the recruiter-style review")
    em.add_argument("--gmail-drafts", action="store_true",
                    help="also save drafts that have a recipient to your Gmail Drafts (never sends)")
    em.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    em.add_argument("--out", help="output path without extension (default: digests/emails-<date>)")
    em.set_defaults(fn=cmd_email)

    al = sub.add_parser("apply-login", help="sign in to Bayt yourself in the agent's browser")
    al.set_defaults(fn=cmd_apply_login)

    apl = sub.add_parser("apply", help="click Easy Apply on Bayt for shortlisted jobs")
    apl.add_argument("job_ids", type=int, nargs="*", help="jobs to apply to (default: shortlisted)")
    apl.add_argument("--limit", type=int, default=10, help="max shortlisted jobs when no ids given")
    apl.add_argument("--dry-run", action="store_true", help="check each posting but click nothing")
    apl.set_defaults(fn=cmd_apply)

    d = sub.add_parser("digest", help="write a Markdown digest of top matches")
    d.add_argument("--min-score", type=int, default=75)
    d.add_argument("--limit", type=int, default=30)
    d.add_argument("--run-id", type=int, help="only jobs first seen in this run")
    d.add_argument("--out", help="file to write (default: stdout)")
    d.set_defaults(fn=cmd_digest)

    rs = sub.add_parser("runs", help="show run history")
    rs.add_argument("--limit", type=int, default=20)
    rs.set_defaults(fn=cmd_runs)
    return ap


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        args.fn(args, Settings.from_env())
    except ConfigError as e:
        sys.exit(f"Config error: {e}")


if __name__ == "__main__":
    main()
