"""How each site has done in recent searches, and switching off the ones that keep failing."""

from jobagent import db
from jobagent.config import AgentConfig

from test_settings_page import call, serve


def searches(conn, outcomes):
    """One search per row of `outcomes`: site name -> a number of jobs, or a reason it failed."""
    ids = {}
    for row in outcomes:
        run = db.start_run(conn, None, {})
        for name, what in row.items():
            ids.setdefault(name, db.upsert_source(conn, "greenhouse", name, f"https://x/{name}", {}))
            if isinstance(what, int):
                db.log_event(conn, run, f"{name}: {what} jobs (0 new)", source_id=ids[name])
            else:
                db.log_event(conn, run, f"{name}: failed: {what}", level="error", source_id=ids[name])
                db.log_event(conn, run, f"{name}: detail fetch failed for one page", level="error", source_id=ids[name])  # not an outcome
        db.finish_run(conn, run, status="succeeded", stats={})


def test_site_health_is_read_from_what_each_search_wrote_down(conn):
    searches(conn, [
        {"Steady": 12, "Fading": 9, "Refused": 40, "Flaky": 5},
        {"Steady": 14, "Fading": 0, "Refused": "the site refused this browser (error 403)", "Flaky": "timeout"},
        {"Steady": 11, "Fading": 0, "Refused": "the site refused this browser (error 403)", "Flaky": 6},
        {"Steady": 13, "Fading": 0, "Refused": "the site refused this browser (error 403)\nmore"},
    ])
    health = db.site_health(conn)
    assert {k: (v["last"], v["dry"], v["searches"]) for k, v in health.items()} == {
        "Steady": ("listed", 0, 4), "Fading": ("empty", 3, 4), "Refused": ("failed", 3, 4), "Flaky": ("listed", 0, 3)}
    assert health["Refused"]["reason"] == "the site refused this browser (error 403)" and health["Steady"]["reason"] == ""
    assert health["Fading"]["delivered_at"] is not None and health["Refused"]["delivered_at"] is not None
    assert db.site_health(conn, days=0) == {}


def test_the_page_lists_health_with_each_site_and_can_switch_several_off(conn, tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("sources:\n" + "".join(f"  - {{kind: greenhouse, name: {n}, board: {n.lower()}}}\n" for n in ("Steady", "Fading", "Refused", "Never")))
    searches(conn, [{"Steady": 3, "Fading": 0, "Refused": "error 403"}] * 3)
    server = serve(str(f))
    try:
        sites = {s["name"]: s for s in call(server, "/api/config")[1]["sites"]}
        assert sites["Refused"]["health"]["last"] == "failed" and sites["Fading"]["health"]["dry"] == 3
        assert sites["Steady"]["health"]["dry"] == 0 and sites["Never"]["health"] is None  # never searched: nothing to say
        code, r = call(server, "/api/config", {"sites": {"Fading": False, "Refused": False}})
        assert code == 200 and [s.enabled for s in AgentConfig.load(f).sources] == [True, False, False, True]
        assert {s["name"]: s["health"]["last"] if s["health"] else None for s in r["sites"]}["Refused"] == "failed"
    finally:
        server.shutdown()
        server.server_close()
