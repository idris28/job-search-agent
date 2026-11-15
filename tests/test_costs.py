"""What a search cost: an estimate in US dollars from the token counts, by model."""

import pytest

from jobagent import costs, db
from jobagent.config import AgentConfig, MatchingPrefs, SourceConfig
from jobagent.pipeline import run_agent

from conftest import FakeBrowser, FakeLLM
from test_dependable import many_jobs


def test_the_price_of_tokens_by_kind_and_of_a_batch():
    sonnet = {"input": 1_000_000, "output": 100_000, "cache_read": 2_000_000, "cache_write": 400_000}
    # 1M in at $2, 0.1M out at $10, 2M read from cache at $0.10, 0.4M written to it at 1.25 x $2
    assert costs.cost("claude-sonnet-5-5", sonnet) == pytest.approx(2.0 + 1.0 + 0.2 + 1.0)
    assert costs.cost("claude-haiku-5-5", {"input": 1_000_000, "output": 1_000_000}) == pytest.approx(0.60)
    assert costs.cost("claude-sonnet-5-5", {}, batch={"input": 1_000_000, "output": 100_000}) == pytest.approx(1.5)  # half price
    assert costs.cost("claude-sonnet-5-5-20261001", {"input": 1_000_000}) == 2.0  # a dated id takes the price of its family
    assert costs.cost("some-other-model", {"input": 1_000_000}) is None
    assert costs.cost("some-other-model", {"input": 1_000_000, "output": 1_000_000}, own={"some-other-model": [1, 3]}) == 4.0
    assert costs.cost("claude-sonnet-5-5", {"input": 1_000_000}, own={"claude-sonnet-5-5": [3, 15, 0.3]}) == 3.0  # your own price wins


class Priced(FakeLLM):
    """A stand-in that reports its tokens by kind, as the real client does."""

    def __init__(self, model, per_score=None, **kw):
        super().__init__(**kw)
        self.model, self.per_score, self.usage, self.batch_usage = model, per_score or {"input": 80_000, "output": 20_000}, {}, {}

    def score_job(self, profile, prefs, job):
        out = super().score_job(profile, prefs, job)
        self.tokens_used += sum(self.per_score.values()) - 100
        for k, n in self.per_score.items():
            self.usage[k] = self.usage.get(k, 0) + n
        return out


def test_two_models_are_added_up_separately_and_said_in_words():
    main, cheap = Priced("claude-sonnet-5-5"), Priced("claude-haiku-5-5")
    main.usage, main.tokens_used = {"input": 150_000, "output": 30_000, "cache_read": 100_000}, 280_000
    cheap.usage, cheap.tokens_used = {"input": 130_000, "output": 8_000}, 138_000
    usage = costs.usage_of((main, cheap, cheap, None))  # the same client twice counts once
    assert usage["claude-sonnet-5-5"]["cost"] == pytest.approx(0.30 + 0.30 + 0.01) and usage["claude-haiku-5-5"]["cost"] == pytest.approx(0.017)
    assert costs.total(usage) == pytest.approx(0.627)
    assert costs.in_words(usage) == "about $0.63 (claude-sonnet-5-5 $0.61, claude-haiku-5-5 $0.02)"
    plain = costs.usage_of((FakeLLM(),))
    assert plain == {} and costs.in_words(plain) == ""
    unknown = FakeLLM()
    unknown.tokens_used = 500
    assert costs.total(costs.usage_of((main, unknown))) is None  # part of it has no known price: say nothing, not a wrong figure


def test_a_search_records_what_it_cost_and_stops_at_a_limit_in_dollars(conn):
    db.save_profile(conn, "Alex", "resume", {})
    feed = [SourceConfig(kind="greenhouse", name="Acme", board="acme")]
    llm = Priced("claude-sonnet-5-5")  # each scoring: 80,000 in and 20,000 out, about 36 cents
    s = run_agent(conn, AgentConfig(matching=MatchingPrefs(concurrency=1), sources=feed), llm, FakeBrowser({}), http=many_jobs(2))
    assert s.cost == pytest.approx(0.72) and s.usage["claude-sonnet-5-5"]["tokens"] == 200_000 == s.tokens
    run = db.list_runs(conn)[0]
    assert float(run["cost_usd"]) == pytest.approx(0.72) and run["usage"]["claude-sonnet-5-5"]["output"] == 40_000

    limited = AgentConfig(matching=MatchingPrefs(concurrency=1, max_cost_per_run=0.5), sources=feed)
    s = run_agent(conn, limited, Priced("claude-sonnet-5-5"), FakeBrowser({}), http=many_jobs(6))
    assert s.scored == 2 and s.status == "partial"  # 36 cents, 72 cents: over the 50 cent limit after the second
    assert db.list_runs(conn)[0]["error"] == "Stopped early: cost limit reached (about $0.72 of $0.50)"

    # A model with no known price cannot be limited in dollars; the token limit still can.
    s = run_agent(conn, limited, FakeLLM(), FakeBrowser({}), http=many_jobs(8))
    assert s.cost is None and s.status == "succeeded" and db.list_runs(conn)[0]["cost_usd"] is None


def test_the_real_client_counts_tokens_by_kind_and_keeps_a_batch_apart():
    import json

    from test_cheaper_scoring import ANSWER, JOB, PREFS, PROFILE, claude, httpx2, message

    def priced(text):
        m = message(text)
        m["usage"] = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 500}
        return m

    llm = claude(lambda request: httpx2.Response(200, json=priced(json.dumps(ANSWER))))
    llm.score_job(PROFILE, PREFS, JOB)
    assert llm.usage == {"input": 1000, "output": 200, "cache_read": 3000, "cache_write": 500} and llm.tokens_used == 4700
    assert costs.cost(llm.model, llm.usage) == pytest.approx((1000 * 2 + 200 * 10 + 3000 * 0.10 + 500 * 2.5) / 1e6, abs=1e-4)
    llm._count(type("R", (), {"usage": type("U", (), {"input_tokens": 400, "output_tokens": 100})()})(), batch=True)
    assert llm.batch_usage == {"input": 400, "output": 100, "cache_read": 0, "cache_write": 0} and llm.tokens_used == 5200
