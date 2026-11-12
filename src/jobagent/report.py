"""Human-readable output: terminal tables and a Markdown digest."""

from __future__ import annotations

import re
from datetime import datetime

from .models import TemplateEmail, company_named


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
        if m.get("salary_text") or m.get("salary_estimate"):
            out.append(f"Pay: {m.get('salary_text') or m['salary_estimate']}")
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
:root{color-scheme:light dark;--s0:#eceff4;--s1:#f5f7fa;--s3:#eceff4;--t1:#111827;--t2:#4b5565;--t3:#6b7487;
--line:rgba(17,24,39,.08);--line-2:rgba(17,24,39,.14);--accent:#2f55d4;--ok:#15803d;--warn:#a15c07;--paper:#fffdf9;
--shadow:0 1px 2px rgba(17,24,39,.08),0 8px 24px rgba(17,24,39,.08);
--sans:"Geist",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"Geist Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root{--s0:#07080d;--s1:#0b0d14;--s3:#1a1e28;--t1:#eef0f5;--t2:#a3a9b8;--t3:#7a8296;
--line:rgba(238,240,245,.08);--line-2:rgba(238,240,245,.14);--accent:#8aa6ff;--ok:#4cc38a;--warn:#d9a23b;--paper:#f4f2ec;
--shadow:0 1px 2px rgba(0,0,0,.2),0 8px 24px rgba(0,0,0,.24)}}
*{box-sizing:border-box}
body{margin:0;background:var(--s1);color:var(--t1);font:400 14px/20px var(--sans);-webkit-font-smoothing:antialiased}
main{max-width:752px;margin:0 auto;padding:48px 16px 64px}
h1{margin:0 0 8px;font-size:28px;line-height:36px;font-weight:500}
.sub{margin:0 0 32px;max-width:68ch;color:var(--t2)}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.job{padding:24px 0 32px;border-top:1px solid var(--line)}
.head{display:flex;justify-content:space-between;align-items:baseline;gap:8px 16px;flex-wrap:wrap}
.head h2{margin:0;font-size:20px;line-height:28px;font-weight:500}
.meta{display:flex;flex-wrap:wrap;gap:4px 16px;margin:4px 0 16px;font-size:13px;color:var(--t2)}
.meta .id{font:400 12px/20px var(--mono);color:var(--t3)}
.tag{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--t2);white-space:nowrap}
.tag::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--c,var(--t3));flex:none}
.ok{--c:var(--ok)}.warn{--c:var(--warn)}
.note{margin:0 0 12px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--s3);
font-size:13px;color:var(--t2)}
.note .tag{margin-right:8px;color:var(--t1)}
.flag{color:var(--t1)}
.flag::before{content:"";display:inline-block;width:6px;height:6px;margin-right:8px;border-radius:50%;
background:var(--warn);vertical-align:middle}
.note ul{margin:4px 0 8px;padding-left:20px}.note p{margin:8px 0 0}
.desk{margin:0 0 12px;padding:16px;border-radius:12px;background:var(--s0)}
.sheet{--t1:#111827;--t2:#4b5565;--t3:#6b7487;--line:rgba(17,24,39,.1);--accent:#2f55d4;padding:8px 32px 32px;
border-radius:2px;background:var(--paper);color:var(--t1);box-shadow:var(--shadow)}
.ln{display:flex;gap:8px;align-items:baseline;padding:14px 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
.ln b{width:56px;flex:none;font-size:13px;font-weight:400;color:var(--t3)}
.ln .subj{font-weight:500}
.mail{margin-top:24px;line-height:24px}
.mail p{margin:0 0 12px}.mail ul{margin:0 0 12px;padding-left:20px}.mail li{margin:0 0 4px}
.mail>:last-child{margin-bottom:0}
.sig{color:var(--t2)}
button{height:32px;margin:0 8px 0 0;padding:0 12px;border:1px solid var(--line-2);border-radius:8px;
background:var(--s3);color:var(--t1);font:500 13px var(--sans);cursor:pointer}
button:hover{border-color:var(--t3)}
details{margin-top:12px;font-size:13px}
summary{cursor:pointer;color:var(--t2)}
.fsub{margin:12px 0 0;color:var(--t2)}.fsub span{color:var(--t1)}
.quiet{margin:8px 0 12px;padding:16px;border-radius:8px;background:var(--s3);font-size:14px}
.quiet p{margin:0 0 12px}.quiet>:last-child{margin-bottom:0}
pre{white-space:pre-wrap;margin:8px 0 0;padding:16px;border:1px solid var(--line);border-radius:8px;
background:var(--s0);color:var(--t2);font:400 12px/20px var(--mono)}
@media (max-width:600px){main{padding:32px 16px 48px}.desk{padding:8px}.sheet{padding:4px 20px 24px}}
"""

_EMAIL_FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
                '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
                '<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500&'
                'family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">')

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
    html = re.sub(r"\[([^\[\]<>]+)\]\((https?://[^\s()<>\"]+)\)", r'<a href="\2">\1</a>', html)
    return re.sub(r"\*\*([^*<>]+)\*\*", r"<b>\1</b>", html)  # **Key skills:** becomes bold


def email_body_html(e) -> str:
    if isinstance(e, TemplateEmail):  # the filled-in template is the whole email
        return _paragraphs_html(e.body)
    bullets = "".join(f"<li>{_h(b)}</li>" for b in e.bullets)
    sig = "<br>".join(_h(x) for x in e.signature)
    return (f"<p>{_h(e.greeting)}</p><p>{_h(e.opener)}</p><ul>{bullets}</ul>"
            f"<p>{_h(e.logistics)}</p><p>{_h(e.call_to_action)}</p>"
            f'<p class="sig">Best regards,<br>{sig}</p>')


def emails_html(items: list[dict], *, title: str) -> str:
    """items: {job, email (RecruiterEmail or TemplateEmail), status, research, review, unfilled}

    Follows DESIGN.md: quiet page, each email on a sheet of paper. "Copy email" takes the sheet's
    own HTML, so nothing from this page's styling travels into the pasted email.
    """
    cards = []
    for n, it in enumerate(items):
        j, e = it["job"], it["email"]
        unfilled = (f'<p class="note flag">Fill in before sending: '
                    f'{_h(", ".join(it["unfilled"]))}</p>' if it.get("unfilled") else "")
        badge = ('<span class="tag ok">Still open</span>' if it["status"] == "open" else
                 '<span class="tag warn">Looks closed</span>' if it["status"] == "closed" else
                 '<span class="tag">Not checked</span>')
        to = _h(e.contact_email) if e.contact_email else "No email on the posting: use the apply page or LinkedIn"
        rec = f", {_h(e.recruiter_name)}" if e.recruiter_name else ""
        url = str(j.get("url") or "")
        meta = [f"<span>{_h(j['company'])}</span>" if company_named(j.get("company")) else "",
                f"<span>{_h(j['location'])}</span>" if j.get("location") else "",
                f'<a href="{_h(url)}">View posting</a>' if url.startswith(("http://", "https://")) else "",
                f'<span class="id">#{j["id"]}</span>']
        research = (f"<details><summary>Recruiter guidance used (web research)</summary>"
                    f"<pre>{_h(it['research'])}</pre></details>" if it.get("research") else "")
        rv = it.get("review")
        review = ""
        if rv is not None:
            cls = "ok" if rv.score >= 8 else "warn"
            li = lambda xs: "".join(f"<li>{_h(x)}</li>" for x in xs)  # noqa: E731
            review = (f'<div class="note"><span class="tag {cls}">Recruiter review {rv.score}/10</span>'
                      f"<span>{_h(rv.first_impression)}</span>"
                      f"<details><summary>Strengths and remaining issues</summary>"
                      f"<p><b>Strengths</b></p><ul>{li(rv.strengths)}</ul>"
                      + (f"<p><b>Issues</b></p><ul>{li(rv.issues)}</ul>" if rv.issues else "")
                      + "</details></div>")
        cards.append(f"""
<section class="job">
  <div class="head"><h2>{_h(j['title'])}</h2>{badge}</div>
  <div class="meta">{''.join(meta)}</div>
  {review}{unfilled}
  <div class="desk"><div class="sheet">
    <div class="ln"><b>To</b><span>{to}{rec}</span></div>
    <div class="ln"><b>Subject</b><span class="subj" id="s{n}">{_h(e.subject)}</span></div>
    <div class="mail" id="b{n}">{email_body_html(e)}</div>
  </div></div>
  <button onclick="cp('s{n}',this)">Copy subject</button><button onclick="cp('b{n}',this)">Copy email</button>
  <details><summary>Follow-up for 5 to 7 days later</summary>
    <p class="fsub">Subject: <span id="fs{n}">{_h(e.follow_up_subject)}</span></p>
    <div class="quiet" id="fb{n}">{_paragraphs_html(e.follow_up_body)}</div>
    <button onclick="cp('fs{n}',this)">Copy subject</button><button onclick="cp('fb{n}',this)">Copy follow-up</button>
  </details>{research}
</section>""")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_h(title)}</title>'
            f"{_EMAIL_FONTS}<style>{_EMAIL_CSS}</style></head><body><main><h1>{_h(title)}</h1>"
            f'<p class="sub">Drafts only. Review, edit, and send them yourself. "Copy email" keeps the '
            f"formatting when pasted into Gmail or Outlook.</p>{''.join(cards)}</main>"
            f"<script>{_EMAIL_JS}</script></body></html>")
