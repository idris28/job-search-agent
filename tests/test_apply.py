from types import SimpleNamespace

from jobagent import cli, db
from jobagent.config import Settings
from jobagent.models import JobPosting

from conftest import TEST_DB


def test_apply_opens_each_job_and_records_the_answer(conn):
    pid = db.save_profile(conn, "Alex", "resume", {})
    for i in (1, 2, 3):
        jid, _ = db.upsert_job(conn, JobPosting(title=f"Java {i}", company="Acme", url=f"https://x/{i}",
                                                location="Dubai"), None, None)
        db.set_application_status(conn, pid, jid, "shortlisted")
    opened, answers = [], iter(["y", "n", "s"])
    args = SimpleNamespace(job_ids=[], limit=10, dry_run=False)
    cli.cmd_apply(args, Settings(database_url=TEST_DB), open_url=opened.append,
                  ask=lambda prompt: next(answers))
    assert opened == ["https://x/1", "https://x/2", "https://x/3"]
    statuses = [r["status"] for r in conn.execute("SELECT status FROM applications ORDER BY job_id")]
    assert statuses == ["applied", "shortlisted", "skipped"]

    opened.clear()
    cli.cmd_apply(SimpleNamespace(job_ids=[], limit=10, dry_run=True), Settings(database_url=TEST_DB),
                  open_url=opened.append, ask=lambda prompt: "y")
    assert opened == []  # a dry run opens nothing
