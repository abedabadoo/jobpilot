"""Local storage and checked-file export for the desktop application."""
import hashlib
import json
import os
from pathlib import Path
import tempfile


def load_draft(data_dir: Path) -> dict | None:
    path = data_dir / "draft.json"
    if not path.exists():
        return None
    draft = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(draft, dict):
        raise ValueError("This saved workspace could not be read as a ResumeForge draft.")
    return draft


def _replace_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".resumeforge-", delete=False) as stage:
        temporary = Path(stage.name)
        try:
            stage.write(data)
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


def save_draft(data_dir: Path, draft: dict) -> None:
    data = json.dumps(draft, indent=2, ensure_ascii=False).encode("utf-8")
    _replace_file(data_dir / "draft.json", data)


def export_checked(run_dir: Path, destination: Path) -> None:
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    report = result["report"]
    if (result["status"] != "ready" or not report.get("geometry_passed")
            or not report.get("quality_review", {}).get("passed")):
        raise ValueError("This resume needs further review before it can be exported.")
    checked = (run_dir / "resume.pdf").read_bytes()
    if hashlib.sha256(checked).hexdigest() != report.get("pdf_sha256"):
        raise ValueError("The PDF has changed since it passed review. Build the resume again.")
    if destination.suffix.lower() != ".pdf":
        raise ValueError("Choose a PDF filename.")
    _replace_file(destination, checked)
