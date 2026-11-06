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
    llm_provider: Literal["openai", "anthropic"] | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    browserbase_api_key: str | None = None
    browserbase_project_id: str | None = None
    browser: Literal["browserbase", "local"] = "browserbase"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL"),
            llm_provider=(os.getenv("LLM_PROVIDER") or None),  # type: ignore[arg-type]
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            anthropic_model=os.getenv("ANTHROPIC_MODEL") or "claude-opus-5-5",
            anthropic_effort=os.getenv("ANTHROPIC_EFFORT") or "medium",  # type: ignore[arg-type]
            openai_api_key=_env("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL") or "gpt-5.4-mini",
            browserbase_api_key=_env("BROWSERBASE_API_KEY"),
            browserbase_project_id=_env("BROWSERBASE_PROJECT_ID"),
            browser=os.getenv("JOBAGENT_BROWSER", "browserbase"),  # type: ignore[arg-type]
        )

    def resolved_llm_provider(self) -> str:
        """LLM_PROVIDER if set; otherwise Claude when only an Anthropic key is present."""
        if self.llm_provider:
            return self.llm_provider
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
    max_age_days: int | None = 30
    notes: str = ""  # free-text preferences passed to the matcher


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
    sources: list[SourceConfig] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "AgentConfig":
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Config file not found: {p}. Copy config.example.yaml to start.")
        return cls.model_validate(yaml.safe_load(p.read_text()) or {})
