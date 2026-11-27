import hashlib
import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_resumeforge_bridge import master_draft, run_result


@pytest.fixture
def integration(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path / "jobpilot-data"))
    monkeypatch.setenv("JOBPILOT_TESTING", "1")
    import jobpilot.service as service

    service = importlib.reload(service)
    master = tmp_path / "resumeforge-master"
    master_draft(master)
    monkeypatch.setattr(service.resumeforge_bridge, "master_workspace", lambda: master)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    executable = tmp_path / "ResumeForge.exe"
    executable.write_bytes(b"app")
    monkeypatch.setattr(service.resumeforge_bridge, "desktop_executable", lambda: executable)
    opened = []
    monkeypatch.setattr(
        service.resumeforge_bridge,
        "open_editor",
        lambda app, workspace: opened.append((app, workspace)),
    )
    client = TestClient(service.app)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    job = service.store.add_job(
        {
            "url": "https://jobs.example.com/42",
            "title": "Operations Specialist",
            "company": "Example Games",
            "description": "Monitor cloud services and respond to production incidents.",
            "status": "needs_review",
            "fit": 81,
            "note": "Original review note",
            "documents": {"resume_pdf": "existing.pdf", "cover_pdf": "cover.pdf"},
            "application": {"documents": {"resume_pdf": "existing.pdf"}},
        }
    )
    return service, client, headers, job, master, opened


def test_open_role_requires_session_and_preserves_master_workspace(integration):
    service, client, headers, job, master, opened = integration
    url = f"/api/jobs/{job['id']}/resumeforge/open"
    assert client.post(url, json={}).status_code == 403
    before = (master / "draft.json").read_bytes()
    response = client.post(url, json={}, headers=headers)
    assert response.status_code == 200
    assert response.json()["opened"] is True
    assert len(opened) == 1
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
    assert opened[0][1] == workspace
    assert (workspace / "draft.json").is_file()
    assert (master / "draft.json").read_bytes() == before
    assert service.store.get_job(job["id"])["status"] == "needs_review"


def test_missing_profile_status_directs_user_to_profile_editor(integration):
    service, client, _, job, _, _ = integration
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
    service.store.update_job(
        job["id"],
        resumeforge={
            "status": "setup_required",
            "workspace": workspace.name,
            "master_revision": "",
        },
    )
    assert client.get(f"/api/jobs/{job['id']}/resumeforge/status").json() == {
        "status": "setup_required",
        "attached": False,
    }


def test_status_and_use_attach_only_checked_pdf_without_changing_tracking(integration):
    service, client, headers, job, _, _ = integration
    base = f"/api/jobs/{job['id']}/resumeforge"
    client.post(base + "/open", json={}, headers=headers)
    assert client.get(base + "/status").json()["status"] == "not_built"
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
    run_id = "a" * 32
    run_result(workspace, run_id)
    assert client.get(base + "/status").json()["status"] == "ready"
    assert client.post(base + "/use", json={}).status_code == 403
    first = client.post(base + "/use", json={}, headers=headers)
    assert first.status_code == 200
    assert first.json()["attached"] is True
    saved = service.store.get_job(job["id"])
    assert saved["status"] == "needs_review"
    assert saved["note"] == "Original review note"
    assert saved.get("applied") is not True
    assert set(saved["documents"]) == {"resumeforge_pdf"}
    pdf = saved["documents"]["resumeforge_pdf"]
    assert pdf.startswith(str(Path.home() / "Downloads" / "JobPilot RF Docs"))
    assert hashlib.sha256(open(pdf, "rb").read()).hexdigest() == saved["resumeforge"]["sha256"]
    assert saved["application"]["documents"]["resumeforge_pdf"] == pdf
    download = client.get("/api/artifact", params={"path": pdf})
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF-")
    second = client.post(base + "/use", json={}, headers=headers)
    assert second.status_code == 200
    assert second.json()["already_attached"] is True
    assert service.store.get_job(job["id"])["documents"]["resumeforge_pdf"] == pdf


