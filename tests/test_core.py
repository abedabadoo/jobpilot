from datetime import datetime, timezone

from jobpilot.core import (
    canonical_url,
    eligibility,
    freshness,
    score_job,
    validate_selection,
)


def test_exclusive_timezone_freshness():
    now = datetime(2026, 10, 12, 14, tzinfo=timezone.utc)
    assert freshness("2026-10-12T05:00:00Z", now) == 0
    assert freshness("2026-10-11T23:00:00Z", now) == 1
    assert freshness("2026-10-10T14:00:00Z", now) == 2
    assert freshness("2026-10-06T14:00:00Z", now) == 3
    assert freshness("2026-10-01", now) == 4


def test_future_invalid_and_unknown_dates_last():
    now = datetime(2026, 10, 12, 14, tzinfo=timezone.utc)
    for value in [None, "", "nonsense", "2026-10-13T00:00:00Z"]:
        assert freshness(value, now) == 5


def test_canonical_keeps_requisition_and_removes_tracking():
    assert canonical_url(
        "https://www.linkedin.com/jobs/view/123/?utm_source=email&trk=x"
    ) == canonical_url("https://linkedin.com/jobs/view/123")
    assert canonical_url("https://indeed.com/viewjob?jk=123&utm_source=x") != canonical_url(
        "https://indeed.com/viewjob?jk=456"
    )


def test_grounded_selection_rejects_new_facts():
    profile = {"experience": [{"facts": [{"id": "e1", "text": "Hardened AWS."}]}]}
    assert validate_selection({"fact_ids": ["e1", "invented"]}, profile) == ["e1"]


def test_fit_distinguishes_relevant_roles():
    p = {"skills": ["AWS", "ISO 27001", "Python"]}
    settings = {"target_roles": ["Security Engineer"]}
    assert score_job(
        {"title": "Security Engineer", "description": "AWS Python ISO 27001"}, p, settings
    ) > score_job({"title": "Barista", "description": "coffee sales"}, p, settings)


def test_location_preferences_do_not_apply_worldwide():
    s = {"location": "Cincinnati, OH", "remote": True}
    assert eligibility({"location": "Remote - US"}, s)[0] == "eligible"
    assert eligibility({"location": "Cincinnati, Ohio"}, s)[0] == "eligible"
    assert eligibility({"location": "Paris, France"}, s)[0] == "excluded"
    assert eligibility({"location": "Remote"}, s)[0] == "review"
