from jobagent.browser import PageContent
from jobagent.config import ConfigError, SourceConfig
from jobagent.sources import SourceContext, build_source
from jobagent.sources.base import html_to_text

import pytest

from conftest import FakeBrowser, FakeLLM, mock_http

GH = {"jobs": [{
    "id": 101, "title": "Senior Java Engineer ", "absolute_url": "https://boards.greenhouse.io/acme/jobs/101",
    "location": {"name": "Dubai, UAE"}, "updated_at": "2026-11-01T10:00:00-04:00",
    "company_name": "Acme",
    "content": "&lt;p&gt;Build &lt;strong&gt;Spring Boot&lt;/strong&gt; services&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Java 21&lt;/li&gt;&lt;/ul&gt;",
}]}

LEVER = [{
    "id": "abc", "text": "Backend Engineer", "hostedUrl": "https://jobs.lever.co/beta/abc",
    "categories": {"location": "Riyadh", "commitment": "Full-time", "team": "Eng"},
    "workplaceType": "hybrid", "descriptionPlain": "We use Java.",
    "lists": [{"text": "Requirements", "content": "<li>5+ years</li>"}],
    "createdAt": 1762000000000,
}]

ASHBY = {"jobs": [
    {"id": "x1", "title": "Platform Engineer", "location": "Doha", "isRemote": False,
     "workplaceType": "OnSite", "employmentType": "FullTime", "jobUrl": "https://jobs.ashbyhq.com/g/x1",
     "descriptionPlain": "Kubernetes", "publishedAt": "2026-10-30T00:00:00.000Z", "isListed": True},
    {"id": "x2", "title": "Hidden", "isListed": False, "jobUrl": "u"},
]}


def ctx(http=None, browser=None, llm=None):
    return SourceContext(http=http or mock_http({}), browser=browser or FakeBrowser({}),
                         llm=llm or FakeLLM())


def test_greenhouse():
    src = build_source(SourceConfig(kind="greenhouse", name="Acme", board="acme"))
    jobs = src.fetch(ctx(http=mock_http({"boards-api.greenhouse.io/v1/boards/acme/jobs": GH})))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Senior Java Engineer" and j.company == "Acme" and j.location == "Dubai, UAE"
    assert "Spring Boot" in j.description and "<" not in j.description
    assert j.posted_at.year == 2026 and j.external_id == "101"


def test_lever():
    src = build_source(SourceConfig(kind="lever", name="Beta", board="beta"))
    j = src.fetch(ctx(http=mock_http({"api.lever.co/v0/postings/beta": LEVER})))[0]
    assert j.remote_type == "hybrid" and j.location == "Riyadh"
    assert "5+ years" in j.description and j.employment_type == "Full-time"


def test_ashby_skips_unlisted():
    src = build_source(SourceConfig(kind="ashby", name="Gamma", board="g"))
    jobs = src.fetch(ctx(http=mock_http({"api.ashbyhq.com/posting-api/job-board/g": ASHBY})))
    assert [j.title for j in jobs] == ["Platform Engineer"]
    assert jobs[0].remote_type == "onsite"


def test_generic_drops_hallucinated_urls_and_caps_detail_pages():
    listing_url = "https://careers.example.com/jobs"
    links = [{"href": "https://careers.example.com/jobs/1", "text": "Java Dev"},
             {"href": "https://careers.example.com/jobs/2", "text": "SRE"}]
    browser = FakeBrowser({
        listing_url: PageContent(listing_url, "Jobs", "Java Dev\nSRE", links),
        "https://careers.example.com/jobs/1": PageContent("u1", "", "Java Dev. Remote OK.", []),
        "https://careers.example.com/jobs/2": RuntimeError("timeout"),
    })
    llm = FakeLLM(listings=[
        {"title": "Java Dev", "url": "https://careers.example.com/jobs/1", "company": None, "location": None},
        {"title": "SRE", "url": "https://careers.example.com/jobs/2", "company": "Ex", "location": "Dubai"},
        {"title": "Made up", "url": "https://careers.example.com/jobs/999", "company": None, "location": None},
    ])
    src = build_source(SourceConfig(kind="generic", name="Example", urls=[listing_url]))
    jobs = src.fetch(ctx(browser=browser, llm=llm))
    assert [j.title for j in jobs] == ["Java Dev", "SRE"]
    assert jobs[0].description.startswith("Java Dev") and jobs[0].remote_type == "remote"
    assert jobs[1].description is None  # detail fetch failed but job kept


