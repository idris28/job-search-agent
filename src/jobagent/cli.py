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
    conn = db.connect(settings.database_url)
    pending = db.pending_migrations(conn)
    if pending:
        conn.close()
        raise ConfigError(f"The database is {len(pending)} update(s) behind ({', '.join(pending)}). "
                          "Run: jsa migrate")
    return conn


def _llm(settings: Settings):
    from .llm import make_llm

    return make_llm(settings)


def _screen(settings: Settings, cfg):
    """The cheaper AI client for the quick first check, when one is set."""
    from .llm import make_llm

    return make_llm(settings, cfg.matching.prescreen_model) if cfg.matching.prescreen_model else None


def _reader(settings: Settings, cfg):
    """The cheaper AI client that reads job-site pages, when one is set."""
    from .llm import make_llm

    return make_llm(settings, cfg.matching.reader_model) if cfg.matching.reader_model else None


def _profile_id(conn) -> int:
    p = db.active_profile(conn)
    if not p:
        raise ConfigError("No profile yet. Run: jsa profile import <resume.pdf>")
    return p["id"]


def _notify_strong(settings, cfg, rows) -> None:
    """Message the user about new jobs scoring at or above matching.notify_min_score."""
    from . import notifier

    floor = cfg.matching.notify_min_score
    strong = [r for r in rows if floor and r["score"] >= floor]
    if not strong:
        return
    try:
        how = notifier.notify(settings, f"{len(strong)} strong new job match(es)",
                              notifier.strong_match_lines(strong))
    except Exception as e:  # noqa: BLE001 - a failed message must not fail the run
        print(f"  ! Could not send the notification: {str(e).splitlines()[0]}")
        return
    if how:
        print(f"Notified you by {how} about {len(strong)} job(s) scoring {floor} or more.")


def _matches_table(rows) -> str:
    return table([{**r, "posted": age(r.get("posted_at"))} for r in rows], MATCH_COLS)


# --- commands ---------------------------------------------------------------


def cmd_migrate(args, settings):
    settings.require("database_url")
    with db.connect(settings.database_url) as conn:
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


def _spent(s) -> str:
    """The tokens of a search and, where the prices are known, about what they cost."""
    from . import costs

    money = costs.in_words(s.usage)
    return f"{s.tokens:,} tokens" + (f", {money}" if money else "")


def _browser_time(browser) -> str:
    """How long the browsers ran, and how much of that was Browserbase, which is the paid part."""
    total, hosted = browser.minutes_used, browser.minutes("browserbase")
    if not total:
        return ""
    return f", {total:.1f} browser minutes" + (f" ({hosted:.1f} of them on Browserbase)" if 0 < hosted < total else
                                               " (on Browserbase)" if hosted else "")


def cmd_run(args, settings):
    from .browser import Browsers
    from .pipeline import run_agent

    cfg = AgentConfig.load(args.config)
    llm = _llm(settings)
    browser = Browsers(settings)
    try:
        with _conn(settings) as conn:
            s = run_agent(conn, cfg, llm, browser, only_source=args.source,
                          score=not args.no_score, prescreen=_screen(settings, cfg),
                          reader=_reader(settings, cfg), batch=cfg.matching.batch_searches, leave_batch=True)
            print(f"\nRun #{s.run_id}: {s.status}. {s.found} jobs found, {s.new} new, "
                  f"{s.filtered} filtered out, {s.scored} scored "
                  + (f"and {s.screened_out} ruled out by the quick check " if s.screened_out else "") +
                  f"({s.skipped_unchanged} unchanged, not re-scored), "
                  + (f"{s.unread} waiting for their page to be read, " if s.unread else "")
                  + (f"{s.batched} sent for scoring as a batch, " if s.batched else "") +
                  f"{s.shortlisted} shortlisted, {_spent(s)}"
                  + (f" ({llm.cache_read_tokens:,} read from cache)" if getattr(llm, "cache_read_tokens", 0) else "")
                  + _browser_time(browser) + ".")
            if s.stopped:
                print(f"  ! Stopped early: {s.stopped}. Raise the limit in config.yaml or run again later.")
            for name, err in s.source_errors.items():
                print(f"  ! {name}: {err}")
            rows = db.top_matches(conn, _profile_id(conn), run_id=s.run_id,
                                  min_score=cfg.matching.shortlist_min_score, limit=15)
            if rows:
                print("\nTop new matches (newest first):\n" + _matches_table(rows))
            _notify_strong(settings, cfg, rows)
    finally:
        browser.close()


def cmd_score(args, settings):
    """Score the stored jobs that were never scored, without reading any site again."""
    from .pipeline import run_agent

    cfg = AgentConfig.load(args.config)
    llm = _llm(settings)
    with _conn(settings) as conn:
        s = run_agent(conn, cfg, llm, None, collect=False, prescreen=_screen(settings, cfg), batch=args.batch)
        print(f"\nRun #{s.run_id}: {s.status}. {s.scored} scored, "
              + (f"{s.screened_out} ruled out by the quick check, " if s.screened_out else "")
              + f"{s.shortlisted} shortlisted, {_spent(s)}.")
        if s.stopped:
            print(f"  ! Stopped early: {s.stopped}. The rest wait for the next time.")
        rows = db.top_matches(conn, _profile_id(conn), run_id=s.run_id,
                              min_score=cfg.matching.shortlist_min_score, limit=15)
        if rows:
            print("\nTop new matches (newest first):\n" + _matches_table(rows))
        _notify_strong(settings, cfg, rows)


