import hashlib
import json
from pathlib import Path

from test_api import api

from jobpilot import resumeforge_bridge
from resumeforge.cover_letter import draft_text, export_pdf
from resumeforge.models import Profile


def test_eighty_percent_starts_each_resumeforge_build_exactly_once(tmp_path, monkeypatch):
    api(tmp_path, monkeypatch)
    from jobpilot import service

    low = service.store.add_job(
        {
            "url": "https://example.com/low",
            "title": "Platform Engineer",
            "company": "Low",
            "description": "AWS and Python operations",
            "fit": 79.99,
            "status": "queued",
        }
    )
    exact = service.store.add_job(
        {
            "url": "https://example.com/high",
            "title": "Platform Engineer",
            "company": "High",
            "description": "AWS and Python operations",
            "fit": 80,
            "status": "queued",
        }
    )
    high = service.store.add_job(
        {
            "url": "https://example.com/highest",
            "title": "Platform Engineer",
            "company": "Highest",
            "description": "AWS and Python operations",
            "fit": 100,
            "status": "queued",
        }
    )
    calls = []

    def build(data, job):
        calls.append(job["id"])
        path = data / "applications" / f"job-{job['id']}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 fictional checked resume")
        return {
            "status": "ready",
            "path": str(path),
            "workspace": service.resumeforge_bridge.workspace_path(data, job).name,
            "run_id": f"run-{job['id']}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    monkeypatch.setattr(service.resumeforge_bridge, "build_resume", build)
    service.process_document_queue()
    service.process_document_queue()
    service.process_document_queue()
    assert len(calls) == 2
    assert set(calls) == {exact["id"], high["id"]}
    assert service.store.get_job(low["id"])["status"] == "queued"
    for job in (exact, high):
        documents = service.store.get_job(job["id"])["documents"]
        assert set(documents) == {"resumeforge_pdf"}
        assert not Path(documents["resumeforge_pdf"]).with_name("Alnajjar_CoverLetter.pdf").exists()


def test_same_title_postings_keep_distinct_stable_resumes(tmp_path, monkeypatch):
    api(tmp_path, monkeypatch)
    from jobpilot import service

    jobs = [
        service.store.add_job(
            {
                "url": f"https://example.com/reposted/{number}",
                "title": "Platform Engineer",
                "company": "Same Employer",
                "description": f"AWS and Python operations for posting {number}.",
                "fit": 90,
                "status": "queued",
            }
        )
        for number in (1, 2)
    ]
    role_folder = service.DATA / "applications" / "Same Employer - Platform Engineer"
    monkeypatch.setattr(service.resumeforge_bridge, "downloads_folder", lambda _job: role_folder)
    calls = []

    def build(data, current):
        calls.append(current["id"])
        destination = service.resumeforge_bridge.resume_destination(data, current)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f"%PDF-1.4 posting {current['id']}".encode())
        return {
            "status": "ready",
            "path": str(destination),
            "workspace": service.resumeforge_bridge.workspace_path(data, current).name,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        }

    monkeypatch.setattr(service.resumeforge_bridge, "build_resume", build)
    for _ in range(6):
        service.process_document_queue()

    assert len(calls) == 2
    paths = [Path(service.store.get_job(job["id"])["documents"]["resumeforge_pdf"]) for job in jobs]
    assert paths[0] != paths[1]
    assert paths[0].name == paths[1].name == "Alnajjar_Resume.pdf"
    assert all(path.is_file() for path in paths)
    assert paths[0].read_bytes() != paths[1].read_bytes()


def test_engine_failure_result_uses_bounded_retries(tmp_path, monkeypatch):
    api(tmp_path, monkeypatch)
    from jobpilot import service

    job = service.store.add_job(
        {
            "url": "https://example.com/engine-failure",
            "title": "Platform Engineer",
            "company": "Retry",
            "description": "Build AWS and Python automation.",
            "fit": 90,
            "status": "queued",
        }
    )
    workspace = service.resumeforge_bridge.workspace_path(service.DATA, job).name
    calls = []

    def build(*_):
        calls.append(job["id"])
        return {"status": "failed", "workspace": workspace}

    monkeypatch.setattr(service.resumeforge_bridge, "build_resume", build)
    service.store.update_job(
        job["id"],
        resumeforge={
            "status": "failed",
            "workspace": workspace,
            "attempts": "damaged",
            "retry_after": None,
        },
    )
    service.process_document_queue()
    assert len(calls) == 1
    assert service.store.get_job(job["id"])["resumeforge"]["attempts"] == 1
    service.process_document_queue()
    assert len(calls) == 1

    for expected_attempts in (2, 3):
        current = service.store.get_job(job["id"])
        service.store.update_job(
            job["id"], resumeforge={**current["resumeforge"], "retry_after": None}
        )
        service.process_document_queue()
        assert service.store.get_job(job["id"])["resumeforge"]["attempts"] == expected_attempts
    service.process_document_queue()
    assert len(calls) == 3


