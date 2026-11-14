"""Settings (secrets from env) and search config (from YAML)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class ConfigError(RuntimeError):
    pass


def _env(name: str) -> str | None:
    """Read an env var, treating empty values and template placeholders like 'sk-...' as unset."""
    v = (os.getenv(name) or "").strip()
    if not v or v.endswith("...") or v in ("changeme", "your-key-here"):
        return None
    return v


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines, does not override real env vars."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


class Settings(BaseModel):
    database_url: str | None = None
    # Which AI to use is configured only in .env: LLM_PROVIDER, LLM_MODEL, LLM_EFFORT.
    llm_provider: Literal["openai", "anthropic"] | None = None
    llm_model: str | None = None
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    browserbase_api_key: str | None = None
    gmail_address: str | None = None
    gmail_app_password: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    browserbase_project_id: str | None = None
    browser: Literal["browserbase", "local"] = "browserbase"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL"),
            llm_provider=(_env("LLM_PROVIDER") or None),  # type: ignore[arg-type]
            # ANTHROPIC_MODEL / OPENAI_MODEL are accepted for older .env files.
            llm_model=(_env("LLM_MODEL") or _env("ANTHROPIC_MODEL") or _env("OPENAI_MODEL")),
            llm_effort=(_env("LLM_EFFORT") or _env("ANTHROPIC_EFFORT")),  # type: ignore[arg-type]
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            openai_api_key=_env("OPENAI_API_KEY"),
            browserbase_api_key=_env("BROWSERBASE_API_KEY"),
            gmail_address=_env("GMAIL_ADDRESS"),
            gmail_app_password=_env("GMAIL_APP_PASSWORD"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            browserbase_project_id=_env("BROWSERBASE_PROJECT_ID"),
            browser=os.getenv("JOBAGENT_BROWSER", "browserbase"),  # type: ignore[arg-type]
        )

    def resolved_llm_provider(self) -> str:
        """LLM_PROVIDER if set; else inferred from LLM_MODEL; else from which key is present."""
        if self.llm_provider:
            return self.llm_provider
        model = (self.llm_model or "").lower()
        if model.startswith("claude"):
            return "anthropic"
        if model.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
            return "openai"
        if self.anthropic_api_key and not self.openai_api_key:
            return "anthropic"
        return "openai"

    def require(self, *names: str) -> None:
        missing = [n.upper() for n in names if not getattr(self, n)]
        if missing:
            raise ConfigError(
                f"Missing environment variable(s): {', '.join(missing)}. See .env.example."
            )


class SearchPrefs(BaseModel):
    roles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    include_title_keywords: list[str] = Field(default_factory=list)
    exclude_title_keywords: list[str] = Field(default_factory=list)
    # Dropped before scoring when the company name contains one of these words (e.g. "bank").
    exclude_company_keywords: list[str] = Field(default_factory=list)
    # Industries the matcher should treat as a dealbreaker (e.g. "banking").
    exclude_industries: list[str] = Field(default_factory=list)
    max_age_days: int | None = 30
    # Lowest acceptable salary in lakhs per year (LPA), for jobs paid in rupees. A job that states
    # a lower range is dropped; a job that does not state its salary is kept.
    min_salary_lpa: float | None = None
    notes: str = ""  # free-text preferences passed to the matcher


def _read_template(file: str) -> str | None:
    """The text of a template file, or None when the setting is empty or the file is missing."""
    p = Path(file) if file else None
    if p is None or not p.is_file():
        return None
    return p.read_text(encoding="utf-8").strip() or None


class ResumeVariant(BaseModel):
    """A CV to attach instead of the default when a job mentions one of the keywords."""

    name: str
    path: str
    keywords: list[str] = Field(default_factory=list)


class OutreachPrefs(BaseModel):
    notice_period: str = ""      # e.g. "60 days, negotiable"; omitted from emails when empty
    resume_filename: str = ""    # e.g. "Alex_Morgan_Java_Engineer.pdf"
    email: str = ""              # contact email for the sign-off; the resume's when empty
    linkedin_url: str = ""       # shown in emails as a clickable "LinkedIn" link
    resume_path: str = ""        # CV file attached to Gmail drafts (`jsa email --gmail-drafts`)
    resume_variants: list[ResumeVariant] = Field(default_factory=list)  # other CVs, by keyword
    follow_up_days: int = 6      # a follow-up is due this many days after an email was sent
    max_sends_per_day: int = 10  # `--send` stops at this many emails a day (0 = no limit)
    send_pause_seconds: int = 20  # wait between sent emails
    research: bool = True        # web-search recruiter advice per country (Claude only)
    max_searches: int = 4        # web searches per country researched
    review: bool = True          # have the model review each draft as a recruiter
    min_review_score: int = 8    # revise drafts the recruiter review scores below this (1-10)
    max_revisions: int = 2
    # Your own email wording with [placeholders], filled in for each job. When the file is
    # missing (or this is ""), emails use the built-in recruiter-style format instead.
    template_file: str = "email_template.txt"
    # Your own cover letter with [placeholders], filled in for each job by `jsa cover-letter`.
    # When the file is missing (or this is ""), a short built-in cover letter is written instead.
    cover_letter_template_file: str = "cover_letter_template.txt"
    # The email for a general application: an HR address with no specific posting (`jsa add-contacts`).
    general_template_file: str = "general_email_template.txt"

    def resume_for(self, job_text: str) -> tuple[str, str]:
        """(name, path) of the CV to attach for a job: the first variant whose keyword the job
        mentions as a whole word or phrase, otherwise the default resume_path."""
        text = f" {re.sub(r'[^a-z0-9+#/]+', ' ', job_text.lower())} "
        for v in self.resume_variants:
            if v.path and any(f" {k.lower().strip()} " in text for k in v.keywords if k.strip()):
                return v.name, v.path
        return "default", self.resume_path

    def template(self) -> str | None:
        return _read_template(self.template_file)

    def cover_letter_template(self) -> str | None:
        return _read_template(self.cover_letter_template_file)

    def general_template(self) -> str | None:
        return _read_template(self.general_template_file)


class MatchingPrefs(BaseModel):
    shortlist_min_score: int = 75
    max_jobs_to_score: int = 100
    notify_min_score: int = 85             # message you about new jobs at or above this (0 = off)
    max_tokens_per_run: int = 0            # stop a run after this many AI tokens (0 = no limit)
    max_browser_minutes_per_run: float = 0  # stop collecting after this much browser time
    concurrency: int = 4
    # A cheaper model that looks at each job first; only the ones it does not rule out get the
    # full scoring. Empty switches the first check off. Example: claude-haiku-5-5
    prescreen_model: str = ""
    # Send the morning routine's scoring as one batch: half the price, answered later (usually
    # within the hour). Claude only. The search waits up to batch_wait_minutes for the answers;
    # if they are not back by then, the next search picks them up.
    batch_scoring: bool = False
    batch_wait_minutes: int = 120


class BackupPrefs(BaseModel):
    folder: str = "backups"  # where `jsa backup` writes; relative to the folder jsa runs from
    keep: int = 7            # the newest this many are kept, older ones are removed
    daily: bool = True       # the morning routine ends with a backup


class SourceConfig(BaseModel):
    kind: Literal["greenhouse", "lever", "ashby", "amazon", "microsoft", "workday", "generic"]
    name: str
    # greenhouse/ashby: board token; lever: company slug; generic: list page URL(s)
    board: str | None = None
    urls: list[str] = Field(default_factory=list)
    company: str | None = None  # display name override
    max_detail_pages: int = 20
    enabled: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def identity_url(self) -> str:
        return self.board or ",".join(self.urls) or self.kind


class AgentConfig(BaseModel):
    search: SearchPrefs = Field(default_factory=SearchPrefs)
    matching: MatchingPrefs = Field(default_factory=MatchingPrefs)
    outreach: OutreachPrefs = Field(default_factory=OutreachPrefs)
    backup: BackupPrefs = Field(default_factory=BackupPrefs)
    sources: list[SourceConfig] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "AgentConfig":
        """config.yaml, with the settings changed on the page laid over it."""
        base, over = _read_both(path)
        return cls.model_validate(_merged(base, over))


# --- settings changed on the page ---------------------------------------------------------------
#
# The page never rewrites config.yaml, which may hold the person's own comments and layout. What
# is changed there is kept in a second file beside it, config.overrides.yaml, holding only the
# values that differ. Every command reads both, so the page and the terminal always agree.

_SECTIONS = ("search", "matching", "outreach", "backup")

# key: (group, kind, label, hint, lowest, highest). Kind is int, float, text, list or bool; a
# trailing "?" means the box may be left empty (not set). The order here is the order on the page.
EDITABLE: dict[str, tuple[str, str, str, str, float | None, float | None]] = {
    "search.include_title_keywords": ("What to look for", "list", "Title must contain one of",
                                      "Words or phrases, separated by commas. Empty keeps every title.", None, None),
    "search.exclude_title_keywords": ("What to look for", "list", "Title must not contain", "", None, None),
    "search.exclude_company_keywords": ("What to look for", "list", "Leave out companies named", "", None, None),
    "search.locations": ("What to look for", "list", "Places",
                         "Countries and cities. A job somewhere else is dropped before scoring.", None, None),
    "search.max_age_days": ("What to look for", "int?", "Oldest posting, in days", "Empty means any age.", 1, 365),
    "search.min_salary_lpa": ("What to look for", "float?", "Lowest salary, in lakhs a year",
                              "Only jobs that state less are dropped. Empty means not set.", 0, None),
    "search.remote_ok": ("What to look for", "bool", "Keep remote jobs", "", None, None),
    "matching.shortlist_min_score": ("Scoring", "int", "Shortlist from score", "", 0, 100),
    "matching.notify_min_score": ("Scoring", "int", "Message me from score", "0 switches messages off.", 0, 100),
    "matching.max_jobs_to_score": ("Scoring", "int", "Most jobs scored in one search", "", 1, 5000),
    "matching.max_tokens_per_run": ("Scoring", "int", "AI budget for one search, in tokens", "0 means no limit.", 0, None),
    "matching.max_browser_minutes_per_run": ("Scoring", "float", "Browser time for one search, in minutes",
                                             "0 means no limit.", 0, None),
    "matching.prescreen_model": ("Scoring", "text", "Cheaper model for a quick first check",
                                 "For example claude-haiku-5-5. Only jobs it does not rule out get the full scoring. "
                                 "Empty switches it off.", None, None),
    "matching.batch_wait_minutes": ("Scoring", "int", "Longest wait for a batch, in minutes",
                                    "After that the next search picks the answers up.", 1, 1440),
    "matching.batch_scoring": ("Scoring", "bool", "Score the morning routine as a batch",
                               "Half the price. The answers come later, usually within the hour. Claude only.", None, None),
    "outreach.max_sends_per_day": ("Emails", "int", "Emails a day", "0 means no limit.", 0, 2000),
    "outreach.send_pause_seconds": ("Emails", "int", "Seconds between emails", "", 0, 3600),
    "outreach.follow_up_days": ("Emails", "int", "Follow up after, in days", "", 1, 90),
    "outreach.notice_period": ("Emails", "text", "When you can join", "Used in emails, for example: immediately.", None, None),
    "backup.daily": ("Backups", "bool", "Back up after the morning routine", "", None, None),
    "backup.keep": ("Backups", "int", "Backups kept", "", 1, 365),
}


def overrides_path(path: str | Path) -> Path:
    p = Path(path)
    return p.with_name(p.stem + ".overrides.yaml")


def _read_both(path: str | Path) -> tuple[dict, dict]:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}. Copy config.example.yaml to start.")
    base = yaml.safe_load(p.read_text()) or {}
    over_file = overrides_path(p)
    try:
        over = (yaml.safe_load(over_file.read_text()) or {}) if over_file.exists() else {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{over_file} could not be read ({e}). Fix it, or delete it to go back to {p.name}.") from e
    if not isinstance(over, dict):
        raise ConfigError(f"{over_file} is not a list of settings. Delete it to go back to {p.name}.")
    return base, over


def _merged(base: dict, over: dict) -> dict:
    out = dict(base)
    for section in _SECTIONS:
        if over.get(section):
            out[section] = {**(base.get(section) or {}), **over[section]}
    switches = over.get("sources") or {}
    if switches:
        out["sources"] = [{**s, "enabled": switches[s["name"]]["enabled"]}
                          if isinstance(s, dict) and "enabled" in (switches.get(s.get("name")) or {}) else s
                          for s in base.get("sources") or []]
    return out


def _coerce(key: str, raw):
    """A value from the page as the type its setting has. Raises ConfigError in plain words."""
    _, kind, label, _, low, high = EDITABLE[key]
    optional, kind = kind.endswith("?"), kind.rstrip("?")
    if kind == "bool":
        if not isinstance(raw, bool):
            raise ConfigError(f"{label}: choose on or off.")
        return raw
    if kind == "list":
        items = raw if isinstance(raw, list) else re.split(r"[,\n]", str(raw or ""))
        seen: list[str] = []
        for item in (str(x).strip() for x in items):
            if item and item.lower() not in (x.lower() for x in seen):
                seen.append(item)
        return seen
    if kind == "text":
        return str(raw or "").strip()
    if raw is None or str(raw).strip() == "":
        if optional:
            return None
        raise ConfigError(f"{label}: a number is needed.")
    try:
        number = float(str(raw).strip())
        value = int(number) if kind == "int" else number
        if kind == "int" and number != value:
            raise ValueError
    except ValueError:
        raise ConfigError(f"{label}: {str(raw).strip()!r} is not a {'whole ' if kind == 'int' else ''}number.") from None
    if (low is not None and value < low) or (high is not None and value > high):
        limits = f"between {low:g} and {high:g}" if low is not None and high is not None else f"{low:g} or more"
        raise ConfigError(f"{label}: must be {limits}.")
    return value


def read_settings(path: str | Path) -> dict:
    """What the page shows: every changeable setting with its value now and its value in
    config.yaml alone, and every site with its switch."""
    base, over = _read_both(path)
    plain, now = AgentConfig.model_validate(base), AgentConfig.model_validate(_merged(base, over))
    fields = []
    for key, (group, kind, label, hint, low, high) in EDITABLE.items():
        section, name = key.split(".")
        value, in_file = getattr(getattr(now, section), name), getattr(getattr(plain, section), name)
        fields.append({"key": key, "group": group, "kind": kind.rstrip("?"), "optional": kind.endswith("?"),
                       "label": label, "hint": hint, "value": value, "file_value": in_file, "changed": value != in_file})
    sites = [{"name": s.name, "kind": s.kind, "enabled": s.enabled, "changed": s.enabled != p.enabled}
             for s, p in zip(now.sources, plain.sources)]
    return {"file": Path(path).name, "overrides_file": overrides_path(path).name, "fields": fields, "sites": sites,
            "changed": sum(f["changed"] for f in fields) + sum(s["changed"] for s in sites)}


def write_settings(path: str | Path, values: dict | None = None, sites: dict | None = None) -> dict:
    """Store settings changed on the page. A value of None, or one equal to config.yaml's, removes
    the override. Nothing is written unless the result is a valid configuration."""
    base, over = _read_both(path)
    plain = AgentConfig.model_validate(base)
    over = {k: dict(v) if isinstance(v, dict) else v for k, v in over.items()}
    for key, raw in (values or {}).items():
        if key not in EDITABLE:
            raise ConfigError("That setting cannot be changed here.")
        section, name = key.split(".")
        value = None if raw is None else _coerce(key, raw)
        chosen = over.setdefault(section, {})
        if raw is None or value == getattr(getattr(plain, section), name):
            chosen.pop(name, None)
        else:
            chosen[name] = value
    known = {s.name: s.enabled for s in plain.sources}
    for name, on in (sites or {}).items():
        if name not in known:
            raise ConfigError(f"There is no site called {name!r} in {Path(path).name}.")
        if on is not None and not isinstance(on, bool):
            raise ConfigError(f"{name}: choose on or off.")
        switches = over.setdefault("sources", {})
        if on is None or on == known[name]:
            switches.pop(name, None)
        else:
            switches[name] = {"enabled": on}
    over = {k: v for k, v in over.items() if v}
    try:
        AgentConfig.model_validate(_merged(base, over))
    except Exception as e:  # noqa: BLE001 - pydantic's message names the field
        raise ConfigError(f"Those settings do not fit together: {str(e).splitlines()[-1].strip()}") from e
    target = overrides_path(path)
    if not over:
        target.unlink(missing_ok=True)
    else:
        text = (f"# Settings changed on the Job Search page. {Path(path).name} is the base and is never rewritten;\n"
                "# this file holds only what differs from it. Delete a line to go back to the value there.\n"
                + yaml.safe_dump(over, sort_keys=True, allow_unicode=True))
        part = target.with_suffix(".part")
        part.write_text(text, encoding="utf-8")
        os.replace(part, target)
    return read_settings(path)
