"""Job feeds of large employers that do not use Greenhouse, Lever or Ashby.

- amazon:    amazon.jobs has an open search feed with full descriptions.
- microsoft: its careers site answers search and job-detail requests as JSON.
- workday:   the careers system behind Adobe, Nvidia, Salesforce and many others. Give the
             public careers address, e.g. https://adobe.wd5.myworkdayjobs.com/external_experienced

These employers list thousands of jobs, so each reader asks only for the candidate's countries
and drops jobs the rule filters would drop anyway before it fetches a description.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..config import ConfigError, SourceConfig
from ..filters import country_of, reject_reason
from ..models import JobPosting
from .base import Source, SourceContext, guess_remote_type, html_to_text, parse_posted

# Our country label -> (name the employer's site uses, ISO code)
_COUNTRIES = {"India": ("India", "IND"), "UAE": ("United Arab Emirates", "ARE"),
              "Saudi Arabia": ("Saudi Arabia", "SAU"), "Qatar": ("Qatar", "QAT")}
_BY_CODE = {code: label for label, (_, code) in _COUNTRIES.items()}


def _wanted(ctx: SourceContext) -> list[str]:
    """The candidate's countries, in the order of their preferences (all four when none are set)."""
    places = getattr(ctx.prefs, "locations", None) or []
    found = [c for c in dict.fromkeys(country_of(p) for p in places) if c in _COUNTRIES]
    return found or list(_COUNTRIES)


def _passes(ctx: SourceContext, job: JobPosting) -> bool:
    return ctx.prefs is None or reject_reason(job, ctx.prefs) is None


def _query(cfg: SourceConfig) -> str:
    return str(cfg.extra.get("query") or "software engineer")


def _limit(cfg: SourceConfig, default: int) -> int:
    return int(cfg.extra.get("max_results") or default)


class AmazonSource(Source):
    """https://www.amazon.jobs/en/search.json, one request per page of 100 jobs."""

    @classmethod
    def validate(cls, cfg: SourceConfig) -> None:
        pass  # nothing to configure: the feed is the same for everyone

    def fetch(self, ctx: SourceContext) -> list[JobPosting]:
        out: dict[str, JobPosting] = {}
        for label in _wanted(ctx):
            code, offset, cap = _COUNTRIES[label][1], 0, _limit(self.cfg, 300)
            while offset < cap:
                r = ctx.http.get("https://www.amazon.jobs/en/search.json", params={
                    "base_query": _query(self.cfg), "normalized_country_code[]": code,
                    "result_limit": 100, "offset": offset, "sort": "recent"})
                r.raise_for_status()
                jobs = r.json().get("jobs") or []
                for j in jobs:
                    where = ", ".join(x for x in (j.get("city"), j.get("state"),
                                                  _BY_CODE.get(j.get("country_code"), label)) if x)
                    parts = [html_to_text(j.get("description")),
                             _section("Basic qualifications", j.get("basic_qualifications")),
                             _section("Preferred qualifications", j.get("preferred_qualifications"))]
                    job = JobPosting(
                        title=(j.get("title") or "").strip(), company=self.cfg.company or "Amazon",
                        url="https://www.amazon.jobs" + (j.get("job_path") or ""), location=where,
                        remote_type=guess_remote_type(where, j.get("title")),
                        employment_type=j.get("job_schedule_type"),
                        description="\n\n".join(p for p in parts if p) or None,
                        posted_at=_amazon_date(j.get("posted_date")),
                        external_id=str(j.get("id_icims") or j.get("id") or ""),
                        raw={"team": (j.get("team") or {}).get("label") if isinstance(j.get("team"), dict) else None,
                             "category": j.get("job_category")})
                    if job.title and job.external_id and _passes(ctx, job):
                        out[job.external_id] = job
                offset += 100
                if len(jobs) < 100:
                    break
        ctx.log(f"{self.cfg.name}: kept {len(out)} jobs that fit your rules")
        return list(out.values())


