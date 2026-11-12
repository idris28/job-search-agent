"""Human-readable output: terminal tables and a Markdown digest."""

from __future__ import annotations

import re
from datetime import datetime

from .models import TemplateEmail


def _trunc(s: str | None, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def table(rows: list[dict], cols: list[tuple[str, str, int]]) -> str:
    """cols: (key, header, width)"""
    head = "  ".join(h.ljust(w) for _, h, w in cols)
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append("  ".join(_trunc(str(r.get(k) if r.get(k) is not None else ""), w).ljust(w)
                               for k, _, w in cols))
    return "\n".join(lines)


MATCH_COLS = [
    ("job_id", "ID", 6), ("score", "Score", 5), ("title", "Title", 38),
    ("company", "Company", 18), ("location", "Location", 22), ("posted", "Posted", 8),
    ("application_status", "Status", 12),
]


def age(posted_at, now: datetime | None = None) -> str:
    """Short age of a posting for tables: "3h", "2d", or "" when unknown."""
    if posted_at is None:
        return ""
    now = now or datetime.now(posted_at.tzinfo)
    hours = max(0, (now - posted_at).total_seconds() / 3600)
    return f"{int(hours)}h" if hours < 24 else f"{int(hours // 24)}d"


def digest_markdown(matches: list[dict], *, title: str = "Job matches") -> str:
    out = [f"# {title}", f"_Generated {datetime.now():%Y-%m-%d %H:%M}_", ""]
    if not matches:
        out.append("No matches yet.")
        return "\n".join(out)
    for m in matches:
        out.append(f"## {m['score']} · {m['title']} at {m['company']}")
        out.append(f"{m.get('location') or 'Location n/a'} · {m.get('remote_type')} · "
                   f"[posting]({m['url']}) · job id {m['job_id']}")
        if m.get("salary_text"):
            out.append(f"Salary: {m['salary_text']}")
        out.append("")
        out.append(m["summary"])
        if m.get("matched_skills"):
            out.append(f"\n**Matches:** {', '.join(m['matched_skills'])}")
        if m.get("missing_skills"):
            out.append(f"**Gaps:** {', '.join(m['missing_skills'])}")
        if m.get("red_flags"):
            out.append(f"**Red flags:** {', '.join(m['red_flags'])}")
        out.append("")
    return "\n".join(out)


# --- recruiter email preview (HTML) -------------------------------------------

_EMAIL_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2430;--muted:#5d6b7e;--line:#e3e7ed;--accent:#2457d6;
--ok:#1e7d4f;--okbg:#e6f4ec;--warn:#9a4b00;--warnbg:#fdf0e1}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--card:#1b2029;--ink:#e7ebf1;--muted:#9aa6b6;
--line:#2c3442;--accent:#7ea2ff;--ok:#6fd3a0;--okbg:#173327;--warn:#ffb46b;--warnbg:#3a2a17}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 16px 64px}h1{font-size:24px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 28px}.card{background:var(--card);border:1px solid var(--line);
border-radius:12px;padding:20px 22px;margin:0 0 22px}.head{display:flex;justify-content:space-between;
gap:12px;flex-wrap:wrap;align-items:baseline}.head h2{font-size:17px;margin:0}.meta{color:var(--muted);
font-size:13px;margin:4px 0 12px}.meta a{color:var(--accent)}.badge{font-size:12px;font-weight:600;
padding:3px 9px;border-radius:999px}.ok{color:var(--ok);background:var(--okbg)}.warn{color:var(--warn);
background:var(--warnbg)}.row{font-size:14px;margin:2px 0}.row b{display:inline-block;width:64px;
color:var(--muted);font-weight:500}.mail{border:1px solid var(--line);border-radius:10px;padding:16px 18px;
margin:12px 0}.mail p{margin:0 0 10px}.mail ul{margin:0 0 10px;padding-left:20px}.mail li{margin:0 0 4px}
.sig{color:var(--muted);font-size:14px;line-height:1.45}button{font:inherit;font-size:13px;cursor:pointer;
border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:5px 11px;
margin-right:6px}button:hover{border-color:var(--accent)}details{margin-top:10px;font-size:14px}
summary{cursor:pointer;color:var(--muted)}pre{white-space:pre-wrap;font:13px/1.5 ui-monospace,Menlo,monospace;
background:var(--bg);padding:10px 12px;border-radius:8px;margin:8px 0 0}
.review{font-size:14px;margin:0 0 12px;padding:10px 12px;border-radius:10px;background:var(--bg)}
.review>span:last-of-type{color:var(--muted)}.review ul{margin:4px 0 8px;padding-left:20px}.review p{margin:6px 0 0}
"""

_EMAIL_JS = """
function cp(id,btn){const el=document.getElementById(id);const html=el.innerHTML,text=el.innerText;
const done=()=>{const t=btn.textContent;btn.textContent='Copied';setTimeout(()=>btn.textContent=t,1200)};
try{navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([html],{type:'text/html'}),
'text/plain':new Blob([text],{type:'text/plain'})})]).then(done,()=>navigator.clipboard.writeText(text).then(done))}
catch(e){navigator.clipboard.writeText(text).then(done)}}
"""


def _h(s) -> str:
    import html as _html
    return _html.escape(str(s or ""))


def _paragraphs_html(text: str | None) -> str:
    """Plain text as <p> blocks: a blank line starts a new paragraph, other line breaks stay."""
    paragraphs = [p for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    html = "".join("<p>" + "<br>".join(_h(line.strip()) for line in p.splitlines()) + "</p>"
                   for p in paragraphs)
    # [LinkedIn](https://...) becomes a clickable link, which survives "Copy email" into Gmail.
    return re.sub(r"\[([^\[\]<>]+)\]\((https?://[^\s()<>\"]+)\)", r'<a href="\2">\1</a>', html)


def email_body_html(e) -> str:
    if isinstance(e, TemplateEmail):  # the filled-in template is the whole email
        return _paragraphs_html(e.body)
    bullets = "".join(f"<li>{_h(b)}</li>" for b in e.bullets)
    sig = "<br>".join(_h(x) for x in e.signature)
    return (f"<p>{_h(e.greeting)}</p><p>{_h(e.opener)}</p><ul>{bullets}</ul>"
            f"<p>{_h(e.logistics)}</p><p>{_h(e.call_to_action)}</p>"
            f'<p class="sig">Best regards,<br>{sig}</p>')


def emails_html(items: list[dict], *, title: str) -> str:
    """items: {job, email (RecruiterEmail or TemplateEmail), status, research, review, unfilled}"""
    cards = []
    for n, it in enumerate(items):
        j, e = it["job"], it["email"]
        unfilled = (f'<div class="row"><span class="badge warn">Fill in before sending: '
                    f'{_h(", ".join(it["unfilled"]))}</span></div>' if it.get("unfilled") else "")
        badge = ('<span class="badge ok">Still open</span>' if it["status"] == "open" else
                 '<span class="badge warn">Looks closed</span>' if it["status"] == "closed" else
                 '<span class="badge warn">Not checked</span>')
        to = _h(e.contact_email) if e.contact_email else "No email on the posting: use the apply page or LinkedIn"
        rec = f' · {_h(e.recruiter_name)}' if e.recruiter_name else ""
        research = (f"<details><summary>Recruiter guidance used (web research)</summary>"
                    f"<pre>{_h(it['research'])}</pre></details>" if it.get("research") else "")
        rv = it.get("review")
        review = ""
        if rv is not None:
            cls = "ok" if rv.score >= 8 else "warn"
            li = lambda xs: "".join(f"<li>{_h(x)}</li>" for x in xs)  # noqa: E731
            review = (f'<div class="review"><span class="badge {cls}">Recruiter review {rv.score}/10</span> '
                      f"<span>{_h(rv.first_impression)}</span>"
                      f"<details><summary>Strengths and remaining issues</summary>"
                      f"<p><b>Strengths</b></p><ul>{li(rv.strengths)}</ul>"
                      + (f"<p><b>Issues</b></p><ul>{li(rv.issues)}</ul>" if rv.issues else "")
                      + "</details></div>")
        cards.append(f"""
