"""A macOS launchd job that runs `jsa daily` every morning."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.jobagent.daily"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_bytes(project_dir: Path, hour: int, minute: int, python: str = sys.executable) -> bytes:
    """The launchd definition: run `jsa daily` from the project folder at hour:minute each day."""
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "jobagent.cli", "daily"],
        "WorkingDirectory": str(project_dir),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(project_dir / "digests" / "daily.log"),
        "StandardErrorPath": str(project_dir / "digests" / "daily.log"),
    })


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def install(project_dir: Path, hour: int, minute: int) -> Path:
    (project_dir / "digests").mkdir(exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    _launchctl("bootout", f"gui/{os.getuid()}", str(PLIST))  # replace an older schedule quietly
    PLIST.write_bytes(plist_bytes(project_dir, hour, minute))
    done = _launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST))
    if done.returncode != 0:
        raise RuntimeError(f"launchctl could not load the schedule: {done.stderr.strip()}")
    return PLIST


def remove() -> bool:
    if not PLIST.exists():
        return False
    _launchctl("bootout", f"gui/{os.getuid()}", str(PLIST))
    PLIST.unlink()
    return True


def info() -> dict:
    """The schedule as data: {"installed": False} or the time, folder and whether it is loaded."""
    if not PLIST.exists():
        return {"installed": False}
    d = plistlib.loads(PLIST.read_bytes())
    t = d["StartCalendarInterval"]
    return {"installed": True, "time": f"{t['Hour']:02d}:{t['Minute']:02d}",
            "folder": d["WorkingDirectory"], "log": d["StandardOutPath"],
            "loaded": _launchctl("print", f"gui/{os.getuid()}/{LABEL}").returncode == 0}


def status() -> str:
    i = info()
    if not i["installed"]:
        return "No daily schedule is installed."
    return (f"Daily at {i['time']} in {i['folder']} "
            f"({'loaded' if i['loaded'] else 'file present but not loaded'}). Log: {i['log']}")
