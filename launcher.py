"""JobPilot desktop and independent local-service launcher."""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from jobpilot.platforms import (
    PosixDesktopInstance,
    application_data_dir,
    find_ollama,
    notify_error,
    set_startup,
)

SERVICE_URL = "http://127.0.0.1:8765"
OLLAMA_URL = "http://127.0.0.1:11436"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def data_directory() -> Path:
    return application_data_dir()


def child_environment(data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "JOBPILOT_DATA_DIR": str(data_dir),
            "PLAYWRIGHT_BROWSERS_PATH": str(data_dir / "browsers"),
            "OLLAMA_HOST": "127.0.0.1:11436",
            "OLLAMA_NO_CLOUD": "1",
            "OLLAMA_MODELS": str(data_dir / "ollama-models"),
            "OLLAMA_CONTEXT_LENGTH": "8192",
            "OLLAMA_FLASH_ATTENTION": "1",
            "OLLAMA_KV_CACHE_TYPE": "q8_0",
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_KEEP_ALIVE": "15m",
            "PYTHONUNBUFFERED": "1",
            "PYINSTALLER_RESET_ENVIRONMENT": "1",
        }
    )
    return env


def validate_loopback(base_url: str) -> str:
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
    ):
        raise ValueError("JobPilot control requires an HTTP loopback endpoint")
    return base_url.rstrip("/")


def request_json(
    path: str,
    payload: dict | None = None,
    *,
    token: str | None = None,
    base_url: str = SERVICE_URL,
    timeout: float = 10,
) -> dict:
    base_url = validate_loopback(base_url)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-JobPilot-Token"] = token
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    with urlopen(Request(base_url + path, data=data, headers=headers), timeout=timeout) as response:
        return json.load(response)


def control_worker(payload: dict, *, base_url: str = SERVICE_URL) -> dict:
    validate_loopback(base_url)
    token = request_json("/api/session", base_url=base_url)["token"]
    return request_json("/api/control", payload, token=token, base_url=base_url)


def app_paths() -> dict:
    frozen = getattr(sys, "frozen", False)
    native_bundle = frozen and sys.platform == "darwin"
    root = (
        Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        if native_bundle
        else Path(sys.executable).resolve().parent
        if frozen
        else Path(__file__).resolve().parent
    )
    config = root / "installed_paths.json"
    paths = json.loads(config.read_text(encoding="utf-8-sig")) if config.exists() else {}
    data = data_directory()
    paths.setdefault("source", str(root))
    default_python = (
        data / "runtime" / "Scripts" / "python.exe"
        if frozen and sys.platform == "win32"
        else Path(sys.executable)
    )
    paths.setdefault("python", str(default_python))
    paths.setdefault("ollama", find_ollama())
    paths.setdefault(
        "desktop_exe", str(root / "JobPilot.exe") if sys.platform == "win32" else sys.executable
    )
    paths.setdefault("data", str(data))
    paths["bundled_service"] = native_bundle
    return paths


def service_command(paths: dict) -> list[str]:
    if paths.get("bundled_service"):
        return [paths["desktop_exe"], "--service-child", "--port", "8765"]
    return [paths["python"], "-m", "jobpilot.service", "--port", "8765"]


def endpoint_ready(base_url: str, path: str, *, service: bool = False) -> bool:
    try:
        result = request_json(path, base_url=base_url, timeout=1)
        return result.get("ok") is True if service else bool(result.get("version"))
    except (OSError, ValueError, KeyError):
        return False


def wait_endpoint(
    base_url: str, path: str, process: subprocess.Popen, *, service: bool = False, seconds: int = 45
) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if endpoint_ready(base_url, path, service=service):
            return
        if process.poll() is not None:
            raise RuntimeError(
                f"JobPilot child exited with code {process.returncode}; see local logs."
            )
        time.sleep(0.25)
    raise RuntimeError(f"Local service did not become ready at {base_url}; see local logs.")


def start_child(
    arguments: list[str], *, cwd: Path, env: dict, log_name: str, data: Path
) -> subprocess.Popen:
    logs = data / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (
        (logs / f"{log_name}.out.log").open("ab") as stdout,
        (logs / f"{log_name}.err.log").open("ab") as stderr,
    ):
        process = subprocess.Popen(
            arguments,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
            start_new_session=sys.platform != "win32",
        )
    (data / f"{log_name}.pid").write_text(str(process.pid), encoding="ascii")
    return process


