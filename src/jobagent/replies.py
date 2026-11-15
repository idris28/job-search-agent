"""A read-only look in the Gmail inbox for answers to the emails that were sent.

Only messages that come from an address the program wrote to, that answer one of its subject
lines, or that report a failed delivery are looked at. Of those only the sender, the date and
the subject line are read, never the text. Nothing in the mailbox is changed: the inbox is
opened read-only and no message is marked as read.

This is off unless `outreach.check_replies` is switched on.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# PEEK reads without marking the message as read; only these header lines are asked for.
_HEADERS = "(BODY.PEEK[HEADER.FIELDS (FROM DATE SUBJECT AUTO-SUBMITTED PRECEDENCE X-AUTOREPLY X-AUTORESPOND X-FAILED-RECIPIENTS)])"
_AUTO_SUBJECT = re.compile(r"^\s*(automatic reply|auto[- ]?reply|autoreply|out of (the )?office|"
                           r"thank you for (your )?(application|applying|interest))", re.I)
_AUTO_SENDER = re.compile(r"\b(no[-_.]?reply|do[-_.]?not[-_.]?reply)@", re.I)
_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw)\s*:\s*)+", re.I)
_RANK = {"automatic": 0, "bounced": 1, "reply": 2}  # a person's answer counts for more than a machine's
LATEST, LATEST_BOUNCES = 5, 50  # how many of the newest messages one search reads


def _since(day: datetime) -> str:
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def _quoted(text: str | None) -> str | None:
    """As a quoted string for an IMAP search, or None when it cannot safely be one."""
    text = (text or "").strip()
    if not text or not text.isascii() or any(c in text for c in '"\\\r\n'):
        return None
    return f'"{text}"'


def _search(imap, *criteria: str, latest: int = LATEST) -> list[bytes]:
    status, data = imap.search(None, *criteria)
    if status != "OK" or not data or not data[0]:
        return []
    return data[0].split()[-latest:]


def _headers(imap, num: bytes):
    status, data = imap.fetch(num, _HEADERS)
    if status != "OK":
        return None
    for part in data or []:
        if isinstance(part, tuple) and len(part) > 1:
            return email.message_from_bytes(part[1], policy=email.policy.default)
    return None


def _when(msg) -> datetime | None:
    try:
        at = parsedate_to_datetime(str(msg.get("Date")))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _kind(msg) -> str:
    """Whether a person wrote this, or a machine did (an out-of-office note, a "we received your
    application" message)."""
    if ((msg.get("Auto-Submitted") or "no").strip().lower() != "no" or msg.get("X-Autoreply") or msg.get("X-Autorespond")
            or (msg.get("Precedence") or "").strip().lower() in ("auto_reply", "bulk", "junk")
            or _AUTO_SUBJECT.search(str(msg.get("Subject") or "")) or _AUTO_SENDER.search(str(msg.get("From") or ""))):
        return "automatic"
    return "reply"


def find_replies(address: str, app_password: str, sent: list[dict], *, imap_factory=imaplib.IMAP4_SSL) -> dict[int, dict]:
    """What the inbox holds in answer to the emails that were sent, by job id: its kind ("reply",
    "automatic" or "bounced"), when it arrived and its subject line.

    Each row of `sent` carries job_id, contact_email, outreach_subject and outreach_sent_at.
    """
    found: dict[int, dict] = {}
    if not sent:
        return found

    def offer(job_id: int, kind: str, at: datetime, subject: str) -> None:
        best = found.get(job_id)
        if best is None or (_RANK[kind], at) > (_RANK[best["kind"]], best["at"]):
            found[job_id] = {"kind": kind, "at": at, "subject": subject[:300]}

    me = address.strip().lower()
    imap = imap_factory("imap.gmail.com")
    try:
        try:
            imap.login(address, app_password)
        except imaplib.IMAP4.error as e:
            raise RuntimeError("Gmail did not accept the sign-in. Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env, "
                               "and that IMAP is switched on in Gmail's settings.") from e
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Gmail's inbox could not be opened.")
        read: dict[bytes, object] = {}

        def message(num: bytes):
            if num not in read:
                read[num] = _headers(imap, num)
            return read[num]

        for row in sent:
            to, sent_at = row["contact_email"].strip().lower(), row["outreach_sent_at"]
            ours = _PREFIX.sub("", row.get("outreach_subject") or "").strip().lower()
            since = _since(sent_at - timedelta(days=1))  # a day early: the search knows dates, not time zones
            nums = _search(imap, "FROM", _quoted(to), "SINCE", since) if _quoted(to) else []
            if _quoted(ours):  # an answer may come from a colleague's address, under the same subject line
                nums += _search(imap, "SUBJECT", _quoted(ours), "SINCE", since)
            for num in dict.fromkeys(nums):
                msg = message(num)
                at = _when(msg) if msg is not None else None
                if at is None or at <= sent_at:
                    continue
                senders = {a.lower() for _, a in getaddresses([str(msg.get("From") or "")])}
                subject = str(msg.get("Subject") or "").strip()
                if me not in senders and (to in senders or (ours and _PREFIX.sub("", subject).strip().lower() == ours)):
                    offer(row["job_id"], _kind(msg), at, subject)

        first = min(r["outreach_sent_at"] for r in sent)
        for num in _search(imap, "FROM", '"mailer-daemon"', "SINCE", _since(first - timedelta(days=1)), latest=LATEST_BOUNCES):
            msg = message(num)
            at = _when(msg) if msg is not None else None
            if at is None:
                continue
            refused = {a.lower() for _, a in getaddresses([str(msg.get("X-Failed-Recipients") or "")])}
            for row in sent:
                if row["contact_email"].strip().lower() in refused and at > row["outreach_sent_at"]:
                    offer(row["job_id"], "bounced", at, str(msg.get("Subject") or "").strip())
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001 - already disconnected
            pass
    return found
