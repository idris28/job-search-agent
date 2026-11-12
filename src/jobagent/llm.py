"""OpenAI calls: resume parsing, job scoring, listing extraction, cover letters."""

from __future__ import annotations

import json
import threading
from typing import TypeVar

from pydantic import BaseModel

from .config import OutreachPrefs, SearchPrefs
from .models import (CandidateProfile, ExtractedListings, JobPosting, MatchResult,
                     PastedJob, RecruiterEmail, RecruiterReview, TemplateEmail)

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
If the candidate gives a minimum salary and the posting states pay clearly below it (convert other
currencies roughly), list that as a red flag and cap the score at 40. A posting that does not state
pay is not penalised.
salary_estimate: give the stated pay if the posting has it; otherwise estimate the likely yearly
range from the role, seniority, company and city, and end it with "(estimate)". An estimate alone
never lowers the score; if its top is clearly below the candidate's minimum, add the red flag
"estimated pay may be below your minimum".
Only list skills that actually appear in the job text as missing_skills. Be concise and specific."""

EXTRACT_INSTRUCTIONS = """You are given the visible text and links of a careers/job search page.
Return every individual job posting on the page: its title, absolute URL (from the links list),
company if shown, location if shown, and how long ago it was posted if shown (the wording on
the page, such as "2 days ago"). Skip navigation, category, and filter links. If the page
has no job postings, return an empty list."""

COVER_LETTER_INSTRUCTIONS = """Write a concise, specific cover letter (under 250 words) for this
candidate and job. Lead with the strongest 2-3 relevant achievements from the resume, mapped to the
job's stated needs. No clichés, no invented facts, no placeholders except [Hiring Manager] if no
name is known. Plain text."""


# Built from recruiter guidance: Bayt (Gulf), Agile Consultants UAE ("how recruiters actually read
# your CV", "why you're not getting interview calls in the UAE"), UKG tech recruiting, Glassdoor,
# JobRise India 2026, noon.ai reply-rate data. Recruiters decide in seconds, scanning for: current
# title + years, stack match with the posting's keywords, a quantified result, location / visa /
# notice period, and an easy next step.
RECRUITER_EMAIL_INSTRUCTIONS = """You write a cold email from a job candidate to the recruiter for
one specific job. Inputs: the resume, the stored posting, the live posting page text (may be missing
or show the job closed), RECRUITER GUIDANCE notes from web research (what recruiters for this role
and country say they look for), outreach preferences, and possibly a PREVIOUS DRAFT with a
RECRUITER REVIEW to fix.

FACTS
- still_open: false only if the live page says the job is closed, expired or removed.
- recruiter_name / contact_email: only if written on the posting itself. Never guess.
- company_hook: one specific thing the posting says about the team/product/problem that the
  candidate's experience fits. Null if the posting is too thin.

