"""A small local web page for the shortlist: read and edit drafts, send them, add pasted posts,
keep notes, and mark jobs applied or skipped."""

from __future__ import annotations

import html
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from . import db
from .actions import ActionError, add_pasted_job, send_stored_draft
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
input[type=text],textarea{width:100%;font:inherit;font-size:14px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:7px 9px;margin:6px 0}textarea{min-height:230px;line-height:1.45}textarea.small{min-height:64px}
.flash{border:1px solid var(--accent);border-radius:10px;padding:10px 14px;margin:14px 0;background:var(--card)}
.stats{display:flex;flex-wrap:wrap;gap:8px 22px;margin:14px 0 0;font-size:14px;color:var(--muted)}.stats b{color:var(--ink)}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}form.block{display:block}
"""


def dashboard_html(rows: list[dict], due_ids: set[int], token: str, now: datetime | None = None, *,
                   progress: dict | None = None, message: str = "") -> str:
    """rows: db.dashboard_rows(); due_ids: jobs whose follow-up is due."""
    h = lambda s: html.escape(str(s if s is not None else ""))  # noqa: E731
    tok = f'<input type="hidden" name="token" value="{h(token)}">'

    def button(job_id, status, label):
        return (f'<form method="post" action="/status">{tok}<input type="hidden" name="job_id" value="{job_id}">'
                f'<input type="hidden" name="status" value="{status}"><button>{label}</button></form>')

    def card(r):
        jid = r["job_id"]
        posted = age(r["posted_at"], now)
        badges = [f'<span class="badge">{h(r["status"])}</span>']
        if r["score"] is not None:
            badges.append(f'<span class="badge {"ok" if r["score"] >= 75 else ""}">score {r["score"]}</span>')
        if r["outreach_sent_at"]:
            badges.append('<span class="badge ok">emailed</span>')
        if jid in due_ids:
            badges.append('<span class="badge warn">follow up today</span>')
        pay = f' · pay: {h(r.get("salary_estimate"))}' if r.get("salary_estimate") else ""
        draft = ""
        if r["outreach_subject"]:
            if r["contact_email"]:
                kind = f' ({h(r["contact_kind"])} address, from {h(urlparse(r["contact_source"]).hostname)})' \
                    if r.get("contact_source") else ""
                to = h(r["contact_email"]) + kind
            else:
                to = "no address known: use the posting's apply button"
            can_send = r["status"] == "shortlisted" and r["contact_email"] and not r["outreach_sent_at"]
            send = (f'<form method="post" action="/send" onsubmit="return confirm(\'Send this email to '
                    f'{h(r["contact_email"])} now?\')">{tok}<input type="hidden" name="job_id" value="{jid}">'
                    f'<button class="primary">Send email</button></form>') if can_send else ""
            draft = (f'<details><summary>Email draft: {h(r["outreach_subject"])}</summary>'
                     f'<div class="meta">To: {to}</div>'
                     f'<form class="block" method="post" action="/draft">{tok}<input type="hidden" name="job_id" value="{jid}">'
                     f'<input type="text" name="subject" aria-label="Subject" value="{h(r["outreach_subject"])}">'
                     f'<textarea name="body" aria-label="Email text">{h(r["outreach_body"])}</textarea>'
                     f'<button>Save changes</button></form>{send}'
                     f'<div class="mail">{_paragraphs_html(r["outreach_body"])}</div></details>')
        notes = (f'<details{" open" if r.get("notes") else ""}><summary>Notes</summary>'
                 f'<form class="block" method="post" action="/note">{tok}<input type="hidden" name="job_id" value="{jid}">'
                 f'<textarea class="small" name="note" aria-label="Notes">{h(r.get("notes"))}</textarea>'
                 f'<button>Save note</button></form></details>')
        buttons = {"shortlisted": button(jid, "applied", "Mark applied") + button(jid, "skipped", "Skip"),
                   "applied": button(jid, "interviewing", "Interviewing") + button(jid, "rejected", "Rejected"),
                   }.get(r["status"], button(jid, "shortlisted", "Back to shortlist"))
        link = f'<a href="{h(r["url"])}" target="_blank" rel="noopener noreferrer">Open posting</a>' \
            if str(r["url"]).startswith("http") else "pasted post"
        return (f'<section class="card"><div class="top"><b>#{jid} {h(r["title"])} at {h(r["company"])}</b>'
                f'<span>{" ".join(badges)}</span></div>'
                f'<div class="meta">{h(r["location"] or "location not given")}'
                f'{" · posted " + posted + " ago" if posted else ""}{pay} · {link}</div>'
                f'<div>{h(r["summary"])}</div>{draft}{notes}<div>{buttons}</div></section>')

    groups = [("Shortlisted", [r for r in rows if r["status"] == "shortlisted"]),
              ("Applied and in progress", [r for r in rows if r["status"] in ("applied", "interviewing", "offer")]),
              ("Set aside", [r for r in rows if r["status"] in ("skipped", "rejected", "withdrawn")])]
    body = "".join(f"<h2>{name} ({len(items)})</h2>" + "".join(card(r) for r in items)
                   for name, items in groups if items) or '<p class="sub">Nothing tracked yet. Run jsa run first.</p>'
    stats = ""
    if progress:
        m, mail = progress["moves"], progress["mail"]
        stats = (f'<div class="stats"><span>Last 7 days:</span><span><b>{m.get("shortlisted", 0)}</b> shortlisted</span>'
                 f'<span><b>{m.get("applied", 0)}</b> applied</span><span><b>{mail["sent"]}</b> emails sent</span>'
                 f'<span><b>{mail["followed_up"]}</b> follow-ups</span>'
                 f'<span><b>{m.get("interviewing", 0)}</b> interviews</span></div>')
    add = (f'<details><summary>Add a job from a post you found (LinkedIn, WhatsApp, email)</summary>'
           f'<form class="block" method="post" action="/add">{tok}'
           f'<textarea class="small" name="text" aria-label="Post text" placeholder="Paste the post here"></textarea>'
           f'<input type="text" name="url" aria-label="Link to the post" placeholder="Link to the post (optional)">'
           f'<button>Read, score and shortlist</button></form></details>')
    flash = f'<div class="flash" role="status">{h(message)}</div>' if message else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>Job Search</title>'
            f"<style>{_CSS}</style></head><body><main><h1>Job search</h1>"
            f'<p class="sub">{len(rows)} tracked jobs, newest postings first.</p>{stats}{flash}{add}'
            f"{body}</main></body></html>")


def serve(settings, cfg, llm_factory, port: int = 8765) -> ThreadingHTTPServer:
    """Build the server. It listens on this Mac only and accepts changes only from its own page."""
    token = secrets.token_urlsafe(16)
    url = settings.database_url

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/":
                self.send_error(404)
                return
            message = (parse_qs(parsed.query).get("msg") or [""])[0]
            with db.connect(url) as conn:
                p = db.active_profile(conn)
                rows = db.dashboard_rows(conn, p["id"]) if p else []
                due = {r["job_id"] for r in db.followups_due(conn, p["id"], cfg.outreach.follow_up_days)} if p else set()
                prog = db.progress(conn, p["id"], 7) if p else None
            body = dashboard_html(rows, due, token, progress=prog, message=message).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode(),
                            keep_blank_values=True)
            get = lambda k: (form.get(k) or [""])[0]  # noqa: E731
            if not secrets.compare_digest(get("token"), token):
                self.send_error(400)
                return
            jid = int(get("job_id")) if get("job_id").isdigit() else None
            message = ""
            try:
                with db.connect(url) as conn:
                    p = db.active_profile(conn)
                    if not p:
                        raise ActionError("No profile yet. Run: jsa profile import <resume.pdf>")
                    pid = p["id"]
                    if self.path == "/add":
                        if not get("text").strip():
                            raise ActionError("Paste the post text first.")
                        job_id, is_new, found, m = add_pasted_job(conn, llm_factory(), cfg, get("text").strip(),
                                                                  get("url").strip() or None)
                        message = (f"{'Added' if is_new else 'Updated'} #{job_id} {found.title} at {found.company}: "
                                   f"score {m.score}.")
                    elif jid is None or not db.get_job(conn, jid):
                        raise ActionError("That job was not found.")
                    elif self.path == "/status" and get("status") in db.APPLICATION_STATUSES:
                        db.set_application_status(conn, pid, jid, get("status"), "set on the web page")
                    elif self.path == "/note":
                        db.set_application_status_if_missing(conn, pid, jid)
                        db.set_note(conn, pid, jid, get("note"))
                        message = f"Note saved for #{jid}."
                    elif self.path == "/draft":
                        if not (get("subject").strip() and get("body").strip()):
                            raise ActionError("The subject and the email text cannot be empty.")
                        db.save_draft_text(conn, pid, jid, get("subject"), get("body"))
                        message = f"Draft saved for #{jid}."
                    elif self.path == "/send":
                        to = send_stored_draft(conn, settings, cfg.outreach, pid, jid)
                        message = f"Email for #{jid} sent to {to}."
                    else:
                        self.send_error(400)
                        return
            except ActionError as e:
                message = str(e)
            except Exception as e:  # noqa: BLE001 - show the reason on the page rather than a blank error
                message = f"That did not work: {str(e).splitlines()[0]}"
            self.send_response(303)
            self.send_header("Location", "/" + (f"?msg={quote(message)}" if message else ""))
            self.end_headers()

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.token = token
    return server
