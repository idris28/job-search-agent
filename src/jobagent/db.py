"""PostgreSQL access: migrations and the small set of queries the agent needs."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .filters import country_of
from .models import MIN_READ_CHARS, JobPosting, MatchResult, company_key, title_key

APPLICATION_STATUSES = (
    "shortlisted", "applied", "interviewing", "offer", "rejected", "withdrawn", "skipped",
)


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row, autocommit=True)


# --- migrations -------------------------------------------------------------


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply any migrations/*.sql not yet recorded. Returns names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
    files = sorted(
        (f for f in resources.files("jobagent.migrations").iterdir() if f.name.endswith(".sql")),
        key=lambda f: f.name,
    )
    applied = []
    for f in files:
        if f.name in done:
            continue
        with conn.transaction():
            conn.execute(f.read_text())
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
        applied.append(f.name)
    _backfill_match_keys(conn)
    return applied


def pending_migrations(conn: psycopg.Connection) -> list[str]:
    """Migration files not yet applied to this database."""
    exists = conn.execute("SELECT to_regclass('schema_migrations') AS t").fetchone()["t"]
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")} if exists else set()
    names = sorted(f.name for f in resources.files("jobagent.migrations").iterdir()
                   if f.name.endswith(".sql"))
    return [n for n in names if n not in done]


def match_key(title: str, company: str, location: str | None) -> str:
    """Identity of a job across job boards: company, meaningful title words, country."""
    return f"{company_key(company)}|{title_key(title, location)}|{country_of(location).lower()}"


def _backfill_match_keys(conn) -> None:
    for r in conn.execute("SELECT id, title, company, location FROM jobs WHERE match_key IS NULL").fetchall():
        conn.execute("UPDATE jobs SET match_key = %s WHERE id = %s",
                     (match_key(r["title"], r["company"], r["location"]), r["id"]))


# --- profiles ---------------------------------------------------------------


def save_profile(conn, name: str, resume_text: str, profile: dict) -> int:
    with conn.transaction():
        conn.execute("UPDATE profiles SET is_active = FALSE WHERE is_active")
        row = conn.execute(
            "INSERT INTO profiles (name, resume_text, profile) VALUES (%s, %s, %s) RETURNING id",
            (name, resume_text, Jsonb(profile)),
        ).fetchone()
    return row["id"]


def active_profile(conn) -> dict | None:
    return conn.execute(
        "SELECT * FROM profiles WHERE is_active ORDER BY id DESC LIMIT 1"
    ).fetchone()


# --- sources ----------------------------------------------------------------


def upsert_source(conn, kind: str, name: str, url: str, config: dict) -> int:
    row = conn.execute(
        """INSERT INTO sources (kind, name, url, config) VALUES (%s, %s, %s, %s)
           ON CONFLICT (kind, url) DO UPDATE SET name = EXCLUDED.name, config = EXCLUDED.config
           RETURNING id""",
        (kind, name, url, Jsonb(config)),
    ).fetchone()
    return row["id"]


# --- runs -------------------------------------------------------------------


# A search holds the advisory lock (_RUN_LOCK, run id) on its connection for as long as it runs.
# PostgreSQL drops the lock when that connection ends, however the program ended, so a row still
# marked 'running' with no lock is a search whose program has gone.
_RUN_LOCK = 7_526_114
STOPPED_EARLY = "Stopped before it finished"
CLOSED_EARLY = "The program closed before this search finished"


def start_run(conn, profile_id: int | None, config_snapshot: dict) -> int:
    close_dead_runs(conn)
    run_id = conn.execute("SELECT nextval(pg_get_serial_sequence('runs', 'id')) AS id").fetchone()["id"]
    conn.execute("SELECT pg_advisory_lock(%s, %s)", (_RUN_LOCK, run_id))  # before the row exists
    conn.execute("INSERT INTO runs (id, profile_id, config_snapshot) VALUES (%s, %s, %s)",
                 (run_id, profile_id, Jsonb(config_snapshot)))
    return run_id


def close_dead_runs(conn) -> list[int]:
    """Give an end to searches still marked running whose program is gone. Returns their ids.

    What such a search saved is kept, so it is recorded as partial, with the jobs it added and
    scored counted from the rows that point back to it. How many it found in all was never
    written down; the number it added is the least that can be.
    """
    rows = conn.execute(
        """UPDATE runs r SET status = 'partial', finished_at = now(), error = %s,
               jobs_found = GREATEST(r.jobs_found, (SELECT count(*) FROM jobs j WHERE j.first_run_id = r.id)),
               jobs_new = (SELECT count(*) FROM jobs j WHERE j.first_run_id = r.id),
               jobs_scored = (SELECT count(*) FROM job_matches m WHERE m.run_id = r.id)
           WHERE r.status = 'running' AND NOT EXISTS (
               SELECT 1 FROM pg_locks l JOIN pg_database d ON d.oid = l.database
               WHERE l.locktype = 'advisory' AND l.granted AND d.datname = current_database()
                 AND l.classid = %s AND l.objid::bigint = r.id AND l.objsubid = 2)
           RETURNING r.id""", (CLOSED_EARLY, _RUN_LOCK)).fetchall()
    return sorted(r["id"] for r in rows)


def finish_run(conn, run_id: int, *, status: str, stats: dict, error: str | None = None) -> None:
    conn.execute(
        """UPDATE runs SET status = %s, finished_at = now(), jobs_found = %s, jobs_new = %s,
               jobs_scored = %s, tokens_used = %s, error = %s
           WHERE id = %s""",
        (
            status,
            stats.get("found", 0),
            stats.get("new", 0),
            stats.get("scored", 0),
            stats.get("tokens", 0),
            error,
            run_id,
        ),
    )
    conn.execute("SELECT pg_advisory_unlock(%s, %s)", (_RUN_LOCK, run_id))


def log_event(conn, run_id: int, message: str, *, level: str = "info",
              source_id: int | None = None, data: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO run_events (run_id, source_id, level, message, data) VALUES (%s,%s,%s,%s,%s)",
        (run_id, source_id, level, message, Jsonb(data) if data is not None else None),
    )


def list_runs(conn, limit: int = 20) -> list[dict]:
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT %s", (limit,)).fetchall()


BATCH_SENT, BATCH_TAKEN = "scoring batch sent", "scoring batch collected"


def pending_batches(conn) -> list[dict]:
    """Scoring batches that were sent and whose answers have not been stored yet. What each one
    holds is in the event that recorded it, so a later search can finish the job."""
    return conn.execute(
        """SELECT e.run_id, e.data FROM run_events e
           WHERE e.message = %s AND e.created_at >= now() - interval '28 days'
             AND NOT EXISTS (SELECT 1 FROM run_events d
                             WHERE d.message = %s AND d.data->>'batch' = e.data->>'batch')
           ORDER BY e.id""", (BATCH_SENT, BATCH_TAKEN)).fetchall()


def partial_reason(unread: list[str], stopped: str = "") -> str:
    """Why a search ended only partly finished, as one line: a limit reached, sites not read."""
    parts = [f"Stopped early: {stopped}"] if stopped else []
    if unread:
        names = ", ".join(unread[:4]) + (f" and {len(unread) - 4} more" if len(unread) > 4 else "")
        parts.append(f"{len(unread)} site{'' if len(unread) == 1 else 's'} could not be read: {names}")
    return "; ".join(parts)


def fill_missing_reasons(conn) -> int:
    """Give a reason to partial searches recorded before the reason was stored. Returns how many.

    It is worked out from what each search logged: an error event for a site means that site
    could not be read, and a warning names the spending limit that was reached.
    """
    rows = conn.execute(
        """SELECT r.id,
                  array_agg(s.name ORDER BY e.id) FILTER (
                      WHERE e.level = 'error' AND s.id IS NOT NULL AND e.message LIKE %s) AS unread,
                  max(substring(e.message FROM %s)) FILTER (WHERE e.level = 'warning') AS stopped
           FROM runs r JOIN run_events e ON e.run_id = r.id LEFT JOIN sources s ON s.id = e.source_id
           WHERE r.status = 'partial' AND r.error IS NULL
           GROUP BY r.id""",
        ("%: failed: %", r"((?:token|browser time) limit reached \([^)]*\))")).fetchall()
    filled = 0
    for r in rows:
        reason = partial_reason(r["unread"] or [], r["stopped"] or "")
        if reason:
            conn.execute("UPDATE runs SET error = %s WHERE id = %s AND error IS NULL", (reason, r["id"]))
            filled += 1
    return filled


def settled_runs(conn, limit: int = 20) -> list[dict]:
    """The latest searches to show: cut-off ones are ended and missing reasons filled in first."""
    close_dead_runs(conn)
    fill_missing_reasons(conn)
    return list_runs(conn, limit)


# --- jobs -------------------------------------------------------------------


def upsert_job(conn, job: JobPosting, source_id: int | None, run_id: int | None) -> tuple[int, bool]:
    """Insert or refresh a job. Returns (job_id, is_new).

    The same job listed on another board, with a slightly different title or company suffix,
    refreshes the row already stored instead of creating a second one.
    """
    key = match_key(job.title, job.company, job.location)
    twin = conn.execute(
        "SELECT id FROM jobs WHERE match_key = %s AND fingerprint <> %s ORDER BY id LIMIT 1",
        (key, job.fingerprint)).fetchone()
    if twin:
        conn.execute(
            """UPDATE jobs SET last_seen_at = now(), is_active = TRUE,
                   description = COALESCE(description, %s), posted_at = COALESCE(posted_at, %s)
               WHERE id = %s""", (job.description, job.posted_at, twin["id"]))
        return twin["id"], False
    row = conn.execute(
        """INSERT INTO jobs (source_id, external_id, fingerprint, url, title, company, location,
                             remote_type, employment_type, salary_text, description, posted_at,
                             first_run_id, raw, match_key)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (fingerprint) DO UPDATE SET
               url = EXCLUDED.url,
               description = COALESCE(EXCLUDED.description, jobs.description),
               salary_text = COALESCE(EXCLUDED.salary_text, jobs.salary_text),
               posted_at = COALESCE(EXCLUDED.posted_at, jobs.posted_at),
               remote_type = EXCLUDED.remote_type,
               last_seen_at = now(),
               is_active = TRUE,
               raw = EXCLUDED.raw
           RETURNING id, (xmax = 0) AS inserted""",
        (
            source_id, job.external_id, job.fingerprint, job.url, job.title, job.company,
            job.location, job.remote_type, job.employment_type, job.salary_text,
            job.description, job.posted_at, run_id,
            Jsonb(json.loads(json.dumps(job.raw, default=str))) if job.raw else None, key,
        ),
    ).fetchone()
    return row["id"], row["inserted"]


_POSTING = """title, company, url, location, remote_type, employment_type, salary_text, description,
              posted_at, external_id"""
# A job-board job whose own page has not been opened: only its list line is stored.
_UNREAD = f"""coalesce(s.kind, '') = 'generic' AND coalesce((s.config->>'max_detail_pages')::int, 20) > 0
              AND length(btrim(coalesce(j.description, ''))) < {MIN_READ_CHARS}"""


def stored_posting(conn, job: JobPosting) -> dict | None:
    """The stored row for a listed job, found the way upsert_job would find it: the same link, the
    same company, title and place, or the same job on another board."""
    return conn.execute(
        f"""SELECT {_POSTING} FROM jobs WHERE url = %s OR fingerprint = %s OR match_key = %s
            ORDER BY (url = %s) DESC, (fingerprint = %s) DESC, id LIMIT 1""",
        (job.url, job.fingerprint, match_key(job.title, job.company, job.location), job.url, job.fingerprint)).fetchone()


def unread_postings(conn, seen_within_days: int, *, source_id: int | None = None, brief: bool = False) -> list[dict]:
    """Job-board jobs listed recently whose own page was never opened, newest first. For one board
    when `source_id` is given. `brief` leaves the text out and names the board, for counting."""
    columns = "j.title, j.company, j.url, j.location, j.remote_type, j.posted_at, s.name AS board" if brief \
        else ", ".join("j." + c.strip() for c in _POSTING.split(","))
    return conn.execute(
        f"""SELECT {columns} FROM jobs j JOIN sources s ON s.id = j.source_id
            WHERE j.is_active AND j.url LIKE 'http%%' AND {_UNREAD}
              AND j.last_seen_at >= now() - make_interval(days => %s) AND (%s::int IS NULL OR j.source_id = %s)
            ORDER BY j.posted_at DESC NULLS LAST, j.id DESC LIMIT 500""",
        (seen_within_days, source_id, source_id)).fetchall()


def existing_match_hash(conn, profile_id: int, job_id: int) -> str | None:
    row = conn.execute(
        "SELECT content_hash FROM job_matches WHERE profile_id = %s AND job_id = %s",
        (profile_id, job_id),
    ).fetchone()
    return row["content_hash"] if row else None


def save_match(conn, profile_id: int, job_id: int, run_id: int | None, m: MatchResult,
               model: str, content_hash: str) -> None:
    conn.execute(
        """INSERT INTO job_matches (profile_id, job_id, run_id, score, verdict, summary,
                                    matched_skills, missing_skills, red_flags, model, content_hash,
                                    salary_estimate)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (profile_id, job_id) DO UPDATE SET
               run_id = EXCLUDED.run_id, score = EXCLUDED.score, verdict = EXCLUDED.verdict,
               summary = EXCLUDED.summary, matched_skills = EXCLUDED.matched_skills,
               missing_skills = EXCLUDED.missing_skills, red_flags = EXCLUDED.red_flags,
               model = EXCLUDED.model, content_hash = EXCLUDED.content_hash,
               salary_estimate = EXCLUDED.salary_estimate, created_at = now()""",
        (
            profile_id, job_id, run_id, max(0, min(100, m.score)), m.verdict, m.summary,
            m.matched_skills, m.missing_skills, m.red_flags, model, content_hash,
            m.salary_estimate,
        ),
    )


def top_matches(conn, profile_id: int, *, min_score: int = 0, limit: int = 25,
                run_id: int | None = None, include_status: bool = True) -> list[dict]:
    sql = """
        SELECT j.id AS job_id, j.title, j.company, j.location, j.remote_type, j.url,
               j.salary_text, j.first_seen_at, j.posted_at, m.score, m.verdict, m.summary,
               m.matched_skills, m.missing_skills, m.red_flags, m.salary_estimate,
               a.status AS application_status
        FROM job_matches m
        JOIN jobs j ON j.id = m.job_id
        LEFT JOIN applications a ON a.job_id = j.id AND a.profile_id = m.profile_id
        WHERE m.profile_id = %s AND m.score >= %s AND j.is_active
    """
    params: list[Any] = [profile_id, min_score]
    if run_id is not None:
        sql += " AND j.first_run_id = %s"
        params.append(run_id)
    if not include_status:
        sql += " AND a.id IS NULL"
    # Newest postings first; jobs with no known posting date come after, best score first.
    sql += " ORDER BY j.posted_at DESC NULLS LAST, m.score DESC, j.first_seen_at DESC LIMIT %s"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def get_job(conn, job_id: int) -> dict | None:
    return conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()


def delete_job(conn, job_id: int) -> None:
    """Remove a job for good; its score, application and history go with it."""
    conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,))


def unscored_jobs(conn, profile_id: int, seen_within_days: int, *, brief: bool = False) -> list[dict]:
    """Jobs a search stored but never scored for this profile, still listed recently, newest first.

    General applications are left out: they have no posting to score. So are job-board jobs whose
    own page was never opened: a later search reads the page first. `brief` cuts the description
    to what the rule filters read, for counting many rows cheaply.
    """
    description = "left(j.description, 1200)" if brief else "j.description"
    return conn.execute(
        f"""SELECT j.id, j.title, j.company, j.url, j.location, j.remote_type, j.employment_type,
                   j.salary_text, {description} AS description, j.posted_at, j.external_id
            FROM jobs j LEFT JOIN sources s ON s.id = j.source_id
            WHERE j.is_active AND j.url NOT LIKE 'general:%%' AND NOT ({_UNREAD})
              AND j.last_seen_at >= now() - make_interval(days => %s)
              AND NOT EXISTS (SELECT 1 FROM job_matches m WHERE m.job_id = j.id AND m.profile_id = %s)
            ORDER BY j.posted_at DESC NULLS LAST, j.id DESC""", (seen_within_days, profile_id)).fetchall()


# --- applications -----------------------------------------------------------


def set_application_status(conn, profile_id: int, job_id: int, status: str,
                           note: str | None = None, *, history_only: bool = False) -> int:
    """Set a job's status and record the change, with `note`, in its history.

    A note the person gave (`jsa status 42 applied --note ...`) also becomes the job's notes. A
    line the program writes ("emailed ...", "set on the web page") is passed with `history_only`,
    so it never replaces what the person wrote in the Notes box."""
    if status not in APPLICATION_STATUSES:
        raise ValueError(f"status must be one of {', '.join(APPLICATION_STATUSES)}")
    kept = None if history_only else note
    with conn.transaction():
        prev = conn.execute(
            "SELECT id, status FROM applications WHERE profile_id = %s AND job_id = %s FOR UPDATE",
            (profile_id, job_id),
        ).fetchone()
        if prev:
            app_id = prev["id"]
            conn.execute(
                """UPDATE applications SET status = %s, updated_at = now(),
                       applied_at = CASE WHEN %s = 'applied' AND applied_at IS NULL
                                         THEN now() ELSE applied_at END,
                       notes = COALESCE(%s, notes)
                   WHERE id = %s""",
                (status, status, kept, app_id),
            )
            from_status = prev["status"]
        else:
            app_id = conn.execute(
                """INSERT INTO applications (profile_id, job_id, status, notes, applied_at)
                   VALUES (%s, %s, %s, %s, CASE WHEN %s = 'applied' THEN now() END) RETURNING id""",
                (profile_id, job_id, status, kept, status),
            ).fetchone()["id"]
            from_status = None
        conn.execute(
            "INSERT INTO application_events (application_id, from_status, to_status, note)"
            " VALUES (%s, %s, %s, %s)",
            (app_id, from_status, status, note),
        )
    return app_id


def save_cover_letter(conn, profile_id: int, job_id: int, text: str) -> None:
    set_application_status_if_missing(conn, profile_id, job_id)
    conn.execute(
        "UPDATE applications SET cover_letter = %s, updated_at = now()"
        " WHERE profile_id = %s AND job_id = %s",
        (text, profile_id, job_id),
    )


def set_application_status_if_missing(conn, profile_id: int, job_id: int,
                                      note: str | None = None) -> bool:
    exists = conn.execute(
        "SELECT 1 FROM applications WHERE profile_id = %s AND job_id = %s", (profile_id, job_id)
    ).fetchone()
    if exists:
        return False
    set_application_status(conn, profile_id, job_id, "shortlisted", note, history_only=True)
    return True


def shortlist_many(conn, profile_id: int, job_ids: Iterable[int]) -> int:
    """Shortlist high scorers, never overriding a status the person already set."""
    n = 0
    for jid in job_ids:
        if set_application_status_if_missing(conn, profile_id, jid, "auto: high match score"):
            n += 1
    return n


def save_outreach(conn, profile_id: int, job_id: int, *, subject: str, body: str,
                  recruiter_name: str | None, contact_email: str | None, still_open: bool,
                  research: str | None = None, follow_up_subject: str | None = None,
                  follow_up_body: str | None = None, review_score: int | None = None,
                  review_notes: str | None = None) -> None:
    set_application_status_if_missing(conn, profile_id, job_id)
    conn.execute(
        """UPDATE applications SET outreach_subject = %s, outreach_body = %s, recruiter_name = %s,
               contact_email = COALESCE(%s, contact_email), posting_open = %s, posting_checked_at = now(),
               company_research = %s, follow_up_subject = %s, follow_up_body = %s,
               review_score = %s, review_notes = %s, updated_at = now()
           WHERE profile_id = %s AND job_id = %s""",
        (subject, body, recruiter_name, contact_email, still_open, research,
         follow_up_subject, follow_up_body, review_score, review_notes, profile_id, job_id),
    )


def shortlisted_job_ids(conn, profile_id: int, limit: int) -> list[int]:
    rows = conn.execute(
        """SELECT a.job_id FROM applications a
           JOIN jobs j ON j.id = a.job_id
           LEFT JOIN job_matches m ON m.job_id = a.job_id AND m.profile_id = a.profile_id
           WHERE a.profile_id = %s AND a.status = 'shortlisted'
           ORDER BY j.posted_at DESC NULLS LAST, m.score DESC NULLS LAST LIMIT %s""",
        (profile_id, limit),
    ).fetchall()
    return [r["job_id"] for r in rows]


def list_applications(conn, profile_id: int) -> list[dict]:
    return conn.execute(
        """SELECT a.id, a.status, a.applied_at, a.updated_at, a.notes, j.id AS job_id,
                  j.title, j.company, j.url, m.score
           FROM applications a JOIN jobs j ON j.id = a.job_id
           LEFT JOIN job_matches m ON m.job_id = a.job_id AND m.profile_id = a.profile_id
           WHERE a.profile_id = %s ORDER BY a.updated_at DESC""",
        (profile_id,),
    ).fetchall()


def is_other_listing(conn, job_id: int, job: JobPosting) -> bool:
    """True when this posting was merged into a job first stored from a different listing."""
    row = conn.execute("SELECT fingerprint FROM jobs WHERE id = %s", (job_id,)).fetchone()
    return bool(row) and row["fingerprint"] != job.fingerprint


# --- sending, follow-ups and the dashboard ------------------------------------


def mark_outreach_sent(conn, profile_id: int, job_id: int, *, again: bool = False) -> None:
    """Record that the job's email went now. Sent `again`, its follow-up starts over: the one that
    belonged to the first email no longer counts."""
    conn.execute(
        """UPDATE applications SET outreach_sent_at = now(),
               follow_up_sent_at = CASE WHEN %s THEN NULL ELSE follow_up_sent_at END
           WHERE profile_id = %s AND job_id = %s""", (again, profile_id, job_id))


def mark_follow_up_sent(conn, profile_id: int, job_id: int) -> None:
    conn.execute("UPDATE applications SET follow_up_sent_at = now() WHERE profile_id = %s AND job_id = %s",
                 (profile_id, job_id))


def sends_today(conn, profile_id: int) -> int:
    """Emails and follow-ups sent since midnight, for the daily cap."""
    return conn.execute(
        """SELECT count(*) FILTER (WHERE outreach_sent_at >= current_date)
                + count(*) FILTER (WHERE follow_up_sent_at >= current_date) AS n
           FROM applications WHERE profile_id = %s""", (profile_id,)).fetchone()["n"]


def followups_due(conn, profile_id: int, after_days: int) -> list[dict]:
    """Emailed jobs with no follow-up yet, sent at least `after_days` ago and still 'applied'."""
    return conn.execute(
        """SELECT a.job_id, j.title, j.company, a.contact_email, a.outreach_sent_at,
                  a.follow_up_subject, a.follow_up_body
           FROM applications a JOIN jobs j ON j.id = a.job_id
           WHERE a.profile_id = %s AND a.status = 'applied' AND a.outreach_sent_at IS NOT NULL
             AND a.follow_up_sent_at IS NULL
             AND a.outreach_sent_at <= now() - make_interval(days => %s)
           ORDER BY a.outreach_sent_at""", (profile_id, after_days)).fetchall()


def dashboard_rows(conn, profile_id: int) -> list[dict]:
    """Every tracked job with its score and draft, newest postings first."""
    return conn.execute(
        """SELECT j.id AS job_id, j.title, j.company, j.location, j.url, j.posted_at,
                  a.status, a.outreach_subject, a.outreach_body, a.contact_email,
                  a.outreach_sent_at, a.follow_up_sent_at, a.notes, a.contact_kind,
                  a.contact_source, m.score, m.summary, m.salary_estimate
           FROM applications a JOIN jobs j ON j.id = a.job_id
           LEFT JOIN job_matches m ON m.job_id = a.job_id AND m.profile_id = a.profile_id
           WHERE a.profile_id = %s
           ORDER BY (a.status = 'shortlisted') DESC, j.posted_at DESC NULLS LAST, m.score DESC NULLS LAST""",
        (profile_id,)).fetchall()


def overview(conn, profile_id: int | None) -> dict:
    """How many jobs sit at each stage, for the web page."""
    return conn.execute(
        """SELECT (SELECT count(*) FROM jobs WHERE is_active) AS found,
                  (SELECT count(*) FROM jobs WHERE is_active
                   AND first_seen_at >= now() - interval '7 days') AS found_week,
                  (SELECT count(*) FROM job_matches m JOIN jobs j ON j.id = m.job_id
                   WHERE m.profile_id = %s AND j.is_active) AS scored,
                  count(*) FILTER (WHERE status = 'shortlisted') AS shortlisted,
                  count(*) FILTER (WHERE outreach_sent_at IS NOT NULL) AS emailed,
                  count(*) FILTER (WHERE status IN ('applied', 'interviewing', 'offer')) AS applied
           FROM applications WHERE profile_id = %s""", (profile_id, profile_id)).fetchone()


def match_countries(conn, profile_id: int) -> list[dict]:
    """Scored jobs per country, most first, for the web page."""
    counts: dict[str, int] = {}
    for r in conn.execute(
            """SELECT j.location FROM job_matches m JOIN jobs j ON j.id = m.job_id
               WHERE m.profile_id = %s AND j.is_active""", (profile_id,)):
        country = country_of(r["location"])
        counts[country] = counts.get(country, 0) + 1
    return [{"country": k, "jobs": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def get_match(conn, profile_id: int, job_id: int) -> dict | None:
    return conn.execute("SELECT * FROM job_matches WHERE profile_id = %s AND job_id = %s",
                        (profile_id, job_id)).fetchone()


def application_events(conn, application_id: int) -> list[dict]:
    return conn.execute(
        "SELECT from_status, to_status, note, created_at FROM application_events"
        " WHERE application_id = %s ORDER BY created_at, id", (application_id,)).fetchall()


def get_application(conn, profile_id: int, job_id: int) -> dict | None:
    return conn.execute("SELECT * FROM applications WHERE profile_id = %s AND job_id = %s",
                        (profile_id, job_id)).fetchone()


def save_contact(conn, profile_id: int, job_id: int, email: str | None, source: str | None,
                 kind: str | None) -> None:
    """Store an application address found away from the posting, with the page it came from.
    An email of None removes the address."""
    set_application_status_if_missing(conn, profile_id, job_id)
    conn.execute(
        """UPDATE applications SET contact_email = %s, contact_source = %s, contact_kind = %s,
               updated_at = now() WHERE profile_id = %s AND job_id = %s""",
        (email, source, kind, profile_id, job_id))


def set_note(conn, profile_id: int, job_id: int, note: str) -> None:
    conn.execute("UPDATE applications SET notes = %s, updated_at = now() WHERE profile_id = %s AND job_id = %s",
                 (note.strip() or None, profile_id, job_id))


def save_draft_text(conn, profile_id: int, job_id: int, subject: str, body: str) -> None:
    conn.execute(
        """UPDATE applications SET outreach_subject = %s, outreach_body = %s, updated_at = now()
           WHERE profile_id = %s AND job_id = %s""", (subject.strip(), body.strip(), profile_id, job_id))


def jobs_needing_contact(conn, profile_id: int, limit: int) -> list[dict]:
    return conn.execute(
        """SELECT j.id AS job_id, j.title, j.company, j.location FROM applications a
           JOIN jobs j ON j.id = a.job_id
           WHERE a.profile_id = %s AND a.status = 'shortlisted' AND a.contact_email IS NULL
           ORDER BY j.posted_at DESC NULLS LAST, j.id LIMIT %s""", (profile_id, limit)).fetchall()


# --- reports ------------------------------------------------------------------


def skill_gaps(conn, profile_id: int, days: int, min_score: int, limit: int) -> tuple[int, list[dict]]:
    """(jobs counted, skills most often missing) across recently scored jobs."""
    where = "m.profile_id = %s AND m.score >= %s AND m.created_at >= now() - make_interval(days => %s)"
    total = conn.execute(f"SELECT count(*) AS n FROM job_matches m WHERE {where}",
                         (profile_id, min_score, days)).fetchone()["n"]
    rows = conn.execute(
        f"""SELECT min(skill) AS skill, count(DISTINCT m.job_id) AS jobs
            FROM job_matches m, unnest(m.missing_skills) AS skill
            WHERE {where} GROUP BY lower(trim(skill)) ORDER BY jobs DESC, 1 LIMIT %s""",
        (profile_id, min_score, days, limit)).fetchall()
    return total, rows


def progress(conn, profile_id: int, days: int) -> dict:
    """What happened in the last `days`: status changes, emails, replies, and jobs per source."""
    moves = {r["to_status"]: r["n"] for r in conn.execute(
        """SELECT e.to_status, count(DISTINCT e.application_id) AS n FROM application_events e
           JOIN applications a ON a.id = e.application_id
           WHERE a.profile_id = %s AND e.created_at >= now() - make_interval(days => %s)
           GROUP BY 1""", (profile_id, days))}
    mail = conn.execute(
        """SELECT count(*) FILTER (WHERE outreach_sent_at >= now() - make_interval(days => %s)) AS sent,
                  count(*) FILTER (WHERE follow_up_sent_at >= now() - make_interval(days => %s)) AS followed_up,
                  count(*) FILTER (WHERE outreach_sent_at IS NOT NULL) AS emailed_ever,
                  count(*) FILTER (WHERE outreach_sent_at IS NOT NULL
                                   AND status IN ('interviewing', 'offer', 'rejected')) AS answered_ever
           FROM applications WHERE profile_id = %s""", (days, days, profile_id)).fetchone()
    sources = conn.execute(
        """SELECT coalesce(s.name, 'added by hand') AS source, count(j.id) AS found,
                  count(a.id) FILTER (WHERE a.status = 'shortlisted') AS shortlisted,
                  count(a.id) FILTER (WHERE a.status IN ('applied', 'interviewing', 'offer')) AS applied
           FROM jobs j LEFT JOIN sources s ON s.id = j.source_id
           LEFT JOIN applications a ON a.job_id = j.id AND a.profile_id = %s
           WHERE j.first_seen_at >= now() - make_interval(days => %s)
           GROUP BY 1 ORDER BY found DESC""", (profile_id, days)).fetchall()
    return {"moves": moves, "mail": mail, "sources": sources}


# --- duplicates already stored ---------------------------------------------------


def duplicate_groups(conn) -> list[dict]:
    """Jobs that share a match_key: each group is one job stored more than once."""
    groups = []
    for g in conn.execute(
            """SELECT array_agg(id ORDER BY id) AS ids FROM jobs WHERE match_key IS NOT NULL
               GROUP BY match_key HAVING count(*) > 1 ORDER BY min(id)""").fetchall():
        rows = conn.execute(
            """SELECT j.id, j.title, j.company, j.location,
                      (SELECT max(CASE a.status WHEN 'shortlisted' THEN 1 WHEN 'skipped' THEN 1 ELSE 2 END)
                       FROM applications a WHERE a.job_id = j.id) AS acted,
                      EXISTS (SELECT 1 FROM job_matches m WHERE m.job_id = j.id) AS scored
               FROM jobs j WHERE j.id = ANY(%s)""", (g["ids"],)).fetchall()
        # Keep the copy you have acted on most, then a scored one, then the oldest.
        keep = sorted(rows, key=lambda r: (-(r["acted"] or 0), not r["scored"], r["id"]))[0]
        groups.append({"keep": keep, "drop": [r for r in rows if r["id"] != keep["id"]]})
    return groups


def merge_duplicates(conn) -> int:
    """Fold each duplicate into the copy that is kept. Returns how many rows were removed."""
    removed = 0
    for g in duplicate_groups(conn):
        keep = g["keep"]["id"]
        with conn.transaction():
            for dup in (r["id"] for r in g["drop"]):
                for table in ("job_matches", "applications"):  # move what the kept copy lacks
                    conn.execute(
                        f"""UPDATE {table} t SET job_id = %s WHERE t.job_id = %s AND NOT EXISTS (
                                SELECT 1 FROM {table} k WHERE k.job_id = %s AND k.profile_id = t.profile_id)""",
                        (keep, dup, keep))
                conn.execute(
                    """UPDATE jobs k SET description = COALESCE(k.description, d.description),
                           posted_at = COALESCE(k.posted_at, d.posted_at)
                       FROM jobs d WHERE k.id = %s AND d.id = %s""", (keep, dup))
                conn.execute("DELETE FROM jobs WHERE id = %s", (dup,))
                removed += 1
    return removed
