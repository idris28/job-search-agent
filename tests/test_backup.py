"""Backups: a database dump that can be read back, a copy of the code, and pruning."""

import shutil
import subprocess

import pytest

from jobagent import backup, cli, db
from jobagent.config import AgentConfig, Settings

from conftest import TEST_DB

needs_pg_dump = pytest.mark.skipif(not backup.find_pg_dump(), reason="pg_dump is not installed")


@needs_pg_dump
def test_a_backup_holds_the_tables_and_old_ones_are_removed(conn, tmp_path):
    db.save_profile(conn, "Alex", "resume", {})
    made = backup.make_backup(TEST_DB, tmp_path, keep=2)
    first = made["file"]
    assert first.exists() and first.stat().st_size > 0 and made["code"] is None and made["removed"] == 0
    assert not list(tmp_path.glob("*.part"))
    restore = shutil.which("pg_restore") or backup.find_pg_dump().replace("pg_dump", "pg_restore")
    listing = subprocess.run([restore, "--list", str(first)], capture_output=True, text=True).stdout
    assert "TABLE DATA public profiles" in listing and "TABLE DATA public jobs" in listing

    # Only the newest `keep` stay; a file that is not a backup is left alone.
    for stamp in ("2026-01-01-080000", "2026-01-02-080000", "2026-01-03-080000"):
        (tmp_path / f"jobagent-{stamp}.dump").write_bytes(b"old")
    (tmp_path / "notes.txt").write_text("mine")
    again = backup.make_backup(TEST_DB, tmp_path, keep=2)
    assert again["file"] != first  # even when both were made within the same second
    assert again["removed"] == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([first.name, again["file"].name, "notes.txt"])
    latest = backup.latest_backup(tmp_path)
    assert latest["file"] == str(again["file"]) and latest["count"] == 2 and latest["size"] > 0
    assert backup.latest_backup(tmp_path / "nowhere") is None


@needs_pg_dump
def test_a_backup_also_copies_the_code_history(conn, tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "a.txt").write_text("hello")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "first"], check=True)
    made = backup.make_backup(TEST_DB, tmp_path / "backups", repo=repo)
    assert made["code"] is not None and made["code"].name.startswith("code-")
    assert subprocess.run(["git", "bundle", "verify", str(made["code"])], capture_output=True, cwd=repo).returncode == 0


def test_a_backup_that_cannot_be_made_says_why(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "find_pg_dump", lambda: None)
    with pytest.raises(backup.BackupError, match="pg_dump was not found"):
        backup.make_backup("postgresql://localhost/x", tmp_path)
    if backup.shutil.which("pg_dump"):
        monkeypatch.undo()
        with pytest.raises(backup.BackupError, match="could not be copied"):
            backup.make_backup("postgresql://localhost:1/nowhere", tmp_path)
        assert list(tmp_path.iterdir()) == []  # nothing half-written is left behind


def test_the_password_stays_off_the_command_line():
    env = backup._connection_env("postgresql://alex:s3cret@db.example:5433/jobs")
    assert env == {"PGHOST": "db.example", "PGPORT": "5433", "PGUSER": "alex", "PGPASSWORD": "s3cret", "PGDATABASE": "jobs"}
    assert backup.human_size(900) == "1 KB" and backup.human_size(3_500_000) == "3.3 MB"


@needs_pg_dump
def test_backup_command_writes_into_the_configured_folder(conn, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("backup: {folder: copies, keep: 3}\n")
    cli.cmd_backup(type("Args", (), {"config": "config.yaml"}), Settings(database_url=TEST_DB))
    out = capsys.readouterr().out
    assert "Backed up to copies/jobagent-" in out and "The newest 3 are kept." in out and "pg_restore" in out
    assert len(list((tmp_path / "copies").glob("jobagent-*.dump"))) == 1
    assert AgentConfig.load("config.yaml").backup.daily is True
