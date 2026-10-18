"""The phone portal exposes only an authenticated, bounded browser controller."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SECRET = "p" * 43
ORIGIN = "http://127.0.0.1:8766"


class Auth:
    session_max_age = 604800

    def __init__(self):
        self.sessions = set()

    def exchange(self, secret):
        if secret != SECRET:
            return None
        self.sessions.add("device-token")
        return "device-token"

    def valid(self, token):
        return token in self.sessions

    def revoke(self, token):
        self.sessions.discard(token)


class Broker:
    def __init__(self):
        self.commands = []
        self.case = {
            "id": "case-1",
            "job_id": 24,
            "company": "Employer",
            "title": "Security Engineer",
            "kind": "verification",
            "note": "Finish verification",
            "state": "waiting",
            "submitted": True,
            "url": "https://jobs.example/apply?token=private#secret",
            "view_id": "view-1",
            "width": 1280,
            "height": 900,
            "internal_secret": "private",
        }

    def list_cases(self):
        return [self.case]

    def get_case(self, case_id):
        if case_id != self.case["id"]:
            raise KeyError(case_id)
        return self.case

    def frame(self, case_id):
        self.get_case(case_id)
        return {"png": b"\x89PNG\r\n\x1a\nimage", "view_id": "view-1", "width": 1280, "height": 900}

    def command(self, case_id, body):
        self.get_case(case_id)
        if body.get("view_id") != "view-1":
            raise ValueError("stale view")
        self.commands.append(body)
        return {"ok": True}


class Notifications:
    def __init__(self):
        self.calls = []

    def public_key(self):
        return "public-vapid-key"

    def subscribe(self, subscription, token):
        self.calls.append(("subscribe", subscription, token))
        return {"ok": True}

    def unsubscribe(self, token):
        self.calls.append(("unsubscribe", token))
        return {"ok": True}

    def test(self, token):
        self.calls.append(("test", token))
        return {"ok": True}


def test_remote_portal_exists():
    assert (Path(__file__).parents[1] / "jobpilot" / "remote.py").exists(), (
        "The remote portal has not been implemented"
    )


@pytest.fixture
def portal():
    source = Path(__file__).parents[1] / "jobpilot" / "remote.py"
    assert source.exists(), "The remote portal has not been implemented"
    from jobpilot.remote import create_remote_app

    broker, auth, push = Broker(), Auth(), Notifications()
    with TestClient(create_remote_app(broker, auth, push), base_url=ORIGIN) as client:
        yield client, broker, auth, push


def pair(client):
    return client.post("/api/pair", json={"secret": SECRET}, headers={"Origin": ORIGIN})


def test_pair_exchanges_fragment_secret_for_httponly_cookie(portal):
    client, _, _, _ = portal
    response = pair(client)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert SECRET not in response.text


@pytest.mark.parametrize(
    "path", ["/api/cases", "/api/cases/case-1", "/api/cases/case-1/frame", "/api/push/key"]
)
def test_unauthenticated_reads_are_denied(portal, path):
    assert portal[0].get(path).status_code == 401


def test_unauthenticated_control_is_denied(portal):
    response = portal[0].post(
        "/api/cases/case-1/input",
        json={"kind": "resume", "view_id": "view-1"},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 401


def test_metadata_uses_an_allowlist_and_removes_url_secrets(portal):
    client, _, _, _ = portal
    pair(client)
    cases = client.get("/api/cases").json()["cases"]
    assert cases[0]["url"] == "https://jobs.example/apply"
    assert "private" not in str(cases)
    assert client.get("/api/cases/case-1").json()["id"] == "case-1"


def test_frame_requires_session_and_has_view_dimensions(portal):
    client, _, _, _ = portal
    pair(client)
    response = client.get("/api/cases/case-1/frame")
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-view-id"] == "view-1"
    assert response.headers["x-browser-width"] == "1280"
    assert "no-store" in response.headers["cache-control"]


def test_input_is_forwarded_with_observed_view_and_stale_view_is_rejected(portal):
    client, broker, _, _ = portal
    pair(client)
    command = {"kind": "click", "view_id": "view-1", "x": 120, "y": 44}
    assert (
        client.post("/api/cases/case-1/input", json=command, headers={"Origin": ORIGIN}).status_code
        == 200
    )
    assert broker.commands == [command]
    command["view_id"] = "old-view"
    assert (
        client.post("/api/cases/case-1/input", json=command, headers={"Origin": ORIGIN}).status_code
        == 409
    )


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "navigate", "url": "https://attacker.example", "view_id": "view-1"},
        {"kind": "key", "key": "Control+L", "view_id": "view-1"},
        {"kind": "text", "text": "x" * 4097, "view_id": "view-1"},
        {"kind": "click", "x": -1, "y": 0, "view_id": "view-1"},
        {"kind": "resume", "view_id": "view-1", "javascript": "alert(1)"},
        {"kind": "resume"},
        {"kind": [], "view_id": "view-1"},
        {"kind": "key", "key": [], "view_id": "view-1"},
        {"kind": "key", "key": {}, "view_id": "view-1"},
        {"kind": "code", "code": "a" * 33, "view_id": "view-1"},
        {"kind": "scroll", "delta_y": 2001, "view_id": "view-1"},
    ],
)
def test_unbounded_or_extra_commands_never_reach_broker(portal, body):
    client, broker, _, _ = portal
    pair(client)
    assert (
        client.post("/api/cases/case-1/input", json=body, headers={"Origin": ORIGIN}).status_code
        == 422
    )
    assert broker.commands == []


@pytest.mark.parametrize("origin", [None, "https://attacker.example", "null"])
def test_all_writes_require_exact_same_origin(portal, origin):
    client, _, _, _ = portal
    headers = {} if origin is None else {"Origin": origin}
    assert client.post("/api/pair", json={"secret": SECRET}, headers=headers).status_code == 403


def test_logout_revokes_the_device_session(portal):
    client, _, auth, _ = portal
    pair(client)
    assert client.post("/api/logout", headers={"Origin": ORIGIN}).status_code == 200
    assert auth.sessions == set()
    assert client.get("/api/cases").status_code == 401


@pytest.mark.parametrize(
    "path", ["/api/session", "/api/state", "/api/artifact", "/docs", "/openapi.json"]
)
def test_main_service_and_developer_routes_do_not_exist(portal, path):
    assert portal[0].get(path).status_code == 404


def test_health_is_deliberately_minimal(portal):
    assert portal[0].get("/api/health").json() == {"ok": True}


def test_pairing_failures_are_rate_limited(portal):
    client, _, _, _ = portal
    for _ in range(5):
        assert (
            client.post(
                "/api/pair", json={"secret": "wrong" * 9}, headers={"Origin": ORIGIN}
            ).status_code
            == 401
        )
    assert (
        client.post("/api/pair", json={"secret": SECRET}, headers={"Origin": ORIGIN}).status_code
        == 429
    )


def test_control_is_rate_limited_per_session(portal):
    client, _, _, _ = portal
    pair(client)
    statuses = [
        client.post(
            "/api/cases/case-1/input",
            json={"kind": "key", "key": "Tab", "view_id": "view-1"},
            headers={"Origin": ORIGIN},
        ).status_code
        for _ in range(45)
    ]
    assert 429 in statuses


def test_push_adapters_require_authenticated_session(portal):
    client, _, _, push = portal
    pair(client)
    assert client.get("/api/push/key").json() == {"public_key": "public-vapid-key"}
    subscription = {
        "endpoint": "https://push.example/token",
        "keys": {"p256dh": "key", "auth": "key"},
    }
    assert (
        client.post(
            "/api/push/subscribe", json=subscription, headers={"Origin": ORIGIN}
        ).status_code
        == 200
    )
    assert push.calls[-1] == ("subscribe", subscription, "device-token")
    assert client.post("/api/push/test", headers={"Origin": ORIGIN}).status_code == 200
    assert client.post("/api/push/unsubscribe", headers={"Origin": ORIGIN}).status_code == 200


def test_public_shell_has_csp_and_local_assets(portal):
    client, _, _, _ = portal
    response = client.get("/")
    assert response.status_code == 200
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "http://" not in response.text and "https://" not in response.text
    script = client.get("/app.js").text
    assert "localStorage" not in script and "sessionStorage" not in script
    assert "replaceState" in script
    assert client.get("/sw.js").status_code == 200
    assert client.get("/manifest.webmanifest").json()["display"] == "standalone"


def test_https_is_required_outside_loopback_and_https_cookie_is_secure(portal):
    from jobpilot.remote import create_remote_app

    _, broker, auth, push = portal
    with TestClient(
        create_remote_app(broker, auth, push), base_url="http://phone.example"
    ) as client:
        assert client.get("/").status_code == 400
    with TestClient(
        create_remote_app(broker, auth, push), base_url="https://phone.example"
    ) as client:
        response = client.post(
            "/api/pair", json={"secret": SECRET}, headers={"Origin": "https://phone.example"}
        )
        assert response.status_code == 200
        assert "secure" in response.headers["set-cookie"].lower()


def test_missing_notification_adapter_reports_unavailable(portal):
    from jobpilot.remote import create_remote_app

    _, broker, auth, _ = portal
    with TestClient(create_remote_app(broker, auth), base_url=ORIGIN) as client:
        pair(client)
        for path in ("/api/push/test", "/api/push/unsubscribe"):
            assert client.post(path, headers={"Origin": ORIGIN}).status_code == 503


def test_unknown_case_is_not_found_after_authentication(portal):
    client, _, _, _ = portal
    pair(client)
    assert client.get("/api/cases/missing").status_code == 404
    assert client.get("/api/cases/missing/frame").status_code == 404
    assert (
        client.post(
            "/api/cases/missing/input",
            json={"kind": "resume", "view_id": "view-1"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "path", ["/api/push/subscribe", "/api/push/test", "/api/push/unsubscribe", "/api/logout"]
)
def test_unauthenticated_writes_are_denied(portal, path):
    assert portal[0].post(path, json={}, headers={"Origin": ORIGIN}).status_code == 401


def _streamed_request(app, chunks, content_length=None):
    """Use ASGI events directly: TestClient's transport buffers generators itself."""
    consumed, messages = [], []
    headers = [
        (b"host", b"127.0.0.1:8766"),
        (b"origin", ORIGIN.encode()),
        (b"content-type", b"application/json"),
    ]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/pair",
        "raw_path": b"/api/pair",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8766),
    }

    async def receive():
        index = len(consumed)
        if index >= len(chunks):
            return {"type": "http.disconnect"}
        consumed.append(index)
        return {"type": "http.request", "body": chunks[index], "more_body": index < len(chunks) - 1}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    return next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    ), consumed


