"""Check that a found application address is really published by the company."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from .models import company_key

# Sites that list or infer other people's addresses: never a company's own page.
_NOT_COMPANY_SITES = ("naukri", "bayt", "linkedin", "indeed", "glassdoor", "facebook", "rocketreach",
                      "zoominfo", "signalhire", "contactout", "apollo.io", "hunter.io", "lusha",
                      "crunchbase", "ambitionbox", "google.", "wikipedia")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def verify_contact(found: dict | None, company: str, http: httpx.Client) -> tuple[dict | None, str]:
    """Return (contact, reason). The contact is kept only when the address is printed on the page
    it was said to come from, and that page looks like the company's own site."""
    if not found or not found.get("email"):
        return None, "no address is published"
    email, url = str(found["email"]).strip(), str(found.get("source_url") or "").strip()
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not _EMAIL_RE.match(email) or not host:
        return None, "the result was not a usable address and page"
    if any(s in host for s in _NOT_COMPANY_SITES):
        return None, f"the page ({host}) is not the company's own site"
    domain = email.rsplit("@", 1)[1].lower()
    words = [w for w in company_key(company).split() if len(w) >= 4]
    squashed = host.replace("-", "").replace(".", "")
    if not (host.endswith(domain) or domain.endswith(host) or any(w in squashed for w in words)):
        return None, f"the page ({host}) does not look like {company}'s site"
    try:
        page = http.get(url, timeout=20, follow_redirects=True).text
    except httpx.HTTPError as e:
        return None, f"the page could not be opened ({type(e).__name__})"
    if email.lower() not in page.lower():
        return None, "the address is not on that page"
    kind = found.get("kind") if found.get("kind") in ("recruiter", "careers", "general") else "general"
    return {"email": email, "source_url": url, "kind": kind}, "found"
