"""Actions used by both the terminal commands and the web page."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from . import db, mailer
from .models import GENERAL_TITLE, GENERAL_URL, JobPosting
from .report import _paragraphs_html


class ActionError(Exception):
    """Something the user needs to know about; the message is shown as is."""


def add_pasted_job(conn, llm, cfg, text: str, url: str | None = None):
    """Read a pasted post, store it, score it and shortlist it.
    Returns (job_id, is_new, found, match)."""
    p = db.active_profile(conn)
    if not p:
        raise ActionError("No profile yet. Run: jsa profile import <resume.pdf>")
    found = llm.read_pasted_job(text)
    link = url or "pasted:" + hashlib.sha256(text.encode()).hexdigest()[:16]
    description = found.description + (f"\n\nSend applications to: {found.contact_email}"
                                       if found.contact_email else "")
    posting = JobPosting(title=found.title, company=found.company, url=link, location=found.location,
                         description=description, posted_at=datetime.now(timezone.utc))
    job_id, is_new = db.upsert_job(conn, posting, None, None)
    m = llm.score_job(p["profile"], cfg.search, posting)
    db.save_match(conn, p["id"], job_id, None, m, llm.model, posting.content_hash)
    db.set_application_status_if_missing(conn, p["id"], job_id, "added from pasted text")
    if found.contact_email:
        db.save_contact(conn, p["id"], job_id, found.contact_email, None, "recruiter")
    return job_id, is_new, found, m


_ADDRESS_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_WEBMAIL = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "live.com", "icloud.com")
_COUNTRY_BY_ENDING = {".sa": "Saudi Arabia", ".ae": "UAE", ".qa": "Qatar", ".in": "India"}


def add_hr_contacts(conn, cfg, text: str, country: str | None = None) -> dict:
    """Put HR addresses on the shortlist as general applications: no posting, just an address.

    One address per line, optionally with the employer's name ("Acme Gulf, hr@acme.sa"). Nothing
    is scored or sent here. Returns {"added": [...], "skipped": [(line, reason), ...]}.
    """
    p = db.active_profile(conn)
    if not p:
        raise ActionError("No profile yet. Run: jsa profile import <resume.pdf>")
    roles = ", ".join(cfg.search.roles) or "software engineering roles"
    added, skipped, seen = [], [], set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        found = _ADDRESS_RE.search(line)
        # An address glued to characters that cannot be part of one ("hr@acme_motors.com") is wrong.
        if not found or (found.end() < len(line) and line[found.end()] in "_@"):
            skipped.append((line, "not a valid email address"))
            continue
        email = found.group(0).lower()
        if email in seen:
            skipped.append((line, "repeated in this list"))
            continue
        seen.add(email)
        domain = email.rsplit("@", 1)[1]
        name = re.sub(r"^\s*\d+\s*[-.)]\s*", "", line.replace(found.group(0), " "))
        name = re.sub(r"\s+", " ", name).strip(" ,;:-|\t")
        company = name or f"{email if domain in _WEBMAIL else domain} (name not given)"
        place = country or next((c for end, c in _COUNTRY_BY_ENDING.items() if domain.endswith(end)), None)
        if conn.execute("SELECT 1 FROM jobs WHERE url = %s", (GENERAL_URL + email,)).fetchone():
            skipped.append((line, "already on your list"))
            continue
        other = conn.execute("SELECT 1 FROM jobs WHERE url LIKE %s AND lower(company) = lower(%s)",
                             (GENERAL_URL + "%", company)).fetchone()
        if other:
            skipped.append((line, "another address for this employer is already on your list"))
            continue
        posting = JobPosting(
            title=GENERAL_TITLE, company=company, url=GENERAL_URL + email, location=place,
            description="GENERAL APPLICATION. There is no job posting. The candidate is writing to "
                        "this employer's HR address to ask about suitable openings. "
                        f"Roles the candidate is looking for: {roles}.")
        job_id, _ = db.upsert_job(conn, posting, None, None)
        db.set_application_status_if_missing(conn, p["id"], job_id, "general application")
        db.save_contact(conn, p["id"], job_id, email, None, "careers")
        added.append({"job_id": job_id, "company": company, "email": email, "country": place})
    return {"added": added, "skipped": skipped}


def send_slots(conn, profile_id: int, outreach) -> int:
    """How many more emails may be sent today under outreach.max_sends_per_day."""
    if not outreach.max_sends_per_day:
        return 10**9
    return max(0, outreach.max_sends_per_day - db.sends_today(conn, profile_id))


def stored_draft_message(conn, settings, outreach, profile_id: int, job_id: int, *,
                         allow_general: bool = False, need_cv: bool = True):
    """Build the email for one job from its saved draft, edits included.
    Returns (message, address)."""
    job, app = db.get_job(conn, job_id), db.get_application(conn, profile_id, job_id)
    if not job or not app or not (app["outreach_subject"] and app["outreach_body"]):
        raise ActionError("There is no draft for this job yet. Draft the email first.")
    if app["status"] != "shortlisted":
        raise ActionError(f"This job is already marked {app['status']}, so it was not emailed again.")
    if not app["contact_email"]:
        raise ActionError("No email address is known for this job. Look for one, or apply on the job site.")
    if app["contact_kind"] == "general" and not allow_general:
        raise ActionError(f"Only a general inbox ({app['contact_email']}) was found, so it was not sent.")
    if not (settings.gmail_address and settings.gmail_app_password):
        raise ActionError("Gmail is not set up: add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to .env.")
    name, path = outreach.resume_for(f"{job['title']} {job['description'] or ''}")
    cv = Path(path).expanduser() if path else None
    if cv is not None and not cv.is_file():
        cv = None
    if cv is None and need_cv:
        raise ActionError(f"The CV file for '{name}' was not found. Set outreach.resume_path.")
    msg = mailer.build_message(settings.gmail_address, app["contact_email"], app["outreach_subject"],
                               app["outreach_body"], _paragraphs_html(app["outreach_body"]), cv)
    return msg, app["contact_email"]


def send_stored_draft(conn, settings, outreach, profile_id: int, job_id: int, *,
                      allow_general: bool = False) -> str:
    """Send the draft saved for one job from the user's Gmail. Returns the address it went to."""
    msg, to = stored_draft_message(conn, settings, outreach, profile_id, job_id,
                                   allow_general=allow_general)
    if send_slots(conn, profile_id, outreach) <= 0:
        raise ActionError(f"The daily limit of {outreach.max_sends_per_day} emails has been reached.")
    mailer.send_messages(settings.gmail_address, settings.gmail_app_password, [msg])
    db.set_application_status(conn, profile_id, job_id, "applied", f"emailed {to}")
    db.mark_outreach_sent(conn, profile_id, job_id)
    return to
