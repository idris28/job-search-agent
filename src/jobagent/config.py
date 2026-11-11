"""Settings (secrets from env) and search config (from YAML)."""

from __future__ import annotations

import os
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
    notes: str = ""  # free-text preferences passed to the matcher


class OutreachPrefs(BaseModel):
    notice_period: str = ""      # e.g. "60 days, negotiable"; omitted from emails when empty
    resume_link: str = ""        # e.g. a Google Drive link; otherwise the email says "attached"
    resume_filename: str = ""    # e.g. "Alex_Morgan_Java_Engineer.pdf"
    research: bool = True        # web-search recruiter advice per country (Claude only)
    max_searches: int = 4        # web searches per country researched
    review: bool = True          # have the model review each draft as a recruiter
    min_review_score: int = 8    # revise drafts the recruiter review scores below this (1-10)
    max_revisions: int = 2
    # Your own email wording with [placeholders], filled in for each job. When the file is
    # missing (or this is ""), emails use the built-in recruiter-style format instead.
    template_file: str = "email_template.txt"

    def template(self) -> str | None:
        p = Path(self.template_file) if self.template_file else None
        if p is None or not p.is_file():
            return None
        return p.read_text(encoding="utf-8").strip() or None


class MatchingPrefs(BaseModel):
    shortlist_min_score: int = 75
    max_jobs_to_score: int = 100
    concurrency: int = 4


class SourceConfig(BaseModel):
    kind: Literal["greenhouse", "lever", "ashby", "generic"]
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
        return self.board or ",".join(self.urls)


class AgentConfig(BaseModel):
    search: SearchPrefs = Field(default_factory=SearchPrefs)
    matching: MatchingPrefs = Field(default_factory=MatchingPrefs)
    outreach: OutreachPrefs = Field(default_factory=OutreachPrefs)
    sources: list[SourceConfig] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "AgentConfig":
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Config file not found: {p}. Copy config.example.yaml to start.")
        return cls.model_validate(yaml.safe_load(p.read_text()) or {})
