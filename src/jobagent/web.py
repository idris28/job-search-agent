"""A small local web page for the shortlist: read drafts and mark jobs applied or skipped."""

from __future__ import annotations

import html
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import db
from .report import _paragraphs_html, age

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2430;--muted:#5d6b7e;--line:#e3e7ed;--accent:#2457d6;
--ok:#1e7d4f;--okbg:#e6f4ec;--warn:#9a4b00;--warnbg:#fdf0e1}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--card:#1b2029;--ink:#e7ebf1;--muted:#9aa6b6;
--line:#2c3442;--accent:#7ea2ff;--ok:#6fd3a0;--okbg:#173327;--warn:#ffb46b;--warnbg:#3a2a17}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:900px;margin:0 auto;padding:28px 16px 60px}h1{font-size:24px;margin:0 0 4px}
h2{font-size:15px;color:var(--muted);margin:26px 0 10px}.sub{color:var(--muted);margin:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:0 0 12px}
.top{display:flex;gap:10px;justify-content:space-between;align-items:baseline;flex-wrap:wrap}
.top b{font-size:16px}.meta{color:var(--muted);font-size:13px;margin:3px 0 8px}.meta a{color:var(--accent)}
.badge{font-size:12px;font-weight:600;padding:2px 9px;border-radius:999px;background:var(--bg);color:var(--muted)}
.ok{color:var(--ok);background:var(--okbg)}.warn{color:var(--warn);background:var(--warnbg)}
form{display:inline}button{font:inherit;font-size:13px;cursor:pointer;border:1px solid var(--line);
background:var(--card);color:var(--ink);border-radius:8px;padding:5px 12px;margin:6px 6px 0 0}
button:hover{border-color:var(--accent)}details{margin-top:8px;font-size:14px}summary{cursor:pointer;color:var(--muted)}
.mail{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-top:8px}.mail p{margin:0 0 8px}
"""


def dashboard_html(rows: list[dict], due_ids: set[int], token: str, now: datetime | None = None) -> str:
    """rows: db.dashboard_rows(); due_ids: jobs whose follow-up is due."""
    h = lambda s: html.escape(str(s if s is not None else ""))  # noqa: E731

    def button(job_id, status, label):
        return (f'<form method="post" action="/status"><input type="hidden" name="token" value="{h(token)}">'
                f'<input type="hidden" name="job_id" value="{job_id}">'
                f'<input type="hidden" name="status" value="{status}"><button>{label}</button></form>')

    def card(r):
        posted = age(r["posted_at"], now)
        badges = [f'<span class="badge">{h(r["status"])}</span>']
        if r["score"] is not None:
            badges.append(f'<span class="badge {"ok" if r["score"] >= 75 else ""}">score {r["score"]}</span>')
        if r["outreach_sent_at"]:
            badges.append('<span class="badge ok">emailed</span>')
        if r["job_id"] in due_ids:
            badges.append('<span class="badge warn">follow up today</span>')
        draft = ""
        if r["outreach_subject"]:
            to = h(r["contact_email"]) if r["contact_email"] else "no address on the posting"
            draft = (f'<details><summary>Email draft: {h(r["outreach_subject"])}</summary>'
                     f'<div class="meta">To: {to}</div><div class="mail">{_paragraphs_html(r["outreach_body"])}</div></details>')
        buttons = {"shortlisted": button(r["job_id"], "applied", "Mark applied") + button(r["job_id"], "skipped", "Skip"),
                   "applied": button(r["job_id"], "interviewing", "Interviewing") + button(r["job_id"], "rejected", "Rejected"),
                   }.get(r["status"], button(r["job_id"], "shortlisted", "Back to shortlist"))
        link = f'<a href="{h(r["url"])}" target="_blank" rel="noopener">Open posting</a>' if str(r["url"]).startswith("http") else "pasted post"
        return (f'<section class="card"><div class="top"><b>#{r["job_id"]} {h(r["title"])} at {h(r["company"])}</b>'
                f'<span>{" ".join(badges)}</span></div>'
                f'<div class="meta">{h(r["location"] or "location not given")}{" · posted " + posted + " ago" if posted else ""} · {link}</div>'
                f'<div>{h(r["summary"])}</div>{draft}<div>{buttons}</div></section>')

    groups = [("Shortlisted", [r for r in rows if r["status"] == "shortlisted"]),
              ("Applied and in progress", [r for r in rows if r["status"] in ("applied", "interviewing", "offer")]),
              ("Set aside", [r for r in rows if r["status"] in ("skipped", "rejected", "withdrawn")])]
    body = "".join(f"<h2>{name} ({len(items)})</h2>" + "".join(card(r) for r in items)
                   for name, items in groups if items) or '<p class="sub">Nothing tracked yet. Run jsa run first.</p>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>Job Search</title>'
            f"<style>{_CSS}</style></head><body><main><h1>Job search</h1>"
            f'<p class="sub">{len(rows)} tracked jobs, newest postings first. Buttons update the database.</p>'
            f"{body}</main></body></html>")


def serve(database_url: str, port: int = 8765) -> ThreadingHTTPServer:
    """Build the server. It listens on this Mac only and accepts changes only from its own page."""
    token = secrets.token_urlsafe(16)

    class Handler(BaseHTTPRequestHandler):
        def _page(self):
            with db.connect(database_url) as conn:
                p = db.active_profile(conn)
                rows = db.dashboard_rows(conn, p["id"]) if p else []
                due = {r["job_id"] for r in db.followups_due(conn, p["id"], 0)} if p else set()
            # "due" here means emailed with no follow-up sent yet and old enough per config;
            # the caller's follow_up_days is applied in cmd_web via serve_due_days.
            return dashboard_html(rows, due & Handler.due_filter(rows), token)

        @staticmethod
        def due_filter(rows):
            now = datetime.now(timezone.utc)
            return {r["job_id"] for r in rows if r["outreach_sent_at"] and not r["follow_up_sent_at"]
                    and (now - r["outreach_sent_at"]).days >= Handler.follow_up_days}

        def do_GET(self):
            if self.path.split("?")[0] != "/":
                self.send_error(404)
                return
            body = self._page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
            get = lambda k: (form.get(k) or [""])[0]  # noqa: E731
            if self.path != "/status" or not secrets.compare_digest(get("token"), token) \
                    or get("status") not in db.APPLICATION_STATUSES or not get("job_id").isdigit():
                self.send_error(400)
                return
            with db.connect(database_url) as conn:
                p = db.active_profile(conn)
                if p and db.get_job(conn, int(get("job_id"))):
                    db.set_application_status(conn, p["id"], int(get("job_id")), get("status"), "set on the web page")
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, *a):
            pass

    Handler.follow_up_days = 6
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.token, server.handler = token, Handler
    return server
