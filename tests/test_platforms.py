import plistlib
from pathlib import Path


def test_explicit_data_directory_does_not_require_localappdata(tmp_path, monkeypatch):
    from jobpilot import platforms

    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path / "custom"))
    assert platforms.application_data_dir() == (tmp_path / "custom").resolve()


def test_mac_data_and_ollama_locations(tmp_path, monkeypatch):
    from jobpilot import platforms

    monkeypatch.delenv("JOBPILOT_DATA_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("JOBPILOT_OLLAMA", raising=False)
    monkeypatch.setattr(platforms.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert platforms.application_data_dir() == tmp_path / "Library/Application Support/JobPilot"
    binary = tmp_path / "Applications/Ollama.app/Contents/Resources/ollama"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(platforms.shutil, "which", lambda _: None)
    assert platforms.find_ollama() == str(binary)


def test_mac_optional_startup_is_a_launch_agent_with_separate_arguments(tmp_path, monkeypatch):
    from jobpilot import platforms

    monkeypatch.setattr(platforms.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(platforms.subprocess, "run", lambda args, **kw: calls.append(args))
    executable = tmp_path / "JobPilot App.app/Contents/MacOS/JobPilot"
    executable.parent.mkdir(parents=True)
    executable.touch()
    result = platforms.set_startup("enable", str(executable))
    agent = tmp_path / "Library/LaunchAgents/com.jobpilot.desktop.plist"
    content = plistlib.loads(agent.read_bytes())
    assert content["ProgramArguments"] == [str(executable), "--background"]
    assert content["RunAtLoad"] is True
    assert content["WorkingDirectory"] == str(executable.parent)
    assert result["startup_enabled"] is True
    assert platforms.set_startup("status", str(executable))["startup_enabled"] is True
    assert platforms.set_startup("disable", str(executable))["startup_enabled"] is False
    assert not agent.exists()
    assert calls


def test_portable_instance_signals_existing_owner_and_releases_lock(tmp_path):
    import sys

    import pytest

    if sys.platform == "win32":
        pytest.skip("POSIX file locking is exercised on native Mac CI")
    from jobpilot.platforms import PosixDesktopInstance

    first = PosixDesktopInstance("test", data=tmp_path)
    second = PosixDesktopInstance("test", data=tmp_path)
    try:
        assert first.owner is True
        assert second.owner is False
        assert not first.wait_for_open(0)
        second.signal_open()
        assert first.wait_for_open(1)
    finally:
        second.close()
        first.close()
    third = PosixDesktopInstance("test", data=tmp_path)
    try:
        assert third.owner is True
    finally:
        third.close()


def test_mac_startup_preserves_the_selected_profile_directory(tmp_path, monkeypatch):
    from jobpilot import platforms

    monkeypatch.setattr(platforms.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path / "custom profile"))
    monkeypatch.setattr(platforms.subprocess, "run", lambda *args, **kwargs: None)
    executable = tmp_path / "JobPilot.app/Contents/MacOS/JobPilot"
    executable.parent.mkdir(parents=True)
    executable.touch()
    platforms.set_startup("enable", str(executable))
    agent = tmp_path / "Library/LaunchAgents/com.jobpilot.desktop.plist"
    payload = plistlib.loads(agent.read_bytes())
    assert payload.get("EnvironmentVariables", {}).get("JOBPILOT_DATA_DIR") == str(
        (tmp_path / "custom profile").resolve()
    )


def test_mac_keep_awake_is_optional_ac_only_and_reaped(monkeypatch):
    from types import SimpleNamespace

    from jobpilot import platforms

    monkeypatch.setattr(platforms.sys, "platform", "darwin")
    calls = []
    stopped = []
    process = SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: stopped.append("terminate"),
        wait=lambda **kw: stopped.append("wait"),
    )
    monkeypatch.setattr(
        platforms.subprocess, "Popen", lambda args, **kw: calls.append(args) or process
    )
    inhibitor = platforms.SystemSleepInhibitor()
    inhibitor.set_enabled(False)
    assert calls == []
    inhibitor.set_enabled(True)
    inhibitor.set_enabled(True)
    assert calls == [["/usr/bin/caffeinate", "-s", "-w", str(platforms.os.getpid())]]
    inhibitor.set_enabled(False)
    assert stopped == ["terminate", "wait"]
    inhibitor.close()
    assert stopped == ["terminate", "wait"]
