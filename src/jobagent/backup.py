"""Backups: a dump of the database and a copy of the code's history, kept in one folder.

Every job, score, draft and application lives in one PostgreSQL database on this machine. A
backup is a single file made with PostgreSQL's own `pg_dump`, which `pg_restore` can read back.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

# Where Homebrew and Postgres.app put pg_dump. The page is started by a double-click, so its
# PATH is the short one macOS gives apps, not the one a terminal has.
_PG_DUMP_PLACES = ("/opt/homebrew/bin/pg_dump", "/usr/local/bin/pg_dump",
                   "/opt/homebrew/opt/postgresql*/bin/pg_dump", "/usr/local/opt/postgresql*/bin/pg_dump",
                   "/Applications/Postgres.app/Contents/Versions/latest/bin/pg_dump")


class BackupError(RuntimeError):
    """A backup could not be made; the message says why in plain words."""


def find_pg_dump() -> str | None:
    found = shutil.which("pg_dump")
    if found:
        return found
    for pattern in _PG_DUMP_PLACES:
        for path in sorted(glob.glob(pattern), reverse=True):  # the newest version first
            if os.access(path, os.X_OK):
                return path
    return None


def _connection_env(database_url: str) -> dict[str, str]:
    """The database address as PG* variables, so the password never appears on a command line."""
    from psycopg.conninfo import conninfo_to_dict

    names = {"host": "PGHOST", "port": "PGPORT", "user": "PGUSER", "password": "PGPASSWORD", "dbname": "PGDATABASE"}
    parts = conninfo_to_dict(database_url)
    return {names[k]: str(v) for k, v in parts.items() if k in names and v not in (None, "")}


def _prune(folder: Path, pattern: str, keep: int) -> int:
    old = sorted(folder.glob(pattern))[:-keep] if keep > 0 else []
    for f in old:
        f.unlink()
    return len(old)


def make_backup(database_url: str, folder: str | Path = "backups", *, keep: int = 7,
                repo: str | Path | None = None) -> dict:
    """Dump the database into `folder`, and bundle the git history of `repo` beside it if there
    is one. Keeps the newest `keep` of each. Returns {"file", "size", "code", "removed"}."""
    pg_dump = find_pg_dump()
    if not pg_dump:
        raise BackupError("pg_dump was not found. It comes with PostgreSQL; with Homebrew it is in "
                          "/opt/homebrew/bin.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out, n = folder / f"jobagent-{stamp}.dump", 0
    while out.exists():  # two backups in the same second must not overwrite each other;
        n += 1           # a letter after the time keeps the names in the order they were made
        out = folder / f"jobagent-{stamp}{chr(ord('a') + n)}.dump"
    part = out.with_suffix(".part")
    done = subprocess.run([pg_dump, "--format=custom", "--no-owner", "--file", str(part)],
                          env={**os.environ, **_connection_env(database_url)}, capture_output=True, text=True)
    if done.returncode != 0 or not part.exists() or part.stat().st_size == 0:
        part.unlink(missing_ok=True)
        why = (done.stderr or "").strip().splitlines()
        raise BackupError("The database could not be copied: " + (why[-1] if why else "pg_dump gave no reason"))
    part.rename(out)  # a half-written file never carries the name of a finished backup

    code = None
    if repo is not None and shutil.which("git") and (Path(repo) / ".git").exists():
        bundle = folder / out.name.replace("jobagent-", "code-").replace(".dump", ".bundle")
        made = subprocess.run(["git", "-C", str(repo), "bundle", "create", str(bundle.resolve()), "--all"],
                              capture_output=True, text=True)
        if made.returncode == 0 and bundle.exists():
            code = bundle
        else:
            bundle.unlink(missing_ok=True)
    removed = _prune(folder, "jobagent-*.dump", keep) + _prune(folder, "code-*.bundle", keep)
    return {"file": out, "size": out.stat().st_size, "code": code, "removed": removed}


def latest_backup(folder: str | Path = "backups") -> dict | None:
    """The newest database backup in `folder`: {"file", "size", "at"}, or None."""
    files = sorted(Path(folder).glob("jobagent-*.dump"))
    if not files:
        return None
    newest = files[-1]
    return {"file": str(newest), "size": newest.stat().st_size, "count": len(files),
            "at": datetime.fromtimestamp(newest.stat().st_mtime).astimezone()}


def human_size(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(1, round(n / 1024))} KB"