def test_declared_oversize_body_is_rejected_without_reading_or_calling_adapter(portal):
    from jobpilot.remote import create_remote_app

    _, broker, auth, _ = portal
    calls = []
    auth.exchange = lambda secret: calls.append(secret)
    status, consumed = _streamed_request(
        create_remote_app(broker, auth), [b"x" * 32769], content_length=32769
    )
    assert status == 413
    assert consumed == [], "An oversized Content-Length should be rejected before reading the body"
    assert calls == []


def test_chunked_body_stops_at_limit_without_buffering_the_remainder(portal):
    from jobpilot.remote import create_remote_app

    _, broker, auth, _ = portal
    calls = []
    auth.exchange = lambda secret: calls.append(secret)
    status, consumed = _streamed_request(
        create_remote_app(broker, auth), [b"x" * 16384, b"x" * 16385, b"unread-remainder"]
    )
    assert status == 413
    assert consumed == [0, 1], "The stream must stop as soon as its bounded body limit is exceeded"
    assert calls == []


def test_valid_chunked_body_remains_available_to_pair_handler(portal):
    import json

    from jobpilot.remote import create_remote_app

    _, broker, auth, _ = portal
    payload = json.dumps({"secret": SECRET}).encode()
    status, consumed = _streamed_request(
        create_remote_app(broker, auth), [payload[:20], payload[20:]]
    )
    assert status == 200 and consumed == [0, 1]
