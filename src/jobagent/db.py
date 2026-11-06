"""PostgreSQL access: migrations and the small set of queries the agent needs."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import JobPosting, MatchResult

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
    return applied


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


def start_run(conn, profile_id: int | None, config_snapshot: dict) -> int:
    return conn.execute(
        "INSERT INTO runs (profile_id, config_snapshot) VALUES (%s, %s) RETURNING id",
        (profile_id, Jsonb(config_snapshot)),
    ).fetchone()["id"]


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


def log_event(conn, run_id: int, message: str, *, level: str = "info",
              source_id: int | None = None, data: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO run_events (run_id, source_id, level, message, data) VALUES (%s,%s,%s,%s,%s)",
        (run_id, source_id, level, message, Jsonb(data) if data is not None else None),
    )


def list_runs(conn, limit: int = 20) -> list[dict]:
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT %s", (limit,)).fetchall()


# --- jobs -------------------------------------------------------------------


def upsert_job(conn, job: JobPosting, source_id: int | None, run_id: int | None) -> tuple[int, bool]:
    """Insert or refresh a job. Returns (job_id, is_new)."""
    row = conn.execute(
        """INSERT INTO jobs (source_id, external_id, fingerprint, url, title, company, location,
                             remote_type, employment_type, salary_text, description, posted_at,
                             first_run_id, raw)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            Jsonb(json.loads(json.dumps(job.raw, default=str))) if job.raw else None,
        ),
    ).fetchone()
    return row["id"], row["inserted"]


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
                                    matched_skills, missing_skills, red_flags, model, content_hash)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (profile_id, job_id) DO UPDATE SET
               run_id = EXCLUDED.run_id, score = EXCLUDED.score, verdict = EXCLUDED.verdict,
               summary = EXCLUDED.summary, matched_skills = EXCLUDED.matched_skills,
               missing_skills = EXCLUDED.missing_skills, red_flags = EXCLUDED.red_flags,
               model = EXCLUDED.model, content_hash = EXCLUDED.content_hash, created_at = now()""",
        (
            profile_id, job_id, run_id, max(0, min(100, m.score)), m.verdict, m.summary,
            m.matched_skills, m.missing_skills, m.red_flags, model, content_hash,
        ),
    )


def top_matches(conn, profile_id: int, *, min_score: int = 0, limit: int = 25,
                run_id: int | None = None, include_status: bool = True) -> list[dict]:
    sql = """
        SELECT j.id AS job_id, j.title, j.company, j.location, j.remote_type, j.url,
               j.salary_text, j.first_seen_at, m.score, m.verdict, m.summary,
               m.matched_skills, m.missing_skills, m.red_flags,
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
    sql += " ORDER BY m.score DESC, j.first_seen_at DESC LIMIT %s"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def get_job(conn, job_id: int) -> dict | None:
    return conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()


# --- applications -----------------------------------------------------------


def set_application_status(conn, profile_id: int, job_id: int, status: str,
                           note: str | None = None) -> int:
    if status not in APPLICATION_STATUSES:
        raise ValueError(f"status must be one of {', '.join(APPLICATION_STATUSES)}")
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
                (status, status, note, app_id),
            )
            from_status = prev["status"]
        else:
            app_id = conn.execute(
                """INSERT INTO applications (profile_id, job_id, status, notes, applied_at)
                   VALUES (%s, %s, %s, %s, CASE WHEN %s = 'applied' THEN now() END) RETURNING id""",
                (profile_id, job_id, status, note, status),
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
    set_application_status(conn, profile_id, job_id, "shortlisted", note)
    return True


def shortlist_many(conn, profile_id: int, job_ids: Iterable[int]) -> int:
    """Shortlist high scorers, never overriding a status the person already set."""
    n = 0
    for jid in job_ids:
        if set_application_status_if_missing(conn, profile_id, jid, "auto: high match score"):
            n += 1
    return n


def list_applications(conn, profile_id: int) -> list[dict]:
    return conn.execute(
        """SELECT a.id, a.status, a.applied_at, a.updated_at, a.notes, j.id AS job_id,
                  j.title, j.company, j.url, m.score
           FROM applications a JOIN jobs j ON j.id = a.job_id
           LEFT JOIN job_matches m ON m.job_id = a.job_id AND m.profile_id = a.profile_id
           WHERE a.profile_id = %s ORDER BY a.updated_at DESC""",
        (profile_id,),
    ).fetchall()
