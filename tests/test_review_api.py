"""Receipt verification never retries an uncertain submission."""

import importlib
import threading

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def review_api(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBPILOT_TESTING", "1")
    import jobpilot.service as service
    from jobpilot import browser

    service = importlib.reload(service)
    monkeypatch.setattr(browser, "login_in_progress", lambda: False)
    client = TestClient(service.app)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    return service, client, headers


def artifact(service, name, folder="evidence"):
    path = service.DATA / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Fixture evidence only", encoding="utf-8")
    return str(path)


def uncertain_job(service, **overrides):
    documents = {"resume_pdf": artifact(service, "resume.pdf", "applications")}
    evidence = [artifact(service, "before-submit.json")]
    return service.store.add_job(
        {
            "url": "https://careers.example.com/job/receipt-review",
            "title": "Security Engineer",
            "company": "Fixture",
            "status": "needs_review",
            "uncertain": True,
            "attempts": 1,
            "submission_checkpoint_at": "2026-10-14T15:00:00+00:00",
            "review_reason": "verification_required",
            "documents": documents,
            "note": "CAPTCHA challenge requires your review after submit was attempted; no receipt verified. Check the existing attempt before retrying.",
            "application": {
                "status": "needs_review",
                "documents": documents,
                "answers_supplied": {"@work_authorized_us": "Yes"},
                "evidence": evidence,
                "review_reason": "verification_required",
            },
            **overrides,
        }
    )


def open_capture(monkeypatch, service, synchronous=None, result=None):
    from jobpilot import browser

    capture = {}

    def opened(job, profile, answers, documents, settings, on_closed=None):
        capture.update(
            job=job,
            answers=answers,
            documents=documents,
            closed=on_closed,
            saved_nonce=service.store.get_job(job["id"]).get("review_session", {}).get("nonce"),
        )
        if synchronous:
            on_closed(synchronous)
        return result or {"status": "opened", "note": "Prepared verification browser opened"}

    monkeypatch.setattr(browser, "open_review", opened, raising=False)
    monkeypatch.setattr(
        browser, "apply", lambda *args, **kwargs: pytest.fail("Receipt review must not apply")
    )
    return capture


def open_review(client, headers, job):
    return client.post(f"/api/jobs/{job['id']}/review", headers=headers, json={"mode": "isolated"})


def confirmed_outcome(service, **overrides):
    return {
        "status": "confirmed",
        "submitted": False,
        "receipt": "Your application has been submitted successfully.",
        "note": "New explicit receipt observed after user verification.",
        "url": "https://careers.example.com/job/receipt-review/thanks",
        "evidence": [artifact(service, "new-receipt.json")],
        **overrides,
    }


def test_opening_review_keeps_original_uncertain_checkpoint_and_uses_original_answers(
    review_api, monkeypatch
):
    service, client, headers = review_api
    job = uncertain_job(service)
    service.store.set("answers", {"@work_authorized_us": "No"})
    capture = open_capture(monkeypatch, service)
    response = open_review(client, headers, job)
    assert response.status_code == 200
    assert response.json()["status"] == "opened"
    current = service.store.get_job(job["id"])
    assert current["status"] == "needs_review" and current["uncertain"] is True
    assert current["attempts"] == job["attempts"]
    assert current["submission_checkpoint_at"] == job["submission_checkpoint_at"]
    assert current["application"] == job["application"]
    assert capture["answers"] == job["application"]["answers_supplied"]
    assert capture["documents"] == job["documents"]
    assert capture["saved_nonce"] == current["review_session"]["nonce"]
    assert current["review_session"]["state"] == "opened"
    assert service.store.metrics()["confirmed"] == 0


def test_new_receipt_callback_confirms_only_the_existing_attempt_and_keeps_package(
    review_api, monkeypatch
):
    service, client, headers = review_api
    job = uncertain_job(service)
    capture = open_capture(monkeypatch, service)
    open_review(client, headers, job)
    outcome = confirmed_outcome(service)
    capture["closed"](outcome)
    current = service.store.get_job(job["id"])
    assert current["status"] == "confirmed" and current["uncertain"] is False
    assert current["confirmed_at"]
    assert current["verification_method"] == "user_assisted_receipt"
    assert "user-assisted" in current["note"].casefold()
    assert current["documents"] == job["documents"]
    assert current["application"]["answers_supplied"] == job["application"]["answers_supplied"]
    assert (
        current["application"]["evidence"] == job["application"]["evidence"] + outcome["evidence"]
    )
    assert current["submission_checkpoint_at"] == job["submission_checkpoint_at"]
    assert current["attempts"] == 1
    assert service.store.metrics()["confirmed"] == 1


def test_callback_can_arrive_before_open_review_returns(review_api, monkeypatch):
    service, client, headers = review_api
    job = uncertain_job(service)
    open_capture(monkeypatch, service, synchronous=confirmed_outcome(service))
    response = open_review(client, headers, job)
    assert response.status_code == 200
    current = service.store.get_job(job["id"])
    assert current["status"] == "confirmed"
    assert current["review_session"]["state"] == "closed"


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "confirmed"},
        {"status": "manually_verified"},
        {"status": "applying"},
        {"status": "submitting"},
        {"status": "prepared"},
        {"status": "skipped"},
        {"uncertain": False},
        {"submission_checkpoint_at": None},
        {"documents": {}},
        {"application": {"evidence": []}},
        {"review_reason": "uncertain_submission"},
        {"review_reason": "auth_required"},
        {"review_reason": "unanswered_fields"},
    ],
)
def test_only_proven_post_submit_verification_holds_can_open(review_api, monkeypatch, overrides):
    service, client, headers = review_api
    job = uncertain_job(service, **overrides)
    from jobpilot import browser

    monkeypatch.setattr(
        browser,
        "open_review",
        lambda *args, **kwargs: pytest.fail("Guard must refuse launch"),
        raising=False,
    )
    assert open_review(client, headers, job).status_code == 409
    assert service.store.get_job(job["id"])["status"] == job["status"]


