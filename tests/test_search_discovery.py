import logging

import pandas as pd

from jobpilot import collectors


def row(identifier, **extra):
    return {
        "job_url": f"https://www.indeed.com/viewjob?jk={identifier}",
        "title": "Security Analyst",
        "company": "Acme",
        "location": "USA",
        "description": "Protect systems",
        **extra,
    }


def test_every_role_and_location_is_searched_even_when_first_query_fills_quota(monkeypatch):
    seen = []

    def search(**kwargs):
        seen.append(kwargs)
        return [row(f"{len(seen)}-{i}") for i in range(kwargs["results_wanted"])]

    monkeypatch.setattr(collectors, "_jobspy_search", search)
    jobs = collectors.discover(
        {
            "sources": ["indeed"],
            "target_roles": ["Security Engineer", "GRC Analyst"],
            "locations": ["Cincinnati, OH"],
            "remote": True,
            "results_per_source": 2,
        },
        {},
    )
    assert len(jobs) == 8
    assert {(q["search_term"], q["location"], q.get("is_remote", False)) for q in seen} == {
        ("Security Engineer", "Cincinnati, OH", False),
        ("Security Engineer", "USA", True),
        ("GRC Analyst", "Cincinnati, OH", False),
        ("GRC Analyst", "USA", True),
    }
    assert all(q["hours_old"] == 168 for q in seen)


def test_discovery_retains_remote_evidence_for_geographic_filter(monkeypatch):
    monkeypatch.setattr(collectors, "_jobspy_search", lambda **kwargs: [row("a", is_remote=True)])
    jobs = collectors.discover({"sources": ["indeed"], "locations": ["Remote"]}, {})
    assert jobs[0]["is_remote"] is True


def test_duplicate_rows_do_not_starve_later_distinct_rows(monkeypatch):
    monkeypatch.setattr(
        collectors, "_jobspy_search", lambda **kwargs: [row("a"), row("a"), row("b")]
    )
    jobs = collectors.discover(
        {"sources": ["indeed"], "locations": ["Remote"], "results_per_source": 2}, {}
    )
    assert [job["url"] for job in jobs] == [
        "https://www.indeed.com/viewjob?jk=a",
        "https://www.indeed.com/viewjob?jk=b",
    ]


def test_missing_descriptions_are_partial_coverage_not_search_errors(monkeypatch):
    monkeypatch.setattr(collectors, "_jobspy_search", lambda **kwargs: [row("a", description=None)])
    jobs = collectors.discover({"sources": ["linkedin"], "locations": ["Remote"]}, {})
    assert jobs[0]["description_missing"] is True
    assert collectors.get_last_errors() == []
    summary = collectors.get_last_search_result()["sources"][0]
    assert summary["status"] == "partial"
    assert summary["descriptions_missing"] == 1


def test_linkedin_stops_after_429_keeps_cards_and_observes_cooldown(monkeypatch):
    calls = []
    clock = [100.0]
    monkeypatch.setattr(collectors, "_search_clock", lambda: clock[0], raising=False)
    monkeypatch.setattr(collectors, "_source_cooldowns", {}, raising=False)

    def search(**kwargs):
        calls.append(kwargs)
        with collectors._errors_lock:
            collectors._search_warnings.append(
                {"source": "linkedin", "note": "LinkedIn response status code 429"}
            )
        return [row("a", description=None)]

    monkeypatch.setattr(collectors, "_jobspy_search", search)
    settings = {
        "sources": ["linkedin"],
        "target_roles": ["Security Engineer", "GRC Analyst"],
        "locations": ["Cincinnati, OH"],
        "remote": True,
    }
    assert len(collectors.discover(settings, {})) == 1
    assert len(calls) == 1
    assert calls[0]["fetch_description"] is False
    assert collectors.get_last_search_result()["sources"][0]["status"] == "blocked"
    assert collectors.discover(settings, {}) == []
    assert len(calls) == 1
    clock[0] += 901
    collectors.discover(settings, {})
    assert len(calls) == 2


