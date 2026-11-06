import os

import httpx
import psycopg
import pytest

from jobagent import db
from jobagent.browser import PageContent
from jobagent.models import ExtractedListing, ExtractedListings, MatchResult

TEST_DB = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
def conn():
    if not TEST_DB:
        pytest.skip("set TEST_DATABASE_URL to run database tests")
    c = db.connect(TEST_DB)
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    db.migrate(c)
    yield c
    c.close()


class FakeLLM:
    model = "fake-model"

    def __init__(self, scores=None, listings=None):
        self.scores = scores or {}
        self.listings = listings or []
        self.scored_titles = []
        self.tokens_used = 0

    def score_job(self, profile, prefs, job):
        self.scored_titles.append(job.title)
        s = self.scores.get(job.title, 50)
        if s == "boom":
            raise RuntimeError("model error")
        self.tokens_used += 100
        return MatchResult(score=s, verdict="strong" if s >= 85 else "good" if s >= 70 else "stretch",
                           summary=f"fit {s}", matched_skills=["Java"], missing_skills=[],
                           red_flags=[])

    def extract_listings(self, text, links, url):
        return ExtractedListings(listings=[ExtractedListing(**l) for l in self.listings])


class FakeBrowser:
    def __init__(self, pages):
        self.pages = pages
        self.visited = []

    def fetch(self, url, *, wait_ms=0):
        self.visited.append(url)
        p = self.pages[url]
        if isinstance(p, Exception):
            raise p
        return p


def mock_http(routes: dict):
    def handler(request: httpx.Request):
        key = f"{request.url.host}{request.url.path}"
        if key not in routes:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=routes[key])
    return httpx.Client(transport=httpx.MockTransport(handler))