def cmd_delete(args, settings):
    """Remove a pasted post or a general application you added yourself."""
    from .actions import ActionError, delete_added_job

    with _conn(settings) as conn:
        pid = _profile_id(conn)
        job = db.get_job(conn, args.job_id)
        if not job:
            sys.exit(f"No job {args.job_id}")
        if not args.yes and input(f"Delete #{job['id']} {job['title']}, {job['company']} for good? [y/N] ").strip().lower() != "y":
            sys.exit("Nothing deleted.")
        try:
            delete_added_job(conn, pid, args.job_id)
        except ActionError as e:
            sys.exit(str(e))
    print(f"Deleted #{args.job_id}.")


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
        if m["salary_estimate"]:
            print(f"Pay: {m['salary_estimate']}")
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
        cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
        template = cfg.outreach.cover_letter_template()
        print("Cover letter format: " + (f"your template ({cfg.outreach.cover_letter_template_file})"
                                         if template else "built-in"))
        text = _llm(settings).cover_letter(p["resume_text"], posting.as_prompt_text(), template,
                                           cfg.outreach)
        db.save_cover_letter(conn, p["id"], args.job_id, text)
    print("\n" + text)
    from .models import unfilled_placeholders

    unfilled = unfilled_placeholders(text)
    if unfilled:
        print(f"\n! Fill in before using: {', '.join(unfilled)}")
    print("\n(Draft saved to the application record. Review and edit before sending.)")


def cmd_answers(args, settings):
    """Write short answers for a job site's application form. The person pastes them in; the
    program submits nothing."""
    from .models import ANSWER_NAMES, JobPosting

    with _conn(settings) as conn:
        p = db.active_profile(conn)
        job = db.get_job(conn, args.job_id)
        if not p or not job:
            sys.exit("Need an imported profile and a valid job id.")
        posting = JobPosting(**{k: job[k] for k in ("title", "company", "url", "location", "remote_type", "description")})
        answers = _llm(settings).application_answers(p["resume_text"], posting.as_prompt_text()).model_dump()
        db.save_answers(conn, p["id"], args.job_id, answers)
    for key, name in ANSWER_NAMES:
        if answers.get(key):
            print(f"\n{name}:\n{answers[key]}")
    print(f"\n(Saved with job #{args.job_id}. Read each one before you paste it into the site's form.)")


def _job_for_writing(conn, job_id: int):
    """(profile, the job's text for the model, the job) for a command that writes something for one job."""
    from .models import JobPosting

    p, job = db.active_profile(conn), db.get_job(conn, job_id)
    if not p or not job:
        sys.exit("Need an imported profile and a valid job id.")
    posting = JobPosting(**{k: job[k] for k in ("title", "company", "url", "location", "remote_type", "description")})
    return p, posting.as_prompt_text(), job


def cmd_cv(args, settings):
    """Write a CV for one job from the resume: the same facts, with what the posting asks for
    first. It is checked against the resume, saved as a PDF, and attached to nothing until the
    person switches that on."""
    from datetime import datetime, timezone

    from . import tailor
    from .actions import applicant_details

    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    with _conn(settings) as conn:
        p, text, job = _job_for_writing(conn, args.job_id)
        cv, notes = tailor.check(_llm(settings).tailored_resume(p["resume_text"], text), p["resume_text"],
                                 (p.get("profile") or {}).get("years_experience"))
        if not cv["experience"]:
            sys.exit("The CV was not written: none of its jobs could be matched to your resume. Try again.")
        details = dict(applicant_details(p, cfg.outreach))
        name = details.get("Name") or "Resume"
        contact = [v for v in (details.get("Email") or settings.gmail_address, details.get("Phone"), details.get("LinkedIn"),
                               details.get("Where you are")) if v]
        file = tailor.file_for(cfg.outreach.tailored_folder, args.job_id, name, cfg.outreach.resume_filename)
        tailor.write_pdf(tailor.page_html(name, contact, cv), file)
        db.save_tailored_cv(conn, p["id"], args.job_id, {"cv": cv, "notes": notes, "file": str(file), "attach": False,
                                                         "written_at": datetime.now(timezone.utc).isoformat()})
    print(f"CV for #{args.job_id} ({job['title']}): {file}")
    for note in notes:
        print(f"  ! {note}")
    print("(Read it before you use it. This job's email carries your usual CV until you switch on "
          "\"Attach it to this job's email\" in the job's panel.)")


def cmd_linkedin(args, settings):
    """Write a connection note and a direct message for the recruiter of one job. The person
    sends them on LinkedIn; the program never signs in there."""
    from .models import NOTE_LIMIT, fit_note

    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    with _conn(settings) as conn:
        p, text, job = _job_for_writing(conn, args.job_id)
        app = db.get_application(conn, p["id"], args.job_id) or {}
        prefs = {"notice_period": cfg.outreach.notice_period}
        written = _llm(settings).linkedin_messages(p["resume_text"], text, app.get("recruiter_name"), prefs)
        messages = {"note": fit_note(written.note), "message": written.message.strip()}
        db.save_linkedin(conn, p["id"], args.job_id, messages)
    print(f"LinkedIn messages for #{args.job_id} ({job['title']})")
    print(f"\nConnection note ({len(messages['note'])} of {NOTE_LIMIT} characters):\n{messages['note']}")
    print(f"\nMessage ({len(messages['message'].split())} words):\n{messages['message']}")
    print("\n(Saved with the job. Send them yourself on LinkedIn; read them first.)")


def cmd_prep(args, settings):
    """Write interview preparation for one job: likely questions with points for each answer,
    questions to ask, and what to revise first."""
    with _conn(settings) as conn:
        p, text, job = _job_for_writing(conn, args.job_id)
        match = db.get_match(conn, p["id"], args.job_id)
        prep = _llm(settings).interview_prep(p["resume_text"], text, (match or {}).get("missing_skills") or []).model_dump()
        db.save_prep(conn, p["id"], args.job_id, prep)
    print(f"Interview preparation for #{args.job_id} ({job['title']})")
    for heading, key in (("Technical questions", "technical"), ("About your work", "experience")):
        print(f"\n{heading}:")
        for q in prep[key]:
            print(f"- {q['question']}")
            for point in q["points"]:
                print(f"    {point}")
    for heading, key in (("Questions to ask them", "ask_them"), ("Revise first", "revise")):
        if prep[key]:
            print(f"\n{heading}:")
            for line in prep[key]:
                print(f"- {line}")
    print(f"\n(Saved with job #{args.job_id}.)")