def test_validation():
    with pytest.raises(ConfigError):
        build_source(SourceConfig(kind="greenhouse", name="x"))
    with pytest.raises(ConfigError):
        build_source(SourceConfig(kind="generic", name="x"))


def test_html_to_text():
    assert html_to_text("<p>a</p><p>b&amp;c</p>") == "a\n\nb&c"


# --- large employers with their own careers systems --------------------------------------

def _prefs(**kw):
    from jobagent.config import SearchPrefs
    return SearchPrefs(locations=["India", "Dubai"], include_title_keywords=["software", "sde"],
                       exclude_title_keywords=["manager"], max_age_days=14, **kw)


def _big_ctx(routes, prefs=None):
    logs = []
    return SourceContext(http=mock_http(routes), browser=FakeBrowser({}), llm=FakeLLM(),
                         log=logs.append, prefs=prefs), logs


def test_amazon_reader_keeps_only_jobs_that_fit_the_rules():
    from datetime import datetime, timezone
    today = f"{datetime.now(timezone.utc):%B %d, %Y}"
    feed = {"hits": 4, "jobs": [
        {"title": "Software Development Engineer II", "city": "Hyderabad", "state": "TS", "country_code": "IND",
         "job_path": "/en/jobs/1/sde", "posted_date": today, "id_icims": "1", "description": "<p>Build services</p>",
         "basic_qualifications": "3+ years<br/>Java", "preferred_qualifications": None},
        {"title": "Software Dev Manager", "city": "Pune", "state": "MH", "country_code": "IND",
         "job_path": "/en/jobs/2/m", "posted_date": today, "id_icims": "2"},
        {"title": "Warehouse Associate", "city": "Dubai", "state": None, "country_code": "ARE",
         "job_path": "/en/jobs/3/w", "posted_date": today, "id_icims": "3"},
        {"title": "Software Engineer", "city": "Dubai", "state": None, "country_code": "ARE",
         "job_path": "/en/jobs/4/old", "posted_date": "January  5, 2020", "id_icims": "4"}]}
    ctx, logs = _big_ctx({"www.amazon.jobs/en/search.json": feed}, _prefs())
    jobs = build_source(SourceConfig(kind="amazon", name="Amazon")).fetch(ctx)
    assert [(j.title, j.location, j.url) for j in jobs] == [
        ("Software Development Engineer II", "Hyderabad, TS, India", "https://www.amazon.jobs/en/jobs/1/sde")]
    assert jobs[0].company == "Amazon" and "Basic qualifications:\n3+ years\nJava" in jobs[0].description
    assert logs[-1] == "Amazon: kept 1 jobs that fit your rules"
    # Without rules (a direct call), everything that parses is returned.
    ctx, _ = _big_ctx({"www.amazon.jobs/en/search.json": feed})
    assert len(build_source(SourceConfig(kind="amazon", name="Amazon")).fetch(ctx)) == 4


