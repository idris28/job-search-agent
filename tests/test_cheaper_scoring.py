"""Cheaper scoring: a quick first check by a smaller model, and scoring as a batch."""

import json

import pytest

from jobagent import db, pipeline
from jobagent.config import SearchPrefs
from jobagent.llm import MATCH_INSTRUCTIONS, PRESCREEN_INSTRUCTIONS
from jobagent.models import JobPosting, MatchResult, Prescreen
from jobagent.pipeline import run_agent

from conftest import FakeBrowser, FakeLLM, mock_http
from test_pipeline import gh, make_cfg

JOBS = {"boards-api.greenhouse.io/v1/boards/acme/jobs": gh(
    ("Senior Java Engineer", "Dubai"), ("Backend Engineer", "Dubai"), ("Backend Intern", "Dubai"))}


class Screen(FakeLLM):
    """The cheaper model: rules out the titles it is given, and can fail on one."""

    model = "cheap-model"

    def __init__(self, rule_out=(), fail_on=None):
        super().__init__()
        self.rule_out, self.fail_on, self.looked_at = set(rule_out), fail_on, []

    def prescreen_job(self, profile, prefs, job):
        self.looked_at.append(job.title)
        if job.title == self.fail_on:
            raise RuntimeError("cheap model unavailable")
        self.tokens_used += 10
        if job.title in self.rule_out:
            return Prescreen(worth_scoring=False, reason="An internship, far below a senior engineer.")
        return Prescreen(worth_scoring=True, reason="Plausible.")


def test_a_quick_first_check_spares_the_full_scoring_for_clear_misses(conn):
    pid = db.save_profile(conn, "Alex", "resume", {})
    llm, screen = FakeLLM(scores={"Senior Java Engineer": 90}), Screen(rule_out={"Backend Intern"})
    s = run_agent(conn, make_cfg(concurrency=1), llm, FakeBrowser({}), http=mock_http(JOBS),
                  only_source="Acme", prescreen=screen)

    assert sorted(screen.looked_at) == ["Backend Engineer", "Backend Intern", "Senior Java Engineer"]
    assert sorted(llm.scored_titles) == ["Backend Engineer", "Senior Java Engineer"]  # the intern role was not scored
    assert (s.scored, s.screened_out, s.shortlisted) == (2, 1, 1)
    assert s.tokens == 200 + 30  # both models count toward the search's total and its budget

    ruled_out = conn.execute("""SELECT m.score, m.verdict, m.summary, m.model FROM job_matches m JOIN jobs j ON j.id = m.job_id
                                WHERE j.title = 'Backend Intern'""").fetchone()
    assert ruled_out == {"score": pipeline.SCREENED_SCORE, "verdict": "poor", "model": "cheap-model",
                         "summary": "Quick check: An internship, far below a senior engineer."}
    assert {r["title"] for r in db.top_matches(conn, pid, min_score=0)} == {"Senior Java Engineer", "Backend Engineer", "Backend Intern"}

    # Recorded like any score, so the next search neither looks at it nor scores it again.
    again = Screen(rule_out={"Backend Intern"})
    s2 = run_agent(conn, make_cfg(), FakeLLM(), FakeBrowser({}), http=mock_http(JOBS), only_source="Acme", prescreen=again)
    assert again.looked_at == [] and (s2.scored, s2.screened_out) == (0, 0)


def test_a_quick_check_that_fails_does_not_cost_the_job_its_scoring(conn):
    db.save_profile(conn, "Alex", "resume", {})
    llm, screen = FakeLLM(), Screen(fail_on="Backend Engineer")
    s = run_agent(conn, make_cfg(concurrency=1), llm, FakeBrowser({}), http=mock_http(JOBS), only_source="Acme", prescreen=screen)
    assert sorted(llm.scored_titles) == ["Backend Engineer", "Backend Intern", "Senior Java Engineer"]
    assert (s.scored, s.screened_out, s.status) == (3, 0, "succeeded")


