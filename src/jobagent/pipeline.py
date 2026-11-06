"""One agent run: collect jobs from every source, store, filter, score, shortlist."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import httpx

from . import db
from .browser import Browser
from .config import AgentConfig
from .filters import reject_reason
from .models import JobPosting
from .sources import SourceContext, build_source

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    run_id: int
    status: str
    found: int = 0
    new: int = 0
    filtered: int = 0
    scored: int = 0
    skipped_unchanged: int = 0
    shortlisted: int = 0
    tokens: int = 0
    source_errors: dict[str, str] = field(default_factory=dict)


def run_agent(conn, cfg: AgentConfig, llm, browser: Browser, *, http: httpx.Client | None = None,
              only_source: str | None = None, score: bool = True) -> RunSummary:
    profile = db.active_profile(conn)
    if profile is None:
        raise RuntimeError("No profile yet. Run: jsa profile import <resume.pdf>")

    run_id = db.start_run(conn, profile["id"], cfg.model_dump(mode="json"))
    summary = RunSummary(run_id=run_id, status="running")
    own_http = http is None
    http = http or httpx.Client(timeout=30, follow_redirects=True,
                                headers={"User-Agent": "jobagent/0.1 (personal job search)"})

    def event(msg: str, level: str = "info", source_id: int | None = None, data=None):
        log.log(logging.WARNING if level in ("warning", "error") else logging.INFO, msg)
        db.log_event(conn, run_id, msg, level=level, source_id=source_id, data=data)

    try:
        # 1. Collect -----------------------------------------------------------
        candidates: list[tuple[int, JobPosting]] = []
        for scfg in cfg.sources:
            if not scfg.enabled or (only_source and scfg.name != only_source):
                continue
            source_id = db.upsert_source(conn, scfg.kind, scfg.name, scfg.identity_url,
                                         scfg.model_dump(mode="json"))
            ctx = SourceContext(http=http, browser=browser, llm=llm,
                                log=lambda m, sid=source_id: event(m, source_id=sid))
            try:
                postings = build_source(scfg).fetch(ctx)
            except Exception as e:  # noqa: BLE001 - one bad source must not kill the run
                summary.source_errors[scfg.name] = str(e)
                event(f"{scfg.name}: failed: {e}", level="error", source_id=source_id)
                continue

            new_here = 0
            for p in postings:
                job_id, is_new = db.upsert_job(conn, p, source_id, run_id)
                new_here += is_new
                why = reject_reason(p, cfg.search)
                if why:
                    summary.filtered += 1
                else:
                    candidates.append((job_id, p))
            summary.found += len(postings)
            summary.new += new_here
            event(f"{scfg.name}: {len(postings)} jobs ({new_here} new)", source_id=source_id)

        # 2. Score -------------------------------------------------------------
        if score and candidates:
            to_score = []
            for job_id, p in candidates:
                if db.existing_match_hash(conn, profile["id"], job_id) == p.content_hash:
                    summary.skipped_unchanged += 1
                else:
                    to_score.append((job_id, p))
            cap = cfg.matching.max_jobs_to_score
            if len(to_score) > cap:
                event(f"{len(to_score)} jobs to score; capped at {cap} (matching.max_jobs_to_score)",
                      level="warning")
                to_score = to_score[:cap]

            strong: list[int] = []
            with ThreadPoolExecutor(max_workers=max(1, cfg.matching.concurrency)) as pool:
                futures = {
                    pool.submit(llm.score_job, profile["profile"], cfg.search, p): (job_id, p)
                    for job_id, p in to_score
                }
                for fut in as_completed(futures):
                    job_id, p = futures[fut]
                    try:
                        m = fut.result()
                    except Exception as e:  # noqa: BLE001
                        event(f"scoring failed for job {job_id} ({p.title}): {e}", level="error")
                        continue
                    db.save_match(conn, profile["id"], job_id, run_id, m, llm.model, p.content_hash)
                    summary.scored += 1
                    if m.score >= cfg.matching.shortlist_min_score:
                        strong.append(job_id)
            summary.shortlisted = db.shortlist_many(conn, profile["id"], strong)

        summary.tokens = getattr(llm, "tokens_used", 0)
        summary.status = "partial" if summary.source_errors else "succeeded"
        db.finish_run(conn, run_id, status=summary.status, stats=summary.__dict__)
        return summary
    except Exception as e:
        summary.status = "failed"
        db.finish_run(conn, run_id, status="failed", stats=summary.__dict__, error=str(e))
        raise
    finally:
        if own_http:
            http.close()
