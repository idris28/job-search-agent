"""Deliver drafted emails through the user's Gmail: save to Drafts, or send."""

from __future__ import annotations

import imaplib
import smtplib
import mimetypes
import re
import time
from email.message import EmailMessage
from pathlib import Path

_LINK_RE = re.compile(r"\[([^\[\]]+)\]\((https?://[^\s()]+)\)")


def build_message(sender: str, to: str, subject: str, body_text: str, body_html: str,
                  attachment: Path | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    # Plain-text readers cannot follow a [LinkedIn](url) link, so spell the address out.
    # ...and cannot show bold, so drop the ** marks.
    msg.set_content(_LINK_RE.sub(r"\1: \2", body_text).replace("**", ""))
    msg.add_alternative(f"<html><body>{body_html}</body></html>", subtype="html")
    if attachment is not None:
        kind = mimetypes.guess_type(attachment.name)[0] or "application/octet-stream"
        maintype, subtype = kind.split("/", 1)
        msg.add_attachment(attachment.read_bytes(), maintype=maintype, subtype=subtype,
                           filename=attachment.name)
    return msg


def _drafts_folder(imap) -> str:
    """Gmail marks its Drafts folder with the \\Drafts flag; its name depends on the language."""
    _, rows = imap.list()
    for row in rows or []:
        line = row.decode() if isinstance(row, bytes) else str(row)
        if "\\Drafts" in line:
            return line.rsplit(' "/" ', 1)[-1].strip()
    return '"[Gmail]/Drafts"'


def save_drafts(address: str, app_password: str, messages: list[EmailMessage], *,
                imap_factory=imaplib.IMAP4_SSL) -> int:
    """Append each message to Gmail Drafts over IMAP. Returns how many were saved."""
    imap = imap_factory("imap.gmail.com")
    try:
        imap.login(address, app_password)
        folder = _drafts_folder(imap)
        for msg in messages:
            status, detail = imap.append(folder, "\\Draft", imaplib.Time2Internaldate(time.time()),
                                         msg.as_bytes())
            if status != "OK":
                raise RuntimeError(f"Gmail refused the draft for {msg['To']}: {detail}")
        return len(messages)
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001 - already disconnected
            pass


def send_messages(address: str, app_password: str, messages: list[EmailMessage], *,
                  smtp_factory=smtplib.SMTP_SSL) -> int:
    """Send each message from the user's Gmail account. Returns how many were sent."""
    with smtp_factory("smtp.gmail.com", 465) as smtp:
        smtp.login(address, app_password)
        for msg in messages:
            smtp.send_message(msg)
    return len(messages)