@pytest.mark.parametrize(
    "note",
    [
        "CAPTCHA challenge requires your review after submit was attempted; no receipt verified. Check the existing attempt before retrying.",
        "Email verification requires your review after submit was attempted; no receipt verified. Check the existing attempt before retrying.",
    ],
)
def test_exact_legacy_verification_note_is_accepted_with_real_checkpoint(
    review_api, monkeypatch, note
):
    service, client, headers = review_api
    job = uncertain_job(
        service,
        review_reason=None,
        note=note,
        application={"evidence": [artifact(service, "legacy.json")]},
    )
    open_capture(monkeypatch, service)
    assert open_review(client, headers, job).status_code == 200


@pytest.mark.parametrize(
    "note",
    [
        "Login, CAPTCHA or verification requires your review",
        "Submission outcome uncertain after interruption. Verify receipt before any retry.",
        "CAPTCHA challenge requires your review",
    ],
)
def test_unstructured_login_or_uncertainty_note_is_not_a_verification_handoff(
    review_api, monkeypatch, note
):
    service, client, headers = review_api
    job = uncertain_job(
        service,
        review_reason=None,
        note=note,
        application={"evidence": [artifact(service, "legacy-refused.json")]},
    )
    open_capture(monkeypatch, service)
    assert open_review(client, headers, job).status_code == 409


@pytest.mark.parametrize(
    "outcome_overrides",
    [
        {"evidence": []},
        {"evidence": ["missing-receipt.json"]},
        {"receipt": ""},
        {"receipt": None},
        {"submitted": True},
        {"submitted": None},
    ],
)
def test_callback_without_new_real_receipt_evidence_remains_uncertain(
    review_api, monkeypatch, outcome_overrides
):
    service, client, headers = review_api
    job = uncertain_job(service)
    capture = open_capture(monkeypatch, service)
    open_review(client, headers, job)
    capture["closed"](confirmed_outcome(service, **outcome_overrides))
    current = service.store.get_job(job["id"])
    assert current["status"] == "needs_review" and current["uncertain"]
    assert current["submission_checkpoint_at"] == job["submission_checkpoint_at"]
    assert current["documents"] == job["documents"]
    assert service.store.metrics()["confirmed"] == 0


