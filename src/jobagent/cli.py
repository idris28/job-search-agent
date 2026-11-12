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
from .report import MATCH_COLS, age, digest_markdown, table


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


def _matches_table(rows) -> str:
    return table([{**r, "posted": age(r.get("posted_at"))} for r in rows], MATCH_COLS)


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
                print("\nTop new matches (newest first):\n" + _matches_table(rows))
    finally:
        browser.close()


def cmd_jobs(args, settings):
    with _conn(settings) as conn:
        rows = db.top_matches(conn, _profile_id(conn), min_score=args.min_score, limit=args.limit,
                              include_status=not args.untracked)
    print(_matches_table(rows) if rows else "No matches at that score yet.")


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
                if browser and job["url"].startswith("http"):  # pasted posts have no page
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
    if args.gmail_drafts or args.send:
        _deliver(items, settings, outreach, send=args.send)
    stem = Path(args.out or f"digests/emails-{date.today():%Y-%m-%d}").with_suffix("")
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".md").write_text("\n".join(md))
    stem.with_suffix(".html").write_text(
        emails_html(items, title=f"Recruiter emails · {date.today():%d %b %Y}"))
    print(f"\nWrote {len(items)} draft(s): {stem.with_suffix('.html')} (open this) "
          f"and {stem.with_suffix('.md')}")


def _deliver(items, settings, outreach, *, send: bool) -> None:
    """Send each ready draft from the user's Gmail, or save it to Gmail Drafts.

    A draft is ready only with a recipient on the posting, an open posting and no unfilled
    placeholder. A job already marked applied is never emailed again.
    """
    from .mailer import build_message, save_drafts, send_messages
    from .report import email_body_html

    settings.require("gmail_address", "gmail_app_password")
    cv = Path(outreach.resume_path).expanduser() if outreach.resume_path else None
    if cv is not None and not cv.is_file():
        raise ConfigError(f"outreach.resume_path not found: {cv}")
    if send and cv is None:
        raise ConfigError("Set outreach.resume_path before sending: the emails say the CV is attached.")
    with _conn(settings) as conn:
        pid = _profile_id(conn)
        done = {a["job_id"] for a in db.list_applications(conn, pid) if a["status"] != "shortlisted"}
        ready = []
        for it in items:
            jid = it["job"]["id"]
            why = ("no email address on the posting" if not it["email"].contact_email else
                   "posting looks closed" if it["status"] == "closed" else
                   "unfilled placeholders" if it["unfilled"] else
                   "already applied or set aside" if send and jid in done else None)
            if why:
                print(f"  not emailed: #{jid} ({why}): {it['job']['url']}")
            else:
                ready.append(it)
        messages = [build_message(settings.gmail_address, it["email"].contact_email,
                                  it["email"].subject, it["email"].plain_text(),
                                  email_body_html(it["email"]), cv) for it in ready]
        if not messages:
            print("No emails to " + ("send." if send else "save as drafts."))
        elif send:
            for it, msg in zip(ready, messages):
                send_messages(settings.gmail_address, settings.gmail_app_password, [msg])
                db.set_application_status(conn, pid, it["job"]["id"], "applied",
                                          f"emailed {it['email'].contact_email}")
                print(f"  sent: #{it['job']['id']} to {it['email'].contact_email}")
            print(f"Sent {len(messages)} email(s) from {settings.gmail_address}.")
        else:
            n = save_drafts(settings.gmail_address, settings.gmail_app_password, messages)
            print(f"Saved {n} draft(s) to Gmail Drafts" + ("" if cv else " (no CV attached: set "
                  "outreach.resume_path)") + ". Review and send them from Gmail.")


