"""Apply to jobs on Bayt with its own "Easy Apply" button, in a browser the user logged into.

The browser is a visible local Chromium with its own profile folder, so the login the user does
once (`jsa apply-login`) is reused. The agent never types credentials, and it stops and hands a
job back whenever the site asks for anything beyond the one click: a sign-in, a CAPTCHA or bot
check, extra questions, or another company's site.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

PROFILE_DIR = Path.home() / ".jobagent" / "browser-profile"
BAYT_LOGIN_URL = "https://www.bayt.com/en/login/"
_APPLY_LINK = "a#applyLink_1"  # Bayt's main apply button, for Easy Apply and external jobs alike

_CAPTCHA = ("captcha", "are you a robot", "verify you are human", "unusual traffic",
            "security check", "security verification", "not a bot", "just a moment")
_APPLIED = ("you have applied", "you applied", "already applied", "application was sent",
            "application has been sent", "successfully applied", "application submitted")
_GONE = ("no longer available", "job has expired", "this job is closed", "no longer accepting")


@dataclass
class ApplyResult:
    status: str  # applied | already_applied | external | login_needed | blocked | closed | needs_you | dry_run
    detail: str = ""


def is_bayt(url: str) -> bool:
    return "bayt.com/" in (url or "")


def read_posting(page_text: str, apply_label: str | None) -> ApplyResult | None:
    """What a Bayt posting page allows, before anything is clicked. None means: go ahead."""
    text = page_text.lower()
    label = (apply_label or "").strip().lower()
    if any(m in text for m in _CAPTCHA):
        return ApplyResult("blocked", "the site is showing a bot check")
    if any(m in text for m in _GONE) or not label:
        if "applied" in label or (not label and any(m in text for m in _APPLIED[:3])):
            return ApplyResult("already_applied")
        return ApplyResult("closed", "no apply button on the posting")
    if "applied" in label:
        return ApplyResult("already_applied")
    if "easy apply" not in label:
        return ApplyResult("external", f'the button says "{apply_label.strip()}"')
    return None


def read_outcome(page_text: str, url: str) -> ApplyResult:
    """What happened after the Easy Apply click. Only an explicit confirmation counts."""
    text = page_text.lower()
    if any(m in text for m in _CAPTCHA):
        return ApplyResult("blocked", "the site is showing a bot check")
    if "/login" in url or "/register" in url or "log in to apply" in text:
        return ApplyResult("login_needed", "run: jsa apply-login")
    if any(m in text for m in _APPLIED):
        return ApplyResult("applied")
    return ApplyResult("needs_you", "the site asked for more than one click; finish it in the window")


@contextmanager
def user_browser():
    """A visible Chromium that keeps its cookies in PROFILE_DIR between runs."""
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False)
        try:
            yield context.pages[0] if context.pages else context.new_page()
        finally:
            context.close()


def apply_on_bayt(page, url: str, *, dry_run: bool = False) -> ApplyResult:
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(2000)
    link = page.query_selector(_APPLY_LINK)
    label = link.inner_text() if link else None
    stop = read_posting(page.inner_text("body"), label)
    if stop:
        return stop
    if dry_run:
        return ApplyResult("dry_run", "Easy Apply is available")
    link.click()
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20_000)
    except Exception:  # noqa: BLE001 - some confirmations appear without a page load
        pass
    page.wait_for_timeout(3000)
    return read_outcome(page.inner_text("body"), page.url)
