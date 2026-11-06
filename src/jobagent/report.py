"""Human-readable output: terminal tables and a Markdown digest."""

from __future__ import annotations

from datetime import datetime


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
    ("company", "Company", 18), ("location", "Location", 22), ("application_status", "Status", 12),
]


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
