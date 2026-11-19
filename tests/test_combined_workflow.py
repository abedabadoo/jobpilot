import json
from pathlib import Path

from test_api import api

from jobpilot import resumeforge_bridge
from resumeforge.cover_letter import draft_text, export_pdf
from resumeforge.models import Profile


def test_eighty_percent_starts_resumeforge_without_a_cover_letter(tmp_path, monkeypatch):
    api(tmp_path, monkeypatch)
    from jobpilot import service

    low = service.store.add_job(
        {
            "url": "https://example.com/low",
            "title": "Platform Engineer",
            "company": "Low",
            "description": "AWS and Python operations",
            "fit": 79,
            "status": "queued",
        }
    )
    high = service.store.add_job(
        {
            "url": "https://example.com/high",
            "title": "Platform Engineer",
            "company": "High",
            "description": "AWS and Python operations",
            "fit": 80,
            "status": "queued",
        }
    )
    calls = []

    def build(data, job):
        calls.append(job["id"])
        return {"status": "ready", "path": str(tmp_path / "Alnajjar_Resume.pdf")}

    monkeypatch.setattr(service.resumeforge_bridge, "build_resume", build)
    service.process_document_queue()
    assert calls == [high["id"]]
    assert service.store.get_job(low["id"])["status"] == "queued"
    documents = service.store.get_job(high["id"])["documents"]
    assert set(documents) == {"resumeforge_pdf"}


def test_bundled_engine_exports_checked_pdf_to_role_folder(tmp_path, monkeypatch):
    source = Path(resumeforge_bridge.__file__).parents[1] / "resumeforge/data/abu.profile.json"
    profile = json.loads(source.read_text(encoding="utf-8"))
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
    assert (folder / "Alnajjar_Resume.pdf").read_bytes().startswith(b"%PDF-")
    assert not (folder / "Alnajjar_CoverLetter.pdf").exists()

    letter = folder / "Alnajjar_CoverLetter.pdf"
    candidate = Profile.model_validate(profile)
    export_pdf(
        draft_text(candidate, job["company"], job["title"], "AWS, Python"), candidate, letter
    )
    assert letter.read_bytes().startswith(b"%PDF-")
