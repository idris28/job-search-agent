from types import SimpleNamespace

from jobagent.config import SearchPrefs
from jobagent.llm import LLM
from jobagent.models import JobPosting, MatchResult


class FakeResponses:
    def __init__(self, parsed):
        self.parsed, self.calls = parsed, []

    def parse(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(output_parsed=self.parsed, usage=SimpleNamespace(total_tokens=42))


def test_score_job_sends_profile_prefs_and_clamps():
    fake = FakeResponses(MatchResult(score=130, verdict="strong", summary="s", matched_skills=[],
                                     missing_skills=[], red_flags=[]))
    llm = LLM("k", "gpt-test", client=SimpleNamespace(responses=fake))
    job = JobPosting(title="Java Engineer", company="Acme", url="u", location="Doha",
                     description="Spring Boot")
    m = llm.score_job({"primary_skills": ["Java"]},
                      SearchPrefs(locations=["Doha"], exclude_industries=["banking"]), job)
    assert m.score == 100 and llm.tokens_used == 42
    call = fake.calls[0]
    assert call["model"] == "gpt-test" and call["text_format"] is MatchResult
    assert "banking" in call["input"] and "excluded industries" in call["instructions"]
    assert "Doha" in call["input"] and "Spring Boot" in call["input"] and "Java" in call["input"]


# --- Claude provider ----------------------------------------------------------

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jobagent.config import ConfigError, Settings
from jobagent.llm import OpenAILLM, make_llm
from jobagent.llm_anthropic import ClaudeLLM


def _claude_server(reply_text: str, stop_reason: str = "end_turn"):
    captured = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            captured["path"] = self.path
            captured["headers"] = dict(self.headers)
            captured["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps({
                "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": reply_text}],
                "stop_reason": stop_reason, "stop_sequence": None,
                "usage": {"input_tokens": 30, "output_tokens": 12},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, captured


def test_claude_score_job_request_shape():
    import anthropic

    reply = MatchResult(score=88, verdict="strong", summary="fits", matched_skills=["Java"],
                        missing_skills=[], red_flags=[]).model_dump_json()
    srv, cap = _claude_server(reply)
    try:
        client = anthropic.Anthropic(api_key="k", base_url=f"http://127.0.0.1:{srv.server_port}",
                                     max_retries=0)
        llm = ClaudeLLM("k", "claude-opus-5-5", client=client)
        job = JobPosting(title="Java Engineer", company="Acme", url="u", location="Riyadh")
        m = llm.score_job({"primary_skills": ["Java"]}, SearchPrefs(locations=["Riyadh"]), job)
    finally:
        srv.shutdown()
    assert m.score == 88 and m.verdict == "strong" and llm.tokens_used == 42
    body = cap["body"]
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "server-side-fallback-2026-07-01" in cap["headers"].get("anthropic-beta", "")
    assert "Riyadh" in body["messages"][0]["content"] and "recruiter" in body["system"]


def test_claude_refusal_raises():
    import anthropic

    srv, _ = _claude_server("", stop_reason="refusal")
    try:
        client = anthropic.Anthropic(api_key="k", base_url=f"http://127.0.0.1:{srv.server_port}",
                                     max_retries=0)
        with pytest.raises(RuntimeError, match="declined"):
            ClaudeLLM("k", "claude-opus-5-5", client=client).cover_letter("r", "j")
    finally:
        srv.shutdown()


def test_provider_selection():
    assert isinstance(make_llm(Settings(anthropic_api_key="a")), ClaudeLLM)
    assert isinstance(make_llm(Settings(openai_api_key="o")), OpenAILLM)
    both = Settings(anthropic_api_key="a", openai_api_key="o", llm_provider="anthropic")
    assert isinstance(make_llm(both), ClaudeLLM)
    with pytest.raises(ConfigError):
        make_llm(Settings())