def ensure_services(paths: dict, data: Path) -> dict:
    data.mkdir(parents=True, exist_ok=True)
    env = child_environment(data)
    status = {}
    if not endpoint_ready(OLLAMA_URL, "/api/version"):
        ollama = Path(paths.get("ollama") or "")
        status["ollama_available"] = False
        if ollama.is_file():
            try:
                process = start_child(
                    [str(ollama), "serve"], cwd=ollama.parent, env=env, log_name="ollama", data=data
                )
                wait_endpoint(OLLAMA_URL, "/api/version", process, seconds=5)
                status.update(ollama_pid=process.pid, ollama_available=True)
            except (OSError, RuntimeError):
                logging.exception("Optional local Ollama could not start; opening JobPilot anyway")
    else:
        status["ollama_reused"] = True
        status["ollama_available"] = True
    if not endpoint_ready(SERVICE_URL, "/api/health", service=True):
        python = Path(paths["python"])
        source = Path(paths["source"])
        if not python.is_file() or (
            not paths.get("bundled_service") and not (source / "jobpilot" / "service.py").is_file()
        ):
            raise RuntimeError(
                "JobPilot runtime/source is missing. Reinstall JobPilot to repair it."
            )
        if sys.platform == "win32" or paths.get("bundled_service"):
            env["JOBPILOT_DESKTOP_EXE"] = paths["desktop_exe"]
        else:
            env.pop("JOBPILOT_DESKTOP_EXE", None)
        process = start_child(
            service_command(paths),
            cwd=source,
            env=env,
            log_name="service",
            data=data,
        )
        wait_endpoint(SERVICE_URL, "/api/health", process, service=True)
        status["service_pid"] = process.pid
    else:
        status["service_reused"] = True
    return status


class DesktopInstance:
    """Per-user desktop singleton; a second launch opens the first dashboard."""

    def __new__(cls, name: str = "JobPilot"):
        if sys.platform != "win32":
            return PosixDesktopInstance(name)
        return super().__new__(cls)

    def __init__(self, name: str = "JobPilot"):
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CreateEventW.argtypes = (
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        kernel.CreateEventW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.SetEvent.argtypes = (wintypes.HANDLE,)
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel = kernel
        self.mutex = kernel.CreateMutexW(None, False, f"Local\\{name}Desktop")
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.owner = ctypes.get_last_error() != 183
        self.event = kernel.CreateEventW(None, False, False, f"Local\\{name}OpenDashboard")
        if not self.event:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def signal_open(self):
        self.kernel.SetEvent(self.event)

    def wait_for_open(self, timeout: float = 0.5) -> bool:
        return self.kernel.WaitForSingleObject(self.event, int(timeout * 1000)) == 0

    def close(self):
        for name in ("event", "mutex"):
            handle = getattr(self, name, None)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)


def configure_macos_reopen(open_window) -> None:
    from webview.platforms.cocoa import BrowserView

    # Finder/Dock normally sends an Apple event to the running application
    # rather than launching another executable. pywebview 6.2 does not handle
    # that event itself, so extend its delegate before the first native window.
    class JobPilotAppDelegate(BrowserView.AppDelegate):
        def applicationShouldHandleReopen_hasVisibleWindows_(self, application, has_windows):
            open_window()
            return True

    BrowserView.AppDelegate = JobPilotAppDelegate


def show_dashboard(background: bool, data: Path, instance: DesktopInstance) -> None:
    import webview

    state = {"quitting": False}
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["ALLOW_DOWNLOADS"] = True
    window = webview.create_window(
        "JobPilot",
        SERVICE_URL,
        width=1380,
        height=900,
        min_size=(1000, 650),
        hidden=background,
        background_color="#10151E",
        text_select=True,
    )

    def open_window(*_):
        window.show()
        window.restore()

    def event_watch():
        while not state["quitting"]:
            if instance.wait_for_open(0.5):
                open_window()

    if sys.platform == "darwin":
        from webview.menu import Menu, MenuAction

        configure_macos_reopen(open_window)

        def quit_native():
            state["quitting"] = True
            window.destroy()

        menu = [
            Menu(
                "JobPilot",
                [
                    MenuAction("Open JobPilot", open_window),
                    MenuAction("Quit dashboard", quit_native),
                ],
            )
        ]
        threading.Thread(target=event_watch, name="JobPilotOpenEvent", daemon=True).start()
        try:
            # Cocoa's event loop and menus must run on the process main thread.
            webview.start(
                gui="cocoa",
                menu=menu,
                private_mode=True,
                storage_path=str(data / "dashboard-webview"),
            )
        finally:
            state["quitting"] = True
            instance.close()
        return

    import pystray
    from PIL import Image, ImageDraw

    icon_image = Image.new("RGBA", (64, 64), "#10151E")
    draw = ImageDraw.Draw(icon_image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill="#5EEAD4")
    draw.line([(23, 21), (23, 39), (26, 43), (32, 43), (36, 39), (36, 21)], fill="#10151E", width=5)

    def action(payload: dict):
        def perform(*_):
            try:
                control_worker(payload)
            except Exception:
                logging.exception("Tray control failed")
                open_window()

        return perform

    def quit_dashboard(icon, _):
        state["quitting"] = True
        icon.stop()
        window.destroy()

    tray = pystray.Icon(
        "JobPilot",
        icon_image,
        "JobPilot — local job assistant",
        pystray.Menu(
            pystray.MenuItem("Open JobPilot", open_window, default=True),
            pystray.MenuItem(
                "Pause search",
                action({"search_enabled": False, "submission_enabled": False}),
            ),
            pystray.MenuItem("Stop worker", action({"action": "stop"})),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit dashboard (worker continues)", quit_dashboard),
        ),
    )

    def closing():
        if not state["quitting"]:
            window.hide()
            return False
        return True

    window.events.closing += closing
    threading.Thread(target=tray.run, name="JobPilotTray", daemon=True).start()
    threading.Thread(target=event_watch, name="JobPilotOpenEvent", daemon=True).start()
    try:
        webview.start(
            gui="edgechromium", private_mode=True, storage_path=str(data / "dashboard-webview")
        )
    finally:
        state["quitting"] = True
        tray.stop()
        instance.close()


