import threading
from datetime import datetime, timedelta, timezone

import pytest
from test_api import api

NOW = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def cleanup_api(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    import jobpilot.service as service

    monkeypatch.setattr(service, "_cleanup_now", lambda: NOW, raising=False)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    return service, client, headers


def add(service, slug, days=None, **extra):
    return service.store.add_job(
        {
            "url": "https://example.com/jobs/" + slug,
            "title": slug,
            "company": "Fixture",
            "posted_at": (NOW - timedelta(days=days)).isoformat() if days is not None else None,
            **extra,
        }
    )


def preview(client):
    response = client.get("/api/jobs/cleanup/preview")
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_is_read_only_inclusive_and_keeps_unknown_and_active(cleanup_api):
    service, client, _ = cleanup_api
    old = add(service, "old", 8)
    boundary = add(service, "boundary", 7)
    add(service, "recent", 6.999)
    add(service, "unknown")
    add(service, "malformed", posted_at="not-a-date")
    add(service, "future", -3)
    add(service, "active", 10, status="applying")
    add(service, "manual", 12, browser_handoff={"mode": "default_browser", "state": "opened"})
    result = preview(client)
    assert result["count"] == 2
    assert {job["id"] for job in result["jobs"]} == {old["id"], boundary["id"]}
    assert result["protected_count"] == 2 and result["unknown_date_count"] == 2
    assert result["cutoff"] == (NOW - timedelta(days=7)).isoformat()
    assert len(service.store.jobs()) == 8


def test_delete_requires_session_token_and_explicit_confirmation(cleanup_api):
    service, client, headers = cleanup_api
    old = add(service, "old", 8)
    snapshot = preview(client)
    body = {"token": snapshot["token"], "confirm": True}
    assert client.post("/api/jobs/cleanup", json=body).status_code == 403
    assert (
        client.post(
            "/api/jobs/cleanup", headers=headers, json={"token": snapshot["token"]}
        ).status_code
        == 400
    )
    assert service.store.get_job(old["id"])
    result = client.post("/api/jobs/cleanup", headers=headers, json=body)
    assert result.status_code == 200
    assert result.json()["deleted_count"] == 1
    assert service.store.get_job(old["id"]) is None
    assert client.post("/api/jobs/cleanup", headers=headers, json=body).status_code == 409


def test_delete_is_limited_to_preview_and_rechecks_changes(cleanup_api):
    service, client, headers = cleanup_api
    old = add(service, "old", 8)
    changed = add(service, "changed", 8)
    unknown = add(service, "unknown")
    snapshot = preview(client)
    arrived = add(service, "arrived-after-preview", 12)
    service.store.update_job(changed["id"], posted_at=(NOW - timedelta(days=1)).isoformat())
    result = client.post(
        "/api/jobs/cleanup", headers=headers, json={"token": snapshot["token"], "confirm": True}
    )
    assert result.status_code == 200
    assert result.json()["deleted_count"] == 1 and result.json()["skipped_count"] == 1
    assert not service.store.get_job(old["id"])
    assert all(service.store.get_job(job["id"]) for job in [changed, unknown, arrived])


def test_expired_or_invalid_preview_does_not_delete(cleanup_api, monkeypatch):
    service, client, headers = cleanup_api
    old = add(service, "old", 9)
    snapshot = preview(client)
    before = service._cleanup_clock()
    monkeypatch.setattr(service, "_cleanup_clock", lambda: before + 301)
    for token in [snapshot["token"], "unknown"]:
        assert (
            client.post(
                "/api/jobs/cleanup", headers=headers, json={"token": token, "confirm": True}
            ).status_code
            == 409
        )
    assert service.store.get_job(old["id"])


def test_active_application_lock_blocks_deletion_without_consuming_preview(cleanup_api):
    service, client, headers = cleanup_api
    old = add(service, "old", 9)
    snapshot = preview(client)
    entered, release = threading.Event(), threading.Event()

    def active():
        with service.application_lock:
            entered.set()
            release.wait(5)

    thread = threading.Thread(target=active)
    thread.start()
    assert entered.wait(2)
    try:
        result = client.post(
            "/api/jobs/cleanup", headers=headers, json={"token": snapshot["token"], "confirm": True}
        )
        assert result.status_code == 409
        assert service.store.get_job(old["id"])
    finally:
        release.set()
        thread.join(3)
    assert (
        client.post(
            "/api/jobs/cleanup", headers=headers, json={"token": snapshot["token"], "confirm": True}
        ).status_code
        == 200
    )


def test_live_verification_browser_blocks_cleanup(cleanup_api, monkeypatch):
    service, client, headers = cleanup_api
    from jobpilot import browser

    old = add(service, "old", 9)
    monkeypatch.setattr(browser, "login_in_progress", lambda: True)
    snapshot = preview(client)
    assert snapshot["busy"]
    assert (
        client.post(
            "/api/jobs/cleanup", headers=headers, json={"token": snapshot["token"], "confirm": True}
        ).status_code
        == 409
    )
    assert service.store.get_job(old["id"])


def test_rediscovery_and_import_do_not_recreate_permanently_deleted_job(cleanup_api):
    service, client, headers = cleanup_api
    old = add(service, "old", 9)
    snapshot = preview(client)
    assert (
        client.post(
            "/api/jobs/cleanup", headers=headers, json={"token": snapshot["token"], "confirm": True}
        ).status_code
        == 200
    )
    result = client.post(
        "/api/import",
        headers=headers,
        json={
            "url": old["url"],
            "title": "Security Engineer",
            "company": "Fixture",
            "description": "AWS cloud security role requiring Python and SOC 2 evidence operations.",
        },
    )
    assert result.status_code == 200
    assert result.json()["jobs"] == [] and result.json()["ignored"] == 1
    assert service.store.jobs() == []
