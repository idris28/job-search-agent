"""Actions used by both the terminal commands and the web page."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from . import db, mailer
from .models import JobPosting
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


def send_slots(conn, profile_id: int, outreach) -> int:
    """How many more emails may be sent today under outreach.max_sends_per_day."""
    if not outreach.max_sends_per_day:
        return 10**9
    return max(0, outreach.max_sends_per_day - db.sends_today(conn, profile_id))


def send_stored_draft(conn, settings, outreach, profile_id: int, job_id: int, *,
                      allow_general: bool = False) -> str:
    """Send the draft saved for one job from the user's Gmail. Returns the address it went to."""
    job, app = db.get_job(conn, job_id), db.get_application(conn, profile_id, job_id)
    if not job or not app or not (app["outreach_subject"] and app["outreach_body"]):
        raise ActionError("There is no draft for this job yet. Run: jsa email " + str(job_id))
    if app["status"] != "shortlisted":
        raise ActionError(f"This job is already marked {app['status']}, so it was not emailed again.")
    if not app["contact_email"]:
        raise ActionError("No email address is known for this job. Try: jsa contacts " + str(job_id))
    if app["contact_kind"] == "general" and not allow_general:
        raise ActionError(f"Only a general inbox ({app['contact_email']}) was found, so it was not sent.")
    if not (settings.gmail_address and settings.gmail_app_password):
        raise ActionError("Gmail is not set up: add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to .env.")
    if send_slots(conn, profile_id, outreach) <= 0:
        raise ActionError(f"The daily limit of {outreach.max_sends_per_day} emails has been reached.")
    name, path = outreach.resume_for(f"{job['title']} {job['description'] or ''}")
    cv = Path(path).expanduser() if path else None
    if cv is None or not cv.is_file():
        raise ActionError(f"The CV file for '{name}' was not found. Set outreach.resume_path.")
    msg = mailer.build_message(settings.gmail_address, app["contact_email"], app["outreach_subject"],
                               app["outreach_body"], _paragraphs_html(app["outreach_body"]), cv)
    mailer.send_messages(settings.gmail_address, settings.gmail_app_password, [msg])
    db.set_application_status(conn, profile_id, job_id, "applied", f"emailed {app['contact_email']}")
    db.mark_outreach_sent(conn, profile_id, job_id)
    return app["contact_email"]
