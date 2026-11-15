"""One agent run: collect jobs from every source, store, filter, score, shortlist."""

from __future__ import annotations

import logging
import queue
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import httpx

from . import costs, db
from .browser import Browser
from .config import AgentConfig
from .filters import reject_reason
from .models import JobPosting, MatchResult
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
    screened_out: int = 0  # ruled out by the quick first check, so not given the full scoring
    skipped_unchanged: int = 0
    unread: int = 0  # job-board jobs left unscored because their own page has not been opened yet
    batched: int = 0  # sent for scoring as a batch whose answers are collected by a later search
    shortlisted: int = 0
    tokens: int = 0
    cost: float | None = None  # an estimate in US dollars; None when a model's price is not known
    usage: dict = field(default_factory=dict)  # tokens and cost by model
    source_errors: dict[str, str] = field(default_factory=dict)
    stopped: str = ""  # why the run stopped early, when a spending limit was reached


WAITING_DAYS = 7  # a stored job counts as still open if a search saw it this recently
SCREENED_SCORE = 20  # the score recorded for a job the quick first check ruled out
SITES_AT_ONCE = 6  # how many company career sites are read at the same time
BATCH_POLL_SECONDS = 30  # how often a search asks whether its scoring batch has been answered


def waiting_jobs(conn, cfg: AgentConfig, profile_id: int, *, brief: bool = False) -> list[tuple[int, JobPosting]]:
    """Stored jobs that pass the rule filters and were never scored, newest first.

    They are left behind when a search reaches its cap or a spending limit, is stopped, or was
    run to collect only.
    """
    out = []
    for r in db.unscored_jobs(conn, profile_id, WAITING_DAYS, brief=brief):
        job_id = r.pop("id")
        posting = _posting(r)
        if reject_reason(posting, cfg.search) is None:
            out.append((job_id, posting))
    return out


def _posting(row: dict) -> JobPosting:
    return JobPosting(**{**row, "remote_type": row["remote_type"] or "unknown"})


def unread_jobs(conn, cfg: AgentConfig) -> int:
    """How many job-board jobs that pass the rule filters wait for their own page to be opened.
    Jobs of a board that is switched off are left out: no search will read them."""
    boards = {s.name for s in cfg.sources if s.enabled and s.kind == "generic" and s.max_detail_pages > 0}
    return sum(1 for r in db.unread_postings(conn, WAITING_DAYS, brief=True)
               if r.pop("board") in boards and reject_reason(_posting(r), cfg.search) is None)


def _recalled(conn, job: JobPosting) -> JobPosting | None:
    """The stored copy of a job a board lists again, reached through the link listed now."""
    row = db.stored_posting(conn, job)
    if row is None:
        return None
    old = _posting(row)
    return old.model_copy(update={
        "url": job.url, "posted_at": old.posted_at or job.posted_at,
        "remote_type": old.remote_type if old.remote_type != "unknown" else job.remote_type})


class _PageReader:
    """Reads job-site pages with the cheaper model. A page it cannot read goes to the main model,
    so a wrong model name or an outage costs a little more instead of losing the site."""

    def __init__(self, cheap, main, warn):
        self.cheap, self.main, self.warn = cheap, main, warn

    def extract_listings(self, text, links, url):
        try:
            return self.cheap.extract_listings(text, links, url)
        except Exception as e:  # noqa: BLE001
            self.warn(f"{self.cheap.model} could not read {url}: {e}. The main model read it instead")
            return self.main.extract_listings(text, links, url)


