import importlib
import json
import threading
import time

import pytest
from test_api import api


@pytest.fixture
def assist(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    from jobpilot import service

    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    return service, client, headers


def add(service, slug="job", **extra):
    return service.store.add_job(
        {
            "url": f"https://example.com/jobs/{slug}",
            "title": "Security Engineer",
            "company": "Example",
            "location": "Cincinnati, OH",
            "description": "AWS cloud security, Python automation and access reviews. " * 3,
            **extra,
        }
    )


def test_external_link_honors_the_visible_posting_target(assist, monkeypatch):
    service, client, headers = assist
    from jobpilot import links

    job = add(service, apply_url="https://apply.example.com/jobs/123")
    opened = []
    monkeypatch.setattr(
        links,
        "open_external_url",
        lambda url: opened.append(url) or {"status": "opened", "opened": True, "url": url},
    )
    result = client.post(
        "/api/browser/open_external", headers=headers, json={"job_id": job["id"], "url": job["url"]}
    )
    assert result.status_code == 200
    assert opened == [job["url"]]


def test_undo_applied_before_queued_regeneration_does_not_resurrect_applied_state(
    assist, monkeypatch
):
    service, client, headers = assist
    job = add(service, status="prepared", documents={"resume_pdf": "fixture.pdf"})
    service.store.mark_applied(job["id"], True)
    assert (
        client.post(f"/api/jobs/{job['id']}/prepare", headers=headers, json={}).status_code == 200
    )
    service.store.mark_applied(job["id"], False)
    monkeypatch.setattr(
        service,
        "prepare",
        lambda *args: {
            "resume_pdf": "new.pdf",
            "generation_mode": "deterministic",
            "generation_note": "Ready",
        },
    )
    service.prepare_job(job["id"])
    updated = service.store.get_job(job["id"])
    assert updated["applied"] is False
    assert updated["status"] == "prepared"


def test_assist_mode_neutralizes_old_submission_and_remote_settings(assist, monkeypatch):
    service, client, _ = assist
    service.store.set(
        "settings",
        {"search_enabled": True, "submission_enabled": True, "remote_intervention_enabled": True},
    )
    service = importlib.reload(service)
    conf = service.settings()
    assert conf["application_mode"] == "assist"
    assert conf["search_enabled"] is True
    assert conf["submission_enabled"] is False
    assert conf["remote_intervention_enabled"] is False
    assert service.store.get("settings")["submission_enabled"] is False


@pytest.mark.parametrize("mode", ["assist", "legacy"])
def test_startup_releases_old_default_browser_tracking_only_in_assist_mode(assist, mode):
    service, client, headers = assist
    service.store.set("settings", {**service.settings(), "application_mode": mode})
    handoff = {
        "mode": "default_browser",
        "state": "opened",
        "opened_at": "2026-10-26T12:00:00Z",
        "purpose": "application",
    }
    draft = add(
        service,
        "held-documents",
        status="needs_review",
        uncertain=True,
        browser_handoff=handoff,
    )
    removable = add(service, "held-removal", browser_handoff=handoff)
    closed = add(
        service,
        "closed-handoff",
        browser_handoff={**handoff, "state": "closed", "outcome": "applied"},
    )

    with client:
        current = service.store.get_job(draft["id"])
        assert current["uncertain"] is True
        assert service.store.get_job(closed["id"])["browser_handoff"] == closed["browser_handoff"]
        if mode == "legacy":
            assert current["browser_handoff"] == handoff
            assert (
                client.post(f"/api/jobs/{draft['id']}/prepare", headers=headers).status_code == 409
            )
            assert (
                client.post(f"/api/jobs/{removable['id']}/remove", headers=headers).status_code
                == 409
            )
        else:
            recovered = current["browser_handoff"]
            assert recovered["state"] == "closed"
            assert recovered["previous_state"] == "opened"
            assert recovered["closed_reason"] == "assist_workflow"
            assert recovered["opened_at"] == "2026-10-26T12:00:00Z"
            assert recovered["purpose"] == "application"
            assert (
                client.post(f"/api/jobs/{draft['id']}/prepare", headers=headers).status_code == 200
            )
            assert (
                client.post(f"/api/jobs/{removable['id']}/remove", headers=headers).status_code
                == 200
            )


def test_assist_controls_cannot_enable_application_or_remote_actions(assist, monkeypatch):
    service, client, headers = assist
    from jobpilot import browser

    monkeypatch.setattr(browser, "apply", lambda *a, **k: pytest.fail("No automated apply"))
    monkeypatch.setattr(service.remote_runtime, "start_async", lambda: pytest.fail("No remote"))
    monkeypatch.setattr(service.remote_runtime, "pairing_link", lambda: pytest.fail("No pairing"))
    assert (
        client.post(
            "/api/control", headers=headers, json={"action": "start", "submission_enabled": True}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/settings",
            headers=headers,
            json={"submission_enabled": True, "application_mode": "legacy"},
        ).status_code
        == 200
    )
    assert service.settings()["submission_enabled"] is False
    assert service.settings()["application_mode"] == "assist"
    assert (
        client.post("/api/remote/control", headers=headers, json={"action": "enable"}).status_code
        == 409
    )
    assert client.post("/api/remote/setup", headers=headers, json={}).status_code == 409
    job = add(service, status="prepared", documents={"resume_pdf": "fixture.pdf"})
    service.apply_job(job["id"])
    assert service.store.get_job(job["id"])["attempts"] == 0


def test_manual_applied_toggle_needs_no_receipt_and_preserves_documents(assist):
    service, client, headers = assist
    job = add(
        service, status="needs_review", uncertain=True, documents={"resume_pdf": "fixture.pdf"}
    )
    assert client.post(f"/api/jobs/{job['id']}/applied", json={"applied": True}).status_code == 403
    result = client.post(f"/api/jobs/{job['id']}/applied", headers=headers, json={"applied": True})
    assert result.status_code == 200
    marked = result.json()["job"]
    assert marked["status"] == "applied" and marked["applied"] is True
    assert marked["applied_at"]
    assert marked["documents"] == job["documents"]
    metrics = client.get("/api/state").json()["metrics"]
    assert metrics["applied"] == 1 and metrics["confirmed"] == 0
    assert metrics["applied_today"] == 1
    result = client.post(f"/api/jobs/{job['id']}/applied", headers=headers, json={"applied": False})
    assert result.status_code == 200
    assert result.json()["job"]["status"] == "needs_review"
    assert not result.json()["job"]["applied_at"]
    assert client.get("/api/state").json()["metrics"]["applied"] == 0


def test_remove_is_permanent_and_does_not_delete_artifacts(assist, tmp_path):
    service, client, headers = assist
    artifact = tmp_path / "resume.pdf"
    artifact.write_text("fixture", encoding="utf-8")
    job = add(service, documents={"resume_pdf": str(artifact)})
    result = client.post(f"/api/jobs/{job['id']}/remove", headers=headers, json={})
    assert result.status_code == 200 and result.json()["deleted_count"] == 1
    assert service.store.get_job(job["id"]) is None
    assert service.store.add_job({"url": job["url"], "title": "Rediscovered"}) is None
    assert artifact.read_text(encoding="utf-8") == "fixture"


@pytest.mark.parametrize("status", ["preparing", "applying", "submitting"])
def test_manual_tracking_cannot_remove_or_reclassify_active_work(assist, status):
    service, client, headers = assist
    job = add(service, status=status)
    assert client.post(f"/api/jobs/{job['id']}/remove", headers=headers, json={}).status_code == 409
    assert (
        client.post(
            f"/api/jobs/{job['id']}/applied", headers=headers, json={"applied": True}
        ).status_code
        == 409
    )
    assert service.store.get_job(job["id"])["status"] == status


def test_document_request_queues_immediately_while_another_document_is_generating(assist):
    service, client, headers = assist
    job = add(service, status="applied", applied=True, applied_at=service.store.now())
    entered, release = threading.Event(), threading.Event()

    def busy():
        with service.application_lock:
            entered.set()
            release.wait(4)

    thread = threading.Thread(target=busy)
    thread.start()
    assert entered.wait(1)
    try:
        started = time.monotonic()
        result = client.post(f"/api/jobs/{job['id']}/prepare", headers=headers, json={})
        assert time.monotonic() - started < 1
        assert result.status_code == 200 and result.json()["queued"] is True
        assert service.store.get_job(job["id"])["preparation_requested"] is True
    finally:
        release.set()
        thread.join(2)


def test_accepted_shutdown_stops_new_document_queue_work_immediately(assist, monkeypatch):
    service, client, headers = assist
    job = add(service, preparation_requested=True)
    monkeypatch.setattr(service, "prepare", lambda *a, **k: pytest.fail("Service is stopping"))

    response = client.post("/api/control", headers=headers, json={"action": "shutdown"})

    assert response.status_code == 200
    assert service.stop_event.is_set()
    service.process_document_queue()
    current = service.store.get_job(job["id"])
    assert current["status"] == "queued" and current["preparation_requested"] is True


@pytest.mark.parametrize("busy_field", ["searching", "submitting", "current"])
def test_rejected_busy_shutdown_keeps_document_worker_running(assist, busy_field):
    service, client, headers = assist
    service.worker[busy_field] = "Active job" if busy_field == "current" else True

    response = client.post("/api/control", headers=headers, json={"action": "shutdown"})

    assert response.status_code == 409
    assert not service.stop_event.is_set()


def test_shutdown_stops_document_work_already_waiting_for_the_application_lock(assist, monkeypatch):
    service, _, _ = assist
    job = add(service, preparation_requested=True)
    selected = threading.Event()
    drafted = []
    original_jobs = service.store.jobs

    def select_jobs():
        rows = original_jobs()
        selected.set()
        return rows

    def prepare(*args, **kwargs):
        drafted.append(True)
        return {
            "resume_pdf": "unexpected.pdf",
            "generation_note": "Known facts",
            "generation_mode": "deterministic",
        }

    monkeypatch.setattr(service.store, "jobs", select_jobs)
    monkeypatch.setattr(service, "prepare", prepare)
    with service.application_lock:
        pending = threading.Thread(target=service.process_document_queue)
        pending.start()
        assert selected.wait(2)
        assert service.control({"action": "shutdown"})["ok"] is True
    pending.join(2)

    assert not pending.is_alive()
    assert drafted == []
    assert service.store.get_job(job["id"])["status"] == "queued"


def test_assist_document_worker_prepares_without_any_application_browser(assist, monkeypatch):
    service, _, _ = assist
    from jobpilot import browser

    job = add(service)
    monkeypatch.setattr(browser, "apply", lambda *a, **k: pytest.fail("No automated apply"))
    monkeypatch.setattr(
        service,
        "prepare",
        lambda *a, **k: {
            "resume_pdf": "fixture.pdf",
            "generation_note": "Known facts",
            "generation_mode": "deterministic",
        },
    )
    service.process_document_queue()
    current = service.store.get_job(job["id"])
    assert current["status"] == "prepared" and current["attempts"] == 0
    assert current["documents"]["resume_pdf"] == "fixture.pdf"


def test_regenerating_manual_applied_documents_preserves_tracking(assist, monkeypatch):
    service, client, headers = assist
    job = add(service, status="applied", applied=True, applied_at=service.store.now())
    monkeypatch.setattr(
        service,
        "prepare",
        lambda *a, **k: {
            "resume_pdf": "new.pdf",
            "generation_note": "Known facts",
            "generation_mode": "deterministic",
        },
    )
    assert client.post(f"/api/jobs/{job['id']}/prepare", headers=headers).status_code == 200
    service.process_document_queue()
    current = service.store.get_job(job["id"])
    assert current["status"] == "applied" and current["applied"] is True
    assert current["applied_at"] == job["applied_at"]
    assert current["documents"]["resume_pdf"] == "new.pdf"


def test_explicit_uncertain_document_request_preserves_submission_history(assist, monkeypatch):
    service, client, headers = assist
    job = add(
        service,
        status="needs_review",
        uncertain=True,
        attempts=1,
        submission_checkpoint_at="2026-10-26T12:00:00Z",
        note="Submission outcome uncertain. Verify the receipt.",
        documents={"resume_pdf": "old.pdf"},
        application={"status": "needs_review", "evidence": ["receipt-check.png"]},
    )
    monkeypatch.setattr(service, "apply_job", lambda *a, **k: pytest.fail("No automated apply"))
    monkeypatch.setattr(
        service,
        "prepare",
        lambda *a, **k: {
            "resume_pdf": "new.pdf",
            "generation_note": "Known facts",
            "generation_mode": "deterministic",
        },
    )

    response = client.post(f"/api/jobs/{job['id']}/prepare", headers=headers, json={})
    assert response.status_code == 200 and response.json()["queued"] is True
    assert service.store.get_job(job["id"])["preparation_requested"] is True
    service.process_document_queue()

    current = service.store.get_job(job["id"])
    assert current["status"] == "needs_review" and current["uncertain"] is True
    assert current["documents"]["resume_pdf"] == "new.pdf"
    assert current["attempts"] == 1
    assert current["submission_checkpoint_at"] == "2026-10-26T12:00:00Z"
    assert current["application"]["evidence"] == ["receipt-check.png"]
    assert "Submission outcome uncertain" in current["note"]
    assert current["preparation_requested"] is False


def test_uncertain_jobs_require_an_explicit_document_request(assist, monkeypatch):
    service, _, _ = assist
    job = add(service, uncertain=True)
    monkeypatch.setattr(service, "prepare", lambda *a, **k: pytest.fail("No implicit drafting"))
    service.process_document_queue()
    current = service.store.get_job(job["id"])
    assert current["status"] == "queued" and current["uncertain"] is True
    assert not current.get("documents")


def test_legacy_uncertain_document_requests_remain_held(assist, monkeypatch):
    service, client, headers = assist
    service.store.set("settings", {**service.settings(), "application_mode": "legacy"})
    job = add(service, status="needs_review", uncertain=True, preparation_requested=True)
    monkeypatch.setattr(service, "prepare", lambda *a, **k: pytest.fail("Legacy receipt is held"))
    assert (
        client.post(f"/api/jobs/{job['id']}/prepare", headers=headers, json={}).status_code == 409
    )
    service.process_document_queue()
    service.prepare_job(job["id"])
    current = service.store.get_job(job["id"])
    assert current["status"] == "needs_review" and current["uncertain"] is True
    assert not current.get("documents")


@pytest.mark.parametrize(
    "active_work",
    [
        {"status": "preparing"},
        {"status": "applying"},
        {"status": "submitting"},
        {"review_session": {"state": "opening"}},
        {"review_session": {"state": "opened"}},
        {"browser_handoff": {"mode": "default_browser", "state": "opened"}},
    ],
)
def test_uncertain_document_drafting_waits_for_active_work(assist, monkeypatch, active_work):
    service, client, headers = assist
    job = add(service, uncertain=True, preparation_requested=True, **active_work)
    monkeypatch.setattr(service, "prepare", lambda *a, **k: pytest.fail("Active work is held"))
    assert (
        client.post(f"/api/jobs/{job['id']}/prepare", headers=headers, json={}).status_code == 409
    )
    service.process_document_queue()
    service.prepare_job(job["id"])
    assert not service.store.get_job(job["id"]).get("documents")


def test_a_blocked_document_request_does_not_starve_other_jobs(assist, monkeypatch):
    service, _, _ = assist
    blocked = add(
        service,
        "blocked",
        browser_handoff={"mode": "default_browser", "state": "opened"},
        preparation_requested=True,
    )
    available = add(service, "available")
    monkeypatch.setattr(
        service,
        "prepare",
        lambda *a, **k: {
            "resume_pdf": "ready.pdf",
            "generation_note": "Known facts",
            "generation_mode": "deterministic",
        },
    )
    service.process_document_queue()
    assert not service.store.get_job(blocked["id"]).get("documents")
    assert service.store.get_job(available["id"])["status"] == "prepared"


def test_document_failure_becomes_persistent_plain_language_problem(assist, monkeypatch):
    service, client, headers = assist
    job = add(service)

    def failed(*args, **kwargs):
        raise RuntimeError(r"SECRET_TOKEN failed at C:\\private\\resume.pdf")

    monkeypatch.setattr(service, "prepare", failed)
    service.prepare_job(job["id"])
    response = client.get("/api/problems")
    assert response.status_code == 200
    problems = response.json()["problems"]
    assert len(problems) == 1
    problem = problems[0]
    assert problem["category"] == "documents"
    assert problem["title"] == job["title"] and problem["url"] == job["url"]
    assert "document" in problem["message"].lower() and not problem["resolved"]
    assert "SECRET_TOKEN" not in response.text and "private" not in response.text
    assert "SECRET_TOKEN" not in client.get("/api/state").text
    assert "SECRET_TOKEN" in (service.DATA / "logs" / "problems.log").read_text(encoding="utf-8")
    assert (
        client.post(f"/api/problems/{problem['id']}/resolve", headers=headers, json={}).status_code
        == 200
    )
    assert service.store.problems()[0]["resolved"] is True


def test_source_failure_creates_a_problem_without_technical_details(assist, monkeypatch):
    service, client, _ = assist
    from jobpilot import collectors

    monkeypatch.setattr(collectors, "discover", lambda *a, **k: [])
    monkeypatch.setattr(
        collectors,
        "get_last_errors",
        lambda: [{"source": "linkedin", "note": "HTTP429 SECRET_TOKEN"}],
    )
    service.discover_once()
    problems = client.get("/api/problems").json()["problems"]
    assert len(problems) == 1 and "linkedin" in problems[0]["message"].lower()
    assert problems[0]["category"] == "search"
    assert "SECRET_TOKEN" not in json.dumps(problems)


def test_keywords_are_available_on_state_and_job_endpoint(assist, monkeypatch):
    service, client, _ = assist
    job = add(service)
    state_job = next(
        row for row in client.get("/api/state").json()["jobs"] if row["id"] == job["id"]
    )
    assert {"terms", "tools", "skills", "matched", "suggested"} <= set(state_job["keywords"])
    assert client.get(f"/api/jobs/{job['id']}/keywords").json() == state_job["keywords"]
