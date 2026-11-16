import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest


def test_desktop_build_keeps_binaries_out_of_the_source_tree(tmp_path):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if not powershell:
        pytest.skip("PowerShell is required for the Windows build script")
    source = tmp_path / "source"
    source.mkdir()
    builder = tmp_path / "fake-builder.ps1"
    builder.write_text(
        """$arguments = $args
$dist = $arguments[[Array]::IndexOf($arguments, '--distpath') + 1]
$output = Join-Path $dist 'JobPilot'
New-Item -ItemType Directory -Path (Join-Path $output '_internal') -Force | Out-Null
Set-Content -LiteralPath (Join-Path $output 'JobPilot.exe') -Value 'build fixture'
Set-Content -LiteralPath (Join-Path $output '_internal/runtime.txt') -Value 'runtime fixture'
exit 0
""",
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "Build-JobPilot.ps1"
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-SourceRoot",
            str(source),
            "-BuildPython",
            str(builder),
            "-WorkRoot",
            str(tmp_path / "build"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "build" / "desktop-dist" / "JobPilot" / "JobPilot.exe").is_file()
    assert not (source / "JobPilot.exe").exists()
    assert not (source / "_internal").exists()


def mac_builder():
    path = Path(__file__).resolve().parents[1] / "scripts/build_macos.py"
    spec = importlib.util.spec_from_file_location("mac_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mac_builder_collects_service_native_keychain_and_fictional_assets(tmp_path):
    builder = mac_builder()
    source = Path(__file__).resolve().parents[1]
    command = builder.build_command(source, tmp_path / "dist", tmp_path / "work")
    assert command[:3] == [builder.sys.executable, "-m", "PyInstaller"]
    assert "jobpilot.service" in command
    assert "keyring.backends.macOS" in command
    assert "webview.platforms.cocoa" in command
    assert "--windowed" in command
    assert "--osx-bundle-identifier" in command
    for asset in ["web", "remote_web", "jobpilot/candidate.json"]:
        assert any(str(source / asset) in item for item in command)
    assert not any("data/" in item or "installed_paths.json" in item for item in command)
    assert "--distpath" in command and str(tmp_path / "dist") in command


def test_mac_builder_archives_app_with_ditto_and_no_python_runtime_dependency(
    tmp_path, monkeypatch
):
    builder = mac_builder()
    monkeypatch.setattr(builder.sys, "platform", "darwin")
    monkeypatch.setattr(builder.platform, "machine", lambda: "arm64")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "PyInstaller" in command:
            dist = Path(command[command.index("--distpath") + 1])
            (dist / "JobPilot.app/Contents/MacOS").mkdir(parents=True)
            (dist / "JobPilot.app/Contents/MacOS/JobPilot").write_text("frozen fixture")
        elif command[0] == "ditto":
            Path(command[-1]).touch()

    monkeypatch.setattr(builder.subprocess, "run", run)
    archive = builder.build(tmp_path / "release")
    assert archive == tmp_path / "release/JobPilot-arm64.app.zip"
    assert archive.is_file()
    assert any(command[:4] == ["ditto", "-c", "-k", "--sequesterRsrc"] for command in calls)
    assert not any("pip" in command for command in calls)


def test_mac_builder_rejects_cross_platform_packaging(tmp_path, monkeypatch):
    builder = mac_builder()
    monkeypatch.setattr(builder.sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="macOS"):
        builder.build(tmp_path)