def test_missing_profile_waits_without_hot_loop_and_retries_after_setup(tmp_path, monkeypatch):
    api(tmp_path, monkeypatch)
    from jobpilot import service

    master = tmp_path / "resumeforge-master"
    calls = []
    job = service.store.add_job(
        {
            "url": "https://example.com/setup",
            "title": "Platform Engineer",
            "company": "Setup",
            "description": "Build AWS and Python automation.",
            "fit": 91,
            "status": "queued",
        }
    )

    def build(data, current):
        calls.append(current["id"])
        if not (master / "draft.json").is_file():
            raise FileNotFoundError("Save your ResumeForge profile first.")
        path = data / "applications" / "setup.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 fictional checked resume")
        return {
            "status": "ready",
            "path": str(path),
            "workspace": service.resumeforge_bridge.workspace_path(data, current).name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    monkeypatch.setattr(service.resumeforge_bridge, "master_workspace", lambda: master)
    monkeypatch.setattr(service.resumeforge_bridge, "build_resume", build)

    service.process_document_queue()
    waiting = service.store.get_job(job["id"])
    assert waiting["resumeforge"]["status"] == "setup_required"
    assert waiting["resumeforge"]["attempts"] == 0
    service.process_document_queue()
    assert calls == [job["id"]]

    master.mkdir()
    (master / "draft.json").write_text("{}", encoding="utf-8")
    service.process_document_queue()
    assert calls == [job["id"], job["id"]]
    assert service.store.get_job(job["id"])["resumeforge"]["status"] == "ready"


def test_unchanged_incomplete_profile_never_hot_loops(tmp_path, monkeypatch):
    api(tmp_path, monkeypatch)
    from jobpilot import service

    master = tmp_path / "resumeforge-master"
    master.mkdir()
    draft = master / "draft.json"
    draft.write_text(json.dumps({"profile": {"name": ""}, "settings": {}}), encoding="utf-8")
    calls = []
    job = service.store.add_job(
        {
            "url": "https://example.com/incomplete-setup",
            "title": "Platform Engineer",
            "company": "Setup",
            "description": "Build AWS and Python automation.",
            "fit": 91,
            "status": "queued",
        }
    )

    def build(*_):
        calls.append(job["id"])
        raise ValueError("Save a complete profile and model settings in ResumeForge first.")

    monkeypatch.setattr(service.resumeforge_bridge, "master_workspace", lambda: master)
    monkeypatch.setattr(service.resumeforge_bridge, "build_resume", build)

    service.process_document_queue()
    blocked = service.store.get_job(job["id"])["resumeforge"]
    assert blocked["status"] == "setup_required"
    assert blocked["master_revision"] == hashlib.sha256(draft.read_bytes()).hexdigest()
    service.process_document_queue()
    service.process_document_queue()
    assert calls == [job["id"]]

    draft.write_text(
        json.dumps({"profile": {"name": "Configured Candidate"}, "settings": {}}),
        encoding="utf-8",
    )
    service.process_document_queue()
    assert calls == [job["id"], job["id"]]


def test_bundled_engine_exports_checked_pdf_to_role_folder(tmp_path, monkeypatch):
    source = Path(resumeforge_bridge.__file__).parents[1] / "resumeforge/data/abu.profile.json"
    profile = json.loads(source.read_text(encoding="utf-8"))
    assert profile["name"] == "Morgan Example"
    assert profile["contact"] == "morgan@example.invalid | Remote | example.invalid/morgan"
    profile["name"] = "Smoke Candidate"
    master = tmp_path / "master"
    master.mkdir()
    (master / "draft.json").write_text(
        json.dumps({"profile": profile, "settings": {"provider": "none"}}),
        encoding="utf-8",
    )
    folder = tmp_path / "JobPilot RF Docs" / "Signal Orchard Studio - Platform Engineer"
    monkeypatch.setattr(resumeforge_bridge, "master_workspace", lambda: master)
    monkeypatch.setattr(resumeforge_bridge, "downloads_folder", lambda job: folder)
    job = {
        "id": 1,
        "company": "Signal Orchard Studio",
        "title": "Platform Engineer",
        "description": "Build AWS test environments, Python automation, GitHub Actions "
        "release pipelines, monitoring, Linux operations, and incident response.",
        "keywords": {"terms": ["AWS", "Python", "GitHub Actions"]},
    }
    result = resumeforge_bridge.build_resume(tmp_path / "data", job)
    assert result["status"] == "ready"
    workspace = resumeforge_bridge.workspace_path(tmp_path / "data", job)
    automatic = folder / workspace.name / "Alnajjar_Resume.pdf"
    assert automatic.read_bytes().startswith(b"%PDF-")
    assert Path(result["path"]) == automatic
    assert not (folder / "Alnajjar_CoverLetter.pdf").exists()

    letter = automatic.parent / "Alnajjar_CoverLetter.pdf"
    candidate = Profile.model_validate(profile)
    export_pdf(
        draft_text(candidate, job["company"], job["title"], "AWS, Python"), candidate, letter
    )
    assert letter.read_bytes().startswith(b"%PDF-")
