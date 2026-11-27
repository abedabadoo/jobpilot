"""Open an opportunity in ResumeForge and read its checked output."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_REPORT_BYTES = 5 * 1024 * 1024
_MAX_PDF_BYTES = 15 * 1024 * 1024
_MAX_MASTER_DRAFT_BYTES = 10 * 1024 * 1024
_STALLED_RUN_NS = 30 * 60 * 1_000_000_000


def master_workspace() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / (
            "ResumeForge/workspace"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/ResumeForge/workspace"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / (
        "ResumeForge/workspace"
    )


def master_revision() -> str:
    """Return a stable revision for the saved master draft, or an empty value."""
    draft = master_workspace() / "draft.json"
    try:
        if draft.is_symlink() or not draft.is_file():
            return ""
        size = draft.stat().st_size
        if not 2 <= size <= _MAX_MASTER_DRAFT_BYTES:
            return ""
        return hashlib.sha256(draft.read_bytes()).hexdigest()
    except OSError:
        return ""


def windows_install_dir() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\ResumeForge") as key:
            value, _ = winreg.QueryValueEx(key, "InstallDir")
    except OSError:
        return None
    return Path(value) if isinstance(value, str) and value.strip() else None


def desktop_executable() -> Path:
    combined = os.environ.get("JOBPILOT_DESKTOP_EXE")
    if combined and Path(combined).is_file():
        return Path(combined).resolve()
    override = os.environ.get("RESUMEFORGE_DESKTOP_EXE")
    if override:
        candidates = [Path(override)]
    elif sys.platform == "win32":
        candidates = []
        registered = windows_install_dir()
        if registered:
            candidates.append(registered / "ResumeForge.exe")
        candidates.append(
            Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
            / "Programs/ResumeForge/ResumeForge.exe"
        )
    elif sys.platform == "darwin":
        candidates = [
            Path.home() / "Applications/ResumeForge.app/Contents/MacOS/ResumeForge",
            Path("/Applications/ResumeForge.app/Contents/MacOS/ResumeForge"),
        ]
    else:
        candidates = []
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Install ResumeForge to open this job in its desktop editor.")


def _job_description(job: dict) -> str:
    description = str(job.get("description") or "").strip()
    if not description:
        raise ValueError("Add this job's description before opening it in ResumeForge.")
    heading = (
        f"{str(job.get('title') or '').strip()} at {str(job.get('company') or '').strip()}".strip()
    )
    return f"{heading}\n\n{description}"[:40000]


def workspace_path(data_dir: Path, job: dict) -> Path:
    posting = {
        "id": int(job["id"]),
        "title": str(job.get("title") or ""),
        "company": str(job.get("company") or ""),
        "description": _job_description(job),
    }
    digest = hashlib.sha256(json.dumps(posting, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return Path(data_dir) / "resumeforge" / f"job-{posting['id']}-{digest}"


def validate_workspace(data_dir: Path, workspace: Path) -> None:
    data_dir = Path(data_dir)
    base = data_dir / "resumeforge"
    draft = workspace / "draft.json"
    if (
        base.is_symlink()
        or workspace.is_symlink()
        or draft.is_symlink()
        or not base.resolve().is_relative_to(data_dir.resolve())
        or not workspace.resolve().is_relative_to(base.resolve())
        or not draft.resolve().is_relative_to(workspace.resolve())
    ):
        raise ValueError("The ResumeForge role workspace is outside JobPilot's data directory.")


def validate_import_directory(data_dir: Path, folder: Path) -> None:
    data_dir = Path(data_dir)
    applications = data_dir / "applications"
    if (
        applications.is_symlink()
        or folder.is_symlink()
        or not applications.resolve().is_relative_to(data_dir.resolve())
        or not folder.resolve().is_relative_to(applications.resolve())
    ):
        raise ValueError("The ResumeForge PDF destination is outside JobPilot's data directory.")


def checked_copy(path: str, digest: str, data_dir: Path) -> bool:
    candidate = Path(path)
    applications = Path(data_dir) / "applications"
    downloads = Path.home() / "Downloads" / "JobPilot RF Docs"
    try:
        return (
            not applications.is_symlink()
            and not applications.is_junction()
            and not downloads.is_symlink()
            and not downloads.is_junction()
            and not candidate.is_symlink()
            and not candidate.is_junction()
            and (
                candidate.resolve().is_relative_to(applications.resolve())
                or candidate.resolve().is_relative_to(downloads.resolve())
            )
            and candidate.is_file()
            and 5 <= candidate.stat().st_size <= _MAX_PDF_BYTES
            and hashlib.sha256(candidate.read_bytes()).hexdigest() == digest
        )
    except OSError:
        return False


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".handoff-", delete=False
    ) as stage:
        temporary = Path(stage.name)
        try:
            json.dump(value, stage, ensure_ascii=False, indent=2)
            stage.flush()
            os.fsync(stage.fileno())
        except BaseException:
            stage.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_workspace(data_dir: Path, job: dict, *, master_dir: Path | None = None) -> Path:
    workspace = workspace_path(data_dir, job)
    validate_workspace(data_dir, workspace)
    draft_path = workspace / "draft.json"
    if draft_path.exists():
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        changed = False
        if not draft.get("job_posting_url"):
            draft["job_posting_url"] = _posting_url(job)
            changed = True
        if not draft.get("job_company") or not draft.get("job_title"):
            draft["job_company"] = posting_company(job)
            draft["job_title"] = str(job.get("title") or "")
            changed = True
        if not draft.get("last_run"):
            try:
                result = checked_run(workspace)
                if result["status"] in {"needs_content", "needs_review"}:
                    preview = _inside(
                        workspace / "runs" / result["run_id"] / "preview.pdf", workspace
                    )
                    if preview.is_file():
                        draft["last_run"] = result["run_id"]
                        changed = True
            except (OSError, ValueError):
                # A damaged previous run must not prevent opening the editor.
                pass
        if changed:
            _atomic_json(draft_path, draft)
        return workspace
    source = (Path(master_dir) if master_dir is not None else master_workspace()) / "draft.json"
    if not source.is_file():
        raise FileNotFoundError(
            "Save your profile in ResumeForge before opening a JobPilot opportunity."
        )
    master = json.loads(source.read_text(encoding="utf-8"))
    profile = master.get("profile")
    settings = master.get("settings")
    if (
        not isinstance(profile, dict)
        or not profile.get("name")
        or profile.get("name") == "Morgan Example"
        or not isinstance(profile.get("roles"), list)
        or not profile["roles"]
        or not isinstance(settings, dict)
    ):
        raise ValueError("Save a complete profile and model settings in ResumeForge first.")
    draft = {
        "version": 2,
        "analyzed": False,
        "last_run": None,
        "profile": profile,
        "settings": settings,
        "job_description": _job_description(job),
        "edit_request": "",
        "keywords": "",  # Preserve ResumeForge’s own posting analysis.
        "job_company": posting_company(job),
        "job_title": str(job.get("title") or ""),
        "job_posting_url": _posting_url(job),
    }
    _atomic_json(draft_path, draft)
    return workspace


def open_editor(executable: Path, workspace: Path) -> None:
    combined = executable.name.lower().startswith("jobpilot")
    subprocess.Popen(
        [
            str(executable),
            *(["--resumeforge-child"] if combined else []),
            "--data-dir",
            str(workspace),
        ],
        cwd=str(executable.parent),
        shell=False,
        close_fds=True,
    )


def posting_company(job: dict) -> str:
    return str(job.get("company") or "Employer").strip()


def _posting_url(job: dict) -> str:
    from .collectors import _alert_destination

    return _alert_destination(str(job.get("apply_url") or job.get("url") or ""))


def downloads_folder(job: dict) -> Path:
    from resumeforge.cover_letter import role_folder

    return role_folder(posting_company(job), str(job.get("title") or "Role"))


def resume_destination(data_dir: Path, job: dict) -> Path:
    """Return a friendly filename in a posting-specific export directory."""
    from resumeforge.cover_letter import posting_subfolder
    from resumeforge.cover_workflow import RESUME_NAME

    return (
        posting_subfolder(downloads_folder(job), workspace_path(data_dir, job).name) / RESUME_NAME
    )


def cover_workspace(data_dir: Path, job: dict):
    from resumeforge.cover_workflow import LetterWorkspace
    from resumeforge.desktop_support import load_draft
    from resumeforge.models import ModelSettings

    workspace = workspace_path(data_dir, job)
    validate_workspace(data_dir, workspace)
    checked = checked_run(workspace)
    if checked["status"] != "ready":
        raise ValueError("Build and check a ResumeForge resume for this role first.")
    saved = load_draft(workspace) or {}
    return LetterWorkspace(
        workspace,
        checked["pdf"].parent,
        resume_destination(data_dir, job),
        posting_company(job),
        str(job.get("title") or ""),
        _job_description(job),
        ModelSettings.model_validate(saved.get("settings") or {}),
        _posting_url(job),
    )


def build_resume(data_dir: Path, job: dict) -> dict:
    """Run the bundled ResumeForge engine; a cover letter requires a separate UI action."""
    from uuid import uuid4

    from resumeforge.desktop_support import export_checked
    from resumeforge.engine import run
    from resumeforge.models import ModelSettings, Profile, RunRequest

    workspace = prepare_workspace(data_dir, job)
    draft_path = workspace / "draft.json"
    saved_input = draft_path.read_bytes()
    draft = json.loads(saved_input)
    # Match the editor's Generate new example achievements mode for unattended
    # builds. The user's master profile and per-role editing preferences stay
    # in the saved draft.
    settings = ModelSettings.model_validate(draft["settings"]).model_copy(
        update={"draft_mode": "inspiration", "wording_policy": "rewrite"}
    )
    request = RunRequest(
        profile=Profile.model_validate(draft["profile"]),
        settings=settings,
        job_description=draft["job_description"],
        # JobPilot's keyword list is a fast lexical summary for the dashboard,
        # not a set the user reviewed. Passing it as reviewed priorities skips
        # ResumeForge's contextual posting analysis and can make generic tools
        # outrank the role's actual responsibilities. Automatic runs therefore
        # analyze the full posting themselves. Priorities become reviewed only
        # after the user confirms them in the ResumeForge editor.
        keywords=[],
        reviewed_priorities=None,
    )
    run_dir = workspace / "runs" / uuid4().hex
    result = run(request, run_dir)
    if draft_path.read_bytes() != saved_input:
        return {"status": "needs_review", "workspace": workspace.name}
    status = result["status"]
    if status == "ready":
        destination = resume_destination(data_dir, job)
        export_checked(run_dir, destination)
    if status == "ready" or (run_dir / "preview.pdf").is_file():
        # The editor can reopen a preview even when the check withheld export.
        draft["last_run"] = run_dir.name
        _atomic_json(draft_path, draft)
    if status != "ready":
        return {"status": status, "workspace": workspace.name}
    return {
        "status": "ready",
        "path": str(destination),
        "workspace": workspace.name,
        "run_id": run_dir.name,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("A ResumeForge run points outside its role workspace.")
    return resolved


def checked_run(workspace: Path) -> dict:
    if workspace.is_symlink() or (workspace / "draft.json").is_symlink():
        raise ValueError("The ResumeForge role workspace is redirected.")
    runs = workspace / "runs"
    if not runs.is_dir():
        return {"status": "not_built"}
    _inside(runs, workspace)

    def modified_at(folder: Path) -> int:
        result = folder / "result.json"
        return result.stat().st_mtime_ns if result.exists() else folder.stat().st_mtime_ns

    folders = sorted(
        (entry for entry in runs.iterdir() if entry.is_dir() and _RUN_ID.fullmatch(entry.name)),
        key=modified_at,
        reverse=True,
    )
    if not folders:
        return {"status": "not_built"}
    folder = _inside(folders[0], workspace)
    report_file = _inside(folder / "result.json", workspace)
    if not report_file.exists():
        if time.time_ns() - folder.stat().st_mtime_ns > _STALLED_RUN_NS:
            return {"status": "unknown", "run_id": folder.name}
        return {"status": "building", "run_id": folder.name}
    if report_file.stat().st_size > _MAX_REPORT_BYTES:
        raise ValueError("The ResumeForge run report is too large to import.")
    try:
        result = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("The ResumeForge run report could not be read.") from exc
    if not isinstance(result, dict):
        raise ValueError("The ResumeForge run report is invalid.")
    draft = workspace / "draft.json"
    if draft.is_file() and draft.stat().st_mtime_ns > report_file.stat().st_mtime_ns:
        try:
            saved = json.loads(draft.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("The ResumeForge role workspace could not be read.") from exc
        if not isinstance(saved, dict) or saved.get("last_run") != folder.name:
            return {"status": "outdated", "run_id": folder.name}
    status = result.get("status")
    if status != "ready":
        return {"status": str(status or "invalid"), "run_id": folder.name}
    report = result.get("report")
    if not isinstance(report, dict) or not (
        report.get("geometry_passed") is True
        and isinstance(report.get("quality_review"), dict)
        and report["quality_review"].get("passed") is True
    ):
        raise ValueError("The ResumeForge PDF has not passed its export checks.")
    pdf = _inside(folder / "resume.pdf", workspace)
    if not pdf.is_file() or not 5 <= pdf.stat().st_size <= _MAX_PDF_BYTES:
        raise ValueError("The checked ResumeForge PDF is missing or too large.")
    content = pdf.read_bytes()
    if not content.startswith(b"%PDF-"):
        raise ValueError("The checked ResumeForge file is not a PDF.")
    digest = hashlib.sha256(content).hexdigest()
    if digest != report.get("pdf_sha256"):
        raise ValueError("The checked ResumeForge PDF changed after its review.")
    return {"status": "ready", "run_id": folder.name, "pdf": pdf, "sha256": digest}
