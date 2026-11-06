import pytest

from jobagent.cli import build_parser, main


def test_parser_has_all_commands():
    p = build_parser()
    for argv in (["migrate"], ["profile", "import", "r.pdf"], ["run"], ["jobs"], ["show", "1"],
                 ["status", "1", "applied"], ["applications"], ["cover-letter", "1"],
                 ["digest"], ["runs"], ["email"], ["email", "94", "96"]):
        assert p.parse_args(argv).fn


def test_missing_env_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as e:
        main(["runs"])
    assert "DATABASE_URL" in str(e.value)


def test_placeholder_keys_are_ignored(monkeypatch):
    from jobagent.config import Settings

    monkeypatch.setenv("OPENAI_API_KEY", "sk-...")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    s = Settings.from_env()
    assert s.openai_api_key is None and s.resolved_llm_provider() == "anthropic"