def cmd_email(args, settings):
    """Check live postings, research each company, draft recruiter emails. Never sends."""
    from datetime import date

    from .browser import Browsers
    from .models import (GENERAL_URL, JobPosting, company_named, names_missing_company,
                         unfilled_placeholders)
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
    # General applications differ only in the employer's name and country, so one written email
    # serves every address in the same country: the name is swapped in afterwards.
    general_cache: dict[tuple, object] = {}
    stand_in, stand_in_short = "Zentrovia Holdings", "Zentrovia"
    roles = ", ".join(cfg.search.roles) or "software engineer"
    llm = _llm(settings)
    browser = None if args.no_browse else Browsers(settings)
    # A posting is checked with the browser its job board is read with, when that board names one.
    board_browser = {s.name: s.browser for s in cfg.sources}
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
                general = job["url"].startswith(GENERAL_URL)  # an HR address with no posting
                job_template = outreach.general_template() if general else template
                if general and not job_template:
                    print(f"  ! skipped: {outreach.general_template_file or 'general_template_file'} "
                          "is missing, and the job email format does not fit a general application")
                    continue
                live = None
                if browser and job["url"].startswith("http"):  # pasted posts have no page
                    print("  checking live posting...")
                    try:
                        board = conn.execute("SELECT name FROM sources WHERE id = %s", (job["source_id"],)).fetchone() \
                            if job.get("source_id") else None
                        live = browser.of(board_browser.get(board["name"] if board else "", "")).fetch(job["url"], wait_ms=1500).text
                    except Exception as ex:  # noqa: BLE001
                        print(f"  ! could not open posting: {str(ex).splitlines()[0]}")
                country = country_of(job["location"])
                if research_on and not general and country not in guidance_cache:
                    print(f"  researching what recruiters in {country} look for...")
                    try:
                        guidance_cache[country] = llm.research_email_content(
                            roles, country, outreach.max_searches)
                    except Exception as ex:  # noqa: BLE001
                        print(f"  ! research failed: {str(ex).splitlines()[0]}")
                        guidance_cache[country] = None
                notes = None if general else guidance_cache.get(country)
                job_text = posting.as_prompt_text()
                if general:
                    named = company_named(job["company"])
                    key = (job["location"] or "", named)
                    if key not in general_cache:
                        print("  drafting the general application email...")
                        sample = posting.model_copy(update={"company": stand_in}) if named else posting
                        general_cache[key] = llm.recruiter_email(
                            p["resume_text"], sample.as_prompt_text(), None, None, outreach,
                            template=job_template)
                    else:
                        print("  reusing the general application email")
                    e = general_cache[key].model_copy(deep=True)
                    e.recruiter_name = e.contact_email = None
                    if named:
                        for field in ("subject", "body", "follow_up_subject", "follow_up_body"):
                            text = getattr(e, field) or ""
                            setattr(e, field, text.replace(stand_in, job["company"])
                                    .replace(stand_in_short, job["company"]))
                else:
                    print("  drafting email...")
                    e = llm.recruiter_email(p["resume_text"], job_text, live, notes, outreach,
                                            template=job_template)
                review = None
                if review_on and not general:
                    for attempt in range(outreach.max_revisions + 1):
                        review = llm.review_email(e, job_text, p["resume_text"], country)
                        print(f"  recruiter review: {review.score}/10"
                              + ("" if review.score >= outreach.min_review_score
                                 or attempt == outreach.max_revisions else ", revising..."))
                        if review.score >= outreach.min_review_score or attempt == outreach.max_revisions:
                            break
                        e = llm.recruiter_email(p["resume_text"], job_text, live, notes, outreach,
                                                previous=e, review=review)
                known = db.get_application(conn, p["id"], jid)
                kind = "recruiter"
                if not e.contact_email and known and known["contact_email"]:
                    e.contact_email, kind = known["contact_email"], known["contact_kind"] or "recruiter"
                body = e.plain_text()
                unfilled = unfilled_placeholders(f"{e.subject}\n{body}\n{e.follow_up_body}")
                if names_missing_company(f"{e.subject}\n{body}\n{e.follow_up_body}", job["company"]):
                    unfilled.append(f'company name ("{job["company"]}" is not a real name)')
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
                              "review": review, "unfilled": unfilled, "contact_kind": kind})
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
        _deliver(items, settings, outreach, send=args.send, general=args.general)
    stem = Path(args.out or f"digests/emails-{date.today():%Y-%m-%d}").with_suffix("")
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".md").write_text("\n".join(md))
    stem.with_suffix(".html").write_text(
        emails_html(items, title=f"Recruiter emails · {date.today():%d %b %Y}"))
    print(f"\nWrote {len(items)} draft(s): {stem.with_suffix('.html')} (open this) "
          f"and {stem.with_suffix('.md')}")


def _send_slots(conn, pid, outreach) -> int:
    from .actions import send_slots

    return send_slots(conn, pid, outreach)


