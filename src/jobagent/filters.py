"""Cheap rule-based filtering before spending LLM tokens."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .config import SearchPrefs
from .models import JobPosting


def _contains_any(text: str, words: list[str]) -> str | None:
    t = f" {text.lower()} "
    for w in words:
        if re.search(rf"(?<![a-z0-9]){re.escape(w.lower())}(?![a-z0-9])", t):
            return w
    return None


_LPA_RE = re.compile(r"(?:(\d+(?:\.\d+)?)\s*(?:-|to)\s*)?(\d+(?:\.\d+)?)\s*(?:lacs?|lakhs?|lpa)\b", re.I)


def stated_salary_lpa(text: str) -> float | None:
    """The top of a salary range written in lakhs, e.g. "15-25 Lacs PA" gives 25. None when the
    text states no such figure ("Not Disclosed")."""
    m = _LPA_RE.search(text)
    return float(m.group(2)) if m else None


def reject_reason(job: JobPosting, prefs: SearchPrefs, now: datetime | None = None) -> str | None:
    """Return why a job is filtered out, or None if it should be scored."""
    if prefs.exclude_title_keywords:
        hit = _contains_any(job.title, prefs.exclude_title_keywords)
        if hit:
            return f"title contains excluded keyword '{hit}'"

    if prefs.exclude_company_keywords:
        hit = _contains_any(job.company, prefs.exclude_company_keywords)
        if hit:
            return f"company name contains excluded keyword '{hit}'"

    if prefs.include_title_keywords and not _contains_any(job.title, prefs.include_title_keywords):
        return "title matches none of include_title_keywords"

    if prefs.locations:
        loc_ok = bool(job.location) and _contains_any(job.location, prefs.locations) is not None
        remote_ok = prefs.remote_ok and (
            job.remote_type == "remote" or "remote" in (job.location or "").lower()
        )
        # Unknown location: let the LLM judge rather than silently dropping it.
        if job.location and not (loc_ok or remote_ok):
            return f"location '{job.location}' not in preferred locations"

    if prefs.min_salary_lpa:
        top = stated_salary_lpa(f"{job.salary_text or ''} {(job.description or '')[:1200]}")
        if top is not None and top < prefs.min_salary_lpa:
            return f"salary up to {top:g} LPA is below the minimum {prefs.min_salary_lpa:g} LPA"

    if prefs.max_age_days and job.posted_at:
        now = now or datetime.now(timezone.utc)
        posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
        if now - posted > timedelta(days=prefs.max_age_days):
            return f"posted more than {prefs.max_age_days} days ago"

    return None


_COUNTRIES = {
    "UAE": ["uae", "united arab emirates", "dubai", "abu dhabi", "sharjah", "ajman"],
    "Saudi Arabia": ["saudi", "ksa", "riyadh", "jeddah", "dammam", "khobar"],
    "Qatar": ["qatar", "doha"],
    "India": ["india", "ahmedabad", "gandhinagar", "bengaluru", "bangalore", "pune", "hyderabad",
              "mumbai", "chennai", "gurugram", "gurgaon", "noida", "delhi", "kolkata"],
}


def country_of(location: str | None) -> str:
    """Best-effort country for a job location; 'Remote' when nothing matches."""
    loc = (location or "").lower()
    for country, words in _COUNTRIES.items():
        if _contains_any(loc, words):
            return country
    return "Remote"
