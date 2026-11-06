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
