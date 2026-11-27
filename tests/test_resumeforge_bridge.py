import hashlib
import json
import os
from pathlib import Path

import pytest

from jobpilot import resumeforge_bridge as bridge


def master_draft(path: Path):
    path.mkdir(parents=True)
    draft = {
        "version": 2,
        "profile": {
            "name": "Jordan Morgan",
            "contact": "jordan@example.com",
            "roles": [
                {
                    "id": "role-1",
                    "company": "Example Co",
                    "title": "Analyst",
                    "dates": "2024–2025",
                    "bullets": [{"id": "fact-1", "text": "Reviewed operational alerts."}],
                }
            ],
        },
        "settings": {"provider": "none", "draft_mode": "grounded"},
        "job_description": "An unrelated saved posting",
        "edit_request": "Keep my custom note",
    }
    (path / "draft.json").write_text(json.dumps(draft), encoding="utf-8")
    return draft


def role(description="Monitor cloud services and respond to incidents."):
    return {
        "id": 42,
        "title": "Operations Specialist",
        "company": "Example Games",
        "description": description,
        "keywords": {"terms": ["Linux", "Incident response"]},
    }


def run_result(workspace: Path, run_id: str, *, status="ready", pdf=b"%PDF-1.4\nexample\n"):
    folder = workspace / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "resume.pdf").write_bytes(pdf)
    result = {
        "status": status,
        "report": {
            "geometry_passed": True,
            "quality_review": {"passed": True},
            "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        },
    }
    (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return folder


def test_role_workspace_uses_saved_resumeforge_profile_without_overwriting_edits(tmp_path):
    source = tmp_path / "resumeforge-master"
    original = master_draft(source)
    data = tmp_path / "jobpilot-data"
    first = bridge.prepare_workspace(data, role(), master_dir=source)
    imported = json.loads((first / "draft.json").read_text(encoding="utf-8"))
    assert imported["profile"] == original["profile"]
    assert imported["settings"] == original["settings"]
    assert "Operations Specialist" in imported["job_description"]
    assert "Monitor cloud services" in imported["job_description"]
    assert imported["keywords"] == ""  # Auto-discovered terms are not user-reviewed priorities
    assert "unrelated saved posting" not in imported["job_description"]
    assert imported["analyzed"] is False
    imported["edit_request"] = "My edits for this role"
    (first / "draft.json").write_text(json.dumps(imported), encoding="utf-8")

    assert bridge.prepare_workspace(data, role(), master_dir=source) == first
    assert json.loads((first / "draft.json").read_text(encoding="utf-8"))["edit_request"] == (
        "My edits for this role"
    )
    changed = bridge.prepare_workspace(data, role("A revised posting."), master_dir=source)
    assert changed != first
    assert first.is_dir()
    assert json.loads((source / "draft.json").read_text(encoding="utf-8")) == original


def test_automatic_build_lets_resumeforge_rank_full_posting(tmp_path, monkeypatch):
    """JobPilot's lexical hints must never masquerade as user-reviewed priorities."""
    source = tmp_path / "resumeforge-master"
    master_draft(source)
    captured = {}

    def run(request, run_dir):
        captured["request"] = request
        run_dir.mkdir(parents=True)
        return {"status": "ready"}

    def export_checked(run_dir, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"%PDF-1.4\nfictional checked resume\n")

    from resumeforge import desktop_support, engine

    monkeypatch.setattr(bridge, "master_workspace", lambda: source)
    monkeypatch.setattr(bridge, "downloads_folder", lambda job: tmp_path / "exports")
    monkeypatch.setattr(engine, "run", run)
    monkeypatch.setattr(desktop_support, "export_checked", export_checked)

    result = bridge.build_resume(tmp_path / "jobpilot-data", role())

    assert result["status"] == "ready"
    assert (
        Path(result["path"]).parent.name
        == bridge.workspace_path(tmp_path / "jobpilot-data", role()).name
    )
    assert Path(result["path"]).name == "Alnajjar_Resume.pdf"
    request = captured["request"]
    assert request.keywords == []
    assert request.reviewed_priorities is None
    assert "Operations Specialist" in request.job_description
    assert "Linux, Incident response" not in request.job_description


def test_reopening_an_existing_held_run_restores_its_preview(tmp_path):
    master = tmp_path / "master"
    master_draft(master)
    data = tmp_path / "data"
    workspace = bridge.prepare_workspace(data, role(), master_dir=master)
    run_id = "c" * 32
    folder = run_result(workspace, run_id, status="needs_content")
    (folder / "preview.pdf").write_bytes(b"%PDF-1.4\nfictional preview\n")

    assert bridge.prepare_workspace(data, role(), master_dir=master) == workspace
    assert json.loads((workspace / "draft.json").read_text())["last_run"] == run_id
    assert bridge.checked_run(workspace)["status"] == "needs_content"


def test_automatic_run_does_not_export_after_editor_saves_new_input(tmp_path, monkeypatch):
    from resumeforge import engine

    master = tmp_path / "master"
    master_draft(master)
    data = tmp_path / "data"
    job = role()
    workspace = bridge.prepare_workspace(data, job, master_dir=master)
    draft_path = workspace / "draft.json"
    edited = {**json.loads(draft_path.read_text()), "edit_request": "New instructions"}

    def run(*_):
        draft_path.write_text(json.dumps(edited), encoding="utf-8")
        return {"status": "ready"}

    monkeypatch.setattr(engine, "run", run)
    assert bridge.build_resume(data, job)["status"] == "needs_review"
    assert json.loads(draft_path.read_text()) == edited


def test_role_workspace_needs_a_real_posting_and_saved_profile(tmp_path):
    source = tmp_path / "master"
    master_draft(source)
    with pytest.raises(ValueError, match="description"):
        bridge.prepare_workspace(tmp_path, role(""), master_dir=source)
    with pytest.raises(FileNotFoundError, match="ResumeForge"):
        bridge.prepare_workspace(tmp_path, role(), master_dir=tmp_path / "missing")


def test_checked_run_uses_latest_ready_report_and_matching_pdf(tmp_path):
    workspace = tmp_path / "role"
    older = run_result(workspace, "a" * 32)
    newer = run_result(workspace, "b" * 32)
    newest = (older / "result.json").stat().st_mtime_ns + 2_000_000_000
    os.utime(newer / "result.json", ns=(newest, newest))
    found = bridge.checked_run(workspace)
    assert found["status"] == "ready"
    assert found["run_id"] == "b" * 32
    assert found["pdf"] == newer / "resume.pdf"
    assert found["sha256"] == hashlib.sha256((newer / "resume.pdf").read_bytes()).hexdigest()
    assert older.is_dir()


@pytest.mark.parametrize("status", ["needs_content", "needs_review", "failed"])
def test_incomplete_run_cannot_supply_checked_pdf(tmp_path, status):
    workspace = tmp_path / "role"
    run_result(workspace, "c" * 32, status=status)
    found = bridge.checked_run(workspace)
    assert found["status"] == status
    assert "pdf" not in found


def test_checked_run_rejects_tampered_pdf_or_failed_checks(tmp_path):
    workspace = tmp_path / "role"
    folder = run_result(workspace, "d" * 32)
    (folder / "resume.pdf").write_bytes(b"%PDF-1.4\ntampered\n")
    with pytest.raises(ValueError, match="changed"):
        bridge.checked_run(workspace)
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    result["report"]["pdf_sha256"] = hashlib.sha256(
        (folder / "resume.pdf").read_bytes()
    ).hexdigest()
    result["report"]["quality_review"]["passed"] = False
    (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="checks"):
        bridge.checked_run(workspace)


def test_checked_run_rejects_malformed_report_and_oversized_pdf(tmp_path):
    workspace = tmp_path / "role"
    folder = run_result(workspace, "f" * 32)
    (folder / "result.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="report"):
        bridge.checked_run(workspace)
    run_result(workspace, "f" * 32)
    with (folder / "resume.pdf").open("r+b") as output:
        output.truncate(15 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="large"):
        bridge.checked_run(workspace)


def test_checked_run_rejects_pdf_escape(tmp_path):
    workspace = tmp_path / "role"
    folder = run_result(workspace, "e" * 32)
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes((folder / "resume.pdf").read_bytes())
    (folder / "resume.pdf").unlink()
    try:
        (folder / "resume.pdf").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks is unavailable")
    with pytest.raises(ValueError, match="workspace"):
        bridge.checked_run(workspace)


def test_open_editor_passes_workspace_as_arguments_without_shell(tmp_path, monkeypatch):
    executable = tmp_path / "ResumeForge.exe"
    executable.write_bytes(b"binary")
    workspace = tmp_path / "role workspace"
    workspace.mkdir()
    calls = []
    monkeypatch.setattr(
        bridge.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    bridge.open_editor(executable, workspace)
    assert calls[0][0][0] == [str(executable), "--data-dir", str(workspace)]
    assert calls[0][1]["shell"] is False


def test_saved_input_change_invalidates_previous_ready_run(tmp_path):
    workspace = tmp_path / "role"
    folder = run_result(workspace, "1" * 32)
    draft = workspace / "draft.json"
    draft.write_text(json.dumps({"last_run": None}), encoding="utf-8")
    after = (folder / "result.json").stat().st_mtime_ns + 2_000_000_000
    os.utime(draft, ns=(after, after))
    assert bridge.checked_run(workspace)["status"] == "outdated"

    draft.write_text(json.dumps({"last_run": folder.name}), encoding="utf-8")
    os.utime(draft, ns=(after, after))
    assert bridge.checked_run(workspace)["status"] == "ready"


def test_new_run_after_saved_draft_is_ready_without_saved_run_reference(tmp_path):
    workspace = tmp_path / "role"
    folder = run_result(workspace, "2" * 32)
    draft = workspace / "draft.json"
    draft.write_text(json.dumps({"last_run": None}), encoding="utf-8")
    before = (folder / "result.json").stat().st_mtime_ns - 2_000_000_000
    os.utime(draft, ns=(before, before))
    assert bridge.checked_run(workspace)["status"] == "ready"


def test_existing_role_workspace_cannot_redirect_to_master(tmp_path):
    master = tmp_path / "master"
    master_draft(master)
    jobpilot_data = tmp_path / "data"
    workspace = bridge.workspace_path(jobpilot_data, role())
    workspace.parent.mkdir(parents=True)
    try:
        workspace.symlink_to(master, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks is unavailable")
    with pytest.raises(ValueError, match="workspace"):
        bridge.prepare_workspace(jobpilot_data, role(), master_dir=master)


def test_registry_install_location_is_supported(tmp_path, monkeypatch):
    if bridge.sys.platform != "win32":
        pytest.skip("Windows registry install location")
    install = tmp_path / "custom-install"
    install.mkdir()
    executable = install / "ResumeForge.exe"
    executable.write_bytes(b"app")
    monkeypatch.delenv("RESUMEFORGE_DESKTOP_EXE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "no-default-install"))
    monkeypatch.setattr(bridge, "windows_install_dir", lambda: install)
    assert bridge.desktop_executable() == executable


def test_old_run_without_report_prompts_retry(tmp_path):
    workspace = tmp_path / "role"
    folder = workspace / "runs" / ("3" * 32)
    folder.mkdir(parents=True)
    old = bridge.time.time_ns() - bridge._STALLED_RUN_NS - 2_000_000_000
    os.utime(folder, ns=(old, old))
    assert bridge.checked_run(workspace)["status"] == "unknown"