def test_microsoft_reader_reads_details_only_for_jobs_that_fit(monkeypatch):
    import time
    now = int(time.time())
    monkeypatch.setattr("jobagent.sources.big.time.sleep", lambda s: None)
    search = {"data": {"positions": [
        {"id": 11, "name": "Senior Software Engineer", "locations": ["India, Telangana, Hyderabad", "India, Uttar Pradesh, Noida"],
         "postedTs": now, "positionUrl": "/careers/job/11"},
        {"id": 12, "name": "Software Engineering Manager", "locations": ["India, Karnataka, Bangalore"], "postedTs": now},
        {"id": 13, "name": "Software Engineer II", "locations": ["India, Multiple Locations, Multiple Locations"], "postedTs": now - 40 * 86400}]}}
    detail = {"data": {"jobDescription": "<p>Azure services</p>"}}
    ctx, logs = _big_ctx({"apply.careers.microsoft.com/api/pcsx/search": search,
                          "apply.careers.microsoft.com/api/pcsx/position_details": detail}, _prefs())
    jobs = build_source(SourceConfig(kind="microsoft", name="Microsoft")).fetch(ctx)
    assert [(j.title, j.location, j.description, j.url) for j in jobs] == [
        ("Senior Software Engineer", "Hyderabad, Telangana, India / Noida, Uttar Pradesh, India", "Azure services",
         "https://apply.careers.microsoft.com/careers/job/11")]
    assert logs[-1] == "Microsoft: 3 found, 1 fit your rules, 1 read in full"


def test_workday_reader_filters_by_country_and_reads_the_job_page():
    from jobagent.sources.big import _country_facets, _workday_base
    assert _workday_base("https://acme.wd5.myworkdayjobs.com/en-US/Careers?q=x") == (
        "https://acme.wd5.myworkdayjobs.com/Careers", "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers")
    assert _workday_base("https://example.com/careers") is None
    facets = [{"facetParameter": "locationMainGroup", "values": [
        {"descriptor": "Country", "facetParameter": "locationCountry", "values": [
            {"descriptor": "India", "id": "in1"}, {"descriptor": "Germany", "id": "de1"}]},
        {"descriptor": "Locations", "facetParameter": "locations", "values": [{"descriptor": "India Office", "id": "x"}]}]}]
    assert _country_facets(facets, ["India", "United Arab Emirates"]) == {"locationCountry": ["in1"]}

    listing = {"total": 3, "facets": facets, "jobPostings": [
        {"title": "Software Engineer", "externalPath": "/job/Kochi/Software-Engineer_R1", "locationsText": "Kochi",
         "postedOn": "Posted 2 Days Ago", "bulletFields": ["R1"]},
        {"title": "Software Engineer, Tools", "externalPath": "/job/x/old_R2", "locationsText": "2 Locations",
         "postedOn": "Posted 30+ Days Ago", "bulletFields": ["R2"]},
        {"title": "Sales Director", "externalPath": "/job/x/sales_R3", "locationsText": "Noida", "postedOn": "Posted Today"}]}
    page = {"jobPostingInfo": {"jobDescription": "<p>Java services</p>", "location": "Kochi", "country": {"descriptor": "India"},
                               "startDate": "2099-01-01", "timeType": "Full time", "jobReqId": "R1",
                               "externalUrl": "https://acme.wd5.myworkdayjobs.com/Careers/job/Kochi/Software-Engineer_R1"}}
    ctx, logs = _big_ctx({"acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs": listing,
                          "acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/job/Kochi/Software-Engineer_R1": page}, _prefs())
    src = build_source(SourceConfig(kind="workday", name="Acme", urls=["https://acme.wd5.myworkdayjobs.com/Careers"]))
    jobs = src.fetch(ctx)
    # "Kochi" is not in the candidate's list, but the site filtered by country and the job page says India.
    assert [(j.title, j.company, j.location, j.description, j.external_id) for j in jobs] == [
        ("Software Engineer", "Acme", "Kochi, India", "Java services", "R1")]
    assert logs[-1] == "Acme: 3 listed, 1 fit your rules, 1 read in full"
    with pytest.raises(ConfigError, match="careers address"):
        build_source(SourceConfig(kind="workday", name="Bad", urls=["https://example.com/jobs"]))
