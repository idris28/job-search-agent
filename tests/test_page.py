"""The page itself, driven in a real browser: every screen, the job table and panel, tasks,
settings, live updates and what it says when something is missing.

Needs Playwright with its Chromium (`playwright install chromium`) and TEST_DATABASE_URL;
skipped without them. No task here runs a real `jsa` command: a short stand-in prints lines.
"""

import json
import re
import sys
import threading
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from jobagent import db, web
from jobagent.config import AgentConfig, Settings, overrides_path
from jobagent.models import JobPosting, MatchResult

from conftest import TEST_DB

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

CONFIG = """search:
  max_age_days: 14
  locations: [India, UAE]
sources:
  - {kind: greenhouse, name: Alpha, board: alpha}
  - {kind: greenhouse, name: Beta, board: beta}
"""
QUICK = "import time\nprint('Naukri: 24 listings read', flush=True)\ntime.sleep(0.5)\nprint('Run #9: finished, 24 jobs found', flush=True)"
SLOW = "import time\nprint('Searching', flush=True)\ntime.sleep(60)"
PLACES = ["Dubai, UAE", "Ahmedabad, India", "Riyadh, Saudi Arabia", "Doha, Qatar"]
SCREENS = [("shortlist", "Shortlist"), ("progress", "In progress"), ("followups", "Follow-ups"), ("matches", "All matches"),
           ("insights", "Insights"), ("activity", "Activity"), ("settings", "Settings")]


@pytest.fixture(scope="module")
def chromium():
    if not TEST_DB:
        pytest.skip("set TEST_DATABASE_URL to run database tests")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {str(e).splitlines()[0]}")
        yield browser
        browser.close()