def test_jobspy_warning_capture_includes_dataframe_errors_without_duplicates(monkeypatch):
    import jobspy

    def scrape(**kwargs):
        logging.getLogger("JobSpy:LinkedIn").error("LinkedIn response status code 429")
        frame = pd.DataFrame([])
        frame.attrs["errors"] = {
            "linkedin": "LinkedIn response status code 429",
            "indeed": "Source unavailable",
        }
        return frame

    monkeypatch.setattr(jobspy, "scrape_jobs", scrape)
    with collectors._errors_lock:
        collectors._search_warnings.clear()
    assert collectors._jobspy_search(site_name=["linkedin"]) == []
    assert collectors._search_warnings == [
        {"source": "linkedin", "note": "LinkedIn response status code 429", "level": "error"},
        {"source": "indeed", "note": "Source unavailable", "level": "error"},
    ]


def test_public_board_does_not_drop_roles_after_first_500_rows(monkeypatch):
    import json

    rows = [
        {
            "id": str(i),
            "title": "Security Analyst",
            "jobUrl": f"https://jobs.ashbyhq.com/acme/{i}",
            "location": "Remote, USA",
            "descriptionPlain": "Protect systems",
            "isListed": True,
        }
        for i in range(501)
    ]
    monkeypatch.setattr(collectors, "_get_public", lambda url: (json.dumps({"jobs": rows}), url))
    jobs = collectors._board_jobs("ashby", "acme")
    assert len(jobs) == 501
    assert jobs[-1]["requisition_id"] == "500"


def test_access_denial_respects_retry_after_and_preserves_other_sources(monkeypatch):
    import requests

    clock = [100.0]
    monkeypatch.setattr(collectors, "_search_clock", lambda: clock[0])
    monkeypatch.setattr(collectors, "_source_cooldowns", {})

    def search(**kwargs):
        if kwargs["site_name"] == ["linkedin"]:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "1800"
            raise requests.HTTPError("Too many requests", response=response)
        return [row("a")]

    monkeypatch.setattr(collectors, "_jobspy_search", search)
    jobs = collectors.discover({"sources": ["linkedin", "indeed"], "locations": ["Remote"]}, {})
    assert len(jobs) == 1
    assert collectors.get_last_search_result()["sources"][0]["retry_after_seconds"] == 1800
    clock[0] = 1001
    collectors.discover({"sources": ["linkedin"], "locations": ["Remote"]}, {})
    assert collectors.get_last_search_result()["sources"][0]["queries_attempted"] == 0


def test_retry_after_http_date_is_observed(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    import requests

    monkeypatch.setattr(collectors, "_source_cooldowns", {})

    def search(**kwargs):
        response = requests.Response()
        response.status_code = 429
        response.headers["Retry-After"] = format_datetime(
            datetime.now(timezone.utc) + timedelta(hours=1)
        )
        raise requests.HTTPError("Too many requests", response=response)

    monkeypatch.setattr(collectors, "_jobspy_search", search)
    collectors.discover({"sources": ["linkedin"], "locations": ["Remote"]}, {})
    assert collectors.get_last_search_result()["sources"][0]["retry_after_seconds"] >= 3598


def test_search_dimensions_are_bounded_and_dates_are_preserved(monkeypatch):
    calls = []

    def search(**kwargs):
        calls.append(kwargs)
        return [row(str(len(calls)), date_posted="2026-10-21")]

    monkeypatch.setattr(collectors, "_jobspy_search", search)
    jobs = collectors.discover(
        {
            "sources": ["indeed"],
            "target_roles": [f"Role {i}" for i in range(10)],
            "locations": [f"City {i}" for i in range(6)],
            "remote": True,
            "hours_old": 24,
        },
        {},
    )
    assert len(calls) == 32
    assert all(query["hours_old"] == 24 for query in calls)
    assert all(job["posted_at"] == "2026-10-21" for job in jobs)


def test_logged_upstream_failure_is_error_instead_of_empty_success(monkeypatch):
    import jobspy

    def scrape(**kwargs):
        logging.getLogger("JobSpy:Indeed").error("Indeed: connection timed out")
        return pd.DataFrame([])

    monkeypatch.setattr(jobspy, "scrape_jobs", scrape)
    jobs = collectors.discover(
        {
            "sources": ["indeed"],
            "target_roles": ["Security Analyst", "GRC Analyst"],
            "locations": ["Remote"],
        },
        {},
    )
    assert jobs == []
    state = collectors.get_last_search_result()["sources"][0]
    assert state["status"] == "error"
    assert state["queries_attempted"] == 1
    assert len(collectors.get_last_errors()) == 1
