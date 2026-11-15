"""A CV written for one job: the resume's own facts, chosen and ordered for that posting.

The model does the choosing. This module then checks what it wrote against the resume, takes out
what the resume does not say, and lays the rest out as a one-column PDF that the software
recruiters use to read CVs can read.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from .models import TailoredResume

MAX_SKILLS = 18
_SPLIT = re.compile(r"[^a-z0-9+#]+")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _flat(text: str) -> str:
    """Lower-case words with one space between them and one at each end, so that a phrase can be
    looked for as whole words."""
    return f" {_SPLIT.sub(' ', text.lower()).strip()} "


def _numbers(text: str) -> set[str]:
    """The figures in a text, written one way: 10,000 and 10000 are the same, and so are 6.0 and 6."""
    found = set()
    for n in _NUMBER.findall(text):
        n = n.replace(",", "")
        found.add(n.rstrip("0").rstrip(".") if "." in n else n)
    return found


def _named(phrase: str, resume: str) -> bool:
    """Whether the resume holds this phrase as whole words. A last "s" more or less does not matter."""
    words = _flat(phrase).split()
    if not words:
        return False
    other = words[-1][:-1] if words[-1].endswith("s") else words[-1] + "s"
    return any(f" {' '.join(words[:-1] + [last])} " in resume for last in (words[-1], other))


def check(written: TailoredResume, resume_text: str, years: float | None = None) -> tuple[dict, list[str]]:
    """What the model wrote, with everything the resume does not say taken out.

    Returns the CV as plain data, and a note for each thing that was taken out or that the
    person should look at. `years` is the total experience worked out when the resume was
    imported; the summary may state it although the resume gives only dates.
    """
    resume, known = _flat(resume_text), _numbers(resume_text)
    if years:
        known |= _numbers(f"{years:g}")
    notes: list[str] = []

    def unknown(text: str) -> str:
        return ", ".join(sorted(n for n in _numbers(text) if n not in known))

    skills, left_out = [], []
    for skill in (s.strip() for s in written.skills):
        if skill and _named(skill, resume):
            if skill.lower() not in {k.lower() for k in skills}:
                skills.append(skill)
        elif skill:
            left_out.append(skill)
    if left_out:
        notes.append(f"Left out, because your resume does not name {'it' if len(left_out) == 1 else 'them'}: {', '.join(left_out)}")

    experience = []
    for job in written.experience:
        employer = job.employer.strip()
        if not _named(employer, resume):
            notes.append(f'Left out the job at "{employer}", because your resume does not name that employer')
            continue
        if job.title.strip() and not _named(job.title, resume):
            notes.append(f'Check the job title "{job.title.strip()}" at {employer}: your resume words it differently')
        if unknown(job.dates):
            notes.append(f'Check the dates "{job.dates.strip()}" at {employer}: your resume gives other ones')
        bullets = []
        for line in (b.strip() for b in job.bullets):
            if line and unknown(line):
                notes.append(f'Left out a line at {employer}, because your resume does not give the figure {unknown(line)}: "{line}"')
            elif line:
                bullets.append(line)
        experience.append({"employer": employer, "title": job.title.strip(), "dates": job.dates.strip(),
                           "location": job.location.strip(), "bullets": bullets})

    for name, text in (("headline", written.headline), ("summary", written.summary)):
        if unknown(text):
            notes.append(f"Check the {name}: your resume does not give the figure {unknown(text)}")

    def lines(items: list[str], heading: str) -> list[str]:
        kept = []
        for line in (i.strip() for i in items):
            if line and all(f" {w} " in resume for w in _flat(line).split() if len(w) > 3) and not unknown(line):
                kept.append(line)
            elif line:
                notes.append(f'Left out under {heading}, because your resume does not say it: "{line}"')
        return kept

    return ({"headline": written.headline.strip(), "summary": written.summary.strip(), "skills": skills[:MAX_SKILLS],
             "experience": experience, "education": lines(written.education, "Education"),
             "other": lines(written.other, "Additional information")}, notes)


_STYLE = """@page{size:A4;margin:14mm 16mm}
*{box-sizing:border-box}
body{margin:0;font:10pt/1.42 Helvetica,Arial,sans-serif;color:#1a1a1a}
h1{margin:0;font-size:20pt;line-height:1.2}
.headline{margin:2pt 0 0;font-size:11pt;color:#333}
.contact{margin:4pt 0 0;font-size:9.5pt;color:#333}
h2{margin:14pt 0 5pt;padding-bottom:2pt;border-bottom:.75pt solid #999;font-size:10.5pt;break-after:avoid}
p{margin:0}
.job{margin-bottom:8pt}
.row{display:flex;justify-content:space-between;gap:12pt;break-after:avoid}
.row span:last-child{text-align:right;white-space:nowrap;color:#444}
ul{margin:3pt 0 0;padding-left:14pt}
li{margin-bottom:1.5pt;break-inside:avoid}"""


def page_html(name: str, contact: list[str], cv: dict) -> str:
    """The CV as one plain column: real text under the usual headings, nothing drawn as a picture."""
    e = html.escape

    def section(heading: str, body: str) -> str:
        return f"<h2>{heading}</h2>{body}" if body else ""

    def listed(items: list[str]) -> str:
        return f"<ul>{''.join(f'<li>{e(i)}</li>' for i in items)}</ul>" if items else ""

    jobs = "".join(
        f'<div class="job"><div class="row"><b>{e(j["title"])}</b><span>{e(j["dates"])}</span></div>'
        f'<div class="row"><span>{e(j["employer"])}</span><span>{e(j["location"])}</span></div>{listed(j["bullets"])}</div>'
        for j in cv["experience"])
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{e(name)}</title><style>{_STYLE}</style></head><body>"
            f"<h1>{e(name)}</h1>"
            + (f'<p class="headline">{e(cv["headline"])}</p>' if cv["headline"] else "")
            + (f'<p class="contact">{e(" | ".join(contact))}</p>' if contact else "")
            + section("Summary", f"<p>{e(cv['summary'])}</p>" if cv["summary"] else "")
            + section("Skills", f"<p>{e(', '.join(cv['skills']))}</p>" if cv["skills"] else "")
            + section("Experience", jobs)
            + section("Education", listed(cv["education"]))
            + section("Additional information", listed(cv["other"]))
            + "</body></html>")


def file_for(folder: str, job_id: int, name: str, filename: str = "") -> Path:
    """Where the CV for one job is kept. Each job has its own folder, so the file itself can carry
    the name a recruiter should see on the attachment."""
    wanted = Path(filename).name if filename else ""
    if not wanted.lower().endswith(".pdf"):
        wanted = (re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "My") + "_Resume.pdf"
    return (Path(folder).expanduser() / f"job-{job_id}" / wanted).resolve()


def write_pdf(page: str, path: Path) -> None:
    """Print the page to a PDF file, with the browser on this computer."""
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as e:
        raise RuntimeError("Playwright is not installed, so the PDF could not be made.") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Error as e:
            raise RuntimeError("The browser for making the PDF is not installed. Run: playwright install chromium") from e
        try:
            tab = browser.new_page()
            tab.set_content(page)
            tab.pdf(path=str(path), format="A4", print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


def tailored_file(application: dict | None) -> Path | None:
    """The CV written for this job, when the person asked for the job's email to carry it and the
    file is still there. Otherwise None, and the usual CV is used."""
    made = (application or {}).get("tailored_cv") or {}
    file = Path(made["file"]) if made.get("attach") and made.get("file") else None
    return file if file is not None and file.is_file() else None
