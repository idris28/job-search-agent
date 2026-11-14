"""The local web app: everything `jsa` does, as a page on this Mac.

Quick changes (status, notes, saving a draft, sending one email) happen in the request. Anything
slow or paid (searching, drafting, looking for addresses) runs as a `jsa` child process whose
output the page shows live. Only one such task runs at a time.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db, scheduler
from .actions import ActionError, add_hr_contacts, can_delete, delete_added_job, send_slots, send_stored_draft
from .config import AgentConfig
from .contacts import _EMAIL_RE
from .models import names_missing_company, unfilled_placeholders
from .pipeline import waiting_jobs
from .report import _paragraphs_html, digest_markdown

MAX_LINES = 4000
MAX_UPLOAD = 10 * 1024 * 1024


# Every action the page can start as a task.
TASKS = ("migrate", "run", "score", "daily", "email", "contacts", "send", "gmail-drafts", "followups",
         "cover-letter", "dedupe", "notify-test", "add")


class TaskRunner:
    """Runs one `jsa` command at a time as a child process and keeps what it prints."""

    def __init__(self, env: dict[str, str] | None = None):
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._count = 0
        self.task: dict | None = None
        self.env = env or {}
        self.command = lambda argv: [sys.executable, "-u", "-m", "jobagent.cli", *argv]
        self.grace_seconds = 15.0  # how long a stopped task may take to tidy up

    def start(self, action: str, label: str, argv: list[str], cleanup=None) -> dict:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise ActionError(f"\"{self.task['label']}\" is still running. Wait for it, or stop it first.")
            proc = subprocess.Popen(
                self.command(argv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONUNBUFFERED": "1", **self.env})
            self._count += 1
            task = {"id": self._count, "action": action, "label": label, "running": True,
                    "exit_code": None, "stopped": False, "lines": [],
                    "started_at": datetime.now(timezone.utc), "ended_at": None}
            self._proc, self.task = proc, task
        threading.Thread(target=self._read, args=(proc, task, cleanup), daemon=True).start()
        return self.snapshot()

    def _read(self, proc, task, cleanup) -> None:
        for line in proc.stdout:
            if len(task["lines"]) < MAX_LINES:
                task["lines"].append(line.rstrip("\n"))
        task["exit_code"] = proc.wait()
        task["ended_at"] = datetime.now(timezone.utc)
        task["running"] = False
        if cleanup:
            cleanup()

    def stop(self) -> bool:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return False
            self.task["stopped"] = True
            proc = self._proc
            proc.terminate()  # the task unwinds: a search records where it ended
            # Stop must always stop. If the task is still tidying up after a while, end it; a
            # search cut off this way is given its end by db.close_dead_runs.
            timer = threading.Timer(self.grace_seconds, lambda: proc.poll() is None and proc.kill())
            timer.daemon = True
            timer.start()
            return True

    def snapshot(self, since: int | None = None) -> dict | None:
        """The task without its output, or with the lines from `since` on."""
        t = self.task
        if t is None:
            return None
        lines = t["lines"]
        out = {k: v for k, v in t.items() if k != "lines"}
        out["total"] = len(lines)
        out["last"] = next((x for x in reversed(lines) if x.strip()), "")
        if since is not None:
            out["lines"] = lines[since:]
        return out


def _first_line(e: Exception) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


def _template_info(file: str) -> dict:
    p = Path(file) if file else None
    found = bool(p and p.is_file())
    return {"file": file, "found": found, "text": p.read_text(encoding="utf-8") if found else ""}


def _page(token: str) -> bytes:
    text = resources.files("jobagent").joinpath("static", "app.html").read_text(encoding="utf-8")
    return text.replace("__TOKEN__", token).encode("utf-8")


def serve(settings, cfg, port: int = 8765, *, config_path: str | None = None,
          runner: TaskRunner | None = None) -> ThreadingHTTPServer:
    """Build the server. It listens on this Mac only and answers only its own page."""
    token = secrets.token_urlsafe(24)
    url = settings.database_url
    runner = runner or TaskRunner({"JOBAGENT_CONFIG": config_path} if config_path else None)

    def config() -> AgentConfig:
        """config.yaml as it is now, so an edit shows up without restarting the page."""
        if config_path and Path(config_path).exists():
            try:
                return AgentConfig.load(config_path)
            except Exception:  # noqa: BLE001 - a half-edited file must not break the page
                pass
        return cfg

    def connect():
        try:
            conn = db.connect(url)
        except Exception as e:  # noqa: BLE001
            raise ActionError(f"The database could not be reached: {_first_line(e)}") from e
        if db.pending_migrations(conn):
            conn.close()
            raise ActionError("The database needs an update first. Use the button at the top of the page.")
        return conn

    def profile_id(conn) -> int:
        p = db.active_profile(conn)
        if not p:
            raise ActionError("Import your resume first, in Settings.")
        return p["id"]

    # --- reading ----------------------------------------------------------------------

    waiting = {"at": 0.0, "task": None, "n": 0}

    def waiting_count(conn, pid: int, c: AgentConfig) -> int:
        """How many stored jobs wait to be scored. Counting reads every unscored job, so the answer
        is kept for two minutes, or until a task starts or ends."""
        t = runner.task
        key = (t["id"], t["running"]) if t else None
        if key != waiting["task"] or time.monotonic() - waiting["at"] > 120:
            waiting.update(at=time.monotonic(), task=key, n=len(waiting_jobs(conn, c, pid, brief=True)))
        return waiting["n"]

    def state() -> dict:
        c = config()
        setup = {"database": "ok", "pending": [], "profile": None,
                 "gmail": bool(settings.gmail_address and settings.gmail_app_password)}
        out = {"setup": setup, "task": runner.snapshot(), "jobs": [], "due": [], "counts": None,
               "sends": None, "shortlist_min_score": c.matching.shortlist_min_score,
               "follow_up_days": c.outreach.follow_up_days,
               "sources": [s.name for s in c.sources if s.enabled], "countries": [],
               "search": {"max_age_days": c.search.max_age_days, "min_salary_lpa": c.search.min_salary_lpa,
                          "score_cap": c.matching.max_jobs_to_score}}
        try:
            conn = db.connect(url)
        except Exception as e:  # noqa: BLE001
            setup.update(database="unreachable", error=_first_line(e))
            return out
        with conn:
            setup["pending"] = db.pending_migrations(conn)
            if setup["pending"]:
                setup["database"] = "behind"
                return out
            p = db.active_profile(conn)
            out["counts"] = db.overview(conn, p["id"] if p else None)
            if not p:
                return out
            setup["profile"] = {"name": p["name"], "imported": p["created_at"]}
            pid = p["id"]
            due = db.followups_due(conn, pid, c.outreach.follow_up_days)
            out["due"] = [r["job_id"] for r in due]
            out["counts"]["due"] = len(due)
            out["counts"]["waiting"] = waiting_count(conn, pid, c)
            out["sends"] = {"today": db.sends_today(conn, pid), "cap": c.outreach.max_sends_per_day}
            out["countries"] = db.match_countries(conn, pid)
            for r in db.dashboard_rows(conn, pid):
                body = r.pop("outreach_body")
                r["has_draft"] = bool(r["outreach_subject"] and body)
                out["jobs"].append(r)
        return out

    def job_detail(job_id: int) -> dict:
        with connect() as conn:
            pid = profile_id(conn)
            job = db.get_job(conn, job_id)
            if not job:
                raise ActionError("That job was not found.")
            app = db.get_application(conn, pid, job_id)
            events = db.application_events(conn, app["id"]) if app else []
            match = db.get_match(conn, pid, job_id)
            due = any(r["job_id"] == job_id for r in db.followups_due(conn, pid, config().outreach.follow_up_days))
        if app:
            app = {k: v for k, v in app.items() if k not in ("company_research", "review_notes")}
            app["body_html"] = _paragraphs_html(app["outreach_body"])
            draft = f"{app['outreach_subject'] or ''}\n{app['outreach_body'] or ''}\n{app['follow_up_body'] or ''}"
            app["unfilled"] = unfilled_placeholders(draft)
            if names_missing_company(draft, job["company"]):
                app["unfilled"].append(f'company name ("{job["company"]}" is not a real name)')
        return {"job": job, "match": match, "application": app, "events": events, "due": due,
                "can_delete": can_delete(job, app) is None}

    def matches(min_score: int) -> dict:
        with connect() as conn:
            return {"jobs": db.top_matches(conn, profile_id(conn), min_score=min_score, limit=300)}

    def insights(days: int) -> dict:
        with connect() as conn:
            pid = profile_id(conn)
            total, gaps = db.skill_gaps(conn, pid, days, 50, 12)
            return {"days": days, "gap_jobs": total, "gaps": gaps, "progress": db.progress(conn, pid, 7),
                    "waiting": len(db.shortlisted_job_ids(conn, pid, 100000)), "runs": db.settled_runs(conn, 15)}

    def settings_info() -> dict:
        c = config()
        o = c.outreach
        cv = Path(o.resume_path).expanduser() if o.resume_path else None
        template = Path(o.template_file) if o.template_file else None
        info = {
            "ai": {"provider": settings.resolved_llm_provider(), "model": settings.llm_model,
                   "ready": bool(settings.anthropic_api_key or settings.openai_api_key)},
            "browser": {"kind": settings.browser, "ready": settings.browser == "local"
                        or bool(settings.browserbase_api_key)},
            "gmail": {"address": settings.gmail_address,
                      "ready": bool(settings.gmail_address and settings.gmail_app_password)},
            "telegram": bool(settings.telegram_bot_token and settings.telegram_chat_id),
            "cv": {"path": o.resume_path, "found": bool(cv and cv.is_file())},
            "template": {"file": o.template_file, "found": bool(template and template.is_file()),
                         "text": template.read_text(encoding="utf-8") if template and template.is_file() else ""},
            "cover_template": _template_info(o.cover_letter_template_file),
            "general_template": _template_info(o.general_template_file),
            "limits": {"sends_per_day": o.max_sends_per_day, "pause_seconds": o.send_pause_seconds,
                       "follow_up_days": o.follow_up_days, "tokens_per_run": c.matching.max_tokens_per_run,
                       "browser_minutes": c.matching.max_browser_minutes_per_run,
                       "min_salary_lpa": c.search.min_salary_lpa, "max_age_days": c.search.max_age_days,
                       "notify_min_score": c.matching.notify_min_score},
            "locations": c.search.locations, "sources": len([s for s in c.sources if s.enabled]),
            "schedule": scheduler.info(), "folder": str(Path.cwd()), "duplicates": [],
        }
        try:
            with connect() as conn:
                info["duplicates"] = db.duplicate_groups(conn)
        except ActionError:
            pass
        return info

    # --- slow work: one `jsa` child process at a time ------------------------------------

    def ready_for(action) -> None:
        """Say now, in the page's own words, why a task cannot work, instead of starting a command
        that stops with a terminal message. Everything but a database update needs the database
        to answer and be up to date; everything that reads or scores jobs needs a resume."""
        if action in ("migrate", "notify-test"):
            return
        with connect() as conn:
            if action not in ("profile", "dedupe"):
                profile_id(conn)

    def start_task(body: dict) -> dict:
        action = body.get("action")
        ids = [str(int(i)) for i in body.get("job_ids") or []]
        cleanup = None
        if action in TASKS:
            ready_for(action)
        if action == "migrate":
            label, argv = "Update the database", ["migrate"]
        elif action == "run":
            label, argv = "Find new jobs", ["run"]
            if body.get("source"):
                if body["source"] not in {s.name for s in config().sources}:
                    raise ActionError("That job site is not in config.yaml.")
                label, argv = f"Search {body['source']}", argv + ["--source", body["source"]]
            if body.get("no_score"):
                argv.append("--no-score")
        elif action == "score":
            label, argv = "Score waiting jobs", ["score"]
        elif action == "daily":
            label, argv = "Morning routine", ["daily"]
        elif action == "email":
            label = "Draft emails" if len(ids) != 1 else f"Draft the email for #{ids[0]}"
            argv = ["email", *ids, "--limit", str(int(body.get("limit") or 10))]
            if body.get("check_live") is False:
                argv.append("--no-browse")
        elif action == "contacts":
            label, argv = "Look for addresses", ["contacts", *ids]
        elif action in ("send", "gmail-drafts"):
            label = "Send ready emails" if action == "send" else "Save drafts to Gmail"
            argv = ["send", *ids] + (["--gmail-drafts"] if action == "gmail-drafts" else []) \
                + (["--general"] if body.get("general") else [])
        elif action == "followups":
            label, argv = "Send follow-ups", ["followups", "--send"]
        elif action == "cover-letter" and len(ids) == 1:
            label, argv = f"Write a cover letter for #{ids[0]}", ["cover-letter", ids[0]]
        elif action == "dedupe":
            label, argv = "Merge duplicate jobs", ["dedupe", "--apply"]
        elif action == "notify-test":
            label, argv = "Send a test notification", ["notify-test"]
        elif action == "add":
            text = str(body.get("text") or "").strip()
            if not text:
                raise ActionError("Paste the post text first.")
            path = _temp_file(text.encode("utf-8"), ".txt")
            label, argv, cleanup = "Add a job from a post", ["add", path], lambda: os.unlink(path)
            link = str(body.get("url") or "").strip()
            if link.startswith(("http://", "https://")):
                argv += ["--url", link]
        else:
            raise ActionError("That action is not known.")
        return runner.start(action, label, argv, cleanup)

    def _temp_file(data: bytes, suffix: str) -> str:
        with tempfile.NamedTemporaryFile(prefix="jobagent-", suffix=suffix, delete=False) as f:
            f.write(data)
            return f.name

    def import_resume(filename: str, data: bytes) -> dict:
        suffix = Path(filename).suffix.lower()
        if suffix not in (".pdf", ".txt", ".md"):
            raise ActionError("Choose a PDF or a text file.")
        if not data:
            raise ActionError("That file is empty.")
        ready_for("profile")
        path = _temp_file(data, suffix)
        return runner.start("profile", "Import your resume", ["profile", "import", path], lambda: os.unlink(path))

    # --- quick changes ----------------------------------------------------------------

    def change(path: str, body: dict) -> dict:
        if path == "/api/schedule":
            if body.get("action") == "remove":
                scheduler.remove()
                return {"message": "The morning routine is switched off."}
            hour, _, minute = str(body.get("time") or "").partition(":")
            if not (hour.isdigit() and minute.isdigit() and int(hour) < 24 and int(minute) < 60):
                raise ActionError("Choose a time, for example 08:00.")
            if not (Path(".env").exists() and Path("config.yaml").exists()):
                raise ActionError("The page was not started from the project folder, so the schedule was not set.")
            scheduler.install(Path.cwd(), int(hour), int(minute))
            return {"message": f"The morning routine will run every day at {int(hour):02d}:{int(minute):02d}."}
        if path == "/api/template":
            cover, kind = body.get("kind") == "cover", body.get("kind")
            o = config().outreach
            file = {"cover": o.cover_letter_template_file, "general": o.general_template_file}.get(kind, o.template_file)
            if not file:
                raise ActionError("This template is switched off in config.yaml.")
            text = str(body.get("text") or "").strip()
            if not text:
                raise ActionError("The template cannot be empty.")
            Path(file).write_text(text + "\n", encoding="utf-8")
            return {"message": "Template saved. New " + ("cover letters" if cover else "drafts") + " will use it."}

        if path == "/api/hr-contacts":
            text = str(body.get("text") or "").strip()
            if not text:
                raise ActionError("Paste at least one email address.")
            country = str(body.get("country") or "").strip() or None
            if country not in (None, "India", "UAE", "Saudi Arabia", "Qatar"):
                raise ActionError("That country is not one of yours.")
            with connect() as conn:
                result = add_hr_contacts(conn, config(), text, country)
            n, k = len(result["added"]), len(result["skipped"])
            return {**result, "message": f"Added {n} general application{'' if n == 1 else 's'}"
                                         + (f", skipped {k}." if k else ".")}

        jid = int(body.get("job_id") or 0)
        with connect() as conn:
            pid = profile_id(conn)
            if not db.get_job(conn, jid):
                raise ActionError("That job was not found.")
            if path == "/api/status":
                if body.get("status") not in db.APPLICATION_STATUSES:
                    raise ActionError("That status is not known.")
                db.set_application_status(conn, pid, jid, body["status"], "set on the web page")
                return {"message": f"#{jid} marked {body['status']}."}
            if path == "/api/note":
                db.set_application_status_if_missing(conn, pid, jid)
                db.set_note(conn, pid, jid, str(body.get("note") or ""))
                return {"message": "Note saved."}
            if path == "/api/draft":
                subject, text = str(body.get("subject") or ""), str(body.get("body") or "")
                if not (subject.strip() and text.strip()):
                    raise ActionError("The subject and the email text cannot be empty.")
                if not db.get_application(conn, pid, jid):
                    raise ActionError("Shortlist this job before writing its email.")
                db.save_draft_text(conn, pid, jid, subject, text)
                return {"message": "Draft saved."}
            if path == "/api/send":
                to = send_stored_draft(conn, settings, config().outreach, pid, jid,
                                       allow_general=bool(body.get("general")))
                left = send_slots(conn, pid, config().outreach)
                return {"message": f"Email sent to {to}." + (f" {left} more can go out today." if left < 100 else "")}
            if path == "/api/contact":
                email = str(body.get("email") or "").strip()
                if not email:  # an empty box clears the address
                    if db.get_application(conn, pid, jid):
                        db.save_contact(conn, pid, jid, None, None, None)
                    return {"message": "Address removed."}
                if not _EMAIL_RE.match(email):
                    raise ActionError("That does not look like an email address.")
                db.save_contact(conn, pid, jid, email, None, "recruiter")
                return {"message": f"Address saved: {email}."}
            if path == "/api/followup-done":
                db.mark_follow_up_sent(conn, pid, jid)
                return {"message": f"#{jid} marked as followed up."}
            if path == "/api/delete":
                delete_added_job(conn, pid, jid)
                return {"message": "Entry deleted."}
        raise ActionError("That action is not known.")

    # --- http -------------------------------------------------------------------------

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, kind: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, default=lambda o: o.isoformat() if hasattr(o, "isoformat")
                                        else str(o)).encode("utf-8"), "application/json; charset=utf-8")

        def _allowed(self, *, need_token: bool) -> bool:
            # The Host check stops another site reaching this page through a DNS trick; the token
            # stops any other page on this Mac's browser from reading or changing anything.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in ("127.0.0.1", "localhost"):
                self.send_error(403)
                return False
            if need_token and not secrets.compare_digest(self.headers.get("X-Token") or "", token):
                self._json({"error": "This page is out of date. Reload it."}, 403)
                return False
            return True

        def _answer(self, fn) -> None:
            try:
                self._json(fn())
            except ActionError as e:
                self._json({"error": str(e)}, 400)
            except (ValueError, TypeError):
                self._json({"error": "That request was not understood."}, 400)
            except Exception as e:  # noqa: BLE001 - show the reason on the page, not a blank error
                self._json({"error": f"That did not work: {_first_line(e)}"}, 500)

        def do_GET(self):
            parsed = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            if parsed.path == "/":
                if self._allowed(need_token=False):
                    self._send(200, _page(token), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/digest":  # a download link cannot carry a header, so the token is in the link
                if not self._allowed(need_token=False):
                    return
                if not secrets.compare_digest(q.get("token", ""), token):
                    self.send_error(403)
                    return
                try:
                    with connect() as conn:
                        rows = db.top_matches(conn, profile_id(conn), min_score=int(q.get("min_score", 75)), limit=50)
                except (ActionError, ValueError) as e:
                    self._json({"error": str(e)}, 400)
                    return
                self._send(200, digest_markdown(rows, title=f"Job matches {date.today():%d %b %Y}").encode("utf-8"),
                           "text/markdown; charset=utf-8",
                           {"Content-Disposition": f'attachment; filename="job-matches-{date.today()}.md"'})
                return
            if not self._allowed(need_token=True):
                return
            routes = {
                "/api/state": state,
                "/api/job": lambda: job_detail(int(q.get("id", 0))),
                "/api/matches": lambda: matches(int(q.get("min_score", 0))),
                "/api/insights": lambda: insights(int(q.get("days", 30))),
                "/api/settings": settings_info,
                "/api/task": lambda: {"task": runner.snapshot(int(q.get("since", 0)))},
            }
            if parsed.path in routes:
                self._answer(routes[parsed.path])
            else:
                self.send_error(404)

        def do_POST(self):
            if not self._allowed(need_token=True):
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD:
                self._json({"error": "That file is too large (10 MB at most)."}, 413)
                return
            raw = self.rfile.read(length)
            path = urlparse(self.path).path
            if path == "/api/profile":
                self._answer(lambda: {"task": import_resume(self.headers.get("X-Filename") or "", raw)})
                return
            try:
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                self._json({"error": "That request was not understood."}, 400)
                return
            if path == "/api/task":
                self._answer(lambda: {"task": start_task(body)})
            elif path == "/api/task/stop":
                self._answer(lambda: {"stopped": runner.stop()})
            elif path == "/api/quit":
                self._json({"message": "The page has stopped. Open Job Search again to start it."})
                runner.stop()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif path in ("/api/status", "/api/note", "/api/draft", "/api/send", "/api/followup-done", "/api/contact", "/api/hr-contacts", "/api/delete",
                          "/api/schedule", "/api/template"):
                self._answer(lambda: change(path, body))
            else:
                self.send_error(404)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.token = token
    server.runner = runner
    return server
