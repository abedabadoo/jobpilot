"""Setup changes may retry blocked forms, never uncertain submissions."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def setup_api(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBPILOT_TESTING", "1")
    import jobpilot.service as service

    service = importlib.reload(service)
    service.store.set("settings", {**service.settings(), "application_mode": "legacy"})
    service.store.set("settings", {**service.settings(), "submission_enabled": True})
    client = TestClient(service.app)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    return service, client, headers


def held_job(service, slug, **overrides):
    return service.store.add_job(
        {
            "url": f"https://careers.example.com/{slug}",
            "title": "Security Engineer",
            "company": "Fixture",
            "location": "Cincinnati, OH",
            "status": "needs_review",
            "attempts": 1,
            "note": "Fields need saved answers or review: Are you authorized to work in the US?",
            **overrides,
        }
    )


def test_changed_answers_requeue_only_answer_held_forms_and_keep_artifacts(setup_api):
    service, client, headers = setup_api
    prepared = held_job(
        service,
        "prepared",
        documents={"resume_pdf": "fixture.pdf"},
        application={"evidence": ["review.png"]},
    )
    fresh = held_job(service, "without-documents")
    result = client.post(
        "/api/answers", headers=headers, json={"answers": {"@work_authorized_us": "Yes"}}
    )
    assert result.status_code == 200
    assert service.store.get_job(prepared["id"])["status"] == "prepared"
    assert service.store.get_job(fresh["id"])["status"] == "queued"
    assert service.store.get_job(prepared["id"])["documents"] == {"resume_pdf": "fixture.pdf"}
    assert service.store.get_job(prepared["id"])["application"]["evidence"] == ["review.png"]
    assert service.store.get_job(prepared["id"])["attempts"] == 1
    assert result.json()["requeued"] == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"uncertain": True},
        {"review_reason": "uncertain_submission"},
        {"status": "applying"},
        {"status": "submitting"},
        {"status": "preparing"},
        {"status": "confirmed"},
        {"status": "manually_verified"},
        {"status": "skipped"},
        {"status": "error"},
        {"status": "prepared"},
        {"note": "Login, CAPTCHA or verification requires your review"},
        {"note": "No supported application form was found; review the employer page"},
        {"note": "The source did not provide a usable job description or employer."},
    ],
)
def test_answer_change_never_requeues_other_gates_or_active_outcomes(setup_api, overrides):
    service, client, headers = setup_api
    job = held_job(service, "protected", **overrides)
    result = client.post(
        "/api/answers", headers=headers, json={"answers": {"@work_authorized_us": "Yes"}}
    )
    assert result.status_code == 200
    current = service.store.get_job(job["id"])
    assert current["status"] == job["status"]
    assert current.get("uncertain") == job.get("uncertain")
    assert current["note"] == job["note"]


def test_unchanged_answers_do_not_retry_again(setup_api):
    service, client, headers = setup_api
    answers = {"@work_authorized_us": "Yes"}
    service.store.set("answers", answers)
    job = held_job(service, "same-answers")
    result = client.post("/api/answers", headers=headers, json={"answers": answers})
    assert result.status_code == 200
    assert service.store.get_job(job["id"])["status"] == "needs_review"
    assert result.json()["requeued"] == 0


def test_explicit_unanswered_review_reason_supports_review_required_status(setup_api):
    service, client, headers = setup_api
    job = held_job(
        service,
        "structured",
        status="review_required",
        review_reason="unanswered_fields",
        note="See recorded screening fields.",
    )
    result = client.post(
        "/api/answers", headers=headers, json={"answers": {"@work_authorized_us": "Yes"}}
    )
    assert result.status_code == 200
    assert service.store.get_job(job["id"])["status"] == "queued"


def login_capture(monkeypatch):
    from jobpilot import browser

    capture = {}

    def opened(platform, url=None, settings=None, on_closed=None):
        capture["closed"] = on_closed
        return {
            "status": "opened",
            "note": "Fixture login browser opened",
            "platform": platform,
            "url": url,
        }

    monkeypatch.setattr(browser, "open_login", opened)
    return capture


@pytest.mark.parametrize("verified", [False, None, "true"])
def test_opening_or_unverified_closing_login_does_not_retry(setup_api, monkeypatch, verified):
    service, client, headers = setup_api
    job = held_job(
        service,
        "auth",
        url="https://www.linkedin.com/jobs/view/100",
        note="Login, CAPTCHA or verification requires your review",
    )
    capture = login_capture(monkeypatch)
    response = client.post(
        "/api/login", headers=headers, json={"mode": "isolated", "platform": "linkedin"}
    )
    assert response.status_code == 200
    assert service.store.get_job(job["id"])["status"] == "needs_review"
    assert callable(capture["closed"])
    capture["closed"](
        {"platform": "linkedin", "url": "https://www.linkedin.com/feed/", "verified": verified}
    )
    assert service.store.get_job(job["id"])["status"] == "needs_review"


def test_verified_login_retries_only_that_platform_and_never_uncertain_jobs(setup_api, monkeypatch):
    service, client, headers = setup_api
    auth_note = "Login, CAPTCHA or verification requires your review"
    matching = held_job(
        service,
        "match",
        url="https://www.linkedin.com/jobs/view/101",
        note=auth_note,
        documents={"resume_pdf": "fixture.pdf"},
    )
    other_site = held_job(
        service, "indeed", url="https://www.indeed.com/viewjob?jk=102", note=auth_note
    )
    uncertain = held_job(
        service,
        "uncertain",
        url="https://www.linkedin.com/jobs/view/103",
        note=auth_note,
        uncertain=True,
    )
    unanswered = held_job(service, "answers", url="https://www.linkedin.com/jobs/view/104")
    active = held_job(
        service,
        "active",
        url="https://www.linkedin.com/jobs/view/105",
        note=auth_note,
        status="applying",
    )
    capture = login_capture(monkeypatch)
    response = client.post(
        "/api/login", headers=headers, json={"mode": "isolated", "platform": "linkedin"}
    )
    assert response.status_code == 200
    assert callable(capture["closed"])
    capture["closed"](
        {"platform": "linkedin", "url": "https://www.linkedin.com/feed/", "verified": True}
    )
    assert service.store.get_job(matching["id"])["status"] == "prepared"
    for job in [other_site, uncertain, unanswered]:
        assert service.store.get_job(job["id"])["status"] == "needs_review"
    assert service.store.get_job(active["id"])["status"] == "applying"


def test_verified_employer_login_is_scoped_to_exact_host(setup_api, monkeypatch):
    service, client, headers = setup_api
    matching = held_job(
        service,
        "employer",
        note="Sign in is required",
        url="https://careers.alpha.example/jobs/1",
        review_reason="auth_required",
    )
    other = held_job(
        service,
        "other-employer",
        note="Sign in is required",
        url="https://careers.beta.example/jobs/2",
        review_reason="auth_required",
    )
    capture = login_capture(monkeypatch)
    response = client.post(
        "/api/login",
        headers=headers,
        json={
            "mode": "isolated",
            "platform": "employer",
            "url": "https://careers.alpha.example/login",
        },
    )
    assert response.status_code == 200
    assert callable(capture["closed"])
    capture["closed"](
        {"platform": "employer", "url": "https://careers.alpha.example/account", "verified": True}
    )
    assert service.store.get_job(matching["id"])["status"] == "queued"
    assert service.store.get_job(other["id"])["status"] == "needs_review"


def test_login_close_callback_is_consumed_once_even_if_form_blocks_again(setup_api, monkeypatch):
    service, client, headers = setup_api
    auth_note = "Login, CAPTCHA or verification requires your review"
    job = held_job(
        service, "one-attempt", url="https://www.linkedin.com/jobs/view/200", note=auth_note
    )
    capture = login_capture(monkeypatch)
    client.post("/api/login", headers=headers, json={"mode": "isolated", "platform": "linkedin"})
    assert callable(capture["closed"])
    completion = {"platform": "linkedin", "url": "https://www.linkedin.com/feed/", "verified": True}
    capture["closed"](completion)
    assert service.store.get_job(job["id"])["status"] == "queued"
    service.store.update_job(job["id"], status="needs_review", note=auth_note)
    capture["closed"](completion)
    assert service.store.get_job(job["id"])["status"] == "needs_review"


def test_mismatched_login_callback_cannot_retry_another_site(setup_api, monkeypatch):
    service, client, headers = setup_api
    job = held_job(
        service,
        "wrong-site",
        url="https://www.indeed.com/viewjob?jk=300",
        note="Login, CAPTCHA or verification requires your review",
    )
    capture = login_capture(monkeypatch)
    client.post("/api/login", headers=headers, json={"mode": "isolated", "platform": "linkedin"})
    assert callable(capture["closed"])
    capture["closed"](
        {"platform": "indeed", "url": "https://www.indeed.com/account", "verified": True}
    )
    assert service.store.get_job(job["id"])["status"] == "needs_review"


def test_application_retains_actual_authentication_site_for_setup_retry(setup_api, monkeypatch):
    service, client, headers = setup_api
    from jobpilot import browser

    job = held_job(
        service,
        "redirect",
        url="https://www.linkedin.com/jobs/view/400",
        status="prepared",
        documents={"resume_pdf": "fixture.pdf"},
    )
    monkeypatch.setattr(
        browser,
        "apply",
        lambda *args, **kwargs: {
            "status": "needs_review",
            "submitted": False,
            "evidence": ["review.png"],
            "note": "Login, CAPTCHA or verification requires your review",
            "review_reason": "auth_required",
            "auth_platform": "employer",
            "auth_url": "https://careers.alpha.example/login",
        },
    )
    service.apply_job(job["id"])
    current = service.store.get_job(job["id"])
    assert current["review_reason"] == "auth_required"
    assert current["auth_platform"] == "employer"
    assert current["auth_url"] == "https://careers.alpha.example/login"
    assert current["application"]["auth_platform"] == "employer"
    capture = login_capture(monkeypatch)
    client.post("/api/login", headers=headers, json={"mode": "isolated", "platform": "linkedin"})
    capture["closed"](
        {"platform": "linkedin", "url": "https://www.linkedin.com/feed/", "verified": True}
    )
    assert service.store.get_job(job["id"])["status"] == "needs_review"
    client.post(
        "/api/login",
        headers=headers,
        json={
            "mode": "isolated",
            "platform": "employer",
            "url": "https://careers.alpha.example/login",
        },
    )
    capture["closed"](
        {"platform": "employer", "url": "https://careers.alpha.example/account", "verified": True}
    )
    assert service.store.get_job(job["id"])["status"] == "prepared"


def test_new_adapter_result_clears_old_answer_gate_before_setup_retry(setup_api, monkeypatch):
    service, client, headers = setup_api
    from jobpilot import browser

    job = held_job(
        service,
        "obsolete-gate",
        status="prepared",
        review_reason="unanswered_fields",
        documents={"resume_pdf": "fixture.pdf"},
    )
    monkeypatch.setattr(
        browser,
        "apply",
        lambda *args, **kwargs: {
            "status": "needs_review",
            "submitted": False,
            "evidence": [],
            "note": "No supported application form was found; review the employer page",
        },
    )
    service.apply_job(job["id"])
    client.post("/api/answers", headers=headers, json={"answers": {"@work_authorized_us": "Yes"}})
    current = service.store.get_job(job["id"])
    assert current["status"] == "needs_review"
    assert current.get("review_reason") is None


def test_initial_classification_excludes_security_sales_role(setup_api):
    service, _, _ = setup_api
    job = service.classify_job(
        {
            "url": "https://careers.example.com/sales",
            "title": "Security Sales Engineer",
            "company": "Fixture",
            "location": "Cincinnati, OH",
            "description": "Develop commercial security-product sales, customer demos, and channel opportunities. "
            * 3,
        },
        service.store.get("profile"),
        service.settings(),
    )
    assert job["status"] == "skipped"


def test_queued_legacy_sales_role_is_reassessed_before_any_application(setup_api, monkeypatch):
    service, _, _ = setup_api
    from jobpilot import browser

    job = held_job(
        service,
        "legacy-role",
        title="Security Sales Engineer",
        status="prepared",
        location="Cincinnati, OH",
        documents={"resume_pdf": "fixture.pdf"},
        description="Security engineering skills and experience for a Cincinnati employer. " * 3,
    )
    monkeypatch.setattr(
        browser,
        "apply",
        lambda *args, **kwargs: {
            "status": "confirmed",
            "submitted": True,
            "evidence": ["fixture-receipt"],
        },
    )
    service.apply_job(job["id"])
    current = service.store.get_job(job["id"])
    assert current["status"] == "skipped"
    assert current["attempts"] == 1
    assert service.store.metrics()["confirmed"] == 0


def test_senior_title_alone_does_not_hold_a_prepared_security_role(setup_api, monkeypatch):
    service, _, _ = setup_api
    from jobpilot import browser

    job = held_job(
        service,
        "stretch-role",
        title="Senior Cloud Security Engineer",
        status="prepared",
        location="Cincinnati, OH",
        documents={"resume_pdf": "fixture.pdf"},
        description="AWS cloud security, Linux and Python engineering. " * 3,
    )
    monkeypatch.setattr(
        browser,
        "apply",
        lambda *args, **kwargs: {
            "status": "needs_review",
            "submitted": False,
            "evidence": [],
            "note": "Fixture stopped before any submission",
        },
    )
    service.apply_job(job["id"])
    assert service.store.get_job(job["id"])["attempts"] == 2
    assert service.store.get_job(job["id"])["status"] == "needs_review"
    assert service.store.metrics()["confirmed"] == 0


def test_initial_classification_retains_collector_application_route(setup_api):
    service, _, _ = setup_api
    job = service.classify_job(
        {
            "url": "https://www.linkedin.com/jobs/view/500",
            "title": "Security Engineer",
            "company": "Fixture",
            "location": "Cincinnati, OH",
            "description": "AWS cloud security and ISO 27001 operations with Linux and Python. "
            * 3,
            "source_url": "https://www.linkedin.com/jobs/view/500",
            "apply_url": "https://careers.example.com/jobs/500",
        },
        service.store.get("profile"),
        service.settings(),
    )
    assert job["apply_url"] == "https://careers.example.com/jobs/500"
    assert job["source_url"] == "https://www.linkedin.com/jobs/view/500"


def test_prepared_remote_role_excluding_ohio_cannot_reach_adapter(setup_api, monkeypatch):
    service, _, _ = setup_api
    from jobpilot import browser

    job = held_job(
        service,
        "wrong-state",
        status="prepared",
        location="Remote - US, California",
        documents={"resume_pdf": "fixture.pdf"},
    )
    monkeypatch.setattr(
        browser,
        "apply",
        lambda *args, **kwargs: {
            "status": "confirmed",
            "submitted": True,
            "evidence": ["fixture-receipt"],
        },
    )
    service.apply_job(job["id"])
    current = service.store.get_job(job["id"])
    assert current["status"] == "skipped"
    assert current["attempts"] == 1
    assert service.store.metrics()["confirmed"] == 0


def test_answers_changed_during_form_inspection_get_one_pass_with_fresh_answers(
    setup_api, monkeypatch
):
    service, _, _ = setup_api
    from jobpilot import browser

    job = held_job(
        service, "answer-race", status="prepared", documents={"resume_pdf": "fixture.pdf"}
    )

    def inspecting(job, profile, answers, documents, settings, checkpoint=None):
        assert answers == {}
        result = service.save_answers({"answers": {"@work_authorized_us": "Yes"}})
        assert result["requeued"] == 0  # The in-progress job must stay protected.
        return {
            "status": "needs_review",
            "submitted": False,
            "evidence": [],
            "review_reason": "unanswered_fields",
            "note": "Fields need saved answers or review: US work authorization",
        }

    monkeypatch.setattr(browser, "apply", inspecting)
    service.apply_job(job["id"])
    current = service.store.get_job(job["id"])
    assert current["status"] == "prepared"
    assert not current["uncertain"]
    assert current["attempts"] == 2


@pytest.mark.parametrize(
    ("outcome", "submitted", "evidence"),
    [
        ("needs_review", True, ["uncertain.png"]),
        ("confirmed", True, ["receipt.png"]),
        ("error", False, []),
    ],
)
def test_answer_race_does_not_requeue_submitted_or_non_answer_outcomes(
    setup_api, monkeypatch, outcome, submitted, evidence
):
    service, _, _ = setup_api
    from jobpilot import browser

    job = held_job(
        service, "protected-answer-race", status="prepared", documents={"resume_pdf": "fixture.pdf"}
    )

    def inspecting(job, profile, answers, documents, settings, checkpoint=None):
        service.save_answers({"answers": {"@work_authorized_us": "Yes"}})
        return {
            "status": outcome,
            "submitted": submitted,
            "evidence": evidence,
            "review_reason": "unanswered_fields",
            "note": "Fields need saved answers or review: US authorization",
        }

    monkeypatch.setattr(browser, "apply", inspecting)
    service.apply_job(job["id"])
    assert service.store.get_job(job["id"])["status"] == outcome


@pytest.mark.parametrize("alias", ["apply_url", "source_url"])
def test_manual_import_rejects_private_application_or_source_alias(setup_api, alias):
    service, client, headers = setup_api
    response = client.post(
        "/api/import",
        headers=headers,
        json={
            "url": "https://example.com/jobs/safe-import",
            "title": "Security Engineer",
            "company": "Fixture",
            "location": "Cincinnati, OH",
            "description": "AWS cloud security engineering with Linux, Python and ISO 27001 evidence operations. "
            * 3,
            alias: "http://127.0.0.1/private-admin",
        },
    )
    assert response.status_code == 400
    assert service.store.jobs() == []


def test_open_login_browser_waits_without_holding_or_counting_queued_jobs(setup_api, monkeypatch):
    service, _, _ = setup_api
    from jobpilot import browser

    job = held_job(
        service, "login-wait", status="prepared", documents={"resume_pdf": "fixture.pdf"}
    )
    monkeypatch.setattr(browser, "login_in_progress", lambda: True, raising=False)
    monkeypatch.setattr(
        browser,
        "apply",
        lambda *args, **kwargs: pytest.fail(
            "Do not inspect applications during interactive sign-in"
        ),
    )
    service.apply_job(job["id"])
    current = service.store.get_job(job["id"])
    assert current["status"] == "prepared"
    assert current["attempts"] == 1
