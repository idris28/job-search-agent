"""The website reached from your phone through Tailscale: it answers to the Mac's Tailscale name only
when that name is set, and still needs the page's key for everything else."""

from jobagent import db
from jobagent.config import Settings, web_hosts

from conftest import TEST_DB
from test_web import Page

NAME = "alex-mac.tail1234.ts.net"


def test_the_names_are_read_as_a_browser_sends_them():
    assert web_hosts(f" https://{NAME.upper()}/ , {NAME}:443, http://other.example:8765/path ,, bad name!") == [NAME, "other.example"]
    assert web_hosts("") == []


def test_the_mac_reads_the_names_from_env(monkeypatch):
    monkeypatch.setenv("JOBAGENT_WEB_HOSTS", f"https://{NAME}")
    assert Settings.from_env().web_hosts == [NAME]
    monkeypatch.delenv("JOBAGENT_WEB_HOSTS")
    assert Settings.from_env().web_hosts == []


def test_the_page_answers_to_the_tailscale_name_only_when_it_is_set(conn):
    db.save_profile(conn, "Alex Morgan", "resume", {})
    closed, opened = Page(), Page(settings=Settings(database_url=TEST_DB, web_hosts=[NAME]))
    try:
        for host, page, code in ((NAME, closed, 403), ("127.0.0.1", closed, 200), (NAME, opened, 200), (NAME.upper() + ":443", opened, 200),
                                 ("evil.example", opened, 403), ("127.0.0.1", opened, 200)):
            assert page.call("/api/state", headers={"Host": host})[0] == code, (host, code)
        assert opened.call("/api/state", headers={"Host": NAME}, token="wrong")[0] == 403  # the name alone is not enough
        assert opened.call("/api/settings")[1]["phone"] == [f"https://{NAME}"]
        assert closed.call("/api/settings")[1]["phone"] == []
    finally:
        closed.close()
        opened.close()
