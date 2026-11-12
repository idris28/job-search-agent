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


def test_recruiter_email_fills_the_candidates_template_when_given():
    from jobagent.config import OutreachPrefs
    from jobagent.models import RecruiterEmail, TemplateEmail

    fake = FakeResponses("parsed")
    llm = LLM("k", "gpt-test", client=SimpleNamespace(responses=fake))
    prefs = OutreachPrefs(notice_period="30 days", linkedin_url="https://l/in/x")
    assert llm.recruiter_email("RESUME", "JOB", None, "GUIDANCE", prefs,
                               template="Dear [Company Name],") == "parsed"
    call = fake.calls[0]
    assert call["text_format"] is TemplateEmail
    assert "Replace every [placeholder]" in call["instructions"]
    assert call["input"] == (
        "TEMPLATE:\nDear [Company Name],\n\nRESUME:\nRESUME\n\nSTORED JOB POSTING:\nJOB"
        "\n\nLIVE POSTING PAGE TEXT:\n(live page could not be loaded)"
        '\n\nOUTREACH PREFERENCES:\n{"notice_period": "30 days", "linkedin_url": "https://l/in/x"}')  # guidance is not sent
    assert "[LinkedIn](URL)" in call["instructions"]

    # Without a template the built-in recruiter format is asked for, exactly as before.
    llm.recruiter_email("RESUME", "JOB", None, "GUIDANCE")
    call = fake.calls[1]
    assert call["text_format"] is RecruiterEmail and "6-second skim" in call["instructions"]
    assert call["input"] == (
        "RESUME:\nRESUME\n\nSTORED JOB POSTING:\nJOB"
        "\n\nLIVE POSTING PAGE TEXT:\n(live page could not be loaded)"
        "\n\nRECRUITER GUIDANCE:\nGUIDANCE\n\nOUTREACH PREFERENCES:\n(none)")


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
        llm = ClaudeLLM("k", "claude-opus-5-5", effort="medium", client=client)
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
    profile_block, job_block = body["messages"][0]["content"]
    # The profile and preferences repeat for every job, so they are marked for prompt caching.
    assert profile_block["cache_control"] == {"type": "ephemeral"} and "primary_skills" in profile_block["text"]
    assert "cache_control" not in job_block and "Riyadh" in job_block["text"]
    assert "recruiter" in body["system"]


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
    # Provider follows the model name, so swapping LLM_MODEL in .env is enough.
    assert isinstance(make_llm(Settings(llm_model="claude-sonnet-5-5", anthropic_api_key="a",
                                        openai_api_key="o")), ClaudeLLM)
    assert isinstance(make_llm(Settings(llm_model="gpt-5.4-mini", anthropic_api_key="a",
                                        openai_api_key="o")), OpenAILLM)
    llm = make_llm(Settings(llm_model="claude-haiku-5-5", llm_effort="low", anthropic_api_key="a"))
    assert llm.model == "claude-haiku-5-5" and llm.effort == "low"
    # Explicit LLM_PROVIDER wins.
    assert isinstance(make_llm(Settings(llm_model="my-custom", llm_provider="anthropic",
                                        anthropic_api_key="a")), ClaudeLLM)
    with pytest.raises(ConfigError, match="LLM_MODEL"):
        make_llm(Settings(anthropic_api_key="a"))
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        make_llm(Settings(llm_model="claude-sonnet-5-5", openai_api_key="o"))
    with pytest.raises(ConfigError):
        make_llm(Settings())


def test_env_vars(monkeypatch):
    for k in ("LLM_PROVIDER", "ANTHROPIC_MODEL", "OPENAI_MODEL", "ANTHROPIC_EFFORT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("LLM_EFFORT", "medium")
    s = Settings.from_env()
    assert (s.llm_model, s.llm_effort) == ("claude-sonnet-5-5", "medium")
    monkeypatch.delenv("LLM_MODEL")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5-5")  # legacy name still works
    assert Settings.from_env().llm_model == "claude-opus-5-5"


def test_claude_content_research_uses_web_search_and_resumes_pause():
    import anthropic

    replies = iter([("", "pause_turn"), ("- Acme builds X (https://acme.ae)", "end_turn")])
    bodies = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            text, stop = next(replies)
            content = [{"type": "text", "text": text}] if text else []
            body = json.dumps({"id": "m", "type": "message", "role": "assistant",
                               "model": "claude-sonnet-5-5", "content": content,
                               "stop_reason": stop, "stop_sequence": None,
                               "usage": {"input_tokens": 5, "output_tokens": 5}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client = anthropic.Anthropic(api_key="k", base_url=f"http://127.0.0.1:{srv.server_port}",
                                     max_retries=0)
        notes = ClaudeLLM("k", "claude-sonnet-5-5", client=client).research_email_content(
            "Senior Java Engineer", "UAE", max_searches=3)
    finally:
        srv.shutdown()
    assert notes == "- Acme builds X (https://acme.ae)"
    assert len(bodies) == 2
    assert bodies[0]["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
    assert bodies[1]["messages"][-1]["role"] == "assistant"
    assert "UAE" in bodies[0]["messages"][0]["content"]
    assert "Do not research specific companies or people" in bodies[0]["system"]
