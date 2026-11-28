"""Verified updates for the per-user Windows desktop installation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

REPO = "abedabadoo/resumeforge"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALLER_NAME = "ResumeForge-Setup-x64.exe"
MAX_DOWNLOAD = 250 * 1024 * 1024
VERSION = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")


@dataclass(frozen=True)
class Update:
    tag: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Prepared:
    update: Update
    installer: Path
    temp_dir: Path
    target_dir: Path


def _version(value: str) -> tuple[int, int, int] | None:
    match = VERSION.fullmatch(value if value.startswith("v") else f"v{value}")
    return tuple(map(int, match.groups())) if match else None


def select_update(releases: list[dict], current: str) -> Update | None:
    installed = _version(current)
    if installed is None:
        raise ValueError("The installed ResumeForge version is invalid")
    eligible = []
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name", ""))
        number = _version(tag)
        if number is None or number <= installed:
            continue
        for asset in release.get("assets", []):
            if asset.get("name") != INSTALLER_NAME:
                continue
            digest = str(asset.get("digest", ""))
            url = str(asset.get("browser_download_url", ""))
            parsed = urllib.parse.urlsplit(url)
            try:
                size = int(asset.get("size", 0))
            except (TypeError, ValueError):
                continue
            if (not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)
                    or parsed.scheme != "https" or parsed.netloc != "github.com"
                    or parsed.path != f"/{REPO}/releases/download/{tag}/{INSTALLER_NAME}"
                    or parsed.query or parsed.fragment or size <= 0 or size > MAX_DOWNLOAD):
                continue
            eligible.append((number, Update(tag, url, digest[7:].lower(), size)))
    return max(eligible, key=lambda item: item[0])[1] if eligible else None


def check_for_update() -> Update | None:
    request = urllib.request.Request(API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "ResumeForge-Windows",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            release = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not isinstance(release, dict):
        raise ValueError("GitHub did not return a valid release")
    return select_update([release], __version__)


def _current_install_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[4]
    if ((candidate / ".resumeforge-install").is_file()
            and (candidate / "ResumeForge.exe").is_file()
            and (candidate / "runtime" / "pythonw.exe").is_file()):
        return candidate
    return None


def _target_dir() -> Path:
    current = _current_install_root()
    if current is not None:
        return current
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    target = base / "Programs" / "ResumeForge"
    if target.exists() and any(target.iterdir()) and not (target / ".resumeforge-install").is_file():
        raise RuntimeError("The default install folder is occupied by another application")
    return target


def prepare_update(update: Update, *, cache_dir: Path | None = None) -> Prepared:
    target = _target_dir()
    folder = Path(tempfile.mkdtemp(prefix="resumeforge-update-", dir=cache_dir))
    installer = folder / INSTALLER_NAME
    try:
        request = urllib.request.Request(update.url, headers={"User-Agent": "ResumeForge-Windows"})
        hasher = hashlib.sha256()
        count = 0
        with urllib.request.urlopen(request, timeout=90) as response, installer.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_DOWNLOAD:
                    raise ValueError("Update download exceeds the permitted size")
                hasher.update(chunk)
                stream.write(chunk)
        if count != update.size or hasher.hexdigest() != update.sha256:
            raise ValueError("Update download failed SHA-256 integrity verification")
        return Prepared(update, installer, folder, target)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def install_after_exit(prepared: Prepared, data_dir: Path) -> None:
    script = Path(__file__).with_name("windows_update_helper.ps1")
    if not script.is_file():
        raise RuntimeError("The Windows update helper is missing from this build")
    helper = prepared.temp_dir / script.name
    shutil.copyfile(script, helper)
    log = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ResumeForge" / "update.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    launcher_pid = os.getppid() if _current_install_root() else 0
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(helper), "-WindowPid", str(os.getpid()),
        "-LauncherPid", str(launcher_pid), "-Installer", str(prepared.installer),
        "-Digest", prepared.update.sha256, "-Target", str(prepared.target_dir),
        "-DataDir", str(data_dir), "-Log", str(log),
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
       creationflags=flags, close_fds=True)
