import threading
import time

import pytest
from test_api import api


@pytest.fixture
def email_api(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    from jobpilot import service

    service.store.set(
        "settings",
        {
            **service.settings(),
            "email": {
                "host": "imap.gmail.com",
                "username": "fixture@example.com",
                "enabled": True,
                "credential_saved": True,
                "scan_limit": 100,
                "lookback_days": 14,
            },
        },
    )
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    return service, client, headers


def wait_done(client):
    end = time.monotonic() + 4
    while time.monotonic() < end:
        status = client.get("/api/email/status").json()
        if status.get("state") not in ["checking", "syncing"]:
            return status
        time.sleep(0.02)
    pytest.fail("Email background task did not complete")


def result(jobs=None):
    return {
        "ok": True,
        "state": "connected",
        "checked_at": "2026-10-26T12:00:00Z",
        "messages_available": 120,
        "messages_checked": 100,
        "messages_skipped": 20,
        "links_found": len(jobs or []),
        "truncated": True,
        "jobs": jobs or [],
    }


@pytest.mark.parametrize("interrupted_state", ["checking", "syncing"])
def test_restart_releases_interrupted_email_check_and_preserves_last_scan(
    email_api, interrupted_state
):
    service, client, _ = email_api
    service.store.set(
        "email_sync",
        {
            "state": interrupted_state,
            "message": "Reading job alerts from Gmail.",
            "checked_at": "2026-10-26T12:00:00Z",
            "messages_checked": 8,
            "links_found": 3,
            "imported": 2,
        },
    )
    assert not service.email_task_running.is_set()

    with client:
        status = client.get("/api/email/status").json()

    assert status["state"] == "error"
    assert "interrupted" in status["message"].lower()
    assert "try again" in status["message"].lower()
    assert status["checked_at"] == "2026-10-26T12:00:00Z"
    assert status["messages_checked"] == 8
    assert status["links_found"] == 3
    assert status["imported"] == 2


def test_failed_scheduled_scan_is_not_reported_as_connected(email_api):
    service, client, _ = email_api
    service._save_email_result(
        {"state": "error", "message": "Reconnect Gmail with an app password."}
    )
    state = client.get("/api/email/status").json()
    assert state["state"] == "error"
    assert "Reconnect" in state["message"]


def test_account_cannot_change_while_its_connection_is_being_verified(email_api, monkeypatch):
    service, client, headers = email_api
    from jobpilot import collectors

    entered, release = threading.Event(), threading.Event()

    def checking(config):
        entered.set()
        release.wait(3)
        return result()

    monkeypatch.setattr(collectors, "check_email_connection", checking)
    monkeypatch.setattr(
        collectors,
        "configure_email",
        lambda body: {"username": "other@example.com", "enabled": True},
    )
    client.post("/api/email/check", headers=headers, json={})
    assert entered.wait(1)
    try:
        response = client.post(
            "/api/email", headers=headers, json={"username": "other@example.com"}
        )
        assert response.status_code == 409
        assert service.settings()["email"]["username"] == "fixture@example.com"
    finally:
        release.set()
    wait_done(client)


def test_scheduled_gmail_import_count_excludes_other_search_sources(email_api, monkeypatch):
    service, client, _ = email_api
    from jobpilot import collectors

    board_job = {
        "url": "https://example.com/jobs/board",
        "source": "linkedin",
        "title": "Security Engineer",
        "company": "Example",
        "location": "Cincinnati, OH",
        "description": "AWS cloud security automation and access reviews. " * 5,
    }
    monkeypatch.setattr(collectors, "discover", lambda *args: [board_job])
    monkeypatch.setattr(collectors, "get_last_errors", lambda: [])
    monkeypatch.setattr(collectors, "get_last_email_result", lambda: {**result(), "links_found": 0})
    service.discover_once()
    assert len(service.store.jobs()) == 1
    assert client.get("/api/email/status").json()["imported"] == 0


def test_connection_check_is_background_and_independent_of_document_lock(email_api, monkeypatch):
    service, client, headers = email_api
    from jobpilot import collectors

    entered, release = threading.Event(), threading.Event()

    def check(config):
        entered.set()
        release.wait(3)
        return result()

    monkeypatch.setattr(collectors, "check_email_connection", check)
    with service.application_lock:
        response = client.post("/api/email/check", headers=headers, json={})
        assert response.status_code == 202 and response.json()["state"] == "checking"
        assert entered.wait(1)
        assert client.get("/api/email/status").json()["state"] == "checking"
        release.set()
    done = wait_done(client)
    assert done["state"] == "connected" and done["messages_available"] == 120
    assert done["credential_saved"] is True and "jobs" not in done


def test_email_sync_imports_once_and_keeps_alert_metadata_on_fetch_failure(email_api, monkeypatch):
    service, client, headers = email_api
    from jobpilot import collectors

    alert = {
        "url": "https://example.com/jobs/1",
        "title": "Security Engineer",
        "company": "Alert Employer",
        "source": "email",
        "location": "Cincinnati, OH",
        "alert_subject": "Your security jobs",
        "alert_from": "alerts@example.com",
        "alert_received_at": "2026-10-26T12:00:00Z",
    }
    monkeypatch.setattr(collectors, "sync_email", lambda config: result([alert]))

    def unavailable(url):
        raise RuntimeError("PRIVATE_PROVIDER_TOKEN")

    monkeypatch.setattr(collectors, "fetch_job", unavailable)
    assert client.post("/api/email/sync", headers=headers, json={}).status_code == 202
    status = wait_done(client)
    assert status["imported"] == 1 and status["truncated"] is True
    job = service.store.jobs()[0]
    assert job["company"] == alert["company"] and job["title"] == alert["title"]
    assert job["alert_received_at"] == alert["alert_received_at"]
    assert job["alert_subject"] == alert["alert_subject"]
    assert job["status"] == "needs_review"
    problem = client.get("/api/problems").json()["problems"][0]
    assert problem["url"] == alert["url"] and "PRIVATE_PROVIDER_TOKEN" not in str(problem)
    client.post("/api/email/sync", headers=headers, json={})
    assert wait_done(client)["imported"] == 0
    assert len(service.store.jobs()) == 1


def test_email_errors_are_actionable_without_exposing_server_details(email_api, monkeypatch):
    service, client, headers = email_api
    from jobpilot import collectors

    def rejected(config):
        raise collectors.EmailConnectionError(
            "Gmail did not accept this connection. Save a Google app password."
        )

    monkeypatch.setattr(collectors, "check_email_connection", rejected)
    client.post("/api/email/check", headers=headers, json={})
    status = wait_done(client)
    assert status["state"] == "error" and "app password" in status["message"]
    assert client.get("/api/problems").json()["problems"][0]["category"] == "email"


def test_open_job_link_does_not_wait_for_document_preparation(email_api, monkeypatch):
    service, client, headers = email_api
    from jobpilot import links

    job = service.store.add_job({"url": "https://example.com/jobs/2", "title": "Engineer"})
    seen = []
    monkeypatch.setattr(
        links,
        "open_external_url",
        lambda url: seen.append(url) or {"status": "opened", "opened": True, "url": url},
    )
    entered, release = threading.Event(), threading.Event()

    def busy():
        with service.application_lock:
            entered.set()
            release.wait(3)

    thread = threading.Thread(target=busy)
    thread.start()
    assert entered.wait(1)
    try:
        response = client.post(
            "/api/browser/open_external", headers=headers, json={"job_id": job["id"]}
        )
        assert response.status_code == 200 and response.json()["opened"] is True
        assert seen == [job["url"]]
    finally:
        release.set()
        thread.join(2)