def cmd_apply(args, settings, *, open_url=None, ask=input):
    """Open each shortlisted job's page in the user's own browser and record what they did.

    Job sites block automated browsers, so the click is the user's: they are already signed in
    there, and no bot check gets in the way.
    """
    import webbrowser

    open_url = open_url or webbrowser.open
    with _conn(settings) as conn:
        pid = _profile_id(conn)
        ids = args.job_ids or db.shortlisted_job_ids(conn, pid, args.limit)
        jobs = [j for j in (db.get_job(conn, i) for i in ids) if j]
        if not jobs:
            print("Nothing to apply to: no job ids given and nothing is shortlisted.")
            return
        applied = 0
        for n, j in enumerate(jobs, 1):
            print(f"[{n}/{len(jobs)}] #{j['id']} {j['title']} at {j['company']} ({j['location'] or 'n/a'})")
            if args.dry_run:
                print(f"    {j['url']}")
                continue
            open_url(j["url"])
            answer = ask("    Opened in your browser. Applied? [y = yes, n = not now, s = skip this job, q = quit] ").strip().lower()
            if answer == "q":
                break
            if answer == "y":
                db.set_application_status(conn, pid, j["id"], "applied", "applied on the job site")
                applied += 1
            elif answer == "s":
                db.set_application_status(conn, pid, j["id"], "skipped")
        if not args.dry_run:
            print(f"Marked {applied} job(s) as applied.")


def cmd_add(args, settings, *, read=None):
    """Add a job from pasted text (for example a LinkedIn post that says to email a CV)."""
    import hashlib
    from datetime import datetime, timezone

    from .models import JobPosting

    text = (Path(args.file).read_text(encoding="utf-8") if args.file
            else (read or sys.stdin.read)()).strip()
    if not text:
        sys.exit("Nothing to add: paste the post text, then press Ctrl-D (or pass a file).")
    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    llm = _llm(settings)
    found = llm.read_pasted_job(text)
    url = args.url or "pasted:" + hashlib.sha256(text.encode()).hexdigest()[:16]
    description = found.description + (f"\n\nSend applications to: {found.contact_email}"
                                       if found.contact_email else "")
    posting = JobPosting(title=found.title, company=found.company, url=url, location=found.location,
                         description=description, posted_at=datetime.now(timezone.utc))
    with _conn(settings) as conn:
        p = db.active_profile(conn)
        if not p:
            sys.exit("No profile yet. Run: jsa profile import <resume.pdf>")
        job_id, is_new = db.upsert_job(conn, posting, None, None)
        m = llm.score_job(p["profile"], cfg.search, posting)
        db.save_match(conn, p["id"], job_id, None, m, llm.model, posting.content_hash)
        db.set_application_status_if_missing(conn, p["id"], job_id, "added from pasted text")
    print(f"{'Added' if is_new else 'Updated'} job #{job_id}: {found.title} at {found.company}"
          f" ({found.location or 'location not given'})")
    print(f"Match score {m.score} ({m.verdict}): {m.summary}")
    if found.contact_email:
        print(f"Applications go to {found.contact_email}. Next: jsa email {job_id} --gmail-drafts"
              f"   (or --send)")
    else:
        print(f"No email address found in the text. Next: jsa email {job_id}")


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
    em.add_argument("--send", action="store_true",
                    help="send the emails that have a recipient from your Gmail, CV attached")
    em.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    em.add_argument("--out", help="output path without extension (default: digests/emails-<date>)")
    em.set_defaults(fn=cmd_email)

    apl = sub.add_parser("apply", help="open shortlisted jobs in your browser to apply, and record it")
    apl.add_argument("job_ids", type=int, nargs="*", help="jobs to open (default: shortlisted)")
    apl.add_argument("--limit", type=int, default=10, help="max shortlisted jobs when no ids given")
    apl.add_argument("--dry-run", action="store_true", help="list the jobs without opening them")
    apl.set_defaults(fn=cmd_apply)

    ad = sub.add_parser("add", help="add a job from pasted text, e.g. a LinkedIn post")
    ad.add_argument("file", nargs="?", help="text file with the post (default: paste, then Ctrl-D)")
    ad.add_argument("--url", help="link to the post, if you have one")
    ad.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    ad.set_defaults(fn=cmd_add)

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
