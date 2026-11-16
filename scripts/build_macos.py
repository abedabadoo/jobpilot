"""Build a complete native JobPilot.app on macOS (no external Python at runtime)."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def build_command(source: Path, output: Path, work: Path) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        "JobPilot",
        "--icon",
        str(source / "assets/jobpilot.ico"),
        "--osx-bundle-identifier",
        "com.jobpilot.desktop",
        "--target-arch",
        platform.machine(),
        "--distpath",
        str(output),
        "--workpath",
        str(work / "build"),
        "--specpath",
        str(work / "spec"),
    ]
    # Dynamic service imports and plugin backends must survive freezing. In
    # particular, pywebview imports Cocoa lazily and keyring discovers backends
    # from package metadata rather than the launcher's normal import graph.
    for package in (
        "jobpilot",
        "webview",
        "keyring",
        "jobspy",
        "curl_cffi",
        "playwright",
        "docx",
        "reportlab",
    ):
        command.extend(["--collect-all", package])
    for module in (
        "jobpilot.service",
        "webview.platforms.cocoa",
        "keyring.backends.macOS",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.lifespan.on",
    ):
        command.extend(["--hidden-import", module])
    command.extend(["--copy-metadata", "keyring"])
    for source_name, destination in (
        ("web", "jobpilot/_assets/web"),
        ("remote_web", "jobpilot/_assets/remote_web"),
        ("jobpilot/candidate.json", "jobpilot"),
        ("LICENSE", "."),
        ("THIRD_PARTY_NOTICES.md", "."),
    ):
        command.extend(["--add-data", f"{source / source_name}:{destination}"])
    identity = os.environ.get("JOBPILOT_CODESIGN_IDENTITY")
    if identity:
        command.extend(["--codesign-identity", identity])
    command.append(str(source / "launcher.py"))
    return command


def build(output: Path, *, dmg: bool = False) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError(
            "Build JobPilot.app on native macOS; cross-platform freezing is unsupported"
        )
    architecture = platform.machine()
    if architecture not in {"arm64", "x86_64"}:
        raise RuntimeError(f"Unsupported macOS architecture: {architecture}")
    source = Path(__file__).resolve().parents[1]
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = output / "macos-build"
    (work / "spec").mkdir(parents=True, exist_ok=True)
    dist = work / "dist"
    env = os.environ.copy()
    env["PYINSTALLER_CONFIG_DIR"] = str(work / "pyinstaller-cache")
    subprocess.run(build_command(source, dist, work), cwd=source, env=env, check=True)
    application = dist / "JobPilot.app"
    if not (application / "Contents/MacOS/JobPilot").is_file():
        raise RuntimeError("PyInstaller did not produce the native JobPilot.app executable")
    archive = output / f"JobPilot-{architecture}.app.zip"
    # ditto preserves app symlinks, permissions and native bundle metadata.
    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(application), str(archive)],
        check=True,
    )
    shutil.copy2(source / "scripts/Install-JobPilot-macOS.command", output)
    if dmg:
        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                "JobPilot",
                "-srcfolder",
                str(application),
                "-ov",
                "-format",
                "UDZO",
                str(output / f"JobPilot-{architecture}.dmg"),
            ],
            check=True,
        )
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/macos"))
    parser.add_argument("--dmg", action="store_true", help="Also create a disk image with hdiutil")
    args = parser.parse_args()
    print(build(args.output, dmg=args.dmg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
