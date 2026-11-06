"""Public ATS job board feeds (Greenhouse, Lever, Ashby)."""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import JobPosting
from .base import Source, SourceContext, guess_remote_type, html_to_text


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class GreenhouseSource(Source):
    """boards.greenhouse.io/<board> -> boards-api.greenhouse.io/v1/boards/<board>/jobs"""

    def fetch(self, ctx: SourceContext) -> list[JobPosting]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.cfg.board}/jobs"
        r = ctx.http.get(url, params={"content": "true"})
        r.raise_for_status()
        out = []
        for j in r.json().get("jobs", []):
            loc = (j.get("location") or {}).get("name")
            desc = html_to_text(j.get("content"))
            out.append(JobPosting(
                title=j["title"].strip(),
                company=self.cfg.company or j.get("company_name") or self.cfg.name,
                url=j["absolute_url"],
                location=loc,
                remote_type=guess_remote_type(loc, j["title"]),
                description=desc,
                posted_at=_iso(j.get("first_published") or j.get("updated_at")),
                external_id=str(j["id"]),
                raw={k: j.get(k) for k in ("id", "internal_job_id", "updated_at", "departments")},
            ))
        return out


class LeverSource(Source):
    """jobs.lever.co/<board> -> api.lever.co/v0/postings/<board>?mode=json"""

    def fetch(self, ctx: SourceContext) -> list[JobPosting]:
        base = self.cfg.extra.get("api_base", "https://api.lever.co")  # EU: api.eu.lever.co
        r = ctx.http.get(f"{base}/v0/postings/{self.cfg.board}", params={"mode": "json"})
        r.raise_for_status()
        out = []
        for j in r.json():
            cats = j.get("categories") or {}
            loc = cats.get("location") or ", ".join(cats.get("allLocations") or []) or None
            sections = [j.get("descriptionPlain") or ""]
            for lst in j.get("lists") or []:
                sections.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content')) or ''}")
            sections.append(j.get("additionalPlain") or "")
            wt = (j.get("workplaceType") or "").lower()
            remote = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite",
                      "onsite": "onsite"}.get(wt) or guess_remote_type(loc, j.get("text"))
            created = j.get("createdAt")
            sal = j.get("salaryRange") or {}
            out.append(JobPosting(
                title=j["text"].strip(),
                company=self.cfg.company or self.cfg.name,
                url=j["hostedUrl"],
                location=loc,
                remote_type=remote,
                employment_type=cats.get("commitment"),
                salary_text=(f"{sal.get('currency', '')} {sal.get('min')}-{sal.get('max')} "
                             f"{sal.get('interval', '')}".strip() if sal else None),
                description="\n\n".join(s for s in sections if s.strip()) or None,
                posted_at=(datetime.fromtimestamp(created / 1000, tz=timezone.utc)
                           if created else None),
                external_id=j["id"],
                raw={"id": j["id"], "team": cats.get("team")},
            ))
        return out


class AshbySource(Source):
    """jobs.ashbyhq.com/<board> -> api.ashbyhq.com/posting-api/job-board/<board>"""

    def fetch(self, ctx: SourceContext) -> list[JobPosting]:
        r = ctx.http.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{self.cfg.board}",
            params={"includeCompensation": "true"},
        )
        r.raise_for_status()
        out = []
        for j in r.json().get("jobs", []):
            if j.get("isListed") is False:
                continue
            loc = j.get("location")
            wt = (j.get("workplaceType") or "").lower()
            remote = ("remote" if j.get("isRemote") or wt == "remote"
                      else {"hybrid": "hybrid", "onsite": "onsite"}.get(wt)
                      or guess_remote_type(loc))
            comp = j.get("compensation") or {}
            out.append(JobPosting(
                title=j["title"].strip(),
                company=self.cfg.company or self.cfg.name,
                url=j.get("jobUrl") or j.get("applyUrl"),
                location=loc,
                remote_type=remote,
                employment_type=j.get("employmentType"),
                salary_text=comp.get("compensationTierSummary"),
                description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                posted_at=_iso(j.get("publishedAt")),
                external_id=j.get("id"),
                raw={"id": j.get("id"), "department": j.get("department")},
            ))
        return out
