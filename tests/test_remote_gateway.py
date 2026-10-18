import io


def test_gateway_only_tunnels_companion_and_reaps_process(tmp_path):
    from jobpilot.remote_gateway import RemoteGateway

    executable = tmp_path / "cloudflared.exe"
    executable.write_bytes(b"fixture")
    calls = []

    class Process:
        stdout = io.StringIO("registered https://fixture-test.trycloudflare.com\n")
        code = None

        def poll(self):
            return self.code

        def terminate(self):
            self.code = 0

        def wait(self, timeout=None):
            return self.code

    process = Process()

    def launch(args, **kwargs):
        calls.append(args)
        return process

    gateway = RemoteGateway(tmp_path, executable=executable, popen=launch)
    assert gateway.start() == "https://fixture-test.trycloudflare.com"
    assert "http://127.0.0.1:8766" in calls[0]
    assert "8765" not in " ".join(calls[0])
    assert gateway.status()["url"] == "https://fixture-test.trycloudflare.com"
    gateway.stop()
    assert process.code == 0
    assert gateway.status()["state"] == "stopped"


def test_cancelled_start_never_spawns_a_tunnel(tmp_path):
    from jobpilot.remote_gateway import RemoteGateway

    calls = []
    gateway = RemoteGateway(tmp_path, popen=lambda *args, **kwargs: calls.append(args))
    assert gateway.start(allowed=lambda: False) == ""
    assert calls == []