def test_incomplete_or_changed_resume_cannot_attach(integration):
    service, client, headers, job, _, _ = integration
    base = f"/api/jobs/{job['id']}/resumeforge"
    client.post(base + "/open", json={}, headers=headers)
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
    folder = run_result(workspace, "b" * 32, status="needs_content")
    response = client.post(base + "/use", json={}, headers=headers)
    assert response.status_code == 409
    assert "review" in response.json()["detail"].lower()
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    result["status"] = "ready"
    (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (folder / "resume.pdf").write_bytes(b"%PDF-1.4\ntampered")
    response = client.post(base + "/use", json={}, headers=headers)
    assert response.status_code == 409
    assert service.store.get_job(job["id"])["documents"] == job["documents"]


def test_missing_attached_copy_can_be_restored_from_checked_run(integration):
    service, client, headers, job, _, _ = integration
    base = f"/api/jobs/{job['id']}/resumeforge"
    client.post(base + "/open", json={}, headers=headers)
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
    run_result(workspace, "d" * 32)
    assert client.post(base + "/use", json={}, headers=headers).status_code == 200
    attached = service.store.get_job(job["id"])["documents"]["resumeforge_pdf"]
    Path(attached).unlink()
    assert client.get(base + "/status").json() == {"status": "ready", "attached": False}
    restored = client.post(base + "/use", json={}, headers=headers)
    assert restored.status_code == 200
    assert Path(attached).is_file()


def test_same_title_sync_keeps_resumes_and_cover_letters_posting_specific(integration):
    service, client, headers, first, _, _ = integration
    second = service.store.add_job(
        {
            **first,
            "id": None,
            "url": "https://jobs.example.com/43",
            "description": "A separate posting for the same employer and title.",
            "documents": {},
            "resumeforge": {},
            "application": {},
        }
    )

    def checked(job, run_id, pdf=b"%PDF-1.4\noriginal resume\n"):
        workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
        folder = run_result(workspace, run_id, pdf=pdf)
        report_file = folder / "result.json"
        report = json.loads(report_file.read_text(encoding="utf-8"))
        report["profile"] = {"name": "Fictional Candidate", "contact": "candidate@example.invalid"}
        report_file.write_text(json.dumps(report), encoding="utf-8")

    for index, job in enumerate((first, second), start=1):
        base = f"/api/jobs/{job['id']}/resumeforge"
        assert client.post(base + "/open", json={}, headers=headers).status_code == 200
        checked(job, str(index) * 32)
    first_context = service.resumeforge_bridge.cover_workspace(service.DATA, first)
    letter_pdf = b"%PDF-1.4\nfirst posting cover\n"
    first_context._commit(0, first_context._draft_record("Saved draft", {}), letter_pdf)

    for job in (first, second):
        response = client.post(f"/api/jobs/{job['id']}/resumeforge/use", json={}, headers=headers)
        assert response.status_code == 200

    first_saved = service.store.get_job(first["id"])["documents"]
    second_saved = service.store.get_job(second["id"])["documents"]
    assert first_saved["resumeforge_pdf"] != second_saved["resumeforge_pdf"]
    assert "resumeforge_cover_pdf" in first_saved
    assert "resumeforge_cover_pdf" not in second_saved

    checked(first, "3" * 32, b"%PDF-1.4\nregenerated resume\n")
    first_route = f"/api/jobs/{first['id']}/resumeforge/use"
    assert client.post(first_route, json={}, headers=headers).status_code == 200
    saved = service.store.get_job(first["id"])
    assert saved["documents"] == {"resumeforge_pdf": str(first_context.resume)}
    assert saved["application"]["documents"] == saved["documents"]
    assert first_context.letter.read_bytes() == letter_pdf
    assert not service.resumeforge_bridge.cover_workspace(service.DATA, first).state()["current"]


def test_document_regeneration_uses_resumeforge_only(integration, monkeypatch):
    service, client, headers, job, _, _ = integration
    base = f"/api/jobs/{job['id']}/resumeforge"
    client.post(base + "/open", json={}, headers=headers)
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
    run_result(workspace, "c" * 32)
    assert client.post(base + "/use", json={}, headers=headers).status_code == 200
    path = service.store.get_job(job["id"])["documents"]["resumeforge_pdf"]
    monkeypatch.setattr(
        service.resumeforge_bridge,
        "build_resume",
        lambda *args: {"status": "ready", "path": path},
    )
    service.prepare_job(job["id"])
    saved = service.store.get_job(job["id"])
    assert saved["documents"]["resumeforge_pdf"] == path
    assert set(saved["documents"]) == {"resumeforge_pdf"}
    assert saved["application"]["documents"]["resumeforge_pdf"] == path


def test_tampered_attached_copy_is_not_treated_as_checked(integration):
    service, client, headers, job, _, _ = integration
    base = f"/api/jobs/{job['id']}/resumeforge"
    client.post(base + "/open", json={}, headers=headers)
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
    run_result(workspace, "e" * 32)
    assert client.post(base + "/use", json={}, headers=headers).status_code == 200
    attached = Path(service.store.get_job(job["id"])["documents"]["resumeforge_pdf"])
    attached.write_bytes(b"%PDF-1.4\ntampered\n")
    assert client.get(base + "/status").json() == {"status": "ready", "attached": False}
    response = client.post(base + "/use", json={}, headers=headers)
    assert response.status_code == 200
    assert response.json()["already_attached"] is False
    assert attached.read_bytes() == (workspace / "runs" / ("e" * 32) / "resume.pdf").read_bytes()


def test_import_preserves_receipt_added_during_pdf_verification(integration, monkeypatch):
    service, client, headers, job, _, _ = integration
    base = f"/api/jobs/{job['id']}/resumeforge"
    client.post(base + "/open", json={}, headers=headers)
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
    run_result(workspace, "f" * 32)
    original = service.resumeforge_bridge.checked_run

    def checked_run(path):
        current = service.store.get_job(job["id"])
        service.store.update_job(
            job["id"], application={**current["application"], "receipt": "confirmed-123"}
        )
        return original(path)

    monkeypatch.setattr(service.resumeforge_bridge, "checked_run", checked_run)
    response = client.post(base + "/use", json={}, headers=headers)
    assert response.status_code == 200
    assert service.store.get_job(job["id"])["application"]["receipt"] == "confirmed-123"


def test_import_rejects_redirected_downloads_folder(integration):
    service, client, headers, job, _, _ = integration
    base = f"/api/jobs/{job['id']}/resumeforge"
    client.post(base + "/open", json={}, headers=headers)
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
    run_result(workspace, "0" * 32)
    outside = service.DATA.parent / "outside-documents"
    outside.mkdir()
    downloads = Path.home() / "Downloads" / "JobPilot RF Docs"
    downloads.parent.mkdir(parents=True, exist_ok=True)
    if downloads.exists():
        pytest.skip("Downloads document directory already exists")
    try:
        downloads.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks is unavailable")
    response = client.post(base + "/use", json={}, headers=headers)
    assert response.status_code == 409
    assert not list(outside.rglob("*.pdf"))


def test_changed_posting_marks_older_resumeforge_document_outdated(integration):
    service, client, headers, job, _, _ = integration
    base = f"/api/jobs/{job['id']}/resumeforge"
    client.post(base + "/open", json={}, headers=headers)
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job)
    run_result(workspace, "4" * 32)
    assert client.post(base + "/use", json={}, headers=headers).status_code == 200
    assert client.get("/api/state").json()["jobs"][0]["resumeforge"]["current"] is True
    service.store.update_job(job["id"], description="Revised posting with a different remit.")
    assert client.get("/api/state").json()["jobs"][0]["resumeforge"]["current"] is False


def test_regeneration_preserves_receipt_added_during_document_build(integration, monkeypatch):
    service, _, _, job, _, _ = integration

    def build_resume(*_):
        current = service.store.get_job(job["id"])
        service.store.update_job(
            job["id"], application={**current["application"], "receipt": "confirmed-456"}
        )
        return {"status": "ready", "path": "new-resumeforge.pdf"}

    monkeypatch.setattr(service.resumeforge_bridge, "build_resume", build_resume)
    service.prepare_job(job["id"])
    assert service.store.get_job(job["id"])["application"]["receipt"] == "confirmed-456"
