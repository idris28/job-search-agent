"""Tell the user about strong new matches: Telegram if set up, else an email to themselves."""

from __future__ import annotations

import httpx


def notify(settings, title: str, lines: list[str], *, http: httpx.Client | None = None) -> str:
    """Send one short message. Returns how it went out: "telegram", "email" or "" (not set up)."""
    text = title + "\n" + "\n".join(lines)
    if settings.telegram_bot_token and settings.telegram_chat_id:
        client = http or httpx.Client(timeout=20)
        try:
            r = client.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                            json={"chat_id": settings.telegram_chat_id, "text": text[:4000],
                                  "disable_web_page_preview": True})
            r.raise_for_status()
        finally:
            if http is None:
                client.close()
        return "telegram"
    if settings.gmail_address and settings.gmail_app_password:
        from . import mailer
        from .report import _paragraphs_html

        msg = mailer.build_message(settings.gmail_address, settings.gmail_address, title, text,
                                   _paragraphs_html(text))
        mailer.send_messages(settings.gmail_address, settings.gmail_app_password, [msg])
        return "email"
    return ""


def strong_match_lines(rows: list[dict]) -> list[str]:
    return [f"{r['score']}  {r['title']} at {r['company']} ({r['location'] or 'n/a'})\n{r['url']}"
            for r in rows]
