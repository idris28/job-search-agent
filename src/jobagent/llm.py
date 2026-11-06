"""OpenAI calls: resume parsing, job scoring, listing extraction, cover letters."""

from __future__ import annotations

import json
import threading
from typing import TypeVar

from pydantic import BaseModel

from .config import OutreachPrefs, SearchPrefs
from .models import (CandidateProfile, ExtractedListings, JobPosting, MatchResult,
                     RecruiterEmail)

T = TypeVar("T", bound=BaseModel)

PROFILE_INSTRUCTIONS = """You extract a structured candidate profile from a resume.
Be faithful to the resume: do not invent skills, titles, or numbers. Normalize skill names
(e.g. "Spring Boot", "PostgreSQL"). Seniority reflects total professional experience and scope."""

MATCH_INSTRUCTIONS = """You are a rigorous technical recruiter scoring how well a job fits a
candidate. Score 0-100:
  85-100 strong: role, seniority, core stack and location all line up; candidate would be competitive.
  70-84  good: solid fit with a few gaps that are learnable or minor.
  50-69  stretch: notable gaps (different primary stack, seniority jump, location friction).
  0-49   poor: wrong field, wrong level, or a hard dealbreaker.
Weigh: core tech stack overlap, years/seniority match, domain, and the candidate's location and
work-mode preferences. A hard location/visa conflict is a red flag and caps the score at 40.
If the employer (or, for a staffing/consulting firm, the end client) is in one of the candidate's
excluded industries, list that as a red flag, set verdict "poor", and cap the score at 30.
Only list skills that actually appear in the job text as missing_skills. Be concise and specific."""

EXTRACT_INSTRUCTIONS = """You are given the visible text and links of a careers/job search page.
Return every individual job posting on the page: its title, absolute URL (from the links list),
company if shown, and location if shown. Skip navigation, category, and filter links. If the page
has no job postings, return an empty list."""

COVER_LETTER_INSTRUCTIONS = """Write a concise, specific cover letter (under 250 words) for this
candidate and job. Lead with the strongest 2-3 relevant achievements from the resume, mapped to the
job's stated needs. No clichés, no invented facts, no placeholders except [Hiring Manager] if no
name is known. Plain text."""


# Built from recruiter and hiring-manager guidance (Bayt Gulf cover-letter guide, Glassdoor,
# JobRise India 2026, noon.ai reply-rate data, ATS Verification "apply to Dubai from abroad").
RECRUITER_EMAIL_INSTRUCTIONS = """You write a cold email from a job candidate to the recruiter or
hiring manager for one specific job. Inputs: the candidate's resume, the stored posting, the text of
the live posting page (may be missing or show the job as closed), web research notes about the
company (may be missing), and the candidate's outreach preferences.

FACTS
- still_open: false only if the live page says the job is closed, expired or removed.
- recruiter_name / contact_email: only if written on the posting or in a research source. Never
  guess or construct names or addresses.
- company_hook: one specific, recent, sourced fact (product launch, expansion, engineering blog
  post, tech stack). Null if research has nothing solid. Never invent one.

EMAIL (what recruiters say gets replies)
- subject: under 60 characters, "<Role> | <credential> | <key skills>", e.g.
  "Senior Java Engineer | 6 yrs IBM & Oracle | Spring Boot".
- greeting: "Hi <first name>," if a name is known, else "Hi <Company> Hiring Team,". Never
  "Dear Sir/Madam", "To whom it may concern" or "Hi All".
- opener: 1-2 sentences. Name the exact role and where it was seen, and use company_hook if there
  is one, so it is clearly not a mass email. Do not start with "I am writing to express".
- bullets: exactly 3. Each maps one requirement from the posting to a real, quantified result from
  the resume (numbers, scale, outcome). Under 25 words each. No re-listing the whole CV.
- logistics: one line with current location (from the resume), relocation willingness for this
  job's country, "employer-sponsored work visa" for UAE/Saudi/Qatar roles, notice period if given
  in the preferences, and that the resume is attached (or the resume link if given).
- call_to_action: one specific, low-pressure ask, e.g. "Would you be open to a 15-minute call
  this week?"
- signature: name, phone with country code (note WhatsApp if it is an Indian mobile), email,
  LinkedIn; copied exactly from the resume.
- Total body (greeting through call_to_action) 110-160 words.
- Tone: confident, warm, specific. Banned: "I am a fast learner", "team player", "perfect fit",
  "Please find my CV attached", "I need this job", buzzword chains, exclamation marks.
- follow_up: a 50-80 word nudge for 5-7 days later, adds one new relevant point, same thread
  subject prefixed "Re: "."""

RESEARCH_INSTRUCTIONS = """You research an employer for a job candidate before they email the
recruiter. Use web search. Find, with sources:
1. What the company does and its size/region in one line.
2. One or two recent (last 12 months) items: product launches, expansion, funding, awards, or
   engineering blog posts / talks, especially about Java, cloud or platform work.
3. The recruiter, talent-acquisition partner or engineering/hiring manager for this team, ONLY if
   a public source (company site, LinkedIn post, job posting, blog) names them. Do not guess.
4. Any public careers email for applications.
Reply with short bullet notes, each ending with its source URL. Say "not found" for anything you
could not verify. Under 200 words."""