def test_initial_evidence_cannot_be_reused_as_a_new_receipt(review_api, monkeypatch):
    service, client, headers = review_api
    job = uncertain_job(service)
    capture = open_capture(monkeypatch, service)
    open_review(client, headers, job)
    capture["closed"](confirmed_outcome(service, evidence=job["application"]["evidence"]))
    assert service.store.get_job(job["id"])["uncertain"]


def test_no_receipt_close_and_duplicate_callback_leave_hold_intact(review_api, monkeypatch):
    service, client, headers = review_api
    job = uncertain_job(service)
    capture = open_capture(monkeypatch, service)
    open_review(client, headers, job)
    capture["closed"](
        {
            "status": "needs_review",
            "submitted": False,
            "note": "Verification browser closed.",
            "evidence": [],
        }
    )
    first = service.store.get_job(job["id"])
    assert first["status"] == "needs_review" and first["uncertain"]
    assert "without a new receipt" in first["note"].casefold()
    capture["closed"](confirmed_outcome(service))
    assert service.store.get_job(job["id"]) == first


@pytest.mark.parametrize(
    "change",
    [
        {"status": "confirmed", "uncertain": False},
        {"status": "manually_verified", "uncertain": False},
        {"status": "skipped"},
        {"status": "applying"},
        {"uncertain": False},
        {"submission_checkpoint_at": "different"},
        {"review_session": {"nonce": "newer-session"}},
    ],
)
def test_stale_callback_never_changes_a_resolved_or_different_session(
    review_api, monkeypatch, change
):
    service, client, headers = review_api
    job = uncertain_job(service)
    capture = open_capture(monkeypatch, service)
    open_review(client, headers, job)
    service.store.update_job(job["id"], **change)
    before = service.store.get_job(job["id"])
    capture["closed"](confirmed_outcome(service))
    assert service.store.get_job(job["id"]) == before


def test_concurrent_browser_and_duplicate_session_are_refused(review_api, monkeypatch):
    service, client, headers = review_api
    from jobpilot import browser

    job = uncertain_job(service)
    capture = open_capture(monkeypatch, service)
    monkeypatch.setattr(browser, "login_in_progress", lambda: True)
    assert open_review(client, headers, job).status_code == 409
    monkeypatch.setattr(browser, "login_in_progress", lambda: False)
    assert open_review(client, headers, job).status_code == 200
    assert open_review(client, headers, job).status_code == 409
    capture["closed"]({"status": "needs_review", "submitted": False, "evidence": []})
    assert open_review(client, headers, job).status_code == 200


def test_active_application_lock_refuses_verification_but_search_alone_does_not(
    review_api, monkeypatch
):
    service, client, headers = review_api
    job = uncertain_job(service)
    open_capture(monkeypatch, service)
    entered, release = threading.Event(), threading.Event()

    def busy():
        with service.application_lock:
            entered.set()
            release.wait(5)

    thread = threading.Thread(target=busy)
    thread.start()
    assert entered.wait(2)
    try:
        assert open_review(client, headers, job).status_code == 409
    finally:
        release.set()
        thread.join(5)
    service.worker["searching"] = True
    assert open_review(client, headers, job).status_code == 200


def test_shutdown_refuses_while_interactive_verification_browser_is_open(review_api, monkeypatch):
    service, client, headers = review_api
    from jobpilot import browser

    service.store.set(
        "settings", {**service.settings(), "search_enabled": True, "submission_enabled": True}
    )
    monkeypatch.setattr(browser, "login_in_progress", lambda: True)
    response = client.post("/api/control", headers=headers, json={"action": "shutdown"})
    assert response.status_code == 409
    assert service.settings()["search_enabled"] and service.settings()["submission_enabled"]