def _deliver(items, settings, outreach, *, send: bool, general: bool = False) -> None:
    """Send each ready draft from the user's Gmail, or save it to Gmail Drafts.

    A draft is ready only with a recipient on the posting, an open posting and no unfilled
    placeholder. A job already marked applied is never emailed again. Sending stops at the
    daily cap and pauses between emails.
    """
    import time

    from . import mailer
    from .report import email_body_html
    from .tailor import tailored_file

    settings.require("gmail_address", "gmail_app_password")

    def cv_for(conn, pid, it) -> tuple[str, Path | None]:
        made = tailored_file(db.get_application(conn, pid, it["job"]["id"]))
        if made is not None:  # the person asked for this job's email to carry the CV written for it
            return "written for this job", made
        name, path = outreach.resume_for(f"{it['job']['title']} {it['job']['description'] or ''}")
        cv = Path(path).expanduser() if path else None
        if cv is not None and not cv.is_file():
            raise ConfigError(f"CV file not found for '{name}': {cv}")
        return name, cv

    with _conn(settings) as conn:
        pid = _profile_id(conn)
        done = {a["job_id"] for a in db.list_applications(conn, pid) if a["status"] != "shortlisted"}
        slots = _send_slots(conn, pid, outreach) if send else 10**9
        ready = []
        for it in items:
            jid = it["job"]["id"]
            why = ("no email address on the posting" if not it["email"].contact_email else
                   "posting looks closed" if it["status"] == "closed" else
                   "unfilled placeholders" if it["unfilled"] else
                   "only a general inbox was found; add --general to use it"
                   if it.get("contact_kind") == "general" and not general else
                   "already applied or set aside" if send and jid in done else
                   f"daily limit of {outreach.max_sends_per_day} emails reached" if len(ready) >= slots
                   else None)
            if why:
                print(f"  not emailed: #{jid} ({why}): {it['job']['url']}")
            else:
                ready.append(it)
        built = []
        for it in ready:
            name, cv = cv_for(conn, pid, it)
            if send and cv is None:
                raise ConfigError("Set outreach.resume_path before sending: the emails say the CV is attached.")
            built.append((it, name, cv, mailer.build_message(
                settings.gmail_address, it["email"].contact_email, it["email"].subject,
                it["email"].plain_text(), email_body_html(it["email"]), cv)))
        if not built:
            print("No emails to " + ("send." if send else "save as drafts."))
        elif send:
            for n, (it, name, cv, msg) in enumerate(built):
                if n and outreach.send_pause_seconds:
                    time.sleep(outreach.send_pause_seconds)
                mailer.send_messages(settings.gmail_address, settings.gmail_app_password, [msg])
                db.set_application_status(conn, pid, it["job"]["id"], "applied",
                                          f"emailed {it['email'].contact_email}", history_only=True)
                db.mark_outreach_sent(conn, pid, it["job"]["id"])
                print(f"  sent: #{it['job']['id']} to {it['email'].contact_email} (CV: {cv.name})")
            print(f"Sent {len(built)} email(s) from {settings.gmail_address}. A follow-up is due in "
                  f"{outreach.follow_up_days} days: jsa followups")
        else:
            n = mailer.save_drafts(settings.gmail_address, settings.gmail_app_password,
                                   [m for _, _, _, m in built])
            for it, name, cv, _ in built:
                print(f"  draft: #{it['job']['id']} (CV: {cv.name if cv else 'none, set outreach.resume_path'})")
            print(f"Saved {n} draft(s) to Gmail Drafts. Review and send them from Gmail.")


def cmd_followups(args, settings):
    """List emailed jobs whose follow-up is due, and send those follow-ups with --send."""
    import time

    from . import mailer
    from .report import _paragraphs_html

    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    outreach = cfg.outreach
    with _conn(settings) as conn:
        pid = _profile_id(conn)
        due = db.followups_due(conn, pid, outreach.follow_up_days)
        if not due:
            print(f"No follow-ups due. One becomes due {outreach.follow_up_days} days after an email is sent.")
            return
        print(f"{len(due)} follow-up(s) due today:")
        for r in due:
            print(f"  #{r['job_id']} {r['title']} at {r['company']}: emailed "
                  f"{r['outreach_sent_at']:%d %b} to {r['contact_email']}")
        if not args.send:
            print("Send them with: jsa followups --send   (or reply in Gmail and run: jsa followups --done <id>)")
            for jid in args.done or []:
                db.mark_follow_up_sent(conn, pid, jid)
                print(f"  #{jid} marked as followed up")
            return
        settings.require("gmail_address", "gmail_app_password")
        slots = _send_slots(conn, pid, outreach)
        for n, r in enumerate(due):
            if n >= slots:
                print(f"  not sent: #{r['job_id']} (daily limit of {outreach.max_sends_per_day} emails reached)")
                continue
            if not (r["contact_email"] and r["follow_up_body"]):
                print(f"  not sent: #{r['job_id']} (no address or follow-up text stored)")
                continue
            if n and outreach.send_pause_seconds:
                time.sleep(outreach.send_pause_seconds)
            msg = mailer.build_message(settings.gmail_address, r["contact_email"], r["follow_up_subject"],
                                       r["follow_up_body"], _paragraphs_html(r["follow_up_body"]))
            mailer.send_messages(settings.gmail_address, settings.gmail_app_password, [msg])
            db.mark_follow_up_sent(conn, pid, r["job_id"])
            print(f"  sent follow-up: #{r['job_id']} to {r['contact_email']}")


_REPLY_WORDS = {"reply": "reply", "automatic": "automatic reply", "bounced": "not delivered"}


def _check_replies(conn, settings, pid) -> list[str]:
    """Look in the Gmail inbox for answers to the emails that were sent, record them, and say what
    was found. Read-only: see replies.py."""
    from . import replies

    waiting = db.awaiting_reply(conn, pid)
    if not waiting:
        return ["No emailed job is waiting for a reply."]
    found = replies.find_replies(settings.gmail_address, settings.gmail_app_password, waiting)
    db.save_replies(conn, pid, [r["job_id"] for r in waiting], found)
    lines = [f"Looked in Gmail for answers to {len(waiting)} email(s): {sum(r['kind'] == 'reply' for r in found.values())} replied, "
             f"{sum(r['kind'] == 'bounced' for r in found.values())} not delivered."]
    for row in waiting:
        r = found.get(row["job_id"])
        if r:
            lines.append(f"  {_REPLY_WORDS[r['kind']]}: #{row['job_id']} {row['title']} at {row['company']} "
                         f"({row['contact_email']}, {r['at']:%d %b}): \"{r['subject']}\"")
    return lines


def cmd_replies(args, settings):
    """Look in Gmail for answers to the emails that were sent. Only when it is switched on."""
    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    if not cfg.outreach.check_replies:
        sys.exit('Looking in Gmail for replies is switched off. Switch on "Look in Gmail for replies" under Settings on the page '
                 "(outreach.check_replies).")
    settings.require("gmail_address", "gmail_app_password")
    with _conn(settings) as conn:
        print("\n".join(_check_replies(conn, settings, _profile_id(conn))))
    print("(A job that was answered, or whose address refused the email, gets no follow-up. Read the reply in Gmail.)")