class BaseLLM:
    """Task methods shared by every provider. Subclasses implement _parse and _text."""

    model: str

    def __init__(self) -> None:
        self._tokens = 0
        self._lock = threading.Lock()

    @property
    def tokens_used(self) -> int:
        return self._tokens

    def _add_tokens(self, n: int) -> None:
        with self._lock:
            self._tokens += n or 0

    def _parse(self, instructions: str, user_input: str, schema: type[T]) -> T:
        raise NotImplementedError

    def _text(self, instructions: str, user_input: str) -> str:
        raise NotImplementedError

    # --- tasks ---------------------------------------------------------------

    def extract_profile(self, resume_text: str) -> CandidateProfile:
        return self._parse(PROFILE_INSTRUCTIONS, f"RESUME:\n{resume_text}", CandidateProfile)

    def score_job(self, profile: dict, prefs: SearchPrefs, job: JobPosting) -> MatchResult:
        payload = (
            "CANDIDATE PROFILE:\n" + json.dumps(profile, indent=1)
            + "\n\nCANDIDATE PREFERENCES:\n"
            + json.dumps({
                "target_roles": prefs.roles,
                "preferred_locations": prefs.locations,
                "open_to_remote": prefs.remote_ok,
                "excluded_industries": prefs.exclude_industries,
                "notes": prefs.notes,
            }, indent=1)
            + "\n\nJOB POSTING:\n" + job.as_prompt_text()
        )
        result = self._parse(MATCH_INSTRUCTIONS, payload, MatchResult)
        result.score = max(0, min(100, result.score))
        return result

    def extract_listings(self, page_text: str, links: list[dict], page_url: str) -> ExtractedListings:
        links_txt = "\n".join(f"- {l['text']} -> {l['href']}" for l in links[:400])
        payload = (f"PAGE URL: {page_url}\n\nPAGE TEXT:\n{page_text[:15000]}\n\nLINKS:\n{links_txt}")
        return self._parse(EXTRACT_INSTRUCTIONS, payload, ExtractedListings)

    def research_company(self, company: str, title: str, location: str | None,
                         max_searches: int = 4) -> str | None:
        """Web research notes for the outreach email; providers without web search return None."""
        return None

    def recruiter_email(self, resume_text: str, job_text: str, live_page_text: str | None,
                        research_notes: str | None = None,
                        outreach: OutreachPrefs | None = None) -> RecruiterEmail:
        live = (live_page_text or "(live page could not be loaded)")[:15000]
        prefs = {}
        if outreach is not None:
            prefs = {k: v for k, v in outreach.model_dump().items()
                     if k in ("notice_period", "resume_link", "resume_filename") and v}
        payload = (f"RESUME:\n{resume_text}\n\nSTORED JOB POSTING:\n{job_text}"
                   f"\n\nLIVE POSTING PAGE TEXT:\n{live}"
                   f"\n\nCOMPANY RESEARCH NOTES:\n{research_notes or '(none)'}"
                   f"\n\nOUTREACH PREFERENCES:\n{json.dumps(prefs) if prefs else '(none)'}")
        return self._parse(RECRUITER_EMAIL_INSTRUCTIONS, payload, RecruiterEmail)

    def cover_letter(self, resume_text: str, job_text: str) -> str:
        return self._text(COVER_LETTER_INSTRUCTIONS, f"RESUME:\n{resume_text}\n\nJOB:\n{job_text}")


class OpenAILLM(BaseLLM):
    def __init__(self, api_key: str, model: str, *, client=None):
        super().__init__()
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, max_retries=4, timeout=90)
        self.client = client
        self.model = model

    def _count(self, resp) -> None:
        usage = getattr(resp, "usage", None)
        if usage is not None:
            self._add_tokens(getattr(usage, "total_tokens", 0))

    def _parse(self, instructions: str, user_input: str, schema: type[T]) -> T:
        resp = self.client.responses.parse(
            model=self.model,
            instructions=instructions,
            input=user_input,
            text_format=schema,
        )
        self._count(resp)
        if resp.output_parsed is None:
            raise RuntimeError("Model returned no parsable output (possibly a refusal)")
        return resp.output_parsed

    def _text(self, instructions: str, user_input: str) -> str:
        resp = self.client.responses.create(
            model=self.model, instructions=instructions, input=user_input,
        )
        self._count(resp)
        return resp.output_text.strip()


LLM = OpenAILLM  # backwards-compatible name


def make_llm(settings) -> BaseLLM:
    """Build the client for the configured provider (LLM_PROVIDER, or whichever key is set)."""
    from .config import ConfigError

    if not (settings.anthropic_api_key or settings.openai_api_key):
        raise ConfigError("Set ANTHROPIC_API_KEY (Claude) or OPENAI_API_KEY in .env")
    if not settings.llm_model:
        raise ConfigError("Set LLM_MODEL in .env, e.g. LLM_MODEL=claude-sonnet-5-5 "
                          "or LLM_MODEL=gpt-5.4-mini")
    provider = settings.resolved_llm_provider()
    if provider == "anthropic":
        from .llm_anthropic import ClaudeLLM

        settings.require("anthropic_api_key")
        return ClaudeLLM(settings.anthropic_api_key, settings.llm_model, effort=settings.llm_effort)
    settings.require("openai_api_key")
    return OpenAILLM(settings.openai_api_key, settings.llm_model)