def run_agent(conn, cfg: AgentConfig, llm, browser: Browser | None, *, http: httpx.Client | None = None,
              only_source: str | None = None, score: bool = True, collect: bool = True,
              prescreen=None, reader=None, batch: bool = False, leave_batch: bool = False) -> RunSummary:
    """One search. With collect=False no site is read: the stored jobs still waiting are scored.

    `prescreen` is a second, cheaper AI client: each job gets its quick look first, and only the
    ones it does not rule out get the full scoring. `reader` is a cheaper client too: it turns
    job-site pages into lists of jobs. `batch` sends the full scoring as one batch, which costs
    half and is answered later; it is used when nobody is waiting for the result. With
    `leave_batch` the search does not wait for the answers at all: a later search stores them.
    """
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

    def tokens_spent() -> int:
        clients = {id(c): c for c in (llm, prescreen, reader) if c is not None}  # one model may serve two jobs
        return sum(getattr(c, "tokens_used", 0) for c in clients.values())

    def spending() -> None:
        """Put what the AI calls used so far, and what that cost, on the summary."""
        summary.usage = costs.usage_of((llm, prescreen, reader), cfg.matching.prices)
        summary.tokens, summary.cost = tokens_spent(), costs.total(summary.usage)

    def over_budget() -> str:
        m = cfg.matching
        tokens = tokens_spent()
        minutes = getattr(browser, "minutes_used", 0.0)
        if m.max_tokens_per_run and tokens >= m.max_tokens_per_run:
            return f"token limit reached ({tokens:,} of {m.max_tokens_per_run:,})"
        spent = costs.total(costs.usage_of((llm, prescreen, reader), m.prices)) if m.max_cost_per_run else None
        if spent is not None and spent >= m.max_cost_per_run:
            return f"cost limit reached (about ${spent:.2f} of ${m.max_cost_per_run:.2f})"
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
        page_llm = llm
        if reader is not None and collect:
            page_llm = _PageReader(reader, llm, lambda m: event(m, level="warning"))
            event(f"Job-site pages are read by {reader.model}")
        chosen = [s for s in cfg.sources if s.enabled and not (only_source and s.name != only_source)] if collect else []
        site_id = {s.name: db.upsert_source(conn, s.kind, s.name, s.identity_url, s.model_dump(mode="json")) for s in chosen}
        found: dict[str, list[tuple[int, JobPosting]]] = {}  # per site, so the jobs keep the order of the settings
        began = time.monotonic()

        def store(scfg, postings, board: bool = False) -> None:
            new_here, kept = 0, []
            for p in postings:
                job_id, is_new = db.upsert_job(conn, p, site_id[scfg.name], run_id)
                new_here += is_new
                why = reject_reason(p, cfg.search)
                if why:
                    summary.filtered += 1
                elif board and not p.is_read:
                    summary.unread += 1
                else:
                    kept.append((job_id, p))
            found[scfg.name] = kept
            summary.found += len(postings)
            summary.new += new_here
            event(f"{scfg.name}: {len(postings)} jobs ({new_here} new)", source_id=site_id[scfg.name])

        def failed(scfg, e: Exception) -> None:  # one bad source must not kill the run
            summary.source_errors[scfg.name] = str(e)
            event(f"{scfg.name}: failed: {e}", level="error", source_id=site_id[scfg.name])

        # Company career sites are read over plain HTTP, several at the same time, while the job
        # boards are read one after another in the browser. Reading costs no AI and no browser
        # time, so a spending limit does not hold these sites back. Only this thread touches the
        # database: what a site being read has to say is queued, and written down here.
        feeds = [s for s in chosen if s.kind != "generic"]
        said: queue.SimpleQueue = queue.SimpleQueue()
        pool = ThreadPoolExecutor(max_workers=SITES_AT_ONCE, thread_name_prefix="site") if feeds else None

        def read_feed(scfg):
            ctx = SourceContext(http=http, browser=None, llm=page_llm, prefs=cfg.search,
                                log=lambda m, sid=site_id[scfg.name]: said.put((m, sid)))
            return build_source(scfg).fetch(ctx)

        reading = {s.name: pool.submit(read_feed, s) for s in feeds}
        taken = 0  # company sites stored so far; they are stored in the order of the settings

        def write_down() -> None:
            while not said.empty():
                message, sid = said.get()
                event(message, source_id=sid)

        def take_in(wait: bool = False) -> None:
            """Store what the company sites have brought so far; with `wait`, everything left."""
            nonlocal taken
            while taken < len(feeds):
                scfg = feeds[taken]
                if not wait and not reading[scfg.name].done():
                    break
                try:
                    postings = reading[scfg.name].result()
                except Exception as e:  # noqa: BLE001
                    write_down()
                    failed(scfg, e)
                else:
                    write_down()
                    store(scfg, postings)
                taken += 1
            write_down()

        try:
            for scfg in chosen:
                if scfg.kind != "generic":
                    continue
                summary.stopped = summary.stopped or over_budget()
                if summary.stopped:
                    event(f"{scfg.name}: skipped, {summary.stopped}", level="warning")
                    continue
                source_id = site_id[scfg.name]
                # A job board may name its own browser; the others are read with the one set in .env.
                ctx = SourceContext(http=http, browser=browser.of(scfg.browser) if hasattr(browser, "of") else browser, llm=page_llm,
                                    log=lambda m, sid=source_id: event(m, source_id=sid),
                                    prefs=cfg.search)
                # A job board's list gives a title, a company and a place. The job's own page is opened
                # once, and until it has been the job is not scored: a title alone tells too little.
                board = scfg.max_detail_pages > 0
                if board:
                    ctx.recall = lambda job: _recalled(conn, job)
                    ctx.unread = [_posting(r) for r in db.unread_postings(conn, WAITING_DAYS, source_id=source_id)]
                try:
                    postings = build_source(scfg).fetch(ctx)
                except Exception as e:  # noqa: BLE001
                    failed(scfg, e)
                else:
                    store(scfg, postings, board)
                take_in()
            take_in(wait=True)
        finally:
            if pool is not None:  # a stopped search must not wait for sites still being read
                pool.shutdown(wait=False, cancel_futures=True)
        for scfg in chosen:
            candidates += found.get(scfg.name, [])
        summary.source_errors = {s.name: summary.source_errors[s.name] for s in chosen if s.name in summary.source_errors}
        if len(chosen) > 1:
            event(f"{len(chosen)} sites read in {(time.monotonic() - began) / 60:.1f} minutes")

        # 2. Score -------------------------------------------------------------
        workers = max(1, cfg.matching.concurrency)
        floor = cfg.matching.shortlist_min_score

        def pooled(jobs, call, done, what, failed=None) -> None:
            """Run `call` for each job, a few at a time, so a spending limit is checked between
            rounds; jobs not reached stay unscored and are picked up by the next search."""
            pool = ThreadPoolExecutor(max_workers=workers)
            try:
                for start in range(0, len(jobs), workers):
                    summary.stopped = summary.stopped or over_budget()
                    if summary.stopped:
                        event(f"{what} stopped with {len(jobs) - start} jobs left: {summary.stopped}", level="warning")
                        break
                    futures = {pool.submit(call, profile["profile"], cfg.search, p): (job_id, p)
                               for job_id, p in jobs[start:start + workers]}
                    for fut in as_completed(futures):
                        job_id, p = futures[fut]
                        try:
                            result = fut.result()
                        except Exception as e:  # noqa: BLE001
                            event(f"{what.lower()} failed for job {job_id} ({p.title}): {e}", level="error")
                            if failed:
                                failed(job_id, p)
                            continue
                        done(job_id, p, result)
            finally:
                # Never wait here for calls still in flight: when the search is stopped its end
                # must be recorded at once, and a job left unscored is picked up next time.
                pool.shutdown(wait=False, cancel_futures=True)

        def keep(job_id: int, m: MatchResult, model: str, content_hash: str) -> None:
            db.save_match(conn, profile["id"], job_id, run_id, m, model, content_hash)
            summary.scored += 1
            if m.score >= floor:
                strong.append(job_id)

        def quick_check(jobs: list) -> list:
            """The cheaper model's first look. A job it rules out is recorded with a low score and
            the reason, so it is not looked at again; the rest go on to the full scoring."""
            passed: list = []

            def done(job_id, p, verdict) -> None:
                if verdict.worth_scoring:
                    passed.append((job_id, p))
                    return
                db.save_match(conn, profile["id"], job_id, run_id,
                              MatchResult(score=SCREENED_SCORE, verdict="poor", summary=f"Quick check: {verdict.reason}",
                                          matched_skills=[], missing_skills=[], red_flags=[]),
                              prescreen.model, p.content_hash)
                summary.screened_out += 1

            # A quick check that fails says nothing about the job, so the job keeps its full scoring.
            pooled(jobs, prescreen.prescreen_job, done, "Quick check", failed=lambda job_id, p: passed.append((job_id, p)))
            event(f"Quick check ({prescreen.model}): {summary.screened_out} of {len(jobs)} jobs ruled out")
            return passed

        def take_batch(batch_id: str, model: str, jobs: dict) -> None:
            """Store the answers of a finished batch. `jobs` maps each request to (job id, text hash)."""
            answers = llm.collect_scores(batch_id)
            for custom_id, (job_id, content_hash) in jobs.items():
                answer = answers.get(custom_id)
                if not isinstance(answer, MatchResult):
                    event(f"scoring failed for job {job_id}: {answer or 'no answer in the batch'}", level="error")
                # The job may have been deleted while the batch ran, or scored meanwhile in the ordinary way.
                elif db.get_job(conn, job_id) and db.existing_match_hash(conn, profile["id"], job_id) != content_hash:
                    keep(job_id, answer, model, content_hash)
            event(db.BATCH_TAKEN, data={"batch": batch_id})

        def score_as_batch(jobs: list) -> None:
            ids = {f"job-{job_id}": (job_id, p) for job_id, p in jobs}
            batch_id = llm.submit_scores(profile["profile"], cfg.search, [(cid, p) for cid, (_, p) in ids.items()])
            held = {cid: [job_id, p.content_hash] for cid, (job_id, p) in ids.items()}
            # Recorded before waiting: if this search is stopped, a later one still finds the batch.
            event(db.BATCH_SENT, data={"batch": batch_id, "model": llm.model, "jobs": held})
            if leave_batch:
                summary.batched += len(jobs)
                event(f"{len(jobs)} jobs sent for scoring as a batch; their scores are stored by the next search, or by Score waiting jobs")
                return
            wait = cfg.matching.batch_wait_minutes
            event(f"{len(jobs)} jobs sent for scoring as a batch; waiting up to {wait} minutes for the answers")
            deadline = time.monotonic() + wait * 60
            while not llm.batch_done(batch_id):
                if time.monotonic() >= deadline:
                    summary.stopped = summary.stopped or (f"the scoring batch was still running after {wait} minutes; "
                                                          "the next search picks its answers up")
                    return
                time.sleep(BATCH_POLL_SECONDS)
            take_batch(batch_id, llm.model, held)

        being_scored: dict[int, str] = {}  # job id -> text hash, for jobs in a batch that is still running
        if score and hasattr(llm, "collect_scores"):
            for waiting in db.pending_batches(conn):  # sent by an earlier search that did not wait long enough
                data = waiting["data"]
                try:
                    if llm.batch_done(data["batch"]):
                        take_batch(data["batch"], data.get("model") or llm.model, data["jobs"])
                    else:
                        being_scored.update({job_id: content_hash for job_id, content_hash in data["jobs"].values()})
                        event(f"The scoring batch from search #{waiting['run_id']} is still running; "
                              f"its {len(data['jobs'])} jobs are not scored again")
                except Exception as e:  # noqa: BLE001 - leave it for the next search rather than lose paid work
                    event(f"The scoring batch from search #{waiting['run_id']} could not be read: {e}", level="warning")

        if score and candidates:
            to_score, queued = [], set()
            for job_id, p in candidates:
                seen_hash = db.existing_match_hash(conn, profile["id"], job_id)
                # A second listing of the same job (another board, or twice in this run) is not
                # scored again for its different wording.
                if job_id in queued or seen_hash == p.content_hash \
                        or (seen_hash and db.is_other_listing(conn, job_id, p)):
                    summary.skipped_unchanged += 1
                elif being_scored.get(job_id) == p.content_hash:
                    pass  # already paid for in a batch; its answer is stored when the batch finishes
                else:
                    queued.add(job_id)
                    to_score.append((job_id, p))
            cap = cfg.matching.max_jobs_to_score
            if len(to_score) > cap:
                event(f"{len(to_score)} jobs to score; capped at {cap} (matching.max_jobs_to_score)",
                      level="warning")
                to_score = to_score[:cap]
            if prescreen is not None and to_score:
                to_score = quick_check(to_score)
            if batch and to_score and hasattr(llm, "submit_scores"):
                score_as_batch(to_score)
            else:
                pooled(to_score, llm.score_job, lambda job_id, p, m: keep(job_id, m, llm.model, p.content_hash), "Scoring")
        if score:
            summary.shortlisted = db.shortlist_many(conn, profile["id"], strong)

        spending()
        summary.status = "partial" if summary.source_errors or summary.stopped else "succeeded"
        db.finish_run(conn, run_id, status=summary.status, stats=summary.__dict__,
                      error=db.partial_reason(list(summary.source_errors), summary.stopped) or None)
        return summary
    except KeyboardInterrupt:
        # Ctrl-C, the page's Stop button, or the program being closed. What was saved is kept:
        # shortlist the jobs already scored high enough, then record where the search ended.
        why = "; ".join(filter(None, [db.STOPPED_EARLY, db.partial_reason(list(summary.source_errors), summary.stopped)]))
        summary.status, summary.stopped = "partial", "stopped before it finished"
        spending()
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
