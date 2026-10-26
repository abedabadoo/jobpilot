"""A normal-browser handoff must never fabricate a receipt or retry a held job."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def tab_api(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBPILOT_TESTING", "1")
    import jobpilot.service as service
    from jobpilot import browser

    service = importlib.reload(service)
    service.store.set("settings", {**service.settings(), "application_mode": "legacy"})
    opened = []

    def dispatch(url):
        opened.append(url)
        return {
            "status": "opened",
            "mode": "default_browser",
            "receipt_tracking": "manual",
            "url": url,
        }

    monkeypatch.setattr(browser, "open_browser_tab", dispatch, raising=False)
    monkeypatch.setattr(browser, "open_review", lambda *a, **k: pytest.fail("No isolated browser"))
    monkeypatch.setattr(browser, "open_login", lambda *a, **k: pytest.fail("No isolated login"))
    monkeypatch.setattr(browser, "apply", lambda *a, **k: pytest.fail("No submit on handoff"))
    client = TestClient(service.app)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    return service, client, headers, opened


def job(service, **overrides):
    return service.store.add_job(
        {
            "url": "https://careers.example.com/job/123",
            "apply_url": "https://careers.example.com/job/123/apply",
            "title": "Security Engineer",
            "company": "Fixture",
            "status": "needs_review",
            "uncertain": True,
            "attempts": 1,
            "submission_checkpoint_at": "2026-10-14T15:00:00+00:00",
            "review_reason": "verification_required",
            "application": {
                "evidence": ["original-receipt-evidence.json"],
                "answers_supplied": {"known": "answer"},
            },
            **overrides,
        }
    )


def test_application_tab_uses_direct_route_and_preserves_uncertain_attempt(tab_api):
    service, client, headers, opened = tab_api
    saved = job(service)
    response = client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={})
    assert response.status_code == 200
    assert response.json()["mode"] == "default_browser"
    assert response.json()["receipt_tracking"] == "manual"
    assert opened == [saved["apply_url"]]
    assert service.store.get_job(saved["id"]) == saved
    assert service.store.metrics()["confirmed"] == 0


def test_posting_tab_uses_original_listing(tab_api):
    service, client, headers, opened = tab_api
    saved = job(service)
    response = client.post(
        f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={"purpose": "posting"}
    )
    assert response.status_code == 200
    assert opened == [saved["url"]]


def test_pre_update_dashboard_review_button_also_uses_regular_browser(tab_api):
    service, client, headers, opened = tab_api
    saved = job(service)
    response = client.post(f"/api/jobs/{saved['id']}/review", headers=headers, json={})
    assert response.status_code == 200
    assert response.json()["mode"] == "default_browser"
    assert opened == [saved["apply_url"]]
    assert service.store.get_job(saved["id"]) == saved


def test_authentication_handoff_opens_specific_employer_route(tab_api):
    service, client, headers, opened = tab_api
    saved = job(
        service, review_reason="auth_required", auth_url="https://careers.example.com/login/job/123"
    )
    response = client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={})
    assert response.status_code == 200
    assert opened == [saved["auth_url"]]
    assert service.store.get_job(saved["id"]) == saved


@pytest.mark.parametrize(
    "auth_url",
    [
        "https://www.linkedin.com/authwall?sessionRedirect=https%3A%2F%2Fwww.linkedin.com%2Fjobs%2Fview%2F4477156554%2F",
        "https://www.linkedin.com/login",
        "https://www.linkedin.com/feed/",
    ],
)
@pytest.mark.parametrize("nested", [False, True])
def test_linkedin_application_uses_specific_job_instead_of_saved_login_redirect(
    tab_api, auth_url, nested
):
    service, client, headers, opened = tab_api
    saved = job(
        service,
        url="https://www.linkedin.com/jobs/view/4477156554/",
        apply_url=None,
        auth_url=None if nested else auth_url,
        review_reason="auth_required",
        application={"auth_url": auth_url} if nested else {},
    )
    response = client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={})
    assert response.status_code == 200
    assert opened == [saved["url"]]
    assert service.store.get_job(saved["id"]) == saved


def test_linkedin_authwall_does_not_override_direct_employer_application(tab_api):
    service, client, headers, opened = tab_api
    saved = job(
        service,
        url="https://www.linkedin.com/jobs/view/4477156554/",
        auth_url="https://www.linkedin.com/authwall",
        review_reason="auth_required",
    )
    assert (
        client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={}).status_code
        == 200
    )
    assert opened == [saved["apply_url"]]


def test_bad_linkedin_apply_route_falls_back_to_original_job_and_legacy_button_uses_same_route(
    tab_api,
):
    service, client, headers, opened = tab_api
    saved = job(
        service,
        url="https://www.linkedin.com/jobs/view/4477156554/",
        apply_url="https://www.linkedin.com/login",
        auth_url="https://www.linkedin.com/authwall",
        review_reason="auth_required",
    )
    assert (
        client.post(f"/api/jobs/{saved['id']}/review", headers=headers, json={}).status_code == 200
    )
    assert opened == [saved["url"]]


def test_job_application_with_only_linkedin_login_routes_never_opens_feed(tab_api):
    service, client, headers, opened = tab_api
    saved = job(
        service,
        url="https://www.linkedin.com/feed/",
        apply_url=None,
        auth_url="https://www.linkedin.com/authwall?sessionRedirect=https%3A%2F%2Fevil.example%2F",
        review_reason="auth_required",
    )
    assert (
        client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={}).status_code
        == 409
    )
    assert opened == []


def test_opening_queued_application_holds_automation_to_avoid_duplicate_submit(tab_api):
    service, client, headers, opened = tab_api
    saved = job(
        service, status="prepared", uncertain=False, attempts=0, submission_checkpoint_at=None
    )
    response = client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={})
    assert response.status_code == 200
    current = service.store.get_job(saved["id"])
    assert current["status"] == "needs_review"
    assert current["review_reason"] == "manual_application"
    assert current["attempts"] == 0
    assert current["application"] == saved["application"]


def test_posting_view_does_not_hold_queued_job(tab_api):
    service, client, headers, opened = tab_api
    saved = job(service, status="queued", uncertain=False)
    response = client.post(
        f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={"purpose": "posting"}
    )
    assert response.status_code == 200
    assert service.store.get_job(saved["id"]) == saved


@pytest.mark.parametrize("status", ["preparing", "applying", "submitting"])
def test_application_handoff_refuses_busy_job(tab_api, status):
    service, client, headers, opened = tab_api
    saved = job(service, status=status)
    response = client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={})
    assert response.status_code == 409
    assert opened == []


def test_failed_browser_dispatch_cannot_change_application_state(tab_api, monkeypatch):
    service, client, headers, opened = tab_api
    from jobpilot import browser

    monkeypatch.setattr(
        browser,
        "open_browser_tab",
        lambda url: {"status": "error", "note": "OS browser handler unavailable"},
    )
    saved = job(service, status="queued", uncertain=False)
    response = client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={})
    assert response.status_code == 400
    assert "unavailable" in response.json()["detail"]
    assert service.store.get_job(saved["id"]) == saved


def test_regular_signin_tab_does_not_connect_or_requeue_worker(tab_api):
    service, client, headers, opened = tab_api
    saved = job(service, uncertain=False, review_reason="auth_required")
    response = client.post("/api/browser-tab", headers=headers, json={"platform": "linkedin"})
    assert response.status_code == 200
    assert opened == ["https://www.linkedin.com/jobs/"]
    assert service.store.get_job(saved["id"]) == saved


def test_pre_update_dashboard_login_also_uses_regular_browser(tab_api):
    service, client, headers, opened = tab_api
    response = client.post("/api/login", headers=headers, json={"platform": "linkedin"})
    assert response.status_code == 200
    assert response.json()["mode"] == "default_browser"
    assert opened == ["https://www.linkedin.com/jobs/"]


def test_employer_portal_requires_an_explicit_url(tab_api):
    service, client, headers, opened = tab_api
    response = client.post("/api/browser-tab", headers=headers, json={"platform": "employer"})
    assert response.status_code == 400
    assert opened == []


def test_normal_browser_endpoints_require_dashboard_token(tab_api):
    service, client, headers, opened = tab_api
    saved = job(service)
    assert client.post("/api/browser-tab", json={"platform": "linkedin"}).status_code == 403
    assert client.post(f"/api/jobs/{saved['id']}/browser-tab", json={}).status_code == 403
    assert opened == []


def test_invalid_purpose_does_not_dispatch(tab_api):
    service, client, headers, opened = tab_api
    saved = job(service)
    response = client.post(
        f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={"purpose": "invalid"}
    )
    assert response.status_code == 400
    assert opened == []


def test_manual_application_handoff_can_record_a_real_receipt(tab_api):
    service, client, headers, opened = tab_api
    saved = job(
        service, status="needs_review", uncertain=False, attempts=0, submission_checkpoint_at=None
    )
    client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={})
    response = client.post(
        f"/api/jobs/{saved['id']}/resolve",
        headers=headers,
        json={
            "outcome": "confirmed",
            "evidence": "Employer portal says application received, receipt 123.",
        },
    )
    assert response.status_code == 200
    current = service.store.get_job(saved["id"])
    assert current["status"] == "manually_verified"
    assert current["attempts"] == 0
    assert current["verification_method"] == "manual"
    assert current["browser_handoff"]["mode"] == "default_browser"
    assert current["browser_handoff"]["state"] == "closed"


def test_active_manual_handoff_holds_retry_until_outcome_recorded(tab_api):
    service, client, headers, opened = tab_api
    saved = job(service, uncertain=False, attempts=0)
    client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={})
    assert client.post(f"/api/jobs/{saved['id']}/retry", headers=headers).status_code == 409
    assert client.post(f"/api/jobs/{saved['id']}/prepare", headers=headers).status_code == 409
    assert (
        client.post(
            f"/api/jobs/{saved['id']}/resolve",
            headers=headers,
            json={
                "outcome": "not_submitted",
                "evidence": "Employer portal shows no submitted application.",
            },
        ).status_code
        == 200
    )
    current = service.store.get_job(saved["id"])
    assert current["browser_handoff"]["state"] == "closed"
    assert client.post(f"/api/jobs/{saved['id']}/retry", headers=headers).status_code == 200


def test_regular_browser_login_cannot_unlock_receipt_resolution(tab_api):
    service, client, headers, opened = tab_api
    saved = job(service, uncertain=False)
    client.post("/api/browser-tab", headers=headers, json={"platform": "linkedin"})
    response = client.post(
        f"/api/jobs/{saved['id']}/resolve",
        headers=headers,
        json={"outcome": "confirmed", "evidence": "Logged into LinkedIn."},
    )
    assert response.status_code == 409


@pytest.mark.parametrize("reason", ["auth_required", "unanswered_fields"])
def test_setup_changes_cannot_requeue_an_active_manual_tab(tab_api, reason):
    service, client, headers, opened = tab_api
    saved = job(service, uncertain=False, review_reason=reason)
    client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={})
    assert service.retry_setup_reviews(reason, "employer", saved["apply_url"]) == 0
    assert service.store.get_job(saved["id"])["status"] == "needs_review"


def test_setup_change_during_os_dispatch_cannot_leave_manual_application_queued(
    tab_api, monkeypatch
):
    service, client, headers, opened = tab_api
    from jobpilot import browser

    saved = job(service, uncertain=False, review_reason="unanswered_fields")

    def dispatch(url):
        assert service.retry_setup_reviews("unanswered_fields") == 1
        return {
            "status": "opened",
            "mode": "default_browser",
            "receipt_tracking": "manual",
            "url": url,
        }

    monkeypatch.setattr(browser, "open_browser_tab", dispatch)
    assert (
        client.post(f"/api/jobs/{saved['id']}/browser-tab", headers=headers, json={}).status_code
        == 200
    )
    current = service.store.get_job(saved["id"])
    assert current["status"] == "needs_review"
    assert service.setup_review_reason(current) is None