class BatchLLM(FakeLLM):
    """Scores through a batch: answers are ready once `ready` is set."""

    def __init__(self, scores=None, ready=True, refuse=()):
        super().__init__(scores=scores)
        self.ready, self.refuse, self.sent, self.one_by_one = ready, set(refuse), {}, []

    def score_job(self, profile, prefs, job):
        self.one_by_one.append(job.title)  # scored in the ordinary way, at the full price
        return super().score_job(profile, prefs, job)

    def submit_scores(self, profile, prefs, jobs):
        batch_id = f"batch_{len(self.sent) + 1}"
        self.sent[batch_id] = dict(jobs)
        return batch_id

    def batch_done(self, batch_id):
        return self.ready

    def collect_scores(self, batch_id):
        out = {}
        for custom_id, job in self.sent[batch_id].items():
            out[custom_id] = RuntimeError("the batch request errored: declined") if job.title in self.refuse \
                else FakeLLM.score_job(self, None, None, job)
        return out


def test_scoring_as_a_batch_stores_the_same_scores(conn, monkeypatch):
    monkeypatch.setattr(pipeline, "BATCH_POLL_SECONDS", 0)
    pid = db.save_profile(conn, "Alex", "resume", {})
    llm = BatchLLM(scores={"Senior Java Engineer": 90, "Backend Engineer": 60}, refuse={"Backend Intern"})
    s = run_agent(conn, make_cfg(), llm, FakeBrowser({}), http=mock_http(JOBS), only_source="Acme", batch=True)

    assert len(llm.sent) == 1 and sorted(llm.sent["batch_1"]) == ["job-1", "job-2", "job-3"]
    assert (s.status, s.scored, s.shortlisted, s.tokens) == ("succeeded", 2, 1, 200)
    listed = {r["title"]: (r["score"], r["application_status"]) for r in db.top_matches(conn, pid, min_score=0)}
    assert listed == {"Senior Java Engineer": (90, "shortlisted"), "Backend Engineer": (60, None)}
    assert db.pending_batches(conn) == []
    said = [r["message"] for r in conn.execute("SELECT message FROM run_events ORDER BY id").fetchall()]
    assert db.BATCH_SENT in said and db.BATCH_TAKEN in said
    assert any(m.startswith("scoring failed for job") and "declined" in m for m in said)  # the refused one is scored another time

    # A plain search right after scores what the batch could not, in the ordinary way.
    after = FakeLLM()
    run_agent(conn, make_cfg(), after, FakeBrowser({}), http=mock_http(JOBS), only_source="Acme")
    assert after.scored_titles == ["Backend Intern"]


def test_a_batch_not_answered_in_time_is_picked_up_by_the_next_search(conn, monkeypatch):
    monkeypatch.setattr(pipeline, "BATCH_POLL_SECONDS", 0)
    pid = db.save_profile(conn, "Alex", "resume", {})
    llm = BatchLLM(scores={"Senior Java Engineer": 90}, ready=False)
    cfg = make_cfg(batch_wait_minutes=0)
    s = run_agent(conn, cfg, llm, FakeBrowser({}), http=mock_http(JOBS), only_source="Acme", batch=True)
    assert s.status == "partial" and s.scored == 0
    assert db.list_runs(conn)[0]["error"] == ("Stopped early: the scoring batch was still running after 0 minutes; "
                                              "the next search picks its answers up")
    waiting = db.pending_batches(conn)
    assert len(waiting) == 1 and waiting[0]["data"]["batch"] == "batch_1" and len(waiting[0]["data"]["jobs"]) == 3
    assert db.top_matches(conn, pid, min_score=0) == []

    # Still running at the next search: nothing is stored, nothing is lost, and nothing is sent twice.
    for as_batch in (True, False):
        again = run_agent(conn, cfg, llm, FakeBrowser({}), http=mock_http(JOBS), only_source="Acme", batch=as_batch)
        assert (again.scored, again.status) == (0, "succeeded")
    assert len(llm.sent) == 1 and len(db.pending_batches(conn)) == 1

    # Once the answers are there, any search stores them, even one that asks for no batch.
    llm.ready = True
    s3 = run_agent(conn, make_cfg(), llm, FakeBrowser({}), http=mock_http({}), collect=False)
    assert (s3.scored, s3.shortlisted) == (3, 1) and db.pending_batches(conn) == []
    assert len(llm.sent) == 1 and llm.one_by_one == []  # paid for once, at the batch price


