"""Answers to the emails that were sent, found by a read-only look in the Gmail inbox. Off until
it is switched on; reads the sender, the date and the subject line, and changes nothing."""

import imaplib
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest

from jobagent import cli, db, replies
from jobagent.config import AgentConfig, OutreachPrefs, Settings
from jobagent.models import JobPosting

from conftest import TEST_DB
from test_web import Page

SENT = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
ME = "alex@example.com"


def row(job_id, to, subject, sent=SENT):
    return {"job_id": job_id, "contact_email": to, "outreach_subject": subject, "outreach_sent_at": sent}


def mail(sender, after, subject, **extra):
    return {"from": sender, "at": SENT + after, "subject": subject, "extra": extra}


class Mailbox:
    """A stand-in inbox. It can be searched and its header lines read. It has no way to change
    anything: a call that would mark, move, add or delete a message is an error."""

    def __init__(self, messages, log, refuse=False):
        self.messages, self.log, self.refuse = messages, log, refuse

    def login(self, address, password):
        self.log.append(("login", address))
        if self.refuse:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

    def select(self, box, readonly=False):
        self.log.append(("select", box, readonly))
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.log.append(("search", *criteria))
        want = dict(zip(criteria[::2], criteria[1::2]))
        since = datetime.strptime(want["SINCE"], "%d-%b-%Y").replace(tzinfo=timezone.utc)
        hits = [str(i).encode() for i, m in enumerate(self.messages, 1)
                if m["at"] >= since and want.get("FROM", '""').strip('"').lower() in m["from"].lower()
                and want.get("SUBJECT", '""').strip('"').lower() in m["subject"].lower()]
        return "OK", [b" ".join(hits)]

    def fetch(self, num, what):
        self.log.append(("fetch", what))
        m = self.messages[int(num) - 1]
        lines = {"From": m["from"], "Date": format_datetime(m["at"]), "Subject": m["subject"], **m["extra"]}
        raw = "".join(f"{k}: {v}\r\n" for k, v in lines.items()) + "\r\n"
        return "OK", [(b"%s (BODY[HEADER.FIELDS (FROM DATE SUBJECT)] {%d}" % (num, len(raw)), raw.encode()), b")"]

    def logout(self):
        self.log.append(("logout",))


def look(rows, messages, **how):
    log = []
    return replies.find_replies(ME, "app-password", rows, imap_factory=lambda host: Mailbox(messages, log, **how)), log


def test_answers_are_told_apart_and_the_mailbox_is_only_read():
    rows = [row(1, "careers@acme.example", "Java Engineer | 8 yrs Java"), row(2, "hr@globex.example", "Backend Developer"),
            row(3, "jobs@initech.example", "Senior Java Developer"), row(4, "talent@umbrella.example", "Java Lead"),
            row(5, "people@hooli.example", "Platform Engineer"), row(6, "team@vandelay.example", "Java Architect"),
            row(7, "Jobs@Wonka.example", 'Engineer, "Payments"')]
    messages = [
        mail("Priya Shah <careers@acme.example>", timedelta(days=1), "Re: Java Engineer | 8 yrs Java"),
        mail("careers@acme.example", timedelta(hours=-3), "About your earlier application"),  # before the email went: not an answer to it
        mail("hr@globex.example", timedelta(hours=1), "Automatic reply: Backend Developer", **{"Auto-Submitted": "auto-replied"}),
        mail("Omar Khan <omar@initech.example>", timedelta(days=2), "RE: Senior Java Developer"),  # a colleague, under the same subject
        mail("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", timedelta(minutes=5), "Delivery Status Notification (Failure)",
             **{"X-Failed-Recipients": "talent@umbrella.example"}),
        mail(f"Alex Morgan <{ME}>", timedelta(days=1), "Re: Platform Engineer"),  # written by the person: not an answer
        mail("team@vandelay.example", timedelta(hours=2), "Thank you for your application"),
        mail("Dana Lee <team@vandelay.example>", timedelta(days=3), "Re: Java Architect"),
        mail("no-reply@wonka.example", timedelta(days=1), "We have your details"),  # another sender, another subject: not looked at
        mail("jobs@wonka.example", timedelta(days=1), "Interview next week?"),
    ]
    found, log = look(rows, messages)
    assert {k: (v["kind"], v["subject"]) for k, v in found.items()} == {
        1: ("reply", "Re: Java Engineer | 8 yrs Java"), 2: ("automatic", "Automatic reply: Backend Developer"),
        3: ("reply", "RE: Senior Java Developer"), 4: ("bounced", "Delivery Status Notification (Failure)"),
        6: ("reply", "Re: Java Architect"),  # a person's answer counts for more than the machine's that came first
        7: ("reply", "Interview next week?")}
    assert found[1]["at"] == SENT + timedelta(days=1)

    assert log[:2] == [("login", ME), ("select", "INBOX", True)] and log[-1] == ("logout",)  # opened read-only, and closed
    fetched = [entry[1] for entry in log if entry[0] == "fetch"]
    assert fetched and all(what.startswith("(BODY.PEEK[HEADER.FIELDS (FROM DATE SUBJECT") for what in fetched)  # header lines, unread stays unread
    assert not any("TEXT" in what or "RFC822" in what for what in fetched)  # never the text of a message
    assert not hasattr(Mailbox, "store") and not hasattr(Mailbox, "append") and not hasattr(Mailbox, "copy")
    searches = [entry[1:] for entry in log if entry[0] == "search"]
    assert ("FROM", '"careers@acme.example"', "SINCE", "09-Nov-2026") in searches  # a day early; the exact time is checked afterwards
    assert not any('Payments' in " ".join(s) for s in searches)  # a subject that cannot be quoted safely is not searched for
    assert ("FROM", '"jobs@wonka.example"', "SINCE", "09-Nov-2026") in searches