<section class="card">
  <div class="head"><h2>#{j['id']} {_h(j['title'])} at {_h(j['company'])}</h2>{badge}</div>
  <div class="meta">{_h(j.get('location'))} · <a href="{_h(j['url'])}">View posting</a></div>
  {review}{unfilled}
  <div class="row"><b>To</b>{to}{rec}</div>
  <div class="row"><b>Subject</b><span id="s{n}">{_h(e.subject)}</span></div>
  <div class="mail" id="b{n}">{email_body_html(e)}</div>
  <button onclick="cp('s{n}',this)">Copy subject</button><button onclick="cp('b{n}',this)">Copy email</button>
  <details><summary>Follow-up for 5–7 days later</summary>
    <div class="row" style="margin-top:8px"><b>Subject</b><span id="fs{n}">{_h(e.follow_up_subject)}</span></div>
    <div class="mail" id="fb{n}">{_paragraphs_html(e.follow_up_body)}</div>
    <button onclick="cp('fs{n}',this)">Copy subject</button><button onclick="cp('fb{n}',this)">Copy follow-up</button>
  </details>{research}
</section>""")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_h(title)}</title>'
            f"<style>{_EMAIL_CSS}</style></head><body><main><h1>{_h(title)}</h1>"
            f'<p class="sub">Drafts only. Review, edit, and send them yourself. "Copy email" keeps the '
            f"formatting when pasted into Gmail or Outlook.</p>{''.join(cards)}</main>"
            f"<script>{_EMAIL_JS}</script></body></html>")
