from jobagent import db
from jobagent.config import AgentConfig, MatchingPrefs, SearchPrefs, SourceConfig
from jobagent.pipeline import run_agent

from conftest import FakeBrowser, FakeLLM, mock_http


def gh(*jobs):
    return {"jobs": [{"id": i, "title": t, "absolute_url": f"https://gh/{i}",
                      "location": {"name": loc}, "content": f"desc {t}"}
                     for i, (t, loc) in enumerate(jobs)]}


def make_cfg(**match):
    return AgentConfig(
        search=SearchPrefs(locations=["Dubai", "India"], include_title_keywords=["java", "backend"]),
        matching=MatchingPrefs(shortlist_min_score=75, **match),
        sources=[SourceConfig(kind="greenhouse", name="Acme", board="acme"),
                 SourceConfig(kind="greenhouse", name="Broken", board="broken")],
    )


def test_full_run(conn):
    db.save_profile(conn, "Alex", "resume", {"primary_skills": ["Java"]})
    http = mock_http({"boards-api.greenhouse.io/v1/boards/acme/jobs": gh(
        ("Senior Java Engineer", "Dubai"),
        ("Backend Engineer", "Pune, India"),
        ("Java Engineer", "Berlin"),          # filtered: location
        ("Designer", "Dubai"),                # filtered: title
        ("Backend Engineer II", "Dubai"),     # scoring error
    )})
    llm = FakeLLM(scores={"Senior Java Engineer": 90, "Backend Engineer": 60,
                          "Backend Engineer II": "boom"})
    s = run_agent(conn, make_cfg(), llm, FakeBrowser({}), http=http)

    assert s.status == "partial" and "Broken" in s.source_errors
    assert (s.found, s.new, s.filtered, s.scored, s.shortlisted) == (5, 5, 2, 2, 1)
    pid = db.active_profile(conn)["id"]
    top = db.top_matches(conn, pid, min_score=0)
    assert [r["title"] for r in top] == ["Senior Java Engineer", "Backend Engineer"]
    assert top[0]["application_status"] == "shortlisted"
    run = db.list_runs(conn)[0]
    assert run["status"] == "partial" and run["jobs_scored"] == 2 and run["tokens_used"] == 200

    # Second run: nothing changed -> no re-scoring, nothing new, status not overridden.
    db.set_application_status(conn, pid, top[0]["job_id"], "applied", "sent CV")
    llm2 = FakeLLM(scores={"Backend Engineer II": 80})
    s2 = run_agent(conn, make_cfg(), llm2, FakeBrowser({}), http=http, only_source="Acme")
    assert s2.status == "succeeded" and s2.new == 0
    assert llm2.scored_titles == ["Backend Engineer II"]  # only the one that failed before
    assert s2.skipped_unchanged == 2
    statuses = {r["title"]: r["status"] for r in db.list_applications(conn, pid)}
    assert statuses == {"Senior Java Engineer": "applied", "Backend Engineer II": "shortlisted"}
    events = conn.execute("SELECT to_status FROM application_events ORDER BY id").fetchall()
    assert [e["to_status"] for e in events] == ["shortlisted", "applied", "shortlisted"]


def test_score_cap(conn):
    db.save_profile(conn, "Alex", "resume", {})
    http = mock_http({"boards-api.greenhouse.io/v1/boards/acme/jobs":
                      gh(*[(f"Java Engineer {i}", "Dubai") for i in range(5)])})
    llm = FakeLLM()
    s = run_agent(conn, make_cfg(max_jobs_to_score=2), llm, FakeBrowser({}), http=http,
                  only_source="Acme")
    assert s.scored == 2 and len(llm.scored_titles) == 2


def test_migrate_idempotent(conn):
    assert db.migrate(conn) == []
