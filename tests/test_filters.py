from datetime import datetime, timedelta, timezone

import yaml

from jobagent.config import AgentConfig, SearchPrefs
from jobagent.filters import reject_reason
from jobagent.models import JobPosting

PREFS = AgentConfig.model_validate(yaml.safe_load(open("config.example.yaml"))).search


def job(title="Senior Java Engineer", location="Dubai, United Arab Emirates", **kw):
    return JobPosting(title=title, company="Acme", url="https://x", location=location, **kw)


def test_target_countries_pass():
    for loc in ["Dubai", "Abu Dhabi, UAE", "Riyadh, Saudi Arabia", "Jeddah", "Doha, Qatar",
                "Bengaluru, Karnataka, India", "Ahmedabad", "KSA"]:
        assert reject_reason(job(location=loc), PREFS) is None, loc


def test_other_locations_rejected():
    assert "location" in reject_reason(job(location="Berlin, Germany"), PREFS)
    assert "location" in reject_reason(job(location="London"), PREFS)


def test_remote_and_unknown_location_pass_to_llm():
    assert reject_reason(job(location="Remote"), PREFS) is None
    assert reject_reason(job(location=None), PREFS) is None


def test_title_keywords():
    assert reject_reason(job(title="Backend Engineer (Java)"), PREFS) is None
    assert "excluded" in reject_reason(job(title="Engineering Manager, Platform"), PREFS)
    assert "include" in reject_reason(job(title="Product Designer"), PREFS)
    # whole word: "javascript" should not match "java"... but 'software engineer' does here
    assert reject_reason(job(title="JavaScript Software Engineer"), PREFS) is None
    assert "include" in reject_reason(job(title="Javanese Translator"), PREFS)


def test_age():
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    old = job(posted_at=now - timedelta(days=45))
    assert "days" in reject_reason(old, PREFS, now=now)
    assert reject_reason(job(posted_at=now - timedelta(days=3)), PREFS, now=now) is None


def test_fingerprint_dedupes_across_urls():
    a = JobPosting(title="Java Engineer", company="Acme Inc", url="https://a", location="Dubai")
    b = JobPosting(title="java  engineer", company="ACME inc.", url="https://b", location="dubai")
    assert a.fingerprint == b.fingerprint


def test_company_exclusion():
    prefs = SearchPrefs(exclude_company_keywords=["bank", "banking"])
    assert "company" in reject_reason(
        JobPosting(title="Java Engineer", company="Emirates NBD Bank", url="u"), prefs)
    assert "company" in reject_reason(
        JobPosting(title="Java Engineer", company="Riyad Bank", url="u"), prefs)
    assert reject_reason(JobPosting(title="Java Engineer", company="Bankr Tech", url="u"), prefs) is None
    assert "banking" in PREFS.exclude_industries and "bank" in PREFS.exclude_company_keywords


def test_country_of():
    from jobagent.filters import country_of
    assert country_of("Dubai - United Arab Emirates") == "UAE"
    assert country_of("Riyadh - Saudi Arabia") == "Saudi Arabia"
    assert country_of("Doha") == "Qatar"
    assert country_of("Hybrid - Pune") == "India"
    assert country_of(None) == "Remote"


def test_minimum_salary_drops_only_jobs_that_state_less():
    from jobagent.filters import stated_salary_lpa

    assert stated_salary_lpa("3 - 7 years | 15-25 Lacs PA | Pune") == 25
    assert stated_salary_lpa("Salary: 18 LPA") == 18 and stated_salary_lpa("12 to 16 lakhs") == 16
    assert stated_salary_lpa("3 - 7 years | Not Disclosed | Bengaluru") is None
    prefs = SearchPrefs(min_salary_lpa=20)
    job = lambda desc: JobPosting(title="Java Dev", company="A", url="u", description=desc)
    assert "below the minimum 20 LPA" in reject_reason(job("5 years | 10-15 Lacs PA"), prefs)
    assert reject_reason(job("5 years | 18-28 Lacs PA"), prefs) is None       # range reaches 20
    assert reject_reason(job("5 years | Not Disclosed"), prefs) is None       # unknown pay is kept
    assert reject_reason(job("x" * 1300 + " similar job 5-8 Lacs PA"), prefs) is None  # other jobs' pay ignored


def test_remote_jobs_tied_to_another_country_are_dropped():
    from jobagent.config import SearchPrefs
    prefs = SearchPrefs(locations=["India", "Dubai", "UAE"], remote_ok=True)

    def why(location, remote_type="unknown"):
        return reject_reason(JobPosting(title="Engineer", company="X", url="u", location=location,
                                        remote_type=remote_type), prefs)

    for place in ("Remote", "Remote - India", "Remote (EMEA)", "Remote, APAC", "Remote, anywhere", "Hybrid - Dubai"):
        assert why(place) is None, place
    assert why(None, "remote") is None and why("Bengaluru, India", "remote") is None
    for place in ("Remote - Brazil", "Remote, United States", "Remote (Canada)"):
        assert "not in preferred locations" in why(place), place
    assert "not in preferred locations" in why("San Francisco", "remote")  # flagged remote, but based elsewhere