def diagnostic(paths: dict, data: Path) -> dict:
    return {
        "source_present": paths.get("bundled_service", False)
        or (Path(paths["source"]) / "jobpilot" / "service.py").is_file(),
        "python_present": Path(paths["python"]).is_file(),
        "ollama_present": Path(paths["ollama"]).is_file(),
        "service_ready": endpoint_ready(SERVICE_URL, "/api/health", service=True),
        "ollama_ready": endpoint_ready(OLLAMA_URL, "/api/version"),
        "data_directory": str(data),
        "startup": set_startup("status", paths["desktop_exe"]),
        "paths": paths,
    }


def main() -> int:
    if "--service-child" in sys.argv[1:]:
        sys.argv.remove("--service-child")
        from jobpilot.service import main as service_main

        service_main()
        return 0
    parser = argparse.ArgumentParser(description="JobPilot desktop and local service")
    parser.add_argument("--background", action="store_true", help="Start with the dashboard hidden")
    parser.add_argument(
        "--service-only",
        action="store_true",
        help="Start/reuse the independent worker service without opening the desktop",
    )
    parser.add_argument(
        "--startup",
        choices=("enable", "disable", "status"),
        help="Configure optional sign-in startup for this user",
    )
    parser.add_argument(
        "--diagnose", action="store_true", help="Report installation and service status"
    )
    parser.add_argument(
        "--verify-dashboard",
        action="store_true",
        help="Run an isolated native dashboard diagnostic",
    )
    parser.add_argument(
        "--service-url", default=SERVICE_URL, help="Loopback URL for dashboard diagnostic"
    )
    parser.add_argument(
        "--verify-timeout", type=float, default=45, help="Dashboard diagnostic deadline"
    )
    parser.add_argument("--report", type=Path, help="Save command results as JSON")
    args = parser.parse_args()
    if args.verify_dashboard:
        if args.report is None:
            parser.error("--verify-dashboard requires --report")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        try:
            url = validate_loopback(args.service_url)
            from jobpilot.desktop_check import verify_dashboard

            result = verify_dashboard(
                url=url,
                report_path=args.report,
                show_dashboard=show_dashboard,
                instance_factory=PosixDesktopInstance,
                timeout=args.verify_timeout,
            )
        except Exception as error:
            result = {"ok": False, "loaded": False, "quit": False, "error": str(error)}
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if sys.stdout:
            print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    paths = app_paths()
    data = Path(os.environ.get("JOBPILOT_DATA_DIR", paths["data"])).resolve()
    (data / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=data / "logs" / "desktop.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    instance = None
    try:
        if not (args.startup or args.diagnose or args.service_only):
            instance = DesktopInstance()
            if not instance.owner:
                instance.signal_open()
                return 0
        if args.startup:
            if (
                args.startup == "enable"
                and sys.platform == "darwin"
                and not paths["bundled_service"]
            ):
                raise RuntimeError("Sign-in startup requires the installed JobPilot.app")
            result = set_startup(args.startup, paths["desktop_exe"])
        elif args.diagnose:
            result = diagnostic(paths, data)
        else:
            result = ensure_services(paths, data)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if sys.stdout:
            print(json.dumps(result, indent=2))
        if not (args.startup or args.diagnose or args.service_only):
            show_dashboard(args.background, data, instance)
        return 0
    except Exception as error:
        logging.exception("Desktop startup failed")
        if args.report:
            args.report.write_text(json.dumps({"error": str(error)}, indent=2), encoding="utf-8")
        if not args.service_only and not args.diagnose and not args.startup:
            notify_error(f"{error}\n\nLogs: {data / 'logs'}")
        return 1
    finally:
        if instance is not None:
            instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
