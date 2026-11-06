"""OpenAI calls: resume parsing, job scoring, listing extraction, cover letters."""

from __future__ import annotations

import json
import threading
from typing import TypeVar

from pydantic import BaseModel

from .config import SearchPrefs
from .models import CandidateProfile, ExtractedListings, JobPosting, MatchResult

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
Only list skills that actually appear in the job text as missing_skills. Be concise and specific."""

EXTRACT_INSTRUCTIONS = """You are given the visible text and links of a careers/job search page.
Return every individual job posting on the page: its title, absolute URL (from the links list),
company if shown, and location if shown. Skip navigation, category, and filter links. If the page
has no job postings, return an empty list."""

COVER_LETTER_INSTRUCTIONS = """Write a concise, specific cover letter (under 250 words) for this
candidate and job. Lead with the strongest 2-3 relevant achievements from the resume, mapped to the
job's stated needs. No clichés, no invented facts, no placeholders except [Hiring Manager] if no
name is known. Plain text."""


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
    provider = settings.resolved_llm_provider()
    if provider == "anthropic":
        from .llm_anthropic import ClaudeLLM

        settings.require("anthropic_api_key")
        return ClaudeLLM(settings.anthropic_api_key, settings.anthropic_model,
                         effort=settings.anthropic_effort)
    settings.require("openai_api_key")
    return OpenAILLM(settings.openai_api_key, settings.openai_model)
