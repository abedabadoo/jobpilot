from test_api import api


def test_remote_setup_requires_local_token_and_keeps_secret_out_of_state(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    import jobpilot.service as service

    service.store.set("settings", {**service.settings(), "application_mode": "legacy"})
    assert client.post("/api/remote/setup", json={}).status_code == 403
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    monkeypatch.setattr(
        service.remote_runtime,
        "pairing_link",
        lambda: "https://fixture.trycloudflare.com/#pair=PRIVATE-PAIRING",
    )
    result = client.post("/api/remote/setup", headers=headers, json={})
    assert result.status_code == 200
    assert result.json()["pairing_link"].endswith("PRIVATE-PAIRING")
    assert result.json()["qr"].startswith("data:image/png;base64,")
    assert "PRIVATE-PAIRING" not in client.get("/api/state").text
    assert "Remote" in client.get("/remote-setup.html").text


def test_remote_control_is_explicit_and_does_not_stop_active_case(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    import jobpilot.service as service

    service.store.set("settings", {**service.settings(), "application_mode": "legacy"})
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    calls = []
    monkeypatch.setattr(service.remote_runtime, "start_async", lambda: calls.append("start"))
    monkeypatch.setattr(service.remote_runtime, "stop", lambda: calls.append("stop"))
    assert (
        client.post("/api/remote/control", headers=headers, json={"action": "enable"}).status_code
        == 200
    )
    assert calls == ["start"]
    assert service.settings()["remote_intervention_enabled"]
    service.remote_runtime.broker.cases["held"] = {"id": "held", "state": "waiting"}
    assert (
        client.post("/api/remote/control", headers=headers, json={"action": "disable"}).status_code
        == 409
    )
    assert calls == ["start"]
    service.remote_runtime.broker.cases.clear()
    assert (
        client.post("/api/remote/control", headers=headers, json={"action": "disable"}).status_code
        == 200
    )
    assert calls == ["start", "stop"]
