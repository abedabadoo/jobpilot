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