class Site:
    """The program running on the test database, and one browser tab open on it."""

    def __init__(self, browser, folder, *, width=1440, height=900):
        self.config = folder / "config.yaml"
        self.config.write_text(CONFIG)
        self.server = web.serve(Settings(database_url=TEST_DB), AgentConfig.load(self.config), 0, config_path=str(self.config))
        self.server.runner.command = lambda argv: [sys.executable, "-u", "-c", SLOW if argv[0] == "daily" else QUICK]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.context = browser.new_context(viewport={"width": width, "height": height})
        # Nothing outside this Mac is fetched (the page asks for its fonts): the tests work offline.
        self.context.route(lambda url: not url.startswith(self.base), lambda route: route.fulfill(status=200, content_type="text/css", body=""))
        self.page = self.context.new_page()
        self.problems, self.asked = [], []
        self.page.on("console", lambda m: self.problems.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.problems.append(str(e)))
        self.page.on("request", lambda r: self.asked.append(r.url[len(self.base):]))
        self.page.goto(self.base + "/")
        expect(self.page.locator("#vsub")).not_to_have_text("Starting up")

    def close(self):
        self.context.close()
        self.server.runner.stop()
        self.server.feed.close()
        self.server.shutdown()
        self.server.server_close()

    def show(self, view):
        """Open a screen from the menu, opening the menu first where the window is narrow."""
        menu = self.page.locator(".menu-btn")
        if menu.is_visible():
            menu.click()
        self.page.locator(f"#tabs [data-view={view}]").click()

    def toast(self, text, bad=False):
        expect(self.page.locator(".toast.bad" if bad else ".toast:not(.bad)").filter(has_text=text).first).to_be_visible()

    def confirm(self, title, button):
        """Answer yes in the "are you sure" box, after checking it is the one expected."""
        box = self.page.locator("#ask")
        expect(box.locator("h2")).to_have_text(title)
        expect(box.locator("button.primary")).to_have_text(button)
        box.locator("button.primary").click()

    def live(self):
        """Wait until the page is being sent updates, instead of asking for them."""
        self.page.wait_for_function("S.live === true")

    def post(self, path, body):
        request = urllib.request.Request(self.base + path, json.dumps(body).encode(),
                                         {"X-Token": self.server.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(request) as r:
            return json.loads(r.read())

    def sideways(self):
        """How far the page can be scrolled sideways; anything above 0 means something sticks out."""
        return self.page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")

    def refusals(self):
        """Requests the program refused on purpose show up as console errors; everything else is a fault."""
        refused = [p for p in self.problems if "Failed to load resource" in p and "status of 4" in p]
        assert [p for p in self.problems if p not in refused] == []
        return len(refused)


@pytest.fixture
def open_site(conn, chromium, tmp_path):
    opened = []

    def make(**how):
        opened.append(Site(chromium, tmp_path, **how))
        return opened[-1]

    yield make
    for site in opened:
        site.close()


def seed(conn, n=3):
    pid = db.save_profile(conn, "Alex Morgan", "resume", {})
    found_on = db.upsert_source(conn, "greenhouse", "Alpha", "https://boards.greenhouse.io/alpha", {})  # found by a search
    now, ids = datetime.now(timezone.utc), []
    for i in range(n):
        jid, _ = db.upsert_job(conn, JobPosting(title=f"Java Engineer {i + 1:02d}", company=f"Company {i + 1:02d}",
                                                url=f"https://example.com/jobs/{i}", location=PLACES[i % 4],
                                                description="Build Java services.", posted_at=now - timedelta(hours=3 + i)), found_on, None)
        db.save_match(conn, pid, jid, None, MatchResult(score=95 - i, verdict="strong", summary="Six years of Java fit this role.",
                                                        matched_skills=["Java"], missing_skills=["Kafka"], red_flags=[]), "m", "h")
        db.set_application_status(conn, pid, jid, "shortlisted")
        ids.append(jid)
    return pid, ids


def draft(conn, pid, jid, to="careers@acme.example"):
    db.save_outreach(conn, pid, jid, subject="Java Engineer | 6 yrs Java", body="Dear Hiring Team,\n\n**Key skills:** Java\n\nBest regards,\nAlex",
                     recruiter_name=None, contact_email=to, still_open=True, follow_up_subject="Re: Java Engineer",
                     follow_up_body="Following up on my application.")


@pytest.mark.parametrize("width", [1440, 390])
def test_every_screen_opens_without_a_fault_on_a_wide_and_a_narrow_window(conn, open_site, width):
    pid, ids = seed(conn, 12)
    draft(conn, pid, ids[0])
    db.set_application_status(conn, pid, ids[1], "applied")
    site = open_site(width=width, height=900 if width > 800 else 844)
    page = site.page
    for view, title in SCREENS:
        site.show(view)
        expect(page.locator("#vtitle")).to_have_text(title)
        expect(page.locator(f"#tabs [data-view={view}]")).to_have_attribute("aria-current", "page")
        if view in ("insights", "activity", "settings"):
            expect(page.locator("#page .card").first).to_be_visible()
            expect(page.locator("#page")).not_to_contain_text("Loading")
            expect(page.locator("#work")).to_be_hidden()
        else:
            expect(page.locator("#tbody")).not_to_contain_text("Loading")
            expect(page.locator("#tbody tr").first).to_be_visible()
        assert site.sideways() <= 0, f"{title} can be scrolled sideways at {width} wide"
    # The numbers along the top are the stored ones.
    site.show("shortlist")
    expect(page.locator('#stats [data-n="shortlisted"] b')).to_have_text("11")
    expect(page.locator('#stats [data-n="applied"] b')).to_have_text("1")
    expect(page.locator("#tbody tr.row")).to_have_count(8)
    # A job's panel fits the window too.
    page.locator(f'tr.row[data-job="{ids[0]}"]').click()
    expect(page.locator("#detail h2")).to_have_text("Java Engineer 01")
    expect(page.locator("#subj")).to_have_value("Java Engineer | 6 yrs Java")
    assert site.sideways() <= 0
    assert site.refusals() == 0


def test_the_job_table_searches_filters_sorts_and_pages(conn, open_site):
    seed(conn, 20)
    site = open_site()
    page, rows, foot = site.page, site.page.locator("#tbody tr.row"), site.page.locator("#tfoot")
    expect(page.locator("#tcount")).to_have_text("20")
    expect(rows).to_have_count(8)
    expect(foot).to_contain_text("Showing 1 to 8 of 20 jobs")
    foot.locator('[aria-label="Next page"]').click()
    expect(foot).to_contain_text("Showing 9 to 16 of 20 jobs")
    expect(foot.locator('[aria-current="page"]')).to_have_text("2")

    page.fill("#tq", "engineer 07")  # the search looks at title, company, place and address, in any case
    expect(rows).to_have_count(1)
    expect(rows.locator(".jt b")).to_have_text("Java Engineer 07")
    expect(page.locator("#tcount")).to_have_text("1 of 20")
    page.fill("#tq", "")

    page.select_option("#f-country", "UAE")
    expect(page.locator("#tcount")).to_have_text("5 of 20")
    expect(page.locator("#tbody td.loc")).to_have_text(["Dubai, UAE"] * 5)
    page.select_option("#f-score", "90")  # 95, 91 and 87, 83, 79 are in the UAE; two reach 90
    expect(rows).to_have_count(2)
    page.select_option("#f-country", "")
    page.select_option("#f-score", "0")

    score = page.locator('th[data-sort="score"]')
    score.click()  # a score is most useful highest first
    expect(score).to_have_attribute("aria-sort", "descending")
    expect(rows.first.locator(".sc b")).to_have_text("95")
    score.click()
    expect(score).to_have_attribute("aria-sort", "ascending")
    expect(rows.first.locator(".sc b")).to_have_text("76")
    page.locator('th[data-sort="title"]').click()
    expect(rows.first.locator(".jt b")).to_have_text("Java Engineer 01")

    page.fill("#tq", "no such job")
    expect(page.locator("#tbody .empty h3")).to_have_text("No job matches these filters")
    page.locator('#tbody [data-act="clear"]').click()
    expect(page.locator("#tcount")).to_have_text("20")
    expect(page.locator("#tq")).to_have_value("")
    assert site.refusals() == 0


def test_a_job_panel_saves_a_note_and_a_draft_and_moves_the_job_on(conn, open_site):
    pid, ids = seed(conn, 3)
    draft(conn, pid, ids[0])
    site = open_site()
    page, panel = site.page, site.page.locator("#detail")
    stored = lambda column, jid=ids[0]: conn.execute(f"SELECT {column} AS v FROM applications WHERE job_id = %s", (jid,)).fetchone()["v"]  # noqa: E731

    page.locator(f'tr.row[data-job="{ids[0]}"]').click()
    expect(page.locator("body")).to_have_class(re.compile(r"\breading\b"))
    expect(panel.locator("h2")).to_have_text("Java Engineer 01")
    expect(panel.locator(".d-score b")).to_have_text("95")
    expect(panel.locator("#addr")).to_have_value("careers@acme.example")

    page.fill("#note", "Call Priya on Thursday")
    panel.locator('[data-act="save-note"]').click()
    site.toast("Note saved")
    page.wait_for_function("S.detail && S.detail.application.notes === 'Call Priya on Thursday'")
    assert stored("notes") == "Call Priya on Thursday"

    page.fill("#subj", "Java Engineer | available now")
    panel.locator('[data-act="save-draft"]').click()
    site.toast("Draft saved")
    page.wait_for_function("S.detail.application.outreach_subject === 'Java Engineer | available now'")
    assert stored("outreach_subject") == "Java Engineer | available now"

    # The same email as the recruiter will see it, and back to the text.
    panel.locator('[data-act="sheet"][data-to="preview"]').click()
    expect(panel.locator("#sheet")).to_have_class(re.compile(r"\bpreview\b"))
    expect(panel.locator("#sheet .rendered")).to_be_visible()
    expect(panel.locator("#sheet .rendered b, #sheet .rendered strong").first).to_have_text("Key skills:")
    panel.locator('[data-act="sheet"][data-to="edit"]').click()
    expect(panel.locator("#body")).to_be_visible()

    panel.locator('[data-act="status"][data-to="applied"]').click()
    site.toast(f"#{ids[0]} marked applied")
    expect(panel.locator(".d-bar .tag")).to_have_text("Applied")
    assert stored("status") == "applied"
    page.keyboard.press("Escape")
    expect(page.locator("body")).not_to_have_class(re.compile(r"\breading\b"))
    expect(page.locator("#tbody tr.row")).to_have_count(2)
    site.show("progress")
    expect(page.locator(f'tr.row[data-job="{ids[0]}"] .tag')).to_have_text("Applied")

    # Typed text is not thrown away without asking.
    site.show("shortlist")
    page.locator(f'tr.row[data-job="{ids[1]}"]').click()
    expect(panel.locator("h2")).to_have_text("Java Engineer 02")
    page.fill("#note", "half a thought")
    page.keyboard.press("Escape")
    expect(page.locator("#ask")).to_be_visible()
    expect(page.locator("#ask h2")).to_have_text("Close without saving?")
    page.locator('#ask [value="no"]').click()
    expect(page.locator("#note")).to_have_value("half a thought")
    panel.locator('[data-act="back"]').click()
    site.confirm("Close without saving?", "Close")
    expect(page.locator("body")).not_to_have_class(re.compile(r"\breading\b"))
    assert stored("notes", ids[1]) in (None, "")
    assert site.refusals() == 0


def test_hr_addresses_are_added_listed_and_can_be_deleted(conn, open_site):
    seed(conn, 2)
    site = open_site()
    page = site.page
    page.locator('.sidebar [data-act="hr"]').click()
    expect(page.locator("#hrdlg")).to_be_visible()
    page.locator('#hrdlg [data-act="hr-go"]').click()
    expect(page.locator("#hrresult")).to_contain_text("Paste at least one email address")
    page.fill("#hrtext", "Acme Gulf, hr@acme.sa\nthis line has no address")
    page.locator('#hrdlg [data-act="hr-go"]').click()
    expect(page.locator("#hrresult")).to_contain_text("Added 1 general application, skipped 1")
    expect(page.locator("#hrresult li")).to_contain_text("this line has no address")
    expect(page.locator("#hrtext")).to_have_value("this line has no address")  # what was not taken stays, to be corrected
    page.locator('#hrdlg [data-act="close-hr"]').click()

    expect(page.locator("#tcount")).to_have_text("3")
    page.select_option("#f-extra", "general")
    row = page.locator("#tbody tr.row")
    expect(row).to_have_count(1)
    expect(row.locator(".jt b")).to_have_text("Acme Gulf")
    expect(row.locator(".jt small")).to_have_text("hr@acme.sa")
    row.click()
    expect(page.locator("#addr")).to_have_value("hr@acme.sa")
    page.locator('#detail [data-act="delete"]').click()
    site.confirm("Delete this entry?", "Delete entry")
    site.toast("Entry deleted")
    expect(page.locator("body")).not_to_have_class(re.compile(r"\breading\b"))
    expect(page.locator("#tcount")).to_have_text("0 of 2")
    assert conn.execute("SELECT count(*) AS n FROM jobs WHERE url LIKE 'general:%%'").fetchone()["n"] == 0
    # A job found by a search has no such button: only what you added yourself can be deleted.
    page.locator('#tbody [data-act="clear"]').click()
    page.locator("#tbody tr.row").first.click()
    expect(page.locator("#detail h2")).to_contain_text("Java Engineer")
    expect(page.locator('#detail [data-act="delete"]')).to_have_count(0)
    assert site.refusals() == 0


def test_a_task_shows_its_progress_as_it_happens_and_can_be_stopped(conn, open_site):
    seed(conn, 2)
    site = open_site()
    page, live = site.page, site.page.locator("#live")
    site.live()
    expect(live).to_be_hidden()
    page.locator('.split > [data-act="run"]').click()
    expect(live.locator("b")).to_have_text("Find new jobs")
    expect(live.locator(".line")).to_have_text("Naukri: 24 listings read")
    expect(live.locator("b")).to_have_text("Find new jobs: done")
    expect(live.locator(".line")).to_have_text("Run #9: finished, 24 jobs found")
    live.locator('[data-view="activity"]').click()
    expect(page.locator("#vtitle")).to_have_text("Activity")
    expect(page.locator("#taskout")).to_have_text("Naukri: 24 listings read\nRun #9: finished, 24 jobs found")
    # The lines were sent to the page; it did not have to keep asking for them.
    assert page.evaluate("S.live") is True
    assert [u for u in site.asked if u.startswith("/api/task?since=") and u != "/api/task?since=0"] == []

    page.locator('.sidebar [data-act="daily"]').click()
    expect(live.locator("b")).to_have_text("Morning routine")
    expect(page.locator("#taskout")).to_have_text("Searching")
    page.locator('.split > [data-act="run"]').click()  # one task at a time
    site.toast('"Morning routine" is still running', bad=True)
    live.locator('[data-act="stop"]').click()
    site.confirm("Stop this task?", "Stop the task")
    expect(live.locator("b")).to_have_text("Morning routine: stopped")
    live.locator('[data-act="dismiss"]').click()
    expect(live).to_be_hidden()
    assert site.refusals() == 1


def test_settings_are_changed_on_the_page_and_kept_beside_the_file(conn, open_site):
    seed(conn, 2)
    site = open_site()
    page = site.page
    age = page.locator('[data-cfg="search.max_age_days"]')
    now = lambda: AgentConfig.load(site.config)  # noqa: E731
    expect(page.locator("#chips")).to_contain_text("last 14 days")
    site.show("settings")
    expect(age).to_have_value("14")
    expect(page.locator('[data-cfg="matching.prescreen_model"]')).to_have_value("")
    expect(page.locator('[data-cfg="matching.reader_model"]')).to_have_value("")
    expect(page.locator('[data-cfg="matching.batch_scoring"]')).not_to_be_checked()

    age.fill("7")
    page.locator('[data-act="cfg-save"]').click()
    site.toast("Settings saved. 1 differs from config.yaml.")
    expect(age).to_have_value("7")
    expect(page.locator(".fld", has=age).locator(".chg")).to_have_text("changed")
    expect(page.locator("#chips")).to_contain_text("last 7 days")
    assert now().search.max_age_days == 7 and overrides_path(site.config).exists()
    assert site.config.read_text() == CONFIG  # the file you wrote is never rewritten

    age.fill("soon")
    page.locator('[data-act="cfg-save"]').click()
    site.toast("Oldest posting, in days: 'soon' is not a whole number", bad=True)
    assert now().search.max_age_days == 7

    beta = page.locator('input[data-site="Beta"]')
    expect(page.locator("#sitecount")).to_have_text("2 of 2 on")
    beta.uncheck()
    site.toast("Beta is switched off")
    expect(page.locator("#sitecount")).to_have_text("1 of 2 on")
    expect(page.locator(".sw", has=beta)).to_have_class(re.compile(r"\bchanged\b"))
    assert [s.enabled for s in now().sources] == [True, False]
    page.fill("#sitefind", "alp")
    expect(page.locator(".sw", has=beta)).to_be_hidden()
    expect(page.locator('.sw:has(input[data-site="Alpha"])')).to_be_visible()

    page.locator('[data-act="cfg-reset"]').click()
    site.confirm("Go back to config.yaml?", "Go back")
    expect(age).to_have_value("14")
    expect(page.locator('[data-act="cfg-reset"]')).to_have_count(0)  # nothing left to go back from
    expect(page.locator(".fld .chg")).to_have_count(0)
    assert now().search.max_age_days == 14 and [s.enabled for s in now().sources] == [True, False]  # site switches stay

    backup = page.locator('[data-act="backup"]')
    if backup.count():  # shown where pg_dump is installed; the stand-in command runs, not a real backup
        backup.click()
        expect(page.locator("#live b")).to_have_text("Back up now: done")
    assert site.refusals() == 1


def test_a_change_made_elsewhere_reaches_an_open_page_at_once(conn, open_site):
    _, ids = seed(conn, 3)
    site = open_site()
    page = site.page
    site.live()
    expect(page.locator("#tbody tr.row")).to_have_count(3)
    asked = len([u for u in site.asked if u == "/api/state"])
    site.post("/api/status", {"job_id": ids[0], "status": "skipped"})  # as another open tab would
    # Well inside the six seconds the page used to wait before it asked again.
    expect(page.locator("#tbody tr.row")).to_have_count(2, timeout=3000)
    expect(page.locator('#tabs [data-c="shortlisted"]')).to_have_text("2")
    assert len([u for u in site.asked if u == "/api/state"]) == asked + 1  # told once, asked once
    assert site.refusals() == 0


def test_the_search_box_for_actions_and_the_light_look(conn, open_site):
    seed(conn, 1)
    site = open_site()
    page = site.page
    page.keyboard.press("Control+k")
    expect(page.locator("#palette")).to_be_visible()
    page.fill("#pq", "missing skills")
    expect(page.locator("#plist button")).to_have_count(1)
    page.keyboard.press("Enter")
    expect(page.locator("#vtitle")).to_have_text("Insights")
    expect(page.locator("#palette")).to_be_hidden()

    assert page.locator("html").get_attribute("data-theme") == "dark"
    page.locator("#th-light").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.reload()
    expect(page.locator("#vsub")).not_to_have_text("Starting up")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")  # remembered
    expect(page.locator("#th-light")).to_have_attribute("aria-pressed", "true")
    assert site.refusals() == 0


def test_the_page_says_what_is_missing_instead_of_failing(conn, open_site):
    site = open_site()  # no resume imported yet
    page = site.page
    expect(page.locator("#notices")).to_contain_text("Import your resume to begin")
    expect(page.locator("#tbody .empty")).to_contain_text("Finish the setup step at the top first")
    page.locator('.split > [data-act="run"]').click()
    site.toast("Import your resume first, in Settings", bad=True)
    expect(page.locator("#live")).to_be_hidden()
    site.show("settings")
    expect(page.locator('.check:has(b:text-is("Resume"))')).to_contain_text("Not imported yet")

    # A database one update behind: the page says so and offers the update, and starts nothing else.
    db.save_profile(conn, "Alex Morgan", "resume", {})
    conn.execute("DELETE FROM schema_migrations WHERE name = (SELECT max(name) FROM schema_migrations)")
    page.reload()
    expect(page.locator("#notices")).to_contain_text("The database needs one update")
    expect(page.locator('#notices [data-act="migrate"]')).to_have_text("Update the database")
    page.locator('.split > [data-act="run"]').click()
    site.toast("The database needs an update first. Use the button at the top of the page.", bad=True)
    assert site.refusals() >= 2
