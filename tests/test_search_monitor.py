from datetime import datetime, timezone

import pytest
from test_api import api


@pytest.fixture
def monitor_api(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    from jobpilot import service

    moment = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "_search_clock", lambda: moment, raising=False)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    return service, client, headers


@pytest.mark.parametrize("route", ["/api/settings", "/api/control"])
def test_enabling_monitoring_requests_an_immediate_check(monitor_api, route):
    service, client, headers = monitor_api
    service.store.set("last_search", "2026-10-27T14:59:00+00:00")
    result = client.post(route, headers=headers, json={"search_enabled": True})
    assert result.status_code == 200
    assert service.search_requested.is_set()
    monitor = client.get("/api/state").json()["search_monitor"]
    assert monitor["enabled"] is True
    assert monitor["next_search_at"] == "2026-10-27T15:00:00+00:00"


def test_interval_changes_update_next_check_without_an_old_deadline(monitor_api):
    service, client, headers = monitor_api
    service.store.set("last_search", "2026-10-27T14:52:00+00:00")
    service.store.set("settings", {**service.settings(), "search_enabled": True})
    client.post("/api/settings", headers=headers, json={"search_interval_minutes": 10})
    monitor = client.get("/api/state").json()["search_monitor"]
    assert monitor["interval_minutes"] == 10
    assert monitor["next_search_at"] == "2026-10-27T15:02:00+00:00"
    client.post("/api/settings", headers=headers, json={"search_interval_minutes": 5})
    assert service.search_due() is True


def test_pause_clears_pending_monitoring_but_keeps_manual_search_available(monitor_api):
    service, client, headers = monitor_api
    client.post("/api/control", headers=headers, json={"search_enabled": True})
    client.post("/api/control", headers=headers, json={"search_enabled": False})
    assert not service.search_requested.is_set()
    monitor = client.get("/api/state").json()["search_monitor"]
    assert monitor["enabled"] is False
    assert monitor["next_search_at"] is None
    assert not service.search_due()
    client.post("/api/control", headers=headers, json={"action": "search"})
    assert service.search_due()
    assert not service.settings()["search_enabled"]


def test_active_search_does_not_advertise_a_second_overlapping_check(monitor_api):
    service, client, _ = monitor_api
    service.worker["searching"] = True
    service.search_requested.set()
    service.store.set("settings", {**service.settings(), "search_enabled": True})
    assert client.get("/api/state").json()["search_monitor"]["next_search_at"] is None
    assert not service.search_due()


def posting(slug, **changes):
    return {
        "url": f"https://example.com/jobs/{slug}",
        "title": "Security Engineer",
        "company": "Example Systems",
        "source": "indeed",
        "location": "Cincinnati, OH",
        "description": "Maintain AWS security controls, review IAM policies, investigate alerts, and automate audit evidence in Python.",
        **changes,
    }


def test_search_summary_explains_new_existing_filtered_and_removed_records(
    monitor_api, monkeypatch
):
    service, client, _ = monitor_api
    from jobpilot import collectors

    service.store.set("settings", {**service.settings(), "min_fit": 0})
    existing = posting("existing")
    service.store.add_job(existing)
    removed = service.store.add_job(posting("removed"))
    service.store.remove_job(removed["id"])
    records = [
        posting("new"),
        existing,
        posting("removed"),
        posting("unrelated", title="Store Manager"),
    ]
    monkeypatch.setattr(collectors, "discover", lambda *_: records)
    monkeypatch.setattr(collectors, "get_last_errors", lambda: [])
    monkeypatch.setattr(
        collectors, "get_last_search_result", lambda: {"sources": []}, raising=False
    )
    service.discover_once()
    result = client.get("/api/state").json()["search_monitor"]["last_result"]
    assert {
        key: result[key] for key in ["checked", "imported", "existing", "filtered", "removed"]
    } == {"checked": 4, "imported": 1, "existing": 1, "filtered": 1, "removed": 1}
    source = next(row for row in result["sources"] if row["source"] == "indeed")
    assert source["checked"] == 4
    assert source["imported"] == 1
    assert len(service.store.jobs()) == 2


def test_partial_source_saves_cards_without_generic_problem_spam(monitor_api, monkeypatch):
    service, client, _ = monitor_api
    from jobpilot import collectors

    monkeypatch.setattr(
        collectors,
        "discover",
        lambda *_: [posting("card", source="linkedin", description="", description_missing=True)],
    )
    monkeypatch.setattr(
        collectors,
        "get_last_errors",
        lambda: [
            {
                "source": "linkedin",
                "note": "Description unavailable; review required: https://example.com/jobs/card",
            }
        ],
    )
    monkeypatch.setattr(
        collectors,
        "get_last_search_result",
        lambda: {
            "sources": [
                {
                    "source": "linkedin",
                    "status": "partial",
                    "message": "Job cards saved; descriptions require opening the posting.",
                    "url": "https://www.linkedin.com/jobs/",
                }
            ]
        },
        raising=False,
    )
    service.discover_once()
    state = client.get("/api/state").json()
    assert len(state["jobs"]) == 1
    assert state["jobs"][0]["status"] == "needs_review"
    assert state["problems"] == []
    row = next(
        row
        for row in state["search_monitor"]["last_result"]["sources"]
        if row["source"] == "linkedin"
    )
    assert row["status"] == "partial"
    assert row["imported"] == 1


def test_failed_search_advances_schedule_instead_of_retrying_each_second(monitor_api, monkeypatch):
    service, client, _ = monitor_api
    from jobpilot import collectors

    service.store.set(
        "settings", {**service.settings(), "search_enabled": True, "search_interval_minutes": 5}
    )

    def unavailable(*_):
        raise RuntimeError("Network unavailable")

    monkeypatch.setattr(collectors, "discover", unavailable)
    service.discover_once()
    monitor = client.get("/api/state").json()["search_monitor"]
    assert monitor["last_search_at"] == "2026-10-27T15:00:00+00:00"
    assert monitor["next_search_at"] == "2026-10-27T15:05:00+00:00"
    assert monitor["last_result"]["status"] == "error"
    assert not service.search_due()


def test_search_repairs_an_existing_alert_that_correct_metadata_now_filters(
    monitor_api, monkeypatch
):
    service, _, _ = monitor_api
    from jobpilot import collectors

    old = service.store.add_job(
        posting("old-alert", source="email", status="needs_review", description_missing=True)
    )
    corrected = posting(
        "old-alert",
        source="email",
        title="Retail Store Manager",
        alert_metadata_version=1,
        description_missing=True,
    )
    monkeypatch.setattr(collectors, "discover", lambda *_: [corrected])
    monkeypatch.setattr(collectors, "get_last_errors", lambda: [])
    monkeypatch.setattr(collectors, "get_last_search_result", lambda: {"sources": []})
    service.discover_once()
    saved = service.store.get_job(old["id"])
    assert saved["title"] == "Retail Store Manager"
    assert saved["status"] == "skipped"
    assert len(service.store.jobs()) == 1
