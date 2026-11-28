"""Verify a frozen Mac service, documents, local extension API and Cocoa dashboard."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def check(application: Path, report: Path, *, gui: bool = False) -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("Run the native Mac smoke check on macOS")
    binary = application.resolve() / "Contents/MacOS/JobPilot"
    if not binary.is_file():
        raise RuntimeError(f"Native application executable missing: {binary}")
    with tempfile.TemporaryDirectory(prefix="jobpilot-bundle-smoke-") as directory:
        temporary = Path(directory)
        data = temporary / "data"
        home = temporary / "home"
        master = home / "Library/Application Support/ResumeForge/workspace"
        master.mkdir(parents=True)
        profile = json.loads(
            (Path(__file__).resolve().parents[1] / "resumeforge/data/abu.profile.json").read_text()
        )
        assert profile["name"] == "Morgan Example"
        assert str(profile.get("contact", "")).endswith("example.invalid/morgan")
        profile["name"] = "Smoke Candidate"
        (master / "draft.json").write_text(
            json.dumps({"version": 2, "profile": profile, "settings": {"provider": "none"}})
        )
        env = {
            **os.environ,
            "HOME": str(home),
            "JOBPILOT_DATA_DIR": str(data),
            "JOBPILOT_TESTING": "0",
        }
        diagnostic = temporary / "diagnostic.json"
        subprocess.run(
            [str(binary), "--diagnose", "--report", str(diagnostic)],
            env=env,
            check=True,
            timeout=30,
        )
        details = json.loads(diagnostic.read_text())
        assert details["source_present"] and details["python_present"], details
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        log_path = temporary / "service.log"
        with log_path.open("wb") as log:
            child = subprocess.Popen(
                [str(binary), "--service-child", "--port", str(port)],
                env=env,
                stdout=log,
                stderr=log,
            )
            result = {}

            def request(path, body=None, headers=None, *, binary_response=False):
                outgoing = dict(headers or {})
                payload = None
                if body is not None:
                    outgoing["Content-Type"] = "application/json"
                    payload = json.dumps(body).encode()
                with urlopen(
                    Request(base + path, payload, headers=outgoing), timeout=10
                ) as response:
                    return response.read() if binary_response else json.load(response)

            try:
                deadline = time.monotonic() + 60
                while True:
                    if child.poll() is not None:
                        raise RuntimeError(log_path.read_text(errors="replace"))
                    try:
                        if request("/api/health").get("ok"):
                            break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Frozen service did not become ready") from None
                        time.sleep(0.25)
                state = request("/api/state")
                assert state["profile"].get("sample_profile") is True
                assert not state["settings"]["submission_enabled"]
                assert b"Chrome autofill" in request("/", binary_response=True)
                token = request("/api/session")["token"]
                dashboard_headers = {"X-JobPilot-Token": token}
                imported = request(
                    "/api/import",
                    {
                        "title": "Platform Engineer",
                        "company": "Fictional Smoke Employer",
                        "url": "https://example.com/careers/jobpilot-smoke",
                        "description": "Build AWS test environments, Python automation, GitHub Actions release pipelines, monitoring, Linux operations, and incident response.",
                    },
                    dashboard_headers,
                )
                job = imported["jobs"][0]
                assert job["fit"] == 80, "The fixture must exercise the exact auto-build threshold"
                job_id = job["id"]
                deadline = time.monotonic() + 180
                while True:
                    job = next(j for j in request("/api/state")["jobs"] if j["id"] == job_id)
                    if job.get("documents", {}).get("resumeforge_pdf"):
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            f"Frozen automatic ResumeForge preparation did not complete: {job}"
                        )
                    time.sleep(0.5)
                assert not job["documents"].get("resumeforge_cover_pdf")
                assert Path(job["documents"]["resumeforge_pdf"]).name == "Alnajjar_Resume.pdf"
                cover_route = f"/api/jobs/{job_id}/cover-letter"
                cover = request(cover_route)
                assert cover["can_generate"] and not cover["exists"]
                letter_path = Path(job["documents"]["resumeforge_pdf"]).with_name(
                    "Alnajjar_CoverLetter.pdf"
                )
                assert not letter_path.exists()
                try:
                    request(
                        cover_route,
                        {
                            "action": "generate",
                            "revision": 0,
                            "instructions": "Rewrite the opening.",
                        },
                        dashboard_headers,
                    )
                except HTTPError as error:
                    assert error.code == 409 and b"Configure a local model" in error.read()
                else:
                    raise AssertionError("A custom rewrite ran without a configured model")
                assert not letter_path.exists()
                deadline = time.monotonic() + 60
                request(cover_route, {"action": "generate", "revision": 0}, dashboard_headers)
                while time.monotonic() < deadline:
                    cover = request(cover_route)
                    if cover["task"]["state"] != "running":
                        break
                    time.sleep(0.2)
                assert cover["ready"], cover["task"]["message"]
                assert letter_path.read_bytes().startswith(b"%PDF")
                extension_id = "a" * 32
                code = request(
                    "/api/extension/pairing", {"extension_id": extension_id}, dashboard_headers
                )["code"]
                extension_headers = {"Origin": f"chrome-extension://{extension_id}"}
                pairing = request("/api/extension/pair", {"code": code}, extension_headers)
                extension_headers["Authorization"] = f"Bearer {pairing['token']}"
                profile = request("/api/extension/profile", {}, extension_headers)["profile"]
                assert profile["name"] == "Jordan Morgan"
                documents = request("/api/extension/documents", {}, extension_headers)["documents"]
                resume = next(item for item in documents if item["kind"] == "resume_pdf")
                payload = request(
                    resume["download_path"], {}, extension_headers, binary_response=True
                )
                assert payload.startswith(b"%PDF")
                request("/api/extension/disconnect", {}, extension_headers)
                result = {
                    "frozen_service": True,
                    "fictional_profile": True,
                    "documents": True,
                    "automatic_resume_at_80": True,
                    "cover_letter_opt_in": True,
                    "extension_api": True,
                    "gui": False,
                }
                if gui:
                    gui_report = temporary / "cocoa.json"
                    gui_process = subprocess.run(
                        [
                            str(binary),
                            "--verify-dashboard",
                            "--service-url",
                            base,
                            "--report",
                            str(gui_report),
                            "--verify-timeout",
                            "45",
                        ],
                        env=env,
                        check=False,
                        timeout=65,
                    )
                    if gui_report.is_file():
                        result["gui"] = json.loads(gui_report.read_text())
                    gui_process.check_returncode()
                    assert result["gui"].get("ok") is True
                    assert result["gui"].get("frozen") is True
                    assert request("/api/health")["ok"] is True
                return result
            finally:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("dist/macos/smoke.json"))
    parser.add_argument("--gui", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.app, args.report, gui=args.gui), indent=2))


if __name__ == "__main__":
    main()