def _section(heading: str, html: str | None) -> str | None:
    text = html_to_text(html)
    return f"{heading}:\n{text}" if text else None


def _amazon_date(text: str | None) -> datetime | None:
    try:
        return datetime.strptime(re.sub(r"\s+", " ", text or "").strip(), "%B %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _patient_get(ctx: SourceContext, url: str, params: dict, pause: float = 0.6):
    """A GET that keeps a polite pace and waits when the site says it is being asked too often."""
    for wait in (0, 8, 25):
        time.sleep(wait or pause)
        r = ctx.http.get(url, params=params)
        if r.status_code != 429:
            break
    r.raise_for_status()
    return r


class MicrosoftSource(Source):
    """apply.careers.microsoft.com: a search of 10 jobs per page, then one request per job kept."""

    BASE = "https://apply.careers.microsoft.com"

    @classmethod
    def validate(cls, cfg: SourceConfig) -> None:
        pass

    def fetch(self, ctx: SourceContext) -> list[JobPosting]:
        found: dict[str, dict] = {}
        for label in _wanted(ctx):
            start, cap = 0, _limit(self.cfg, 100)
            while start < cap:
                r = _patient_get(ctx, f"{self.BASE}/api/pcsx/search", {
                    "domain": "microsoft.com", "query": _query(self.cfg), "location": _COUNTRIES[label][0],
                    "start": start, "sort_by": "timestamp"})
                positions = (r.json().get("data") or {}).get("positions") or []
                for p in positions:
                    found.setdefault(str(p["id"]), p)
                start += 10
                if len(positions) < 10:
                    break
        out: list[JobPosting] = []
        kept = sorted((p for p in found.values() if _passes(ctx, self._posting(p, None))),
                      key=lambda p: p.get("postedTs") or 0, reverse=True)
        for p in kept[: self.cfg.max_detail_pages]:
            description = None
            try:
                r = _patient_get(ctx, f"{self.BASE}/api/pcsx/position_details",
                                 {"position_id": p["id"], "domain": "microsoft.com", "hl": "en"})
                description = html_to_text((r.json().get("data") or {}).get("jobDescription"))
            except Exception as e:  # noqa: BLE001 - keep the job, scored on its title alone
                ctx.log(f"{self.cfg.name}: no description for {p.get('name')}: {type(e).__name__}")
            out.append(self._posting(p, description))
        ctx.log(f"{self.cfg.name}: {len(found)} found, {len(kept)} fit your rules, {len(out)} read in full")
        return out

    def _posting(self, p: dict, description: str | None) -> JobPosting:
        # "India, Telangana, Hyderabad" -> "Hyderabad, Telangana, India"
        places = [", ".join(reversed([x.strip() for x in loc.split(",") if "Multiple" not in x]))
                  for loc in (p.get("locations") or [])[:3]]
        where = " / ".join(places) or None
        return JobPosting(
            title=(p.get("name") or "").strip(), company=self.cfg.company or "Microsoft",
            url=self.BASE + (p.get("positionUrl") or f"/careers/job/{p['id']}"), location=where,
            remote_type=guess_remote_type(where, p.get("workLocationOption")), description=description,
            posted_at=(datetime.fromtimestamp(p["postedTs"], tz=timezone.utc) if p.get("postedTs") else None),
            external_id=str(p["id"]), raw={"department": p.get("department"), "job_id": p.get("displayJobId")})


class WorkdaySource(Source):
    """<tenant>.wdN.myworkdayjobs.com/<site>: a search of 20 jobs per page, then one request per job kept."""

    @classmethod
    def validate(cls, cfg: SourceConfig) -> None:
        if not cfg.urls or not _workday_base(cfg.urls[0]):
            raise ConfigError(f"Source '{cfg.name}' (workday) needs its careers address in 'urls', "
                              "like https://adobe.wd5.myworkdayjobs.com/external_experienced")

    def fetch(self, ctx: SourceContext) -> list[JobPosting]:
        site, api = _workday_base(self.cfg.urls[0])
        body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": _query(self.cfg)}
        first = self._search(ctx, api, body)
        facets = _country_facets(first.get("facets") or [], [_COUNTRIES[c][0] for c in _wanted(ctx)])
        if facets:  # ask the site for the candidate's countries only
            body["appliedFacets"] = facets
            first = self._search(ctx, api, body)
        listed, total, cap = list(first.get("jobPostings") or []), int(first.get("total") or 0), _limit(self.cfg, 100)
        while len(listed) < min(total, cap):
            body["offset"] = len(listed)
            more = self._search(ctx, api, body).get("jobPostings") or []
            if not more:
                break
            listed += more
        company = self.cfg.company or self.cfg.name
        kept = []
        for j in listed:
            where = j.get("locationsText")
            if where and re.fullmatch(r"\d+ Locations?", where.strip()):
                where = None  # "3 Locations": the job page has the real ones
            draft = JobPosting(title=(j.get("title") or "").strip(), company=company,
                               url=site + (j.get("externalPath") or ""), location=where,
                               posted_at=parse_posted(j.get("postedOn")))
            # When the site already filtered by country, a bare city ("Kochi") is in one of the
            # candidate's countries: judge the place later, from the job page, not from this text.
            check = draft.model_copy(update={"location": None}) if facets else draft
            if draft.title and j.get("externalPath") and _passes(ctx, check):
                kept.append((j, draft))
        kept.sort(key=lambda x: x[1].posted_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        out = []
        for j, draft in kept[: self.cfg.max_detail_pages]:
            try:
                r = ctx.http.get(api + j["externalPath"], headers={"Accept": "application/json"})
                r.raise_for_status()
                info = r.json().get("jobPostingInfo") or {}
            except Exception as e:  # noqa: BLE001 - keep the job, scored on its title alone
                ctx.log(f"{self.cfg.name}: no description for {draft.title}: {type(e).__name__}")
                info = {}
            country = (info.get("country") or {}).get("descriptor")
            where = info.get("location") or draft.location
            if where and country and country.lower() not in where.lower():
                where = f"{where}, {country}"
            job = draft.model_copy(update={
                "url": info.get("externalUrl") or draft.url, "location": where,
                "remote_type": guess_remote_type(where, draft.title),
                "employment_type": info.get("timeType"),
                "description": html_to_text(info.get("jobDescription")),
                "posted_at": _iso_date(info.get("startDate")) or draft.posted_at,
                "external_id": info.get("jobReqId") or (j.get("bulletFields") or [None])[0]})
            if _passes(ctx, job):  # the real location and date can still rule it out
                out.append(job)
        ctx.log(f"{self.cfg.name}: {len(listed)} listed, {len(kept)} fit your rules, {len(out)} read in full")
        return out

    def _search(self, ctx: SourceContext, api: str, body: dict) -> dict:
        r = ctx.http.post(api + "/jobs", json=body, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()


def _workday_base(address: str) -> tuple[str, str] | None:
    """(public site address, feed address) from a careers address, or None if it is not Workday's."""
    u = urlparse(address.strip())
    host = (u.hostname or "").lower()
    parts = [p for p in u.path.split("/") if p and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)]
    if not host.endswith(".myworkdayjobs.com") or not parts:
        return None
    tenant, site = host.split(".")[0], parts[0]
    return f"https://{host}/{site}", f"https://{host}/wday/cxs/{tenant}/{site}"


def _country_facets(facets: list[dict], names: list[str]) -> dict[str, list[str]]:
    """The site's own filter for these countries, wherever it nests it: {parameter: [ids]}."""
    wanted, out = {n.lower() for n in names}, {}

    def walk(items: list[dict], parameter: str | None) -> None:
        for item in items:
            param = item.get("facetParameter") or parameter
            if item.get("id") and param and "country" in param.lower() \
                    and str(item.get("descriptor", "")).lower() in wanted:
                out.setdefault(param, []).append(item["id"])
            walk(item.get("values") or [], param)

    walk(facets, None)
    return out


def _iso_date(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc) if text else None
    except ValueError:
        return None