def test_nothing_sent_means_no_look_and_a_refused_sign_in_is_said_plainly():
    assert look([], [mail("x@y.example", timedelta(days=1), "Hello")]) == ({}, [])
    log = []
    with pytest.raises(RuntimeError, match="Gmail did not accept the sign-in"):
        replies.find_replies(ME, "wrong", [row(1, "careers@acme.example", "Java Engineer")], imap_factory=lambda host: Mailbox([], log, refuse=True))
    assert log == [("login", ME), ("logout",)]


def emailed(conn, n=4):
    pid = db.save_profile(conn, "Alex Morgan", "resume", {})
    ids = []
    for i in range(1, n + 1):
        jid, _ = db.upsert_job(conn, JobPosting(title=f"Java Engineer {i}", company=f"Company {i}", url=f"https://jobs.example.com/{i}",
                                                location="Dubai"), None, None)
        db.save_outreach(conn, pid, jid, subject=f"Java Engineer {i}", body="Dear Hiring Team", recruiter_name=None,
                         contact_email=f"careers@company{i}.example", still_open=True, follow_up_subject=f"Re: Java Engineer {i}",
                         follow_up_body="Following up.")
        db.set_application_status(conn, pid, jid, "applied")
        db.mark_outreach_sent(conn, pid, jid)
        ids.append(jid)
    conn.execute("UPDATE applications SET outreach_sent_at = now() - interval '7 days'")
    return pid, ids


def test_the_command_is_off_until_switched_on_then_records_answers_and_stops_their_follow_ups(conn, monkeypatch, tmp_path, capsys):
    pid, ids = emailed(conn)
    looked = []
    at = datetime.now(timezone.utc) - timedelta(days=1)
    answers = {ids[0]: {"kind": "reply", "at": at, "subject": "Re: Java Engineer 1"}, ids[1]: {"kind": "bounced", "at": at, "subject": "Delivery failed"},
               ids[2]: {"kind": "automatic", "at": at, "subject": "Out of office"}}
    monkeypatch.setattr(replies, "find_replies", lambda address, password, rows: looked.append((address, [r["job_id"] for r in rows])) or answers)
    settings = Settings(database_url=TEST_DB, gmail_address=ME, gmail_app_password="p")
    off, on = tmp_path / "off.yaml", tmp_path / "on.yaml"
    off.write_text("outreach: {follow_up_days: 6}\n")
    on.write_text("outreach: {follow_up_days: 6, check_replies: true}\n")

    assert AgentConfig().outreach.check_replies is False  # nothing looks in the mailbox unless the person asked for it
    with pytest.raises(SystemExit, match="switched off"):
        cli.cmd_replies(SimpleNamespace(config=str(off)), settings)
    assert looked == [] and len(db.followups_due(conn, pid, 6)) == 4

    cli.cmd_replies(SimpleNamespace(config=str(on)), settings)
    out = capsys.readouterr().out
    assert looked == [(ME, ids)]
    assert "Looked in Gmail for answers to 4 email(s): 1 replied, 1 not delivered." in out
    assert f'reply: #{ids[0]} Java Engineer 1 at Company 1 (careers@company1.example, {at:%d %b}): "Re: Java Engineer 1"' in out
    assert f"not delivered: #{ids[1]}" in out and f"automatic reply: #{ids[2]}" in out
    kept = {i: db.get_application(conn, pid, i) for i in ids}
    assert [kept[i]["reply_kind"] for i in ids] == ["reply", "bounced", "automatic", None]
    assert kept[ids[0]]["reply_subject"] == "Re: Java Engineer 1" and all(kept[i]["replies_checked_at"] for i in ids)
    assert kept[ids[0]]["status"] == "applied"  # what the reply means is for the person to say

    # A person's answer and a refused address get no follow-up; an automatic reply and silence still do.
    assert [r["job_id"] for r in db.followups_due(conn, pid, 6)] == ids[2:]
    cli.cmd_replies(SimpleNamespace(config=str(on)), settings)
    assert looked[-1] == (ME, ids[2:])  # the answered ones are not looked for again

    db.mark_outreach_sent(conn, pid, ids[1], again=True)  # written to once more: the old failed delivery no longer stands
    assert db.get_application(conn, pid, ids[1])["reply_kind"] is None

    conn.execute("UPDATE applications SET status = 'interviewing'")
    cli.cmd_replies(SimpleNamespace(config=str(on)), settings)
    assert "No emailed job is waiting for a reply." in capsys.readouterr().out and len(looked) == 2


def test_the_page_offers_the_check_only_when_it_is_switched_on(conn):
    pid, ids = emailed(conn, 1)
    db.save_replies(conn, pid, ids, {ids[0]: {"kind": "reply", "at": datetime.now(timezone.utc), "subject": "Re: Java Engineer 1"}})
    for on in (False, True):
        page = Page(cfg=AgentConfig(outreach=OutreachPrefs(check_replies=on)))
        started = []
        page.server.runner.command = lambda argv: started.append(argv) or [sys.executable, "-c", "print('ok')"]
        try:
            state = page.call("/api/state")[1]
            assert state["check_replies"] is on and state["jobs"][0]["reply_kind"] == "reply" and state["due"] == []
            code, r = page.call("/api/task", {"action": "replies"})
            if on:
                assert code == 200 and r["task"]["label"] == "Check for replies" and started == [["replies"]]
                page.wait()
            else:
                assert code == 400 and "switched off" in r["error"] and started == []
            shown = page.call(f"/api/job?id={ids[0]}")[1]["application"]
            assert shown["reply_kind"] == "reply" and shown["reply_subject"] == "Re: Java Engineer 1"
        finally:
            page.close()
