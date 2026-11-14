"""Live updates: open pages are sent task output and changes instead of asking for them."""

import http.client
import json
import sys
import threading
import time

from jobagent import db, web
from jobagent.config import AgentConfig, Settings
from jobagent.models import JobPosting

from conftest import TEST_DB


class Stream:
    """One open page listening to the program."""

    def __init__(self, server, token=None):
        host, port = server.server_address
        self.conn = http.client.HTTPConnection(host, port, timeout=10)
        self.conn.request("GET", f"/api/events?token={server.token if token is None else token}")
        self.response = self.conn.getresponse()

    def next(self):
        """The next event as (name, data); comments that only keep the line open are skipped."""
        name, data = None, None
        while True:
            line = self.response.fp.readline().decode("utf-8")
            if not line:
                raise AssertionError("the stream ended")
            line = line.rstrip("\n")
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
            elif line == "" and name:
                return name, data

    def close(self):
        self.conn.close()


def post(server, path, body):
    c = http.client.HTTPConnection(*server.server_address, timeout=10)
    c.request("POST", path, json.dumps(body), {"X-Token": server.token, "Content-Type": "application/json"})
    r = c.getresponse()
    out = r.status, json.loads(r.read())
    c.close()
    return out


def test_open_pages_are_sent_task_output_and_changes(conn):
    pid = db.save_profile(conn, "Alex", "resume", {})
    job_id, _ = db.upsert_job(conn, JobPosting(title="Java Engineer", company="Acme", url="https://x/1"), None, None)
    db.set_application_status(conn, pid, job_id, "shortlisted")
    server = web.serve(Settings(database_url=TEST_DB), AgentConfig(), 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        refused = Stream(server, token="wrong")
        assert refused.response.status == 403
        refused.close()

        first, second = Stream(server), Stream(server)  # two open pages
        assert first.response.status == 200
        assert first.response.getheader("Content-Type").startswith("text/event-stream")

        # A task's lines arrive as they are printed, each event saying where its lines start.
        script = "import time\nprint('one', flush=True)\ntime.sleep(0.3)\nprint('two', flush=True)"
        server.runner.command = lambda argv: [sys.executable, "-c", script]
        assert post(server, "/api/task", {"action": "notify-test"})[0] == 200
        for stream in (first, second):
            lines, running, changed = [], True, 0
            while running:
                name, data = stream.next()
                if name == "changed":
                    changed += 1
                    continue
                assert name == "task" and data["from"] == len(lines) and data["task"]["label"] == "Send a test notification"
                lines += data["lines"]
                running = data["task"]["running"]
            assert lines == ["one", "two"] and data["task"]["exit_code"] == 0 and "lines" not in data["task"]

        # Something stored changing is announced to every page, without saying what.
        assert post(server, "/api/note", {"job_id": job_id, "note": "call back"})[0] == 200
        for stream in (first, second):
            name, data = stream.next()
            while name != "changed":  # the task start was a change too, and may still be queued
                name, data = stream.next()
            assert data == {}

        # A page that opens later is brought up to date with the last task at once.
        late = Stream(server)
        name, data = late.next()
        assert name == "task" and data["from"] == 0 and data["lines"] == ["one", "two"] and not data["task"]["running"]
        for stream in (first, second, late):
            stream.close()
    finally:
        server.feed.close()
        server.shutdown()
        server.server_close()


def test_the_feed_wakes_on_a_change_and_otherwise_waits():
    feed = web.Feed()
    seen = feed.wait((-1, -1), 5)  # anything differs from "nothing seen yet"
    assert seen == (0, 0)
    started = time.monotonic()
    assert feed.wait(seen, 0.2) == seen and time.monotonic() - started >= 0.15  # nothing changed: it waited
    threading.Timer(0.1, feed.task_changed).start()
    assert feed.wait(seen, 5) == (1, 0)
    feed.data_changed()
    assert feed.wait((1, 0), 5) == (1, 1)
    feed.close()
    started = time.monotonic()
    feed.wait((1, 1), 5)
    assert time.monotonic() - started < 1  # a closed feed lets every waiting page go
