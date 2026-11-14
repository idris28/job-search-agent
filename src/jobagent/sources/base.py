from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

from ..browser import Browser
from ..config import ConfigError, SourceConfig
from ..models import JobPosting, RemoteType


@dataclass
class SourceContext:
    """What an adapter may use. Tests pass fakes for all three."""

    http: httpx.Client
    browser: Browser
    llm: object  # jobagent.llm.LLM
    log: Callable[[str], None] = lambda msg: None
    prefs: object = None  # config.SearchPrefs: lets a reader skip jobs the rule filters would drop
    # Set by the search for job boards, so each job's own page is opened once:
    recall: Callable[[JobPosting], JobPosting | None] = lambda job: None  # the stored copy of a listed job
    unread: list = field(default_factory=list)  # stored for this board earlier, page not opened yet


class Source(ABC):
    needs_browser = False

    def __init__(self, cfg: SourceConfig):
        self.cfg = cfg

    @classmethod
    def validate(cls, cfg: SourceConfig) -> None:
        if not cfg.board:
            raise ConfigError(f"Source '{cfg.name}' ({cfg.kind}) needs a 'board' value")

    @abstractmethod
    def fetch(self, ctx: SourceContext) -> list[JobPosting]: ...


_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr)[^>]*>", re.I)


def html_to_text(raw: str | None) -> str | None:
    if not raw:
        return None
    s = html.unescape(raw)  # Greenhouse double-encodes
    s = _BLOCK_RE.sub("\n", s)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


_AGO_RE = re.compile(r"(\d+)\s*\+?\s*(minute|min|hour|hr|day|week|month)s?\s+ago", re.I)
_UNIT_HOURS = {"minute": 1 / 60, "min": 1 / 60, "hour": 1, "hr": 1, "day": 24, "week": 168, "month": 720}


def parse_posted(text: str | None, now: datetime | None = None) -> datetime | None:
    """When a job was posted, from wording like "2 days ago", "30+ days ago" or "Just now"."""
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    low = text.lower()
    m = _AGO_RE.search(low)
    if m:
        return now - timedelta(hours=int(m.group(1)) * _UNIT_HOURS[m.group(2).lower()])
    if re.search(r"just now|few (minutes|hours) ago|\btoday\b", low):
        return now
    if "yesterday" in low:
        return now - timedelta(days=1)
    return None


def guess_remote_type(*texts: str | None) -> RemoteType:
    blob = " ".join(t for t in texts if t).lower()
    if "hybrid" in blob:
        return "hybrid"
    if "remote" in blob or "work from home" in blob or "wfh" in blob:
        return "remote"
    if "on-site" in blob or "onsite" in blob or "in office" in blob:
        return "onsite"
    return "unknown"
