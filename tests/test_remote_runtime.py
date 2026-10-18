"""Remote disable/re-enable must not leave a dead server or a late tunnel."""

import threading
import time
from types import SimpleNamespace

import pytest

from jobpilot import remote_runtime


def wait_for(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail("Remote lifecycle did not reach the expected state")


class FakeGateway:
    def __init__(self, *_args):
        self.url = ""
        self.starts = 0
        self.entered = threading.Event()
        self.start_gate = threading.Event()
        self.start_gate.set()
        self.stop_entered = threading.Event()
        self.stop_gate = threading.Event()
        self.stop_gate.set()

    def status(self):
        return {"state": "connected" if self.url else "stopped", "url": self.url}

    def start(self, allowed=None):
        self.entered.set()
        self.start_gate.wait(3)
        if allowed is not None and not allowed():
            return ""
        self.starts += 1
        self.url = "https://test-only.trycloudflare.com"
        return self.url

    def stop(self):
        self.stop_entered.set()
        self.start_gate.set()
        self.stop_gate.wait(3)
        self.url = ""


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    import uvicorn

    from jobpilot import remote, remote_auth, remote_notifications

    servers = []
    start_ready = threading.Event()
    start_ready.set()

    class Server:
        def __init__(self, config):
            self.config = config
            self.started = False
            self.should_exit = False
            self.crash = threading.Event()
            servers.append(self)

        def run(self):
            while not self.should_exit and not start_ready.is_set():
                time.sleep(0.005)
            if self.should_exit:
                return
            self.started = True
            while not self.should_exit and not self.crash.is_set():
                time.sleep(0.005)
            # Match Uvicorn: started is historical and stays true after exit.

    monkeypatch.setattr(uvicorn, "Server", Server)
    monkeypatch.setattr(uvicorn, "Config", lambda app, **kwargs: SimpleNamespace(app=app, **kwargs))
    monkeypatch.setattr(remote_runtime, "RemoteGateway", FakeGateway)
    monkeypatch.setattr(remote, "create_remote_app", lambda *args: object())
    monkeypatch.setattr(
        remote_auth,
        "RemoteAuth",
        lambda *args: SimpleNamespace(
            valid_hash=lambda digest: True, pairing_secret=lambda: "PRIVATE_PAIRING_SECRET"
        ),
    )
    monkeypatch.setattr(
        remote_notifications,
        "RemoteNotifications",
        lambda *args, **kwargs: SimpleNamespace(
            status=lambda: {"subscribed_devices": 0}, notify=lambda case: None
        ),
    )
    instance = remote_runtime.RemoteRuntime(tmp_path, threading.Event())
    yield instance, servers, start_ready
    instance.gateway.stop_gate.set()
    instance.gateway.start_gate.set()
    instance.stop()


def test_stopped_server_does_not_report_listening_and_reenable_creates_new_server(runtime):
    instance, servers, _ = runtime
    instance.start_async()
    wait_for(lambda: not instance.starting)
    assert instance.status()["listening"] is True
    assert instance.gateway.starts == 1
    instance.stop()
    assert servers[0].started is True
    assert instance.status()["listening"] is False
    instance.start_async()
    wait_for(lambda: not instance.starting)
    assert instance.status()["listening"] is True
    assert len(servers) == 2
    assert instance.gateway.starts == 2


def test_server_that_exited_unexpectedly_is_recreated_even_if_started_is_true(runtime):
    instance, servers, _ = runtime
    instance.start_async()
    wait_for(lambda: not instance.starting)
    servers[0].crash.set()
    instance.thread.join(timeout=1)
    assert instance.status()["listening"] is False
    assert instance.gateway.status()["url"] == ""
    instance.start_async()
    wait_for(lambda: not instance.starting)
    assert len(servers) == 2
    assert instance.status()["listening"] is True


def test_disable_while_server_starting_prevents_any_tunnel_start(runtime):
    instance, servers, start_ready = runtime
    start_ready.clear()
    instance.start_async()
    wait_for(lambda: bool(servers))
    instance.stop()
    start_ready.set()
    wait_for(lambda: not instance.starting)
    assert instance.gateway.starts == 0
    assert instance.status()["listening"] is False
    assert not instance.thread.is_alive()


def test_disable_while_gateway_starting_cancels_late_tunnel(runtime):
    instance, servers, _ = runtime
    instance.gateway.start_gate.clear()
    instance.start_async()
    assert instance.gateway.entered.wait(2)
    instance.stop()
    wait_for(lambda: not instance.starting)
    assert instance.gateway.starts == 0
    assert instance.gateway.status()["url"] == ""
    assert instance.status()["listening"] is False


def test_enable_requested_during_disable_waits_then_starts_new_generation(runtime):
    instance, servers, _ = runtime
    instance.start_async()
    wait_for(lambda: not instance.starting)
    instance.gateway.stop_entered.clear()
    instance.gateway.stop_gate.clear()
    stopper = threading.Thread(target=instance.stop)
    stopper.start()
    assert instance.gateway.stop_entered.wait(2)
    instance.start_async()
    instance.gateway.stop_gate.set()
    stopper.join(timeout=2)
    assert not stopper.is_alive()
    wait_for(lambda: not instance.starting)
    assert instance.status()["listening"] is True
    assert len(servers) == 2


def test_repeated_enable_during_start_does_not_spawn_duplicate_companions(runtime):
    instance, servers, start_ready = runtime
    start_ready.clear()
    instance.start_async()
    wait_for(lambda: bool(servers))
    for _ in range(10):
        instance.start_async()
    start_ready.set()
    wait_for(lambda: not instance.starting)
    assert len(servers) == 1
    assert instance.gateway.starts == 1
    assert "PRIVATE_PAIRING_SECRET" not in str(instance.status())


def test_companion_crash_between_readiness_check_and_tunnel_spawn_cancels_generation(runtime):
    instance, servers, _ = runtime
    start = instance.gateway.start
    attempted = threading.Event()

    def crash_then_start(allowed=None):
        servers[0].crash.set()
        instance.thread.join(timeout=1)
        assert not instance.thread.is_alive()
        try:
            return start(allowed=allowed)
        finally:
            attempted.set()

    instance.gateway.start = crash_then_start
    instance.start_async()
    assert attempted.wait(2)
    wait_for(lambda: not instance.starting)
    assert instance.gateway.starts == 0
    assert instance.gateway.status()["url"] == ""
    assert instance.status()["listening"] is False
