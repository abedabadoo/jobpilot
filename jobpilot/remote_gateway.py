"""An outbound HTTPS tunnel restricted to the isolated companion portal."""

import re
import subprocess
import threading
from pathlib import Path


class RemoteGateway:
    def __init__(self, data_dir, executable=None, popen=None):
        self.data_dir = Path(data_dir)
        self.executable = (
            Path(executable) if executable else self.data_dir.parent / "tools" / "cloudflared.exe"
        )
        self.popen = popen or subprocess.Popen
        self.process = None
        self.url = ""
        self.state = "stopped"
        self.error = ""
        self.lock = threading.RLock()
        self.ready = threading.Event()

    def status(self):
        with self.lock:
            return {
                "state": self.state,
                "url": self.url,
                "error": self.error,
                "temporary_hostname": True,
            }

    def start(self, allowed=None):
        with self.lock:
            if allowed is not None and not allowed():
                return ""
            if self.process and self.process.poll() is None:
                return self.url
            if not self.executable.is_file():
                self.state = "error"
                self.error = "Install the verified cloudflared executable in JobPilot/tools first."
                raise RuntimeError(self.error)
            self.state, self.url, self.error = "starting", "", ""
            self.ready.clear()
            if allowed is not None and not allowed():
                self.state = "stopped"
                return ""
            self.process = self.popen(
                [
                    str(self.executable),
                    "tunnel",
                    "--no-autoupdate",
                    "--url",
                    "http://127.0.0.1:8766",
                    "--protocol",
                    "http2",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            threading.Thread(
                target=self._read, args=(self.process,), name="remote-tunnel-output", daemon=True
            ).start()
        self.ready.wait(45)
        with self.lock:
            if not self.url:
                self.error = "HTTPS tunnel is still connecting. Check remote setup again shortly."
            return self.url

    def _read(self, process):
        try:
            for line in process.stdout:
                match = re.search(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com\b", line)
                if match:
                    with self.lock:
                        if self.process is process and self.state != "stopped":
                            self.url, self.state, self.error = match[0], "connected", ""
                    self.ready.set()
            with self.lock:
                if (
                    self.process is process
                    and self.state != "stopped"
                    and process.poll() is not None
                ):
                    self.state, self.url = "error", ""
                    self.error = "HTTPS tunnel stopped. Reconnect from local remote setup."
            self.ready.set()
        except Exception:
            with self.lock:
                if self.state != "stopped":
                    self.state, self.error = "error", "HTTPS tunnel connection failed."
            self.ready.set()

    def stop(self):
        with self.lock:
            process = self.process
            self.state, self.url = "stopped", ""
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        self.ready.set()
