"""Small desktop platform boundary; importing this module never loads Win32 APIs."""

from __future__ import annotations

import atexit
import json
import os
import plistlib
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


def application_data_dir() -> Path:
    override = os.environ.get("JOBPILOT_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "JobPilot"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "JobPilot"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "JobPilot"


def find_ollama() -> str:
    explicit = os.environ.get("JOBPILOT_OLLAMA")
    if explicit:
        return str(Path(explicit).expanduser())
    found = shutil.which("ollama")
    if found:
        return found
    if sys.platform == "darwin":
        locations = [
            Path("/opt/homebrew/bin/ollama"),
            Path("/usr/local/bin/ollama"),
            Path("/Applications/Ollama.app/Contents/Resources/ollama"),
            Path.home() / "Applications/Ollama.app/Contents/Resources/ollama",
        ]
    elif sys.platform == "win32":
        locations = [
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "Programs/Ollama/ollama.exe"
        ]
    else:
        locations = []
    return next((str(path) for path in locations if path.is_file()), "")


def set_startup(mode: str, executable: str) -> dict:
    if sys.platform == "win32":
        import winreg

        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
        ) as key:
            if mode == "enable":
                if not Path(executable).is_file():
                    raise RuntimeError("Installed JobPilot executable is missing")
                winreg.SetValueEx(key, "JobPilot", 0, winreg.REG_SZ, f'"{executable}" --background')
            elif mode == "disable":
                try:
                    winreg.DeleteValue(key, "JobPilot")
                except FileNotFoundError:
                    pass
            try:
                command = winreg.QueryValueEx(key, "JobPilot")[0]
            except FileNotFoundError:
                command = None
        return {"startup_enabled": command is not None, "command": command}
    if sys.platform != "darwin":
        return {"startup_enabled": False, "command": None}
    label = "com.jobpilot.desktop"
    agent = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    if mode == "enable":
        if not Path(executable).is_file():
            raise RuntimeError("Installed JobPilot executable is missing")
        agent.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": label,
            "ProgramArguments": [executable, "--background"],
            "RunAtLoad": True,
            "WorkingDirectory": str(Path(executable).parent),
            "ProcessType": "Interactive",
        }
        if os.environ.get("JOBPILOT_DATA_DIR"):
            payload["EnvironmentVariables"] = {"JOBPILOT_DATA_DIR": str(application_data_dir())}
        temporary = agent.with_suffix(".tmp")
        temporary.write_bytes(plistlib.dumps(payload))
        temporary.chmod(0o600)
        temporary.replace(agent)
        # Enable next sign-in without bootstrapping a second desktop now.
        subprocess.run(
            ["launchctl", "enable", f"gui/{getattr(os, 'getuid', lambda: 0)()}/{label}"],
            check=False,
            capture_output=True,
        )
    elif mode == "disable":
        agent.unlink(missing_ok=True)
        # Do not bootout: disabling startup should not terminate this dashboard.
    enabled = agent.is_file()
    return {
        "startup_enabled": enabled,
        "command": [executable, "--background"] if enabled else None,
    }


class PosixDesktopInstance:
    """Advisory lock released by the OS on exit, plus a same-user reopen signal."""

    def __init__(self, name: str = "JobPilot", *, data: Path | None = None):
        import fcntl

        data = data or application_data_dir()
        data.mkdir(parents=True, exist_ok=True)
        self.lock = (data / f".{name}-desktop.lock").open("a+b")
        self.signal_path = data / f".{name}-desktop-open"
        self._seen = self._signal_value()
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.owner = True
        except BlockingIOError:
            self.owner = False

    def _signal_value(self):
        try:
            return self.signal_path.read_bytes()
        except FileNotFoundError:
            return b""

    def signal_open(self):
        self.signal_path.write_text(str(time.time_ns()), encoding="ascii")

    def wait_for_open(self, timeout: float = 0.5) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            signal = self._signal_value()
            if signal != self._seen:
                self._seen = signal
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            threading.Event().wait(min(remaining, 0.1))

    def close(self):
        if not self.lock.closed:
            self.lock.close()


class SystemSleepInhibitor:
    """Keep an AC-powered Mac awake while requested, tied to the service PID."""

    def __init__(self):
        self.process = None
        atexit.register(self.close)

    def set_enabled(self, enabled: bool):
        if sys.platform != "darwin":
            return
        if not enabled:
            self.close()
        elif self.process is None or self.process.poll() is not None:
            self.process = subprocess.Popen(
                ["/usr/bin/caffeinate", "-s", "-w", str(os.getpid())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def close(self):
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def notify_error(message: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "JobPilot startup", 0x10)
    elif sys.platform == "darwin":
        # Pass user-visible text as argv, never interpolate it into AppleScript.
        subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                'on run argv\ndisplay alert "JobPilot startup" message (item 1 of argv) as critical\nend run',
                message,
            ],
            check=False,
            capture_output=True,
        )
    else:
        print(json.dumps({"error": message}), file=sys.stderr)
