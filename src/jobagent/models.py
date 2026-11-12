"""Data shapes shared across the agent."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RemoteType = Literal["remote", "hybrid", "onsite", "unknown"]


NOT_NAMED = "(not named in the posting)"
_NO_COMPANY_RE = re.compile(
    r"^(unknown|undisclosed|anonymous|hidden|none|company|employer|n/?a|-*|"
    r"not (disclosed|specified|mentioned|given|available|named))$|confidential|stealth|"
    r"\(name not given\)$", re.I)
GENERAL_URL = "general:"   # jobs.url prefix of a general application: an HR address, no posting
GENERAL_TITLE = "General application"


def company_named(company: str | None) -> bool:
    """False when a posting gives no real company name ("Unknown", "Confidential Company", ...)."""
    return not _NO_COMPANY_RE.search((company or "").strip())


def names_missing_company(text: str, company: str | None) -> bool:
    """True when a draft writes the stand-in name of a company the posting does not name."""
    stand_in = (company or "").strip()
    return bool(stand_in) and not company_named(stand_in) and \
        re.search(rf"(?<![\w-]){re.escape(stand_in)}(?![\w-])", text, re.I) is not None


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
            f"Company: {self.company if company_named(self.company) else NOT_NAMED}",
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


_COMPANY_SUFFIXES = {"pvt", "private", "ltd", "limited", "llc", "inc", "llp", "fze", "fzco", "fz",
                     "co", "corp", "corporation", "plc", "wll", "india"}
_TITLE_NOISE = {"job", "jobs", "opening", "openings", "urgent", "urgently", "hiring", "required",
                "requirement", "wanted", "vacancy", "for", "in", "at", "the", "a", "an", "and",
                "immediate", "joiner", "joiners", "position", "role"}
_TITLE_ALIASES = {"sr": "senior", "jr": "junior", "dev": "developer", "engg": "engineer"}


def company_key(name: str) -> str:
    """A company name without its legal suffix: "Acme Pvt. Ltd." and "Acme" are the same."""
    words = [w for w in _norm(name).split() if w not in _COMPANY_SUFFIXES]
    return " ".join(words) or _norm(name)


def title_key(title: str, location: str | None = None) -> str:
    """A job title reduced to its meaningful words, in any order.

    "Sr. Java Developer - Dubai" and "Senior Java Developer" give the same key; "Java Developer"
    and "Java Developer II" do not, so different jobs are never merged.
    """
    place = set(_norm(location or "").split())
    words = {_TITLE_ALIASES.get(w, w) for w in _norm(title).split()}
    return " ".join(sorted(w for w in words if w not in _TITLE_NOISE and w not in place))


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
    salary_estimate: str | None = Field(default=None, description=(
        "Pay the posting states, or else your estimate of the likely yearly range for this role, "
        "company and city in local currency, e.g. '18-26 LPA (estimate)'. Null if you cannot judge."))


class ExtractedListing(BaseModel):
    title: str
    url: str
    company: str | None
    location: str | None
    posted: str | None = Field(default=None, description='How long ago it was posted, as the page shows it, e.g. "2 days ago"')


class ExtractedListings(BaseModel):
    listings: list[ExtractedListing]


class RecruiterEmail(BaseModel):
    still_open: bool = Field(description="False if the live page says the job is closed/expired/removed")
    recruiter_name: str | None = Field(description="Recruiter named on the posting itself; never guessed")
    contact_email: str | None = Field(description="An application email shown on the posting")
    company_hook: str | None = Field(description="What the posting says about the team/product that the candidate fits")
    subject: str = Field(description="Under 60 characters: Role | credential | key skills")
    greeting: str
    opener: str = Field(description="One or two sentences: the role, where it was seen, and the company hook")
    bullets: list[str] = Field(description="Exactly 3 quantified achievements mapped to the job's needs")
    logistics: str = Field(description="Location, relocation, visa and notice-period line")
    call_to_action: str
    signature: list[str] = Field(description="Name, phone (with country code), email, LinkedIn, one per line")
    follow_up_subject: str
    follow_up_body: str = Field(description="Polite 50-80 word follow-up to send after 5-7 days with no reply")

    def plain_text(self) -> str:
        parts = [self.greeting, "", self.opener, ""]
        parts += [f"\u2022 {b}" for b in self.bullets]
        parts += ["", self.logistics, "", self.call_to_action, "", "Best regards,", *self.signature]
        return "\n".join(parts)


class TemplateEmail(BaseModel):
    """An email written by filling in the candidate's own template for one job."""

    still_open: bool = Field(description="False if the live page says the job is closed/expired/removed")
    recruiter_name: str | None = Field(description="Recruiter named on the posting itself; never guessed")
    contact_email: str | None = Field(description="An application email shown on the posting")
    subject: str = Field(description="Under 60 characters: Role | credential | key skills")
    body: str = Field(description="The template from greeting to sign-off with every placeholder "
                                  "filled in for this job; paragraphs separated by a blank line")
    follow_up_subject: str
    follow_up_body: str = Field(description="Polite 50-80 word follow-up to send after 5-7 days with no reply")

    def plain_text(self) -> str:
        return self.body.strip()


# "[Job Title]" or a described blank like "[4 or 5 areas of my experience ...]", but not "[1]".
_PLACEHOLDER_RE = re.compile(r"\[[A-Za-z0-9][^\[\]\n]{2,199}\](?!\()")  # not a [text](url) link


def unfilled_placeholders(text: str) -> list[str]:
    """Template blanks such as "[Company Name]" that are still in a draft."""
    return list(dict.fromkeys(_PLACEHOLDER_RE.findall(text)))


class PastedJob(BaseModel):
    """A job read out of text the user pasted, such as a LinkedIn post."""

    title: str = Field(description="The role being hired for")
    company: str = Field(description="The hiring company; 'Unknown' if the text does not say")
    location: str | None
    contact_email: str | None = Field(description="Where the text says to send applications")
    description: str = Field(description="Everything the text says about the role and how to apply, kept in full")


class RecruiterReview(BaseModel):
    first_impression: str
    score: int = Field(description="1-10 likelihood the recruiter replies or forwards it")
    would_reply: bool
    strengths: list[str]
    issues: list[str]
    rewrite_instructions: list[str]
