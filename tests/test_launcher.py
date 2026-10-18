import importlib.util
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def launcher_module():
    path = Path(__file__).resolve().parents[1] / "launcher.py"
    assert path.exists(), "Desktop launcher has not been implemented"
    spec = importlib.util.spec_from_file_location("desktop_launcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_checkout_uses_the_current_python_interpreter(tmp_path, monkeypatch):
    launcher = launcher_module()
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(launcher, "__file__", str(tmp_path / "launcher.py"))
    monkeypatch.setattr(launcher.sys, "frozen", False, raising=False)
    paths = launcher.app_paths()
    assert paths["python"] == launcher.sys.executable
    assert Path(paths["source"]) == tmp_path


def test_frozen_desktop_uses_its_installed_runtime(tmp_path, monkeypatch):
    launcher = launcher_module()
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / "JobPilot.exe"))
    paths = launcher.app_paths()
    assert Path(paths["python"]) == tmp_path / "data" / "runtime" / "Scripts" / "python.exe"
    assert Path(paths["source"]) == tmp_path


def test_child_inference_and_browser_are_isolated_from_parent_environment(tmp_path):
    """Dropping child-only settings would allow cloud inference or shared profiles."""
    launcher = launcher_module()
    original = os.environ.copy()
    env = launcher.child_environment(tmp_path)
    assert env["OLLAMA_NO_CLOUD"] == "1"
    assert env["OLLAMA_HOST"] == "127.0.0.1:11436"
    assert Path(env["OLLAMA_MODELS"]) == tmp_path / "ollama-models"
    assert Path(env["PLAYWRIGHT_BROWSERS_PATH"]) == tmp_path / "browsers"
    assert os.environ == original


def test_worker_pause_carries_session_token_and_disables_both_engines():
    """Missing token or a partial pause would leave one engine running."""
    launcher = launcher_module()
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/api/session"
            payload = {"token": "local-session-test-token"}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_POST(self):
            seen.append(
                (
                    self.path,
                    self.headers.get("X-JobPilot-Token"),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        launcher.control_worker(
            {"search_enabled": False, "submission_enabled": False},
            base_url=f"http://127.0.0.1:{server.server_port}",
        )
        assert seen == [
            (
                "/api/control",
                "local-session-test-token",
                {"search_enabled": False, "submission_enabled": False},
            )
        ]
    finally:
        server.shutdown()
        server.server_close()


def test_control_client_rejects_external_endpoints():
    """A remote control endpoint would expose the local session capability."""
    launcher = launcher_module()
    with pytest.raises(ValueError, match="loopback"):
        launcher.control_worker({"action": "stop"}, base_url="https://example.com")


def test_only_one_desktop_instance_owns_launch_until_it_exits():
    """Losing the singleton lets double-clicking launch concurrent workers."""
    launcher = launcher_module()
    name = "JobPilotTest" + uuid.uuid4().hex
    first = launcher.DesktopInstance(name)
    second = launcher.DesktopInstance(name)
    try:
        assert first.owner is True
        assert second.owner is False
    finally:
        second.close()
        first.close()
    third = launcher.DesktopInstance(name)
    try:
        assert third.owner is True
    finally:
        third.close()
