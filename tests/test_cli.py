import pytest

from jobagent.cli import build_parser, main


def test_parser_has_all_commands():
    p = build_parser()
    for argv in (["migrate"], ["profile", "import", "r.pdf"], ["run"], ["jobs"], ["show", "1"],
                 ["status", "1", "applied"], ["applications"], ["cover-letter", "1"],
                 ["digest"], ["runs"]):
        assert p.parse_args(argv).fn


def test_missing_env_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as e:
        main(["runs"])
    assert "DATABASE_URL" in str(e.value)