# --- the real Anthropic library against a stand-in for the API: checks what is sent and how answers are read ---

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

PROFILE = {"name": "Alex", "primary_skills": ["Java"]}
PREFS = SearchPrefs(roles=["Java Engineer"], locations=["Dubai"])
JOB = JobPosting(title="Senior Java Engineer", company="Acme", url="https://x/1", location="Dubai", description="Java and Spring Boot.")
ANSWER = {"score": 140, "verdict": "strong", "summary": "Fits.", "matched_skills": ["Java"], "missing_skills": [],
          "red_flags": [], "salary_estimate": None}


def message(text, stop_reason="end_turn"):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20}}


def claude(handler, model="claude-sonnet-5-5"):
    from jobagent.llm_anthropic import ClaudeLLM

    client = anthropic.Anthropic(api_key="test-key", max_retries=0,
                                 http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    return ClaudeLLM("test-key", model, effort="low", client=client)


def test_claude_batch_requests_carry_the_scoring_request_without_the_fallback():
    seen = {}
    batch = {"id": "msgbatch_1", "type": "message_batch", "processing_status": "in_progress",
             "request_counts": {"processing": 2, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0},
             "created_at": "2026-11-15T08:00:00Z", "expires_at": "2026-11-16T08:00:00Z", "ended_at": None,
             "archived_at": None, "cancel_initiated_at": None, "results_url": None}

    def handler(request):
        seen["path"], seen["headers"], seen["body"] = request.url.path, request.headers, json.loads(request.content)
        return httpx2.Response(200, json=batch)

    llm = claude(handler)
    assert llm.submit_scores(PROFILE, PREFS, [("job-1", JOB), ("job-2", JOB)]) == "msgbatch_1"
    assert seen["path"] == "/v1/messages/batches"
    assert "fallback" not in (seen["headers"].get("anthropic-beta") or "")
    requests = seen["body"]["requests"]
    assert [r["custom_id"] for r in requests] == ["job-1", "job-2"]
    params = requests[0]["params"]
    assert "fallbacks" not in params and "betas" not in params  # a batch request cannot set them
    assert params["model"] == "claude-sonnet-5-5" and params["system"] == MATCH_INSTRUCTIONS
    candidate, posting = params["messages"][0]["content"]
    assert candidate["cache_control"] == {"type": "ephemeral"} and '"primary_skills"' in candidate["text"]
    assert posting["text"].startswith("JOB POSTING:\nTitle: Senior Java Engineer")
    out = params["output_config"]
    assert out["effort"] == "low" and out["format"]["type"] == "json_schema"
    assert {"score", "verdict", "summary", "matched_skills"} <= set(out["format"]["schema"]["properties"])


def test_claude_batch_answers_are_read_one_by_one():
    done = {"id": "msgbatch_1", "type": "message_batch", "processing_status": "ended",
            "request_counts": {"processing": 0, "succeeded": 3, "errored": 1, "canceled": 0, "expired": 0},
            "created_at": "2026-11-15T08:00:00Z", "expires_at": "2026-11-16T08:00:00Z", "ended_at": "2026-11-15T08:20:00Z",
            "archived_at": None, "cancel_initiated_at": None,
            "results_url": "https://api.anthropic.com/v1/messages/batches/msgbatch_1/results"}
    lines = [
        {"custom_id": "job-2", "result": {"type": "errored", "error": {"type": "error", "error": {"type": "invalid_request_error", "message": "too long"}}}},
        {"custom_id": "job-1", "result": {"type": "succeeded", "message": message(json.dumps(ANSWER))}},
        {"custom_id": "job-3", "result": {"type": "succeeded", "message": message("", stop_reason="refusal")}},
        {"custom_id": "job-4", "result": {"type": "succeeded", "message": message("not json")}},
    ]

    def handler(request):
        if request.url.path.endswith("/results"):
            return httpx2.Response(200, content="\n".join(json.dumps(x) for x in lines), headers={"content-type": "application/x-jsonl"})
        return httpx2.Response(200, json=done)

    llm = claude(handler)
    assert llm.batch_done("msgbatch_1") is True
    answers = llm.collect_scores("msgbatch_1")
    assert isinstance(answers["job-1"], MatchResult) and answers["job-1"].score == 100  # held to the 0-100 range
    assert "errored" in str(answers["job-2"]) and "too long" in str(answers["job-2"])
    assert "declined" in str(answers["job-3"]) and isinstance(answers["job-4"], Exception)
    assert llm.tokens_used == 3 * 120  # every answered request is counted, also the ones that could not be used


def test_the_quick_check_runs_on_the_cheaper_model():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=message(json.dumps({"worth_scoring": False, "reason": "A sales role."})))

    llm = claude(handler, model="claude-haiku-5-5")
    verdict = llm.prescreen_job(PROFILE, PREFS, JOB)
    assert verdict == Prescreen(worth_scoring=False, reason="A sales role.")
    assert seen["body"]["model"] == "claude-haiku-5-5" and seen["body"]["system"] == PRESCREEN_INSTRUCTIONS
    assert seen["body"]["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert set(seen["body"]["output_config"]["format"]["schema"]["properties"]) == {"worth_scoring", "reason"}
    assert llm.tokens_used == 120


def test_both_are_off_until_switched_on_in_the_settings(tmp_path):
    from jobagent.config import AgentConfig, Settings, read_settings, write_settings
    from jobagent.llm import make_llm

    f = tmp_path / "config.yaml"
    f.write_text("search:\n  roles: [Java Engineer]\n")
    plain = AgentConfig.load(f).matching
    assert (plain.prescreen_model, plain.batch_scoring, plain.batch_wait_minutes) == ("", False, 120)

    write_settings(f, {"matching.prescreen_model": " claude-haiku-5-5 ", "matching.batch_scoring": True,
                       "matching.batch_wait_minutes": "45"})
    chosen = AgentConfig.load(f).matching
    assert (chosen.prescreen_model, chosen.batch_scoring, chosen.batch_wait_minutes) == ("claude-haiku-5-5", True, 45)
    shown = {x["key"]: x for x in read_settings(f)["fields"]}
    assert shown["matching.prescreen_model"]["group"] == "Scoring" and shown["matching.batch_scoring"]["changed"]

    # The quick check gets its own client on the cheaper model; the full scoring keeps the usual one.
    settings = Settings(anthropic_api_key="test-key", llm_provider="anthropic", llm_model="claude-sonnet-5-5")
    assert make_llm(settings).model == "claude-sonnet-5-5"
    assert make_llm(settings, chosen.prescreen_model).model == "claude-haiku-5-5"


# --- a cheaper model for reading job-site pages ---

BOARD = "https://board.example.com/java-jobs"
BOARD_LINKS = [{"href": "https://board.example.com/jobs/1", "text": "Senior Java Engineer"},
               {"href": "https://board.example.com/jobs/2", "text": "Backend Engineer"}]
BOARD_LISTINGS = [{"title": "Senior Java Engineer", "url": "https://board.example.com/jobs/1", "company": "Acme", "location": "Dubai"},
                  {"title": "Backend Engineer", "url": "https://board.example.com/jobs/2", "company": "Acme", "location": "Dubai"}]


def board_cfg():
    from jobagent.config import AgentConfig, MatchingPrefs, SourceConfig

    return AgentConfig(search=SearchPrefs(locations=["Dubai"], include_title_keywords=["java", "backend"]),
                       matching=MatchingPrefs(shortlist_min_score=75),
                       sources=[SourceConfig(kind="generic", name="Board", urls=[BOARD])])


def board_browser():
    from jobagent.browser import PageContent

    return FakeBrowser({BOARD: PageContent(BOARD, "Jobs", "Senior Java Engineer\nBackend Engineer", BOARD_LINKS),
                        "https://board.example.com/jobs/1": PageContent("u1", "", "Java and Spring Boot in Dubai.", []),
                        "https://board.example.com/jobs/2": PageContent("u2", "", "Backend services in Dubai.", [])})


class PageReader(FakeLLM):
    """The cheaper model: it reads pages, and must never be asked to score."""

    model = "cheap-model"

    def __init__(self, listings=None, broken=False):
        super().__init__(listings=listings)
        self.broken, self.pages_read = broken, []

    def extract_listings(self, text, links, url):
        self.pages_read.append(url)
        if self.broken:
            raise RuntimeError("model not found")
        self.tokens_used += 40
        return super().extract_listings(text, links, url)

    def score_job(self, profile, prefs, job):
        raise AssertionError("the page reader was asked to score a job")


class MainModel(FakeLLM):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.pages_read = []

    def extract_listings(self, text, links, url):
        self.pages_read.append(url)
        self.tokens_used += 500
        return super().extract_listings(text, links, url)


def test_a_cheaper_model_reads_the_job_site_pages_and_the_main_one_scores(conn):
    db.save_profile(conn, "Alex", "resume", {})
    main, reader = MainModel(scores={"Senior Java Engineer": 90}), PageReader(listings=BOARD_LISTINGS)
    s = run_agent(conn, board_cfg(), main, board_browser(), http=mock_http({}), reader=reader)

    assert reader.pages_read == [BOARD] and main.pages_read == []
    assert sorted(main.scored_titles) == ["Backend Engineer", "Senior Java Engineer"]
    assert (s.status, s.found, s.scored, s.shortlisted) == ("succeeded", 2, 2, 1)
    assert s.tokens == 200 + 40  # both models count toward the search's total and its budget
    said = [r["message"] for r in conn.execute("SELECT message FROM run_events ORDER BY id").fetchall()]
    assert "Job-site pages are read by cheap-model" in said

    # Scoring stored jobs reads no page, so the reader is not mentioned or used.
    again = PageReader(listings=BOARD_LISTINGS)
    run_agent(conn, board_cfg(), MainModel(), None, http=mock_http({}), collect=False, reader=again)
    assert again.pages_read == []


def test_a_page_the_cheaper_model_cannot_read_goes_to_the_main_model(conn):
    db.save_profile(conn, "Alex", "resume", {})
    main, reader = MainModel(listings=BOARD_LISTINGS), PageReader(broken=True)  # for example a mistyped model name
    s = run_agent(conn, board_cfg(), main, board_browser(), http=mock_http({}), reader=reader)

    assert reader.pages_read == [BOARD] and main.pages_read == [BOARD]
    assert (s.status, s.found, s.scored, s.source_errors) == ("succeeded", 2, 2, {})  # the site is not lost
    warned = conn.execute("SELECT message FROM run_events WHERE level = 'warning'").fetchall()
    assert [w["message"] for w in warned] == [f"cheap-model could not read {BOARD}: model not found. The main model read it instead"]


def test_the_page_reader_is_a_setting_and_runs_on_its_own_model(tmp_path):
    from jobagent import cli
    from jobagent.config import AgentConfig, Settings, read_settings, write_settings

    f = tmp_path / "config.yaml"
    f.write_text("search:\n  roles: [Java Engineer]\n")
    settings = Settings(anthropic_api_key="test-key", llm_provider="anthropic", llm_model="claude-sonnet-5-5")
    assert AgentConfig.load(f).matching.reader_model == "" and cli._reader(settings, AgentConfig.load(f)) is None

    write_settings(f, {"matching.reader_model": "claude-haiku-5-5"})
    cfg = AgentConfig.load(f)
    assert cfg.matching.reader_model == "claude-haiku-5-5"
    assert {x["key"]: x for x in read_settings(f)["fields"]}["matching.reader_model"]["changed"]
    assert cli._reader(settings, cfg).model == "claude-haiku-5-5" and cli._screen(settings, cfg) is None

    # What the real library sends when the cheaper model reads a page.
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=message(json.dumps({"listings": BOARD_LISTINGS[:1]})))

    found = claude(handler, model="claude-haiku-5-5").extract_listings("Senior Java Engineer", BOARD_LINKS, BOARD)
    assert [x.title for x in found.listings] == ["Senior Java Engineer"]
    assert seen["body"]["model"] == "claude-haiku-5-5" and BOARD in seen["body"]["messages"][0]["content"]
