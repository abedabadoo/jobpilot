import importlib
import threading

import pytest
from fastapi.testclient import TestClient


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBPILOT_TESTING", "1")
    import jobpilot.service as service

    service = importlib.reload(service)
    return TestClient(service.app)


def test_api_requires_mutation_token(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/control", json={"action": "stop"}).status_code == 403
    token = client.get("/api/session").json()["token"]
    result = client.post(
        "/api/control", json={"action": "stop"}, headers={"X-JobPilot-Token": token}
    )
    assert result.status_code == 200
    assert not client.get("/api/state").json()["settings"]["search_enabled"]


def test_fresh_installation_uses_a_paused_fictional_sample_profile(tmp_path, monkeypatch):
    state = api(tmp_path, monkeypatch).get("/api/state").json()
    assert state["profile"]["sample_profile"] is True
    assert state["profile"]["name"] == "Jordan Morgan"
    assert state["settings"]["search_enabled"] is False
    assert state["settings"]["submission_enabled"] is False
    assert state["jobs"] == []


def test_import_and_artifact_boundaries(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    result = client.post(
        "/api/import",
        headers=headers,
        json={
            "title": "Cloud Security Engineer",
            "company": "Example",
            "url": "https://example.com/job/123",
            "description": "AWS ISO/IEC 27001 Python",
        },
    )
    assert result.status_code == 200
    assert client.get("/api/state").json()["jobs"][0]["title"] == "Cloud Security Engineer"
    assert client.get("/api/artifact", params={"path": "C:/Windows/win.ini"}).status_code == 403


def test_uncertain_retry_requires_receipt_review(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    import jobpilot.service as service

    service.store.set("settings", {**service.settings(), "application_mode": "legacy"})
    job = service.store.add_job(
        {"url": "https://example.com/uncertain", "title": "Security", "company": "Example"}
    )
    service.store.update_job(job["id"], status="needs_review", uncertain=True)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    assert client.post(f"/api/jobs/{job['id']}/retry", headers=headers).status_code == 409
    assert client.post(f"/api/jobs/{job['id']}/prepare", headers=headers).status_code == 409


def test_preparing_review_documents_does_not_requeue_submission(tmp_path, monkeypatch):
    api(tmp_path, monkeypatch)
    import jobpilot.service as service

    job = service.store.add_job(
        {
            "url": "https://example.com/review",
            "title": "Security",
            "company": "Example",
            "status": "needs_review",
            "note": "Location must be verified.",
        }
    )
    monkeypatch.setattr(
        service,
        "prepare",
        lambda *args: {"generation_note": "", "generation_mode": "deterministic"},
    )
    service.prepare_job(job["id"])
    assert service.store.get_job(job["id"])["status"] == "needs_review"
    assert "Location must be verified" in service.store.get_job(job["id"])["note"]


def test_graceful_shutdown_pauses_before_exiting(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    import jobpilot.service as service

    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    service.worker["submitting"] = True
    assert (
        client.post("/api/control", headers=headers, json={"action": "shutdown"}).status_code == 409
    )
    service.worker["submitting"] = False
    response = client.post("/api/control", headers=headers, json={"action": "shutdown"})
    assert response.status_code == 200
    state = client.get("/api/state").json()
    assert not state["settings"]["search_enabled"] and not state["settings"]["submission_enabled"]


def test_job_mutations_cannot_change_active_adapter(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    import jobpilot.service as service
    from jobpilot import browser

    service.store.set(
        "settings", {**service.settings(), "application_mode": "legacy", "submission_enabled": True}
    )
    entered, release = threading.Event(), threading.Event()

    def adapter(job, profile, answers, documents, settings, checkpoint=None):
        entered.set()
        release.wait(5)
        return {
            "status": "needs_review",
            "submitted": False,
            "evidence": [],
            "note": "Fixture form",
        }

    monkeypatch.setattr(browser, "apply", adapter)
    job = service.store.add_job(
        {
            "url": "https://example.com/active",
            "title": "Security Engineer",
            "location": "Cincinnati, OH",
            "company": "Fixture",
            "status": "prepared",
            "documents": {"resume_pdf": "fixture"},
        }
    )
    thread = threading.Thread(target=service.apply_job, args=(job["id"],))
    thread.start()
    assert entered.wait(3)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    try:
        assert client.post(f"/api/jobs/{job['id']}/skip", headers=headers).status_code == 409
        assert client.post(f"/api/jobs/{job['id']}/retry", headers=headers).status_code == 409
        assert client.post(f"/api/jobs/{job['id']}/prepare", headers=headers).status_code == 409
    finally:
        release.set()
        thread.join(5)


def test_active_submit_receipt_cannot_be_resolved(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    import jobpilot.service as service

    job = service.store.add_job(
        {
            "url": "https://example.com/active-submit",
            "title": "Security",
            "company": "Fixture",
            "status": "submitting",
            "uncertain": True,
        }
    )
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    assert (
        client.post(
            f"/api/jobs/{job['id']}/resolve",
            headers=headers,
            json={"outcome": "not_submitted", "evidence": "Test"},
        ).status_code
        == 409
    )
    assert service.store.get_job(job["id"])["uncertain"]


def test_interrupted_review_preparation_restores_review_gate(tmp_path, monkeypatch):
    api(tmp_path, monkeypatch)
    import jobpilot.service as service

    job = service.store.add_job(
        {
            "url": "https://example.com/review-crash",
            "title": "Security",
            "company": "Fixture",
            "status": "needs_review",
            "note": "Verify remote USA eligibility.",
        }
    )

    def crash(*args):
        raise SystemExit("Fixture interruption")

    monkeypatch.setattr(service, "prepare", crash)
    with pytest.raises(SystemExit):
        service.prepare_job(job["id"])
    service.store.recover()
    recovered = service.store.get_job(job["id"])
    assert recovered["status"] == "needs_review"
    assert "Verify remote USA eligibility" in recovered["note"]


def test_dashboard_email_aliases_match_collector_contract(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    from jobpilot import collectors

    observed = {}

    def configure(config):
        observed.update(config)
        assert config["username"] == "fixture@example.com"
        assert config["mailbox"] == "Alerts"
        return {
            "host": config["host"],
            "username": config["username"],
            "mailbox": config["mailbox"],
            "enabled": True,
        }

    monkeypatch.setattr(collectors, "configure_email", configure)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    result = client.post(
        "/api/email",
        headers=headers,
        json={
            "host": "imap.example.com",
            "user": "fixture@example.com",
            "folder": "Alerts",
            "password": "fixture-secret",
            "enabled": True,
        },
    )
    assert result.status_code == 200
    assert "fixture-secret" not in client.get("/api/state").text


def test_import_preserves_same_eligibility_gates_as_discovery(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    result = client.post(
        "/api/import",
        headers=headers,
        json={
            "url": "https://example.com/paris",
            "title": "Security Engineer",
            "company": "Fixture",
            "location": "Paris, France",
            "description": "AWS cloud security engineering and ISO 27001 evidence operations. " * 4,
        },
    )
    assert result.json()["jobs"][0]["status"] == "skipped"


def test_manual_receipt_is_separate_from_adapter_confirmed_counter(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    import jobpilot.service as service

    job = service.store.add_job(
        {
            "url": "https://example.com/manual-receipt",
            "title": "Security",
            "company": "Fixture",
            "status": "needs_review",
            "uncertain": True,
        }
    )
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    response = client.post(
        f"/api/jobs/{job['id']}/resolve",
        headers=headers,
        json={"outcome": "confirmed", "evidence": "Receipt personally verified."},
    )
    assert response.status_code == 200
    assert service.store.get_job(job["id"])["status"] == "manually_verified"
    assert service.store.metrics()["confirmed"] == 0


def test_pause_before_checkpoint_prevents_submission(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    import jobpilot.service as service
    from jobpilot import browser

    service.store.set(
        "settings", {**service.settings(), "application_mode": "legacy", "submission_enabled": True}
    )
    entered, release = threading.Event(), threading.Event()
    clicked = []

    def adapter(job, profile, answers, documents, settings, checkpoint=None):
        entered.set()
        release.wait(5)
        checkpoint({"url": job["url"]})
        clicked.append(True)
        return {"status": "confirmed", "submitted": True, "evidence": ["fixture"]}

    monkeypatch.setattr(browser, "apply", adapter)
    job = service.store.add_job(
        {
            "url": "https://example.com/pause",
            "title": "Security Engineer",
            "location": "Cincinnati, OH",
            "company": "Fixture",
            "status": "prepared",
            "documents": {"resume_pdf": "fixture"},
        }
    )
    thread = threading.Thread(target=service.apply_job, args=(job["id"],))
    thread.start()
    assert entered.wait(3)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    client.post("/api/control", headers=headers, json={"submission_enabled": False})
    release.set()
    thread.join(5)
    assert clicked == []
    assert service.store.get_job(job["id"])["status"] == "prepared"


def test_import_cannot_supply_status_or_upload_paths(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    response = client.post(
        "/api/import",
        headers=headers,
        json={
            "url": "https://example.com/import-safe",
            "title": "Security Engineer",
            "company": "Fixture",
            "location": "Cincinnati, OH",
            "description": "AWS cloud security and vulnerability analysis requirements. " * 4,
            "status": "confirmed",
            "documents": {"resume_pdf": "C:/Windows/win.ini"},
            "uncertain": False,
        },
    )
    job = response.json()["jobs"][0]
    assert job["status"] == "queued"
    assert "documents" not in job
    assert service_metrics(client)["confirmed"] == 0


def service_metrics(client):
    return client.get("/api/state").json()["metrics"]
