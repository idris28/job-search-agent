"""Data shapes shared across the agent."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RemoteType = Literal["remote", "hybrid", "onsite", "unknown"]


class JobPosting(BaseModel):
    """A job as returned by a source adapter, before it is stored."""

    title: str
    company: str
    url: str
    location: str | None = None
    remote_type: RemoteType = "unknown"
    employment_type: str | None = None
    salary_text: str | None = None
    description: str | None = None
    posted_at: datetime | None = None
    external_id: str | None = None
    raw: dict | None = None

    @property
    def fingerprint(self) -> str:
        """Stable identity used to dedupe the same job seen via different URLs/runs."""
        key = "|".join(_norm(x) for x in (self.company, self.title, self.location or ""))
        return hashlib.sha256(key.encode()).hexdigest()[:32]

    @property
    def content_hash(self) -> str:
        """Changes when the text we score changes, so we know when to re-score."""
        body = "\n".join([self.title, self.location or "", self.description or ""])
        return hashlib.sha256(body.encode()).hexdigest()[:32]

    def as_prompt_text(self, max_chars: int = 12000) -> str:
        parts = [
            f"Title: {self.title}",
            f"Company: {self.company}",
            f"Location: {self.location or 'n/a'} ({self.remote_type})",
        ]
        if self.employment_type:
            parts.append(f"Employment type: {self.employment_type}")
        if self.salary_text:
            parts.append(f"Salary: {self.salary_text}")
        parts.append("")
        parts.append((self.description or "(no description captured)")[:max_chars])
        return "\n".join(parts)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# --- LLM structured outputs -------------------------------------------------


class CandidateProfile(BaseModel):
    name: str
    headline: str = Field(description="One-line professional headline")
    years_experience: float
    seniority: Literal["junior", "mid", "senior", "staff", "principal"]
    current_location: str
    primary_skills: list[str] = Field(description="Core skills the candidate is strongest in")
    secondary_skills: list[str]
    past_titles: list[str]
    domains: list[str] = Field(description="Industries/problem domains worked in")
    highlights: list[str] = Field(description="3-6 quantified achievements")
    education: list[str]


class MatchResult(BaseModel):
    score: int = Field(description="0-100 fit score")
    verdict: Literal["strong", "good", "stretch", "poor"]
    summary: str = Field(description="2-3 sentences on why this score")
    matched_skills: list[str]
    missing_skills: list[str]
    red_flags: list[str] = Field(
        description="Dealbreakers vs preferences: location, seniority mismatch, visa, etc."
    )


class ExtractedListing(BaseModel):
    title: str
    url: str
    company: str | None
    location: str | None


class ExtractedListings(BaseModel):
    listings: list[ExtractedListing]


class RecruiterEmail(BaseModel):
    still_open: bool = Field(description="False if the live page says the job is closed/expired/removed")
    recruiter_name: str | None = Field(description="Recruiter or hiring manager named on the page, if any")
    contact_email: str | None = Field(description="An email address shown on the page for applying, if any")
    key_requirements: list[str] = Field(description="The 3-6 requirements the email addresses")
    subject: str
    body: str