def cmd_daily(args, settings):
    """The morning job: search, write the digest, list follow-ups, and email yourself one summary."""
    from datetime import date

    from . import mailer
    from .browser import Browsers
    from .pipeline import run_agent
    from .report import _paragraphs_html

    cfg = AgentConfig.load(args.config)
    llm, browser = _llm(settings), Browsers(settings)
    try:
        with _conn(settings) as conn:
            s = run_agent(conn, cfg, llm, browser, prescreen=_screen(settings, cfg), reader=_reader(settings, cfg),
                          batch=cfg.matching.batch_scoring)
            pid = _profile_id(conn)
            new = db.top_matches(conn, pid, run_id=s.run_id, min_score=cfg.matching.shortlist_min_score, limit=20)
            if cfg.outreach.check_replies and settings.gmail_address and settings.gmail_app_password:
                try:  # before the follow-ups are listed, so an answered email is not followed up
                    print("\n".join(_check_replies(conn, settings, pid)))
                except Exception as e:  # noqa: BLE001 - a mailbox that does not answer must not fail the morning routine
                    print(f"Replies were not checked: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
            due = db.followups_due(conn, pid, cfg.outreach.follow_up_days)
            waiting = len(db.shortlisted_job_ids(conn, pid, 1000))
    finally:
        browser.close()
    _notify_strong(settings, cfg, new)
    Path("digests").mkdir(exist_ok=True)
    digest = Path(f"digests/{date.today():%Y-%m-%d}.md")
    digest.write_text(digest_markdown(new, title=f"New matches {date.today():%d %b %Y}"), encoding="utf-8")
    lines = [f"Run #{s.run_id}: {s.status}. {s.found} jobs found, {s.new} new, {s.scored} scored, "
             f"{s.shortlisted} shortlisted, {_spent(s)}."]
    lines += [f"Stopped early: {s.stopped}."] if s.stopped else []
    lines += [f"Site problem: {name}: {str(err).splitlines()[0]}" for name, err in s.source_errors.items()]
    lines += ["", f"New strong matches ({len(new)}):"] + [
        f"- #{r['job_id']} {r['title']} at {r['company']} ({r['location'] or 'n/a'}), score {r['score']}"
        for r in new] or ["- none today"]
    lines += ["", f"Follow-ups due ({len(due)}):"] + [
        f"- #{r['job_id']} {r['title']} at {r['company']}" for r in due]
    lines += ["", f"{waiting} job(s) on your shortlist. Next: jsa email --gmail-drafts, jsa apply, jsa followups."]
    summary = "\n".join(lines)
    print(summary + f"\nDigest: {digest}")
    if settings.gmail_address and settings.gmail_app_password:
        msg = mailer.build_message(settings.gmail_address, settings.gmail_address,
                                   f"Job search: {len(new)} new matches, {len(due)} follow-ups due",
                                   summary, _paragraphs_html(summary))
        mailer.send_messages(settings.gmail_address, settings.gmail_app_password, [msg])
        print(f"Summary emailed to {settings.gmail_address}.")
    if cfg.backup.daily:
        from .backup import BackupError

        try:
            print(_backup(settings, cfg))
        except BackupError as e:  # a missed backup must not fail the morning routine
            print(f"No backup today: {e}")


def _backup(settings, cfg) -> str:
    """Make a backup and say what was written, in one line."""
    from .backup import human_size, make_backup

    settings.require("database_url")
    b = make_backup(settings.database_url, cfg.backup.folder, keep=cfg.backup.keep, repo=Path.cwd())
    return (f"Backed up to {b['file']} ({human_size(b['size'])})"
            + (f", with a copy of the code in {b['code'].name}" if b["code"] else "")
            + f". The newest {cfg.backup.keep} are kept.")


def cmd_backup(args, settings):
    """Copy the database (and the code's history) into the backups folder."""
    from .backup import BackupError

    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    try:
        print(_backup(settings, cfg))
    except BackupError as e:
        sys.exit(str(e))
    print("To bring one back: pg_restore --clean --if-exists --no-owner --dbname <database> <file>")


def cmd_schedule(args, settings):
    """Install, remove or show the launchd job that runs `jsa daily` each morning."""
    from . import scheduler

    if args.action == "status":
        print(scheduler.status())
    elif args.action == "remove":
        print("Daily schedule removed." if scheduler.remove() else "No daily schedule was installed.")
    else:
        hour, _, minute = args.time.partition(":")
        if not (hour.isdigit() and minute.isdigit() and int(hour) < 24 and int(minute) < 60):
            raise ConfigError("--time must be HH:MM, for example 08:00")
        for needed in (".env", "config.yaml"):
            if not Path(needed).exists():
                raise ConfigError(f"Run this from the project folder: {needed} was not found here.")
        path = scheduler.install(Path.cwd(), int(hour), int(minute))
        print(f"Installed. `jsa daily` will run every day at {int(hour):02d}:{int(minute):02d} "
              f"while this Mac is awake.\n{path}\nRemove it with: jsa schedule remove")


def cmd_web(args, settings):
    """Open the local web app: every command as a button, on this Mac only."""
    import webbrowser

    from . import web

    settings.require("database_url")
    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    try:
        server = web.serve(settings, cfg, args.port, config_path=args.config)
    except OSError as e:
        raise ConfigError(f"Port {args.port} is in use: the page may already be open at "
                          f"http://127.0.0.1:{args.port}/ ({e.strerror})") from e
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Job search page: {url}   (Ctrl-C to stop)", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.runner.stop()
        server.server_close()


def cmd_send(args, settings):
    """Send the saved drafts as they are, edits included, or save them to Gmail Drafts."""
    import time

    from . import mailer
    from .actions import ActionError, send_stored_draft, stored_draft_message

    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    outreach = cfg.outreach
    with _conn(settings) as conn:
        pid = _profile_id(conn)
        ids = args.job_ids or db.shortlisted_job_ids(conn, pid, args.limit)
        if not ids:
            print("Nothing to send: no job ids given and nothing is shortlisted.")
            return
        sent, drafts = 0, []
        for jid in ids:
            try:
                if args.gmail_drafts:
                    msg, to = stored_draft_message(conn, settings, outreach, pid, jid,
                                                   allow_general=args.general, need_cv=False)
                    drafts.append(msg)
                    print(f"  draft: #{jid} to {to}", flush=True)
                else:
                    if sent and outreach.send_pause_seconds:
                        time.sleep(outreach.send_pause_seconds)
                    to = send_stored_draft(conn, settings, outreach, pid, jid, allow_general=args.general)
                    sent += 1
                    print(f"  sent: #{jid} to {to}", flush=True)
            except ActionError as e:
                print(f"  not {'saved' if args.gmail_drafts else 'sent'}: #{jid} ({e})", flush=True)
        if args.gmail_drafts:
            n = mailer.save_drafts(settings.gmail_address, settings.gmail_app_password, drafts) if drafts else 0
            print(f"Saved {n} draft(s) to Gmail Drafts. Review and send them from Gmail.")
        else:
            print(f"Sent {sent} email(s)." + (f" A follow-up is due in {outreach.follow_up_days} days."
                                              if sent else ""))


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
                db.set_application_status(conn, pid, j["id"], "applied", "applied on the job site", history_only=True)
                applied += 1
            elif answer == "s":
                db.set_application_status(conn, pid, j["id"], "skipped")
        if not args.dry_run:
            print(f"Marked {applied} job(s) as applied.")


def cmd_add(args, settings, *, read=None):
    """Add a job from pasted text (for example a LinkedIn post that says to email a CV)."""
    from .actions import ActionError, add_pasted_job

    from .llm import picture_kind

    raw = Path(args.file).read_bytes() if args.file else None
    kind = picture_kind(raw) if raw else None
    llm = _llm(settings) if kind else None
    if kind:  # a screenshot or photo of the post: its text is read first, and shown
        text = llm.read_pictures([(raw, kind)])
        if not text:
            sys.exit("No text was found in that picture. Try a clearer screenshot.")
        print(f"Text read from the picture (check the email address):\n{text}\n")
    else:
        text = (raw.decode("utf-8") if raw is not None else (read or sys.stdin.read)()).strip()
    if not text:
        sys.exit("Nothing to add: paste the post text, then press Ctrl-D (or pass a file).")
    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    llm = llm or _llm(settings)
    with _conn(settings) as conn:
        try:
            job_id, is_new, found, m = add_pasted_job(conn, llm, cfg, text, args.url)
        except ActionError as e:
            sys.exit(str(e))
        app = db.get_application(conn, _profile_id(conn), job_id) or {}
        first_seen = (db.get_job(conn, job_id) or {}).get("first_seen_at")
    print(f"{'Added' if is_new else 'Updated'} job #{job_id}: {found.title} at {found.company}"
          f" ({found.location or 'location not given'})")
    print(f"Match score {m.score} ({m.verdict}): {m.summary}")
    sent = app.get("outreach_sent_at")
    if sent:
        # The same post pasted again after its email went: say what happened, and offer no second email.
        from datetime import timedelta

        def day(d):
            return d.astimezone().strftime("%d %b").lstrip("0")

        follow_up = ("Its follow-up has gone too." if app.get("follow_up_sent_at")
                     else f"Its follow-up is due from {day(sent + timedelta(days=cfg.outreach.follow_up_days))}."
                     if app.get("status") == "applied" else "")
        print(f"You added this post before{', on ' + day(first_seen) if first_seen else ''}. Its email went to "
              f"{app.get('contact_email') or 'the recruiter'} on {day(sent)} at {sent.astimezone():%H:%M}, "
              f"so nothing is sent again by itself. {follow_up}".rstrip())
        print("To write to them once more, open the job on the website and use Send again.")
    elif found.contact_email:
        print(f"Applications go to {found.contact_email}. Next: jsa email {job_id} --gmail-drafts"
              f"   (or --send)")
    else:
        print(f"No email address found in the text. Next: jsa email {job_id}")


def cmd_add_contacts(args, settings, *, read=None):
    """Add HR addresses as general applications (no posting), ready to draft and send."""
    from .actions import ActionError, add_hr_contacts

    text = (Path(args.file).read_text(encoding="utf-8") if args.file else (read or sys.stdin.read)()).strip()
    if not text:
        sys.exit("Nothing to add: give one address per line, optionally with the employer's name.")
    cfg = AgentConfig.load(args.config) if Path(args.config).exists() else AgentConfig()
    with _conn(settings) as conn:
        try:
            result = add_hr_contacts(conn, cfg, text, args.country)
        except ActionError as e:
            sys.exit(str(e))
    for a in result["added"]:
        print(f"  added #{a['job_id']}: {a['email']} ({a['company']}{', ' + a['country'] if a['country'] else ''})")
    for line, why in result["skipped"]:
        print(f"  skipped: {line} ({why})")
    print(f"Added {len(result['added'])} general application(s), skipped {len(result['skipped'])}. "
          "They are on your shortlist with no email drafted yet.")


def cmd_contacts(args, settings):
    """Look on each company's own website for a published application address."""
    import httpx

    from .contacts import verify_contact
    from .models import company_key

    llm = _llm(settings)
    http = httpx.Client(headers={"User-Agent": "jobagent/0.1 (personal job search)"})
    seen: dict[str, tuple[dict | None, str]] = {}
    try:
        with _conn(settings) as conn:
            pid = _profile_id(conn)
            if args.job_ids:
                jobs = [{"job_id": j["id"], **{k: j[k] for k in ("title", "company", "location")}}
                        for j in (db.get_job(conn, i) for i in args.job_ids) if j]
            else:
                jobs = db.jobs_needing_contact(conn, pid, args.limit)
            if not jobs:
                print("Every shortlisted job already has an address, or nothing is shortlisted.")
                return
            found_n = 0
            for j in jobs:
                key = company_key(j["company"])
                if key not in seen:  # one search per company, however many of its jobs you have
                    try:
                        seen[key] = verify_contact(llm.find_contact(j["company"], j["location"]),
                                                   j["company"], http)
                    except Exception as e:  # noqa: BLE001
                        seen[key] = (None, f"the search failed: {str(e).splitlines()[0]}")
                contact, why = seen[key]
                if contact:
                    db.save_contact(conn, pid, j["job_id"], contact["email"], contact["source_url"],
                                    contact["kind"])
                    found_n += 1
                    note = "  (general inbox: not used unless you add --general)" if contact["kind"] == "general" else ""
                    print(f"#{j['job_id']} {j['company']}: {contact['email']} [{contact['kind']}]{note}\n"
                          f"    from {contact['source_url']}")
                else:
                    print(f"#{j['job_id']} {j['company']}: none ({why})")
            print(f"\nFound an address for {found_n} of {len(jobs)} job(s). "
                  + ("Their emails can now be drafted and sent." if found_n else
                     "None of these companies publishes one: apply on the job sites, "
                     "or add an address yourself if you find one."))
    finally:
        http.close()


def cmd_gaps(args, settings):
    """The skills job postings ask for most often that your resume does not show."""
    with _conn(settings) as conn:
        total, rows = db.skill_gaps(conn, _profile_id(conn), args.days, args.min_score, args.limit)
    if not rows:
        print(f"No scored jobs at {args.min_score} or more in the last {args.days} days.")
        return
    print(f"Skills missing most often, across {total} jobs scoring {args.min_score}+ "
          f"in the last {args.days} days:\n")
    for r in rows:
        share = round(100 * r["jobs"] / total) if total else 0
        print(f"  {r['skill'][:34]:<34} {r['jobs']:>4} jobs  {share:>3}%  {'#' * max(1, share // 3)}")
    print("\nLearning the top few, or adding ones you already know to your resume and re-importing it, "
          "raises your scores.")


def cmd_progress(args, settings):
    """A summary of the last week: what you applied to, what was sent, and which sites deliver."""
    with _conn(settings) as conn:
        pid = _profile_id(conn)
        p = db.progress(conn, pid, args.days)
        waiting = len(db.shortlisted_job_ids(conn, pid, 100000))
    m, mail = p["moves"], p["mail"]
    print(f"Last {args.days} days\n")
    print(f"  Shortlisted   {m.get('shortlisted', 0):>4}      Emails sent      {mail['sent']:>4}")
    print(f"  Applied       {m.get('applied', 0):>4}      Follow-ups sent  {mail['followed_up']:>4}")
    print(f"  Interviewing  {m.get('interviewing', 0):>4}      Offers           {m.get('offer', 0):>4}")
    print(f"  Rejected      {m.get('rejected', 0):>4}      Skipped          {m.get('skipped', 0):>4}")
    if mail["emailed_ever"]:
        rate = round(100 * mail["answered_ever"] / mail["emailed_ever"])
        print(f"\n  Reply rate: {mail['answered_ever']} of {mail['emailed_ever']} emailed jobs moved on "
              f"to an interview, offer or rejection ({rate}%).")
    print(f"  Still on your shortlist: {waiting}")
    if p["sources"]:
        print("\n" + table(p["sources"], [("source", "Source", 26), ("found", "Found", 6),
                                          ("shortlisted", "Shortlisted", 11), ("applied", "Applied", 7)]))


def cmd_dedupe(args, settings):
    """Show jobs stored more than once, and merge them with --apply."""
    with _conn(settings) as conn:
        groups = db.duplicate_groups(conn)
        if not groups:
            print("No duplicate jobs.")
            return
        extra = sum(len(g["drop"]) for g in groups)
        for g in groups:
            k = g["keep"]
            print(f"keep #{k['id']} {k['title']} at {k['company']} ({k['location'] or 'n/a'})")
            for d in g["drop"]:
                print(f"   merge #{d['id']} {d['title']} at {d['company']} ({d['location'] or 'n/a'})")
        if not args.apply:
            print(f"\n{extra} duplicate row(s) in {len(groups)} group(s). Nothing was changed. "
                  "Merge them with: jsa dedupe --apply")
            return
        removed = db.merge_duplicates(conn)
        print(f"\nMerged {removed} duplicate row(s). Scores and application status were kept on the copy "
              "shown as 'keep'.")


def cmd_notify_test(args, settings):
    """Send yourself a test notification."""
    from . import notifier

    how = notifier.notify(settings, "Job search agent: test message", ["Notifications are working."])
    print(f"Sent by {how}." if how else
          "Nothing is set up. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env, or the Gmail settings.")


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
        rows = db.settled_runs(conn, args.limit)
    cols = [("id", "Run", 5), ("status", "Status", 10), ("started_at", "Started", 19),
            ("jobs_found", "Found", 6), ("jobs_new", "New", 5), ("jobs_scored", "Scored", 6),
            ("tokens_used", "Tokens", 8), ("cost_usd", "Cost $", 7), ("error", "Error", 30)]
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

    sc = sub.add_parser("score", help="score stored jobs that were never scored, without searching again")
    sc.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    sc.add_argument("--batch", action="store_true", help="send the scoring as one batch: half price, answered later (Claude only)")
    sc.set_defaults(fn=cmd_score)

    dl = sub.add_parser("delete", help="remove a pasted post or a general application you added")
    dl.add_argument("job_id", type=int)
    dl.add_argument("--yes", action="store_true", help="do not ask first")
    dl.set_defaults(fn=cmd_delete)

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

    an = sub.add_parser("answers", help="write short answers for a job site's application form")
    an.add_argument("job_id", type=int)
    an.set_defaults(fn=cmd_answers)

    cv = sub.add_parser("cv", help="write a CV for one job from your resume, as a PDF")
    cv.add_argument("job_id", type=int)
    cv.set_defaults(fn=cmd_cv)

    li = sub.add_parser("linkedin", help="write a LinkedIn connection note and message for one job's recruiter")
    li.add_argument("job_id", type=int)
    li.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    li.set_defaults(fn=cmd_linkedin)

    pr = sub.add_parser("prep", help="write interview preparation for one job")
    pr.add_argument("job_id", type=int)
    pr.set_defaults(fn=cmd_prep)

    cl = sub.add_parser("cover-letter", help="draft a cover letter for a job")
    cl.add_argument("job_id", type=int)
    cl.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    cl.set_defaults(fn=cmd_cover_letter)

    em = sub.add_parser("email", help="check live postings and draft recruiter emails (never sends)")
    em.add_argument("job_ids", type=int, nargs="*", help="jobs to email (default: shortlisted)")
    em.add_argument("--limit", type=int, default=10, help="max shortlisted jobs when no ids given")
    em.add_argument("--no-browse", action="store_true", help="skip opening the live posting")
    em.add_argument("--no-research", action="store_true", help="skip web research on recruiter advice")
    em.add_argument("--no-review", action="store_true", help="skip the recruiter-style review")
    em.add_argument("--gmail-drafts", action="store_true",
                    help="also save drafts that have a recipient to your Gmail Drafts (never sends)")
    em.add_argument("--general", action="store_true",
                    help="also use a general inbox (info@...) found by `jsa contacts`")
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
    ad.add_argument("file", nargs="?", help="text file, or a picture (PNG, JPG, WebP, GIF), of the post (default: paste, then Ctrl-D)")
    ad.add_argument("--url", help="link to the post, if you have one")
    ad.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    ad.set_defaults(fn=cmd_add)

    rp = sub.add_parser("replies", help="look in Gmail for answers to the emails you sent (off unless switched on)")
    rp.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    rp.set_defaults(fn=cmd_replies)

    fu = sub.add_parser("followups", help="list follow-ups that are due; --send sends them")
    fu.add_argument("--send", action="store_true", help="send the due follow-ups from your Gmail")
    fu.add_argument("--done", type=int, nargs="*", help="mark these jobs as followed up by hand")
    fu.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    fu.set_defaults(fn=cmd_followups)

    dl = sub.add_parser("daily", help="search, write the digest and email yourself one summary")
    dl.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    dl.set_defaults(fn=cmd_daily)

    bk = sub.add_parser("backup", help="copy the database and the code's history into the backups folder")
    bk.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    bk.set_defaults(fn=cmd_backup)

    sc = sub.add_parser("schedule", help="run `jsa daily` every morning (macOS)")
    sc.add_argument("action", choices=["install", "remove", "status"])
    sc.add_argument("--time", default="08:00", help="when to run each day, HH:MM (default 08:00)")
    sc.set_defaults(fn=cmd_schedule)

    wb = sub.add_parser("web", help="open the local web app: every command as a button")
    wb.add_argument("--port", type=int, default=8765)
    wb.add_argument("--no-open", action="store_true", help="do not open the browser")
    wb.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    wb.set_defaults(fn=cmd_web)

    sd = sub.add_parser("send", help="send the saved drafts as they are (no redrafting)")
    sd.add_argument("job_ids", type=int, nargs="*", help="jobs to send (default: shortlisted)")
    sd.add_argument("--limit", type=int, default=25, help="max shortlisted jobs when no ids given")
    sd.add_argument("--gmail-drafts", action="store_true", help="save to Gmail Drafts instead of sending")
    sd.add_argument("--general", action="store_true", help="also use a general inbox (info@...)")
    sd.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    sd.set_defaults(fn=cmd_send)

    ac = sub.add_parser("add-contacts", help="add HR addresses as general applications (no posting)")
    ac.add_argument("file", nargs="?", help="text file, one address per line (default: paste, then Ctrl-D)")
    ac.add_argument("--country", help="where these employers are, e.g. \"Saudi Arabia\"")
    ac.add_argument("--config", default=os.getenv("JOBAGENT_CONFIG", "config.yaml"))
    ac.set_defaults(fn=cmd_add_contacts)

    ct = sub.add_parser("contacts", help="look for a published application address for shortlisted jobs")
    ct.add_argument("job_ids", type=int, nargs="*", help="jobs to look up (default: shortlisted without one)")
    ct.add_argument("--limit", type=int, default=10)
    ct.set_defaults(fn=cmd_contacts)

    gp = sub.add_parser("gaps", help="skills you are most often missing")
    gp.add_argument("--days", type=int, default=30)
    gp.add_argument("--min-score", type=int, default=50, help="only count jobs scoring at least this")
    gp.add_argument("--limit", type=int, default=15)
    gp.set_defaults(fn=cmd_gaps)

    pg = sub.add_parser("progress", help="summary of the last week")
    pg.add_argument("--days", type=int, default=7)
    pg.set_defaults(fn=cmd_progress)

    dd = sub.add_parser("dedupe", help="show jobs stored twice; --apply merges them")
    dd.add_argument("--apply", action="store_true", help="merge the duplicates")
    dd.set_defaults(fn=cmd_dedupe)

    sub.add_parser("notify-test", help="send yourself a test notification").set_defaults(fn=cmd_notify_test)

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
    _unwind_on_terminate()
    try:
        args.fn(args, Settings.from_env())
    except ConfigError as e:
        sys.exit(f"Config error: {e}")
    except KeyboardInterrupt:
        sys.exit("Stopped before it finished.")


def _unwind_on_terminate() -> None:
    """Treat a terminate signal like Ctrl-C.

    The page's Stop button and a shutdown end the program with SIGTERM, which by default stops it
    dead. Raising KeyboardInterrupt instead lets a search record where it ended and lets the
    browser session close.
    """
    import signal

    def stop(signum, frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, stop)
    except ValueError:  # not the main thread: nothing to install
        pass


if __name__ == "__main__":
    main()
