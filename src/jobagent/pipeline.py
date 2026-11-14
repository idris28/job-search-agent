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
    stopped: str = ""  # why the run stopped early, when a spending limit was reached


WAITING_DAYS = 7  # a stored job counts as still open if a search saw it this recently


def waiting_jobs(conn, cfg: AgentConfig, profile_id: int, *, brief: bool = False) -> list[tuple[int, JobPosting]]:
    """Stored jobs that pass the rule filters and were never scored, newest first.

    They are left behind when a search reaches its cap or a spending limit, is stopped, or was
    run to collect only.
    """
    out = []
    for r in db.unscored_jobs(conn, profile_id, WAITING_DAYS, brief=brief):
        job_id = r.pop("id")
        posting = JobPosting(**{**r, "remote_type": r["remote_type"] or "unknown"})
        if reject_reason(posting, cfg.search) is None:
            out.append((job_id, posting))
    return out


def run_agent(conn, cfg: AgentConfig, llm, browser: Browser | None, *, http: httpx.Client | None = None,
              only_source: str | None = None, score: bool = True, collect: bool = True) -> RunSummary:
    """One search. With collect=False no site is read: the stored jobs still waiting are scored."""
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

    def over_budget() -> str:
        m = cfg.matching
        tokens = getattr(llm, "tokens_used", 0)
        minutes = getattr(browser, "minutes_used", 0.0)
        if m.max_tokens_per_run and tokens >= m.max_tokens_per_run:
            return f"token limit reached ({tokens:,} of {m.max_tokens_per_run:,})"
        if m.max_browser_minutes_per_run and minutes >= m.max_browser_minutes_per_run:
            return f"browser time limit reached ({minutes:.1f} of {m.max_browser_minutes_per_run:g} minutes)"
        return ""

    strong: list[int] = []  # jobs scored high enough to shortlist
    try:
        # 1. Collect -----------------------------------------------------------
        candidates: list[tuple[int, JobPosting]] = []
        if not collect:
            candidates = waiting_jobs(conn, cfg, profile["id"])
            event(f"{len(candidates)} stored jobs are waiting to be scored")
        for scfg in cfg.sources if collect else []:
            if not scfg.enabled or (only_source and scfg.name != only_source):
                continue
            summary.stopped = summary.stopped or over_budget()
            if summary.stopped:
                event(f"{scfg.name}: skipped, {summary.stopped}", level="warning")
                continue
            source_id = db.upsert_source(conn, scfg.kind, scfg.name, scfg.identity_url,
                                         scfg.model_dump(mode="json"))
            ctx = SourceContext(http=http, browser=browser, llm=llm,
                                log=lambda m, sid=source_id: event(m, source_id=sid),
                                prefs=cfg.search)
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
            to_score, queued = [], set()
            for job_id, p in candidates:
                seen_hash = db.existing_match_hash(conn, profile["id"], job_id)
                # A second listing of the same job (another board, or twice in this run) is not
                # scored again for its different wording.
                if job_id in queued or seen_hash == p.content_hash \
                        or (seen_hash and db.is_other_listing(conn, job_id, p)):
                    summary.skipped_unchanged += 1
                else:
                    queued.add(job_id)
                    to_score.append((job_id, p))
            cap = cfg.matching.max_jobs_to_score
            if len(to_score) > cap:
                event(f"{len(to_score)} jobs to score; capped at {cap} (matching.max_jobs_to_score)",
                      level="warning")
                to_score = to_score[:cap]

            workers = max(1, cfg.matching.concurrency)
            pool = ThreadPoolExecutor(max_workers=workers)
            try:
                # Scored a few at a time so a spending limit is checked between batches; jobs
                # left over stay unscored and are picked up by the next run.
                for start in range(0, len(to_score), workers):
                    summary.stopped = summary.stopped or over_budget()
                    if summary.stopped:
                        event(f"Scoring stopped with {len(to_score) - start} jobs left: {summary.stopped}",
                              level="warning")
                        break
                    futures = {
                        pool.submit(llm.score_job, profile["profile"], cfg.search, p): (job_id, p)
                        for job_id, p in to_score[start:start + workers]
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
            finally:
                # Never wait here for calls still in flight: when the search is stopped its end
                # must be recorded at once, and a job left unscored is picked up next time.
                pool.shutdown(wait=False, cancel_futures=True)
            summary.shortlisted = db.shortlist_many(conn, profile["id"], strong)

        summary.tokens = getattr(llm, "tokens_used", 0)
        summary.status = "partial" if summary.source_errors or summary.stopped else "succeeded"
        db.finish_run(conn, run_id, status=summary.status, stats=summary.__dict__,
                      error=db.partial_reason(list(summary.source_errors), summary.stopped) or None)
        return summary
    except KeyboardInterrupt:
        # Ctrl-C, the page's Stop button, or the program being closed. What was saved is kept:
        # shortlist the jobs already scored high enough, then record where the search ended.
        why = "; ".join(filter(None, [db.STOPPED_EARLY, db.partial_reason(list(summary.source_errors), summary.stopped)]))
        summary.status, summary.stopped = "partial", "stopped before it finished"
        summary.tokens = getattr(llm, "tokens_used", 0)
        try:
            summary.shortlisted = db.shortlist_many(conn, profile["id"], strong)
            db.finish_run(conn, run_id, status="partial", stats=summary.__dict__, error=why)
        except Exception as e:  # noqa: BLE001 - the stop can land mid-query; close_dead_runs ends it later
            log.warning("could not record that run %s was stopped: %s", run_id, e)
        raise
    except Exception as e:
        summary.status = "failed"
        db.finish_run(conn, run_id, status="failed", stats=summary.__dict__, error=str(e))
        raise
    finally:
        if own_http:
            http.close()
