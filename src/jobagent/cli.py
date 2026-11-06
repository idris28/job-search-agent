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