CONTENT RECRUITERS LOOK FOR (put it where a 6-second skim finds it)
1. First sentence: who you are in recruiter terms: current title, years of experience, core stack,
   and the employers (e.g. "Software Engineer with 6+ years building Java/Spring Boot services at
   IBM and Oracle"), plus the exact role you are applying for.
2. Fit: mirror 4-6 exact keywords/technologies from the posting, but only ones the resume backs.
3. Proof: exactly 3 bullets, each = requirement from the posting -> your quantified result
   (numbers, scale, outcome, your own ownership). Under 25 words each. Never vague ("worked on
   backend services").
4. Logistics recruiters must know: current location, relocation to this job's country, visa
   ("employer-sponsored work visa" for UAE/Saudi/Qatar), notice period if given, resume attached.
   Never mention salary.
5. Easy next step: one specific, low-pressure ask (e.g. a 15-minute call this week).
Follow the RECRUITER GUIDANCE notes where they add market-specific points.

FORMAT
- subject: under 60 characters, "<Role> | <credential> | <key skills>", e.g.
  "Senior Java Engineer | 6 yrs IBM & Oracle | Spring Boot".
- greeting: "Hi <first name>," if a name is on the posting, else "Hi <Company> Hiring Team,".
  Never "Dear Sir/Madam", "To whom it may concern", "Hi All".
- opener: 1-2 sentences covering point 1 and, if present, company_hook.
- signature: name, phone with country code (note WhatsApp only for an Indian mobile), email,
  LinkedIn, copied exactly from the resume.
- Body (greeting through call_to_action) 110-160 words. Confident, warm, specific.
- Banned: "I am writing to express", "fast learner", "team player", "perfect fit", "Please find my
  CV attached", "I need this job", exclamation marks, invented facts.
- follow_up: 50-80 words for 5-7 days later, adds one new relevant result, subject "Re: <subject>".
- If a RECRUITER REVIEW is given, fix every issue it lists while keeping all facts true."""

# Used instead of RECRUITER_EMAIL_INSTRUCTIONS when the candidate supplies their own template
# (outreach.template_file): the layout and wording are theirs, only the blanks are ours.
TEMPLATE_EMAIL_INSTRUCTIONS = """You fill in a job candidate's own email TEMPLATE for one specific
job. Inputs: the template, the resume, the stored posting, the live posting page text (may be
missing or show the job closed) and outreach preferences.

FACTS
- still_open: false only if the live page says the job is closed, expired or removed.
- recruiter_name / contact_email: only if written on the posting itself. Never guess.

BODY: the template, made specific to this job
- Keep the template as the candidate wrote it: the same greeting, paragraphs, sentences and
  sign-off, in the same order. Do not add, remove, merge or rephrase them.
- Replace every [placeholder] with what it asks for, for THIS job. A placeholder is either a
  label ("[Job Title]") or a short description of what to write there. Job title and company: as
  the posting gives them. Everything about the candidate (years, employers, skills, experience,
  achievements, results): from the resume. When they can join, what is attached, and their
  email address and LinkedIn URL: from the outreach preferences (for the email address, the
  resume's if the preferences give none).
- Write a LinkedIn URL as the link [LinkedIn](URL), never as a bare URL. Copy any [text](URL)
  link already in the template unchanged, and keep its **bold** marks exactly where they are.
- Make it specific to the posting. Skills and areas of experience: the ones this posting asks for
  that the resume shows, by name or by work that plainly involves them, most important first and
  in the posting's own terms where they mean the same thing. Leave out anything the resume does
  not show, however prominent in the posting. An achievement with its result or metric: one
  resume statement that gives both, the one closest to what this posting stresses; never join
  separate achievements into one claim or suggest one result caused another. Never invent or
  inflate anything.
- Keep each detail as brief as its sentence needs, so the email stays short and reads naturally.
- Change the template's fixed words only where they would be untrue or ungrammatical for this
  candidate and job (for example "previous role" when the achievement is from the current role).
- If there is nothing true to put in a placeholder (for example no LinkedIn URL in the resume, or
  no notice period in the preferences), leave that line, sentence or phrase out. Never output a
  square-bracket placeholder.
- Separate paragraphs with one blank line; keep the sign-off lines on consecutive lines.

SUBJECT AND FOLLOW-UP
- subject: under 60 characters, "<Role> | <credential> | <key skills>", e.g.
  "Senior Java Engineer | 6 yrs IBM & Oracle | Spring Boot".
- follow_up: 50-80 words for 5-7 days later, in the template's tone with its greeting and
  sign-off, adding one new relevant result; subject "Re: <subject>"."""

CONTENT_RESEARCH_INSTRUCTIONS = """Use web search to find current advice from recruiters, hiring
managers and recruitment agencies about what CONTENT in a candidate's application or cold email
makes recruiters reply, for the given role and country. Cover: what recruiters scan for first,
which details are expected in that market (e.g. visa status, notice period, location, local
experience), keyword/skill expectations for this kind of role, and common mistakes that get emails
ignored. Do not research specific companies or people. Reply with 6-10 short bullet notes, each
ending with its source URL. Under 220 words."""

RECRUITER_REVIEW_INSTRUCTIONS = """You are a busy senior tech recruiter in {country} hiring for the
role below. You get about 200 candidate emails a day and decide in seconds. Review the candidate's
email as that recruiter would, against the job posting and the resume.
- first_impression: what you took away in the first 6 seconds (subject + first lines).
- score: 1-10 for how likely you are to reply or forward it to the hiring manager.
- would_reply: true if you would reply or forward it.
- strengths: what works.
- issues: concrete problems (missing info you need, weak or vague bullets, keyword gaps vs the
  posting, wrong tone, too long, cliches, anything untrue vs the resume). Empty if none.
- rewrite_instructions: specific edits that would raise the score. Empty if score >= 9.
Be honest and strict; do not inflate scores."""

PASTED_JOB_INSTRUCTIONS = """You are given text a job seeker pasted, usually a social media post
by a recruiter or employee announcing a vacancy. Extract the one job it describes. Use only what
the text says: do not guess a company, location or email address. Copy the email address exactly.
If the post lists several roles, take the first and mention the others in the description."""

CONTACT_INSTRUCTIONS = """Find an email address a job candidate can send an application to at the
given company. Use web search. Accept an address only if it is printed on the company's own website
(its careers, jobs, contact or about page). Prefer a named recruiter or an address for careers, jobs,
HR or talent; a general address such as info@ is a last resort. Never construct, guess or infer an
address from a pattern, and never take one from a contact-database or people-search site.
Reply with one line of JSON and nothing else:
{"email": "<address>", "source_url": "<page it is printed on>", "kind": "recruiter|careers|general"}
or {"email": null} when no such address is published."""


class BaseLLM:
    """Task methods shared by every provider. Subclasses implement _parse and _text."""

    model: str

    def __init__(self) -> None:
        self._tokens = 0
        self.cache_read_tokens = 0  # input tokens served from the provider's prompt cache
        self._lock = threading.Lock()

    @property
    def tokens_used(self) -> int:
        return self._tokens

    def _add_tokens(self, n: int) -> None:
        with self._lock:
            self._tokens += n or 0

    def _parse(self, instructions: str, user_input: str, schema: type[T], *,
               cached_prefix: str = "") -> T:
        """cached_prefix is the part of the message that repeats across calls (the resume, the
        template); it is sent first so the provider can cache it."""
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
                "minimum_salary_lakhs_per_year_inr": prefs.min_salary_lpa,
                "notes": prefs.notes,
            }, indent=1)
            + "\n\n"
        )
        result = self._parse(MATCH_INSTRUCTIONS, "JOB POSTING:\n" + job.as_prompt_text(),
                             MatchResult, cached_prefix=payload)
        result.score = max(0, min(100, result.score))
        return result

    def extract_listings(self, page_text: str, links: list[dict], page_url: str) -> ExtractedListings:
        links_txt = "\n".join(f"- {l['text']} -> {l['href']}" for l in links[:400])
        payload = (f"PAGE URL: {page_url}\n\nPAGE TEXT:\n{page_text[:15000]}\n\nLINKS:\n{links_txt}")
        return self._parse(EXTRACT_INSTRUCTIONS, payload, ExtractedListings)

    def find_contact(self, company: str, location: str | None) -> dict | None:
        """A published application address for a company; providers without web search return None."""
        return None

    def read_pasted_job(self, text: str) -> PastedJob:
        return self._parse(PASTED_JOB_INSTRUCTIONS, f"PASTED TEXT:\n{text[:15000]}", PastedJob)

    def research_email_content(self, roles: str, country: str,
                               max_searches: int = 4) -> str | None:
        """Web-researched recruiter guidance; providers without web search return None."""
        return None

    def review_email(self, email: RecruiterEmail, job_text: str, resume_text: str,
                     country: str) -> RecruiterReview:
        payload = (f"JOB POSTING:\n{job_text}\n\nCANDIDATE RESUME:\n{resume_text}"
                   f"\n\nCANDIDATE EMAIL\nSubject: {email.subject}\n\n{email.plain_text()}")
        return self._parse(RECRUITER_REVIEW_INSTRUCTIONS.format(country=country or "the region"),
                           payload, RecruiterReview)

    def recruiter_email(self, resume_text: str, job_text: str, live_page_text: str | None,
                        guidance_notes: str | None = None,
                        outreach: OutreachPrefs | None = None,
                        previous: RecruiterEmail | None = None,
                        review: RecruiterReview | None = None,
                        template: str | None = None) -> RecruiterEmail | TemplateEmail:
        """Draft the email for one job. With a template, the candidate's own wording is filled in
        for the job; guidance notes and reviews shape wording, so they are not used then."""
        live = (live_page_text or "(live page could not be loaded)")[:15000]
        prefs = {}
        if outreach is not None:
            prefs = {k: v for k, v in outreach.model_dump().items()
                     if k in ("notice_period", "resume_filename", "email",
                              "linkedin_url") and v}
        resume = f"RESUME:\n{resume_text}\n\n"  # the same for every job, so sent as a cached prefix
        payload = f"STORED JOB POSTING:\n{job_text}\n\nLIVE POSTING PAGE TEXT:\n{live}"
        prefs_text = f"\n\nOUTREACH PREFERENCES:\n{json.dumps(prefs) if prefs else '(none)'}"
        if template:
            return self._parse(TEMPLATE_EMAIL_INSTRUCTIONS, payload + prefs_text, TemplateEmail,
                               cached_prefix=f"TEMPLATE:\n{template}\n\n{resume}")
        payload += f"\n\nRECRUITER GUIDANCE:\n{guidance_notes or '(none)'}{prefs_text}"
        if previous is not None and review is not None:
            payload += (f"\n\nPREVIOUS DRAFT:\nSubject: {previous.subject}\n\n"
                        f"{previous.plain_text()}\n\nRECRUITER REVIEW:\n"
                        f"{review.model_dump_json(indent=1)}")
        return self._parse(RECRUITER_EMAIL_INSTRUCTIONS, payload, RecruiterEmail,
                           cached_prefix=resume)

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

    def _parse(self, instructions: str, user_input: str, schema: type[T], *,
               cached_prefix: str = "") -> T:
        resp = self.client.responses.parse(
            model=self.model,
            instructions=instructions,
            input=cached_prefix + user_input,  # OpenAI caches a repeated prefix on its own
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
