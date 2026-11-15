"""Settings changed on the page: kept beside config.yaml, which is never rewritten."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from jobagent import web
from jobagent.config import AgentConfig, ConfigError, Settings, overrides_path, read_settings, write_settings

from conftest import TEST_DB

CONFIG = """# my own notes stay here
search:
  max_age_days: 14          # two weeks
  include_title_keywords: [java, backend]
  locations: [Dubai, India]
sources:
  - {kind: greenhouse, name: Acme, board: acme}
  # switched off by hand
  - {kind: generic, name: Naukrigulf, urls: ["https://x.example/jobs"], enabled: false}
"""


@pytest.fixture
def cfg_file(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(CONFIG)
    return f


def test_page_settings_are_kept_beside_the_file_which_is_never_rewritten(cfg_file):
    info = write_settings(cfg_file, {"search.max_age_days": "7", "search.include_title_keywords": "java, Spring Boot, JAVA",
                                     "matching.shortlist_min_score": 75, "outreach.notice_period": " immediately "},
                          {"Naukrigulf": True})
    assert cfg_file.read_text() == CONFIG  # comments and layout untouched
    # 75 is what config.yaml already means, so it is not stored; the list drops its repeat.
    assert info["changed"] == 4
    stored = overrides_path(cfg_file).read_text()
    assert "max_age_days: 7" in stored and "shortlist_min_score" not in stored and stored.startswith("# Settings changed")

    cfg = AgentConfig.load(cfg_file)  # every command reads both files
    assert cfg.search.max_age_days == 7 and cfg.search.include_title_keywords == ["java", "Spring Boot"]
    assert cfg.outreach.notice_period == "immediately" and [s.enabled for s in cfg.sources] == [True, True]
    assert cfg.search.locations == ["Dubai", "India"]  # what was not changed still comes from config.yaml

    by_key = {f["key"]: f for f in read_settings(cfg_file)["fields"]}
    assert by_key["search.max_age_days"] == {**by_key["search.max_age_days"], "value": 7, "file_value": 14, "changed": True}
    assert by_key["search.locations"]["changed"] is False
    assert [(s["name"], s["enabled"], s["changed"]) for s in read_settings(cfg_file)["sites"]] == \
        [("Acme", True, False), ("Naukrigulf", True, True)]

    # Putting a value back to config.yaml's, or sending nothing for it, removes the override.
    info = write_settings(cfg_file, {"search.max_age_days": 14, "search.include_title_keywords": None,
                                     "outreach.notice_period": ""}, {"Naukrigulf": None})
    assert info["changed"] == 0 and not overrides_path(cfg_file).exists()
    assert AgentConfig.load(cfg_file).sources[1].enabled is False


@pytest.mark.parametrize("values, sites, said", [
    ({"search.max_age_days": "0"}, {}, "Oldest posting, in days: must be between 1 and 365."),
    ({"matching.shortlist_min_score": "high"}, {}, "Shortlist from score: 'high' is not a whole number."),
    ({"matching.max_jobs_to_score": ""}, {}, "Most jobs scored in one search: a number is needed."),
    ({"matching.max_tokens_per_run": "-5"}, {}, "AI budget for one search, in tokens: must be 0 or more."),
    ({"search.remote_ok": "yes"}, {}, "Keep remote jobs: choose on or off."),
    ({"sources": []}, {}, "That setting cannot be changed here."),
    ({}, {"Nowhere": False}, "There is no site called 'Nowhere' in config.yaml."),
])
def test_a_setting_that_cannot_be_right_is_refused_and_nothing_is_written(cfg_file, values, sites, said):
    with pytest.raises(ConfigError) as e:
        write_settings(cfg_file, values, sites)
    assert str(e.value) == said and not overrides_path(cfg_file).exists()


def test_an_empty_box_means_not_set_where_that_is_allowed(cfg_file):
    write_settings(cfg_file, {"search.max_age_days": "", "search.min_salary_lpa": "20"})
    cfg = AgentConfig.load(cfg_file)
    assert cfg.search.max_age_days is None and cfg.search.min_salary_lpa == 20


def test_a_damaged_overrides_file_is_explained(cfg_file):
    overrides_path(cfg_file).write_text("search: [unclosed")
    with pytest.raises(ConfigError, match="could not be read"):
        AgentConfig.load(cfg_file)


def call(server, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{path}", data=data,
                                 headers={"X-Token": server.token})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def serve(config_path):
    server = web.serve(Settings(database_url=TEST_DB), AgentConfig(), 0, config_path=config_path)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_page_reads_and_saves_settings(conn, cfg_file):
    server = serve(str(cfg_file))
    try:
        code, info = call(server, "/api/config")
        assert code == 200 and info["file"] == "config.yaml" and len(info["sites"]) == 2
        assert call(server, "/api/state")[1]["sources"] == ["Acme"]

        code, r = call(server, "/api/config", {"sites": {"Naukrigulf": True}})
        assert code == 200 and r["message"] == "Naukrigulf is switched on."
        assert call(server, "/api/state")[1]["sources"] == ["Acme", "Naukrigulf"]  # in effect at once

        code, r = call(server, "/api/config", {"values": {"search.max_age_days": 3}})
        assert r["message"] == "Settings saved. 2 differ from config.yaml."
        assert call(server, "/api/state")[1]["search"]["max_age_days"] == 3

        code, r = call(server, "/api/config", {"values": {"search.max_age_days": "soon"}})
        assert code == 400 and r["error"] == "Oldest posting, in days: 'soon' is not a whole number."
        assert call(server, "/api/config", {"values": []})[0] == 400
        assert cfg_file.read_text() == CONFIG
    finally:
        server.shutdown()
        server.server_close()


def test_without_a_settings_file_the_page_says_so(conn):
    server = serve(None)
    try:
        code, r = call(server, "/api/config")
        assert code == 400 and "no config.yaml was found" in r["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_a_job_board_can_name_the_browser_it_is_read_with(conn, cfg_file):
    assert [s.browser for s in AgentConfig.load(cfg_file).sources] == ["", ""]  # none named: the one in .env reads them all
    info = write_settings(cfg_file, browsers={"Naukrigulf": "browserbase"})
    board = info["sites"][1]
    assert (board["uses_browser"], board["browser"], board["browser_changed"], board["enabled"]) == (True, "browserbase", True, False)
    assert info["sites"][0]["uses_browser"] is False and info["changed"] == 1
    assert [s.browser for s in AgentConfig.load(cfg_file).sources] == ["", "browserbase"]

    # The switch and the browser of one site are kept side by side, and each can go back on its own.
    write_settings(cfg_file, sites={"Naukrigulf": True})
    chosen = AgentConfig.load(cfg_file).sources[1]
    assert (chosen.enabled, chosen.browser) == (True, "browserbase")
    write_settings(cfg_file, browsers={"Naukrigulf": ""})
    chosen = AgentConfig.load(cfg_file).sources[1]
    assert (chosen.enabled, chosen.browser) == (True, "") and "browser" not in overrides_path(cfg_file).read_text()
    write_settings(cfg_file, sites={"Naukrigulf": None})
    assert not overrides_path(cfg_file).exists() and cfg_file.read_text() == CONFIG

    for browsers, said in (({"Acme": "browserbase"}, "Acme is read without a browser, so there is none to choose."),
                           ({"Naukrigulf": "firefox"}, "Naukrigulf: choose the browser on this Mac or Browserbase."),
                           ({"Nowhere": "local"}, "There is no site called 'Nowhere' in config.yaml.")):
        with pytest.raises(ConfigError) as e:
            write_settings(cfg_file, browsers=browsers)
        assert str(e.value) == said
    assert not overrides_path(cfg_file).exists()

    server = serve(str(cfg_file))
    try:
        assert call(server, "/api/settings")[1]["browser"] == {"kind": "browserbase", "hosted": [], "boards": 0, "key": False, "ready": True}
        code, r = call(server, "/api/config", {"browsers": {"Naukrigulf": "local"}})
        assert code == 200 and r["message"] == "Naukrigulf is read with the browser on this Mac."
        code, r = call(server, "/api/config", {"browsers": {"Naukrigulf": "browserbase"}, "sites": {"Naukrigulf": True}})
        assert code == 200 and r["sites"][1]["browser"] == "browserbase"
        # Browserbase is named but there is no key: Setup says so.
        assert call(server, "/api/settings")[1]["browser"] == {"kind": "browserbase", "hosted": ["Naukrigulf"], "boards": 1, "key": False, "ready": False}
        assert call(server, "/api/config", {"browsers": {"Acme": "local"}})[1]["error"] == "Acme is read without a browser, so there is none to choose."
        assert call(server, "/api/config", {"browsers": ["Naukrigulf"]})[0] == 400
    finally:
        server.shutdown()
        server.server_close()
