"""Explicit, verified updates for standalone Intel macOS ResumeForge.app installs.

An update is offered only from official GitHub Releases with a matching
sha256 asset digest. App replacement runs in a separate helper after the
current process exits; no Python, Homebrew, or manual DMG handling is needed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile

REPO = "abedabadoo/resumeforge"
API = "https://api.github.com/repos/" + REPO + "/releases?per_page=30"
ZIP_NAME = "ResumeForge-macOS-Intel.zip"
MAX_DOWNLOAD = 250 * 1024 * 1024
MAX_UNCOMPRESSED = 800 * 1024 * 1024
BUNDLE_ID = "com.resumeforge.desktop"


@dataclass(frozen=True)
class Update:
    tag: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Prepared:
    update: Update
    extracted_app: Path
    installed_app: Path
    destination_app: Path
    temp_dir: Path


def installed_app() -> Path | None:
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    for parent in executable.parents:
        if parent.suffix == ".app":
            return parent
    return None


def current_tag() -> str:
    info = Path(__file__).with_name("build_info.json")
    try:
        return str(json.loads(info.read_text(encoding="utf-8")).get("tag", ""))
    except (OSError, ValueError, TypeError):
        return ""


def select_update(releases: list[dict], current: str) -> Update | None:
    eligible = []
    for release in releases:
        if release.get("draft"):
            continue
        tag = str(release.get("tag_name", ""))
        if not re.fullmatch(r"mac-intel-[0-9a-f]{8}", tag):
            continue
        asset = next((a for a in release.get("assets", [])
                      if a.get("name") == ZIP_NAME), None)
        if not asset:
            continue
        digest = str(asset.get("digest", ""))
        url = str(asset.get("browser_download_url", ""))
        parsed = urllib.parse.urlparse(url)
        if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
            continue
        if (parsed.scheme != "https" or parsed.hostname != "github.com"
                or parsed.path != f"/{REPO}/releases/download/{tag}/{ZIP_NAME}"
                or parsed.query or parsed.fragment):
            continue
        try:
            size = int(asset.get("size", 0))
        except (ValueError, TypeError):
            continue
        if size <= 0 or size > MAX_DOWNLOAD:
            continue
        eligible.append((str(release.get("published_at", "")),
                         Update(tag, url, digest[7:].lower(), size)))
    if not eligible:
        return None
    tag = max(eligible, key=lambda row: row[0])[1]
    return None if tag.tag == current else tag


def check_for_update() -> Update | None:
    if installed_app() is None:
        raise RuntimeError("Updates are available in the installed Intel Mac app.")
    request = urllib.request.Request(API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "ResumeForge-macOS-Intel",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        releases = json.load(response)
    if not isinstance(releases, list):
        raise ValueError("GitHub did not return a valid release listing")
    return select_update(releases, current_tag())


def _check_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not members or len(members) > 15000:
            raise ValueError("The update archive contains an invalid number of files")
        total = sum(member.file_size for member in members)
        if total > MAX_UNCOMPRESSED:
            raise ValueError("The update archive exceeds its expected size")
        for member in members:
            name = member.filename
            parts = PurePosixPath(name).parts
            if (not parts or parts[0] != "ResumeForge.app"
                    or any(part in (".", "..") for part in parts)
                    or name.startswith("/") or "\\" in name):
                raise ValueError("Unsafe file path in update archive")
            # Framework symlinks are supported, but never allow ZIP-provided
            # symlinks that resolve outside the application directory.
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                target = archive.read(member).decode("utf-8", "strict")
                parent = list(parts[:-1])
                if target.startswith("/"):
                    raise ValueError("Update archive contains an absolute symlink")
                for part in PurePosixPath(target).parts:
                    if part == "..":
                        if len(parent) <= 1:
                            raise ValueError("Update archive contains an escaping symlink")
                        parent.pop()
                    elif part not in ("", "."):
                        parent.append(part)


# Mach-O CPU types: CPU_ARCH_ABI64 | CPU_TYPE_X86.
# Inspect the executable header directly instead of invoking /usr/bin/lipo,
# which is an Xcode Command Line Tools utility and may fail on an ordinary Mac.
_INTEL64_CPU = 0x01000007
_MACHO64_ENDIAN = {
    b"\xcf\xfa\xed\xfe": "<",  # MH_MAGIC_64, little endian
    b"\xfe\xed\xfa\xcf": ">",  # MH_MAGIC_64, big endian
}


def _intel_macho(binary: Path) -> bool:
    """Check the bundled executable's 64-bit Mach-O CPU type using Python only.

    The separate codesign verification authenticates the extracted bundle;
    this check enforces the correct native CPU family without requiring
    Xcode, Homebrew, or the Apple developer CLI on the user's machine.
    """
    with binary.open("rb") as stream:
        header = stream.read(32)
    if len(header) < 32:
        raise ValueError("The application executable is incomplete.")
    endian = _MACHO64_ENDIAN.get(header[:4])
    if endian is None:
        raise ValueError("The application executable is not a 64-bit Mach-O binary.")
    return struct.unpack_from(endian + "I", header, 4)[0] == _INTEL64_CPU


def _bundle_check(app: Path) -> None:
    info = app / "Contents" / "Info.plist"
    binary = app / "Contents" / "MacOS" / "ResumeForge"
    if not (app.is_dir() and info.is_file() and binary.is_file()):
        raise ValueError("The update is missing the macOS application executable")
    with info.open("rb") as stream:
        metadata = plistlib.load(stream)
    if (metadata.get("CFBundleIdentifier") != BUNDLE_ID or
            metadata.get("CFBundleExecutable") != "ResumeForge"):
        raise ValueError("The update does not identify itself as ResumeForge")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                   check=True, capture_output=True, timeout=30)
    if not _intel_macho(binary):
        raise ValueError("This update is not built for an Intel (x86_64) Mac.")


def _install_target(current: Path) -> Path:
    """Use a user-writable location when the current app is protected/mounted."""
    if os.access(current.parent, os.W_OK):
        return current
    target = Path.home() / "Applications" / "ResumeForge.app"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        _bundle_check(target)
    return target


def prepare_update(update: Update) -> Prepared:
    current = installed_app()
    if current is None:
        raise RuntimeError("Updates require a packaged Intel Mac installation")
    directory = Path(tempfile.mkdtemp(prefix="resumeforge-update-",
                                     dir=Path.home() / "Library" / "Caches"
                                     if (Path.home() / "Library" / "Caches").is_dir() else None))
    try:
        payload = directory / ZIP_NAME
        request = urllib.request.Request(update.url, headers={"User-Agent": "ResumeForge-macOS-Intel"})
        hasher = hashlib.sha256()
        count = 0
        with urllib.request.urlopen(request, timeout=90) as response, payload.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_DOWNLOAD:
                    raise ValueError("Update exceeds the permitted size")
                hasher.update(chunk)
                stream.write(chunk)
        if count != update.size or hasher.hexdigest() != update.sha256:
            raise ValueError("Update download failed SHA-256 integrity verification")
        _check_archive(payload)
        subprocess.run(["/usr/bin/ditto", "-x", "-k", str(payload), str(directory)],
                       check=True, capture_output=True, timeout=120)
        app = directory / "ResumeForge.app"
        _bundle_check(app)
        return Prepared(update, app, current, _install_target(current), directory)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def install_after_exit(prepared: Prepared) -> None:
    """Spawn a detached built-in helper; GUI must quit immediately afterward."""
    script = Path(__file__).with_name("mac_update_helper.sh")
    if not script.is_file():
        raise RuntimeError("The packaged Mac update helper is missing")
    logger = Path.home() / "Library" / "Logs" / "ResumeForge" / "update.log"
    logger.parent.mkdir(parents=True, exist_ok=True)
    # Copy outside the old .app so the helper remains available while replacing.
    helper = prepared.temp_dir / "install-update.sh"
    shutil.copyfile(script, helper)
    with logger.open("a", encoding="utf-8") as log:
        subprocess.Popen(["/bin/sh", str(helper), str(os.getpid()),
                          str(prepared.destination_app), str(prepared.extracted_app),
                          str(prepared.temp_dir), str(logger)],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True, close_fds=True)
