"""Web Push stays generic and never becomes an authenticated SSRF proxy."""

import base64
import hashlib
import importlib
import importlib.util
import json
import socket
import threading
from types import SimpleNamespace

import pytest

# The P-256 generator is a valid uncompressed public key, not a private key.
PUBLIC_POINT = bytes.fromhex(
    "046b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296"
    "4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5"
)


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def subscription(endpoint="https://fcm.googleapis.com/fcm/send/private-device-token"):
    return {
        "endpoint": endpoint,
        "expirationTime": None,
        "keys": {"p256dh": b64(PUBLIC_POINT), "auth": b64(b"0123456789abcdef")},
    }


@pytest.fixture
def notifications_module(monkeypatch):
    module = pytest.importorskip("jobpilot.remote_notifications")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    return module


def test_notification_adapter_exists():
    assert importlib.util.find_spec("jobpilot.remote_notifications") is not None, (
        "The Web Push notification adapter has not been implemented"
    )


@pytest.fixture
def configured(tmp_path, notifications_module):
    calls, vault = [], {}

    def send(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=201)

    adapter = notifications_module.RemoteNotifications(tmp_path, vault=vault, sender=send)
    return adapter, calls, vault


def test_public_key_is_valid_stable_and_private_material_is_vault_only(
    tmp_path, notifications_module
):
    vault = {}
    first = notifications_module.RemoteNotifications(tmp_path, vault=vault)
    public = first.public_key()
    assert len(base64.urlsafe_b64decode(public + "==")) == 65
    assert base64.urlsafe_b64decode(public + "==")[0] == 4
    second = notifications_module.RemoteNotifications(tmp_path, vault=vault)
    assert second.public_key() == public
    assert len(vault) == 1
    private = next(iter(vault.values()))
    assert private != public
    assert all(private not in path.read_text() for path in tmp_path.rglob("*.json"))


def test_subscription_persists_by_session_hash_and_never_returns_endpoint(
    configured, tmp_path, notifications_module
):
    adapter, calls, vault = configured
    token = "paired-device-secret-" + "x" * 40
    response = adapter.subscribe(subscription(), token)
    assert response["subscribed"] is True
    assert "private-device-token" not in json.dumps(response)
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1
    text = files[0].read_text()
    assert token not in text
    assert hashlib.sha256(token.encode()).hexdigest() in text
    restarted = notifications_module.RemoteNotifications(
        tmp_path, vault=vault, sender=lambda **kw: SimpleNamespace(status_code=201)
    )
    assert restarted.status()["subscribed_devices"] == 1
    assert restarted.test(token)["delivered"] == 1
    assert restarted.unsubscribe(token)["subscribed"] is False
    assert restarted.test(token)["delivered"] == 0
    assert calls == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/token",
        "https://updates.push.services.mozilla.com/wpush/v2/token",
        "https://web.push.apple.com/Q-device-token",
    ],
)
def test_real_push_service_endpoints_are_accepted(configured, endpoint):
    adapter, _, _ = configured
    assert adapter.subscribe(subscription(endpoint), "x" * 43)["subscribed"] is True


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/token",
        "https://fcm.googleapis.com.evil.example/fcm/send/token",
        "https://evilpush.services.mozilla.com/wpush/token",
        "https://push.services.mozilla.com/wpush/token",
        "https://fcm.googleapis.com@127.0.0.1/token",
        "https://user:password@fcm.googleapis.com/fcm/send/token",
        "https://127.0.0.1/token",
        "https://[::1]/token",
        "https://fcm.googleapis.com:444/token",
        "https://fcm.googleapis.com/token#secret",
        "https://fcm.googleapis.com/token\r\nX-Header: bad",
        "https://fcm.googleapis.com\\@localhost/token",
    ],
)
def test_untrusted_endpoint_never_persists_or_sends(configured, endpoint):
    adapter, calls, _ = configured
    with pytest.raises(ValueError):
        adapter.subscribe(subscription(endpoint), "x" * 43)
    assert adapter.status()["subscribed_devices"] == 0
    assert calls == []


def test_private_dns_answer_is_rejected_even_for_allowlisted_hostname(configured, monkeypatch):
    adapter, calls, _ = configured
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError):
        adapter.subscribe(subscription(), "x" * 43)
    assert calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"keys": {}},
        {"keys": {"auth": b64(b"too short"), "p256dh": b64(PUBLIC_POINT)}},
        {"keys": {"auth": b64(b"x" * 16), "p256dh": b64(b"\x04" + b"\0" * 64)}},
        {"keys": {"auth": "not*base64", "p256dh": b64(PUBLIC_POINT)}},
        {"endpoint": "https://fcm.googleapis.com/" + "a" * 4097},
        {"untrustedExtra": "a" * 10000},
    ],
)
def test_bounded_subscription_keys_must_be_cryptographically_valid(configured, changes):
    adapter, _, _ = configured
    with pytest.raises(ValueError):
        adapter.subscribe({**subscription(), **changes}, "x" * 43)


def test_one_subscription_per_session_replaces_old_and_endpoint_deduplicates(configured):
    adapter, calls, _ = configured
    adapter.subscribe(subscription(), "first-" + "x" * 40)
    adapter.subscribe(subscription(), "second-" + "x" * 40)
    assert adapter.test("first-" + "x" * 40)["delivered"] == 0
    assert adapter.test("second-" + "x" * 40)["delivered"] == 1
    assert adapter.status()["subscribed_devices"] == 1
    assert len(calls) == 1


def test_notify_is_generic_and_once_for_a_new_waiting_case(
    configured, tmp_path, notifications_module
):
    adapter, calls, vault = configured
    adapter.subscribe(subscription(), "x" * 43)
    case = {
        "id": "case-01",
        "state": "waiting",
        "title": "SECRET_JOB_TITLE",
        "note": "password SECRET_PASSWORD code SECRET_CODE",
        "url": "https://employer.example/private?token=SECRET_TOKEN",
        "screenshot": "SECRET_PNG",
    }
    assert adapter.notify(case)["delivered"] == 1
    assert adapter.notify({**case, "updated_at": "later"})["delivered"] == 0
    assert adapter.notify({**case, "id": "closed-case", "state": "closed"})["delivered"] == 0
    payload = json.loads(calls[0]["data"])
    assert payload["title"] == "JobPilot needs your attention"
    assert payload["url"] == "/"
    assert "SECRET_" not in json.dumps(payload)
    assert "case-01" not in json.dumps(payload)
    assert calls[0]["content_encoding"] == "aes128gcm"
    assert calls[0]["ttl"] == 3600
    assert calls[0]["timeout"] <= 15
    assert calls[0]["verbose"] is False
    restarted = notifications_module.RemoteNotifications(
        tmp_path,
        vault=vault,
        sender=lambda **kwargs: pytest.fail("Duplicate notification after restart"),
    )
    assert restarted.notify(case)["delivered"] == 0
    assert all("SECRET_" not in path.read_text() for path in tmp_path.rglob("*.json"))


def test_concurrent_repeated_case_only_delivers_once(configured):
    adapter, calls, _ = configured
    adapter.subscribe(subscription(), "x" * 43)
    threads = [
        threading.Thread(target=adapter.notify, args=({"id": "one-case", "state": "waiting"},))
        for _ in range(10)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert len(calls) == 1


@pytest.mark.parametrize("status,remaining", [(410, 0), (404, 0), (429, 1), (503, 1), (302, 1)])
def test_delivery_failure_is_redacted_and_gone_subscription_is_pruned(
    tmp_path, notifications_module, caplog, status, remaining
):
    class Failure(Exception):
        status_code = status

    def fail(**kwargs):
        raise Failure("SECRET_PROVIDER_BODY https://fcm.googleapis.com/private SECRET_KEYS")

    adapter = notifications_module.RemoteNotifications(tmp_path, vault={}, sender=fail)
    adapter.subscribe(subscription(), "x" * 43)
    result = adapter.test("x" * 43)
    assert result["delivered"] == 0
    assert result["failed"] == 1
    assert adapter.status()["subscribed_devices"] == remaining
    assert f"HTTP {status}" in adapter.status()["last_error"]
    assert "SECRET_" not in json.dumps(result) + json.dumps(adapter.status()) + caplog.text
    assert all("SECRET_" not in path.read_text() for path in tmp_path.rglob("*.json"))


def test_sender_session_disables_redirects_proxies_and_rechecks_destination(
    configured, monkeypatch
):
    adapter, calls, _ = configured
    adapter.subscribe(subscription(), "x" * 43)
    adapter.test("x" * 43)
    session = calls[0]["requests_session"]
    assert session.trust_env is False
    import requests

    sends = []
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda self, method, url, **kwargs: (
            sends.append((method, url, kwargs)) or SimpleNamespace(status_code=201)
        ),
    )
    session.post(subscription()["endpoint"], allow_redirects=True)
    assert sends[0][2]["allow_redirects"] is False
    with pytest.raises(ValueError):
        session.post("http://127.0.0.1/private")
    assert len(sends) == 1


def test_invalid_saved_destination_is_never_sent(tmp_path, configured, notifications_module):
    adapter, calls, vault = configured
    adapter.subscribe(subscription(), "x" * 43)
    path = next(tmp_path.rglob("*.json"))
    payload = json.loads(path.read_text())
    saved = next(iter(payload["subscriptions"].values()))
    saved["endpoint"] = "http://127.0.0.1/private"
    path.write_text(json.dumps(payload))
    restarted = notifications_module.RemoteNotifications(
        tmp_path, vault=vault, sender=lambda **kwargs: pytest.fail("Corrupt endpoint was sent")
    )
    assert restarted.test("x" * 43)["delivered"] == 0


def test_vault_failure_never_creates_a_plaintext_private_key(tmp_path, notifications_module):
    class BrokenVault:
        def get_password(self, *args):
            raise RuntimeError("SECRET_VAULT_DIAGNOSTIC")

        def set_password(self, *args):
            pytest.fail("A failed read must not rotate the signing key")

    adapter = notifications_module.RemoteNotifications(tmp_path, vault=BrokenVault())
    with pytest.raises(RuntimeError, match="credential storage") as captured:
        adapter.public_key()
    assert "SECRET_" not in str(captured.value)
    assert not list(tmp_path.rglob("*.pem"))


def test_expired_or_revoked_device_is_pruned_before_any_delivery(tmp_path, notifications_module):
    active = set()
    calls = []
    adapter = notifications_module.RemoteNotifications(
        tmp_path,
        vault={},
        sender=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(status_code=201),
        session_active=lambda digest: digest in active,
    )
    token = "x" * 43
    adapter.subscribe(subscription(), token)
    active.add(hashlib.sha256(token.encode()).hexdigest())
    assert adapter.test(token)["delivered"] == 1
    active.clear()
    assert adapter.notify({"id": "new-waiting-case", "state": "waiting"})["delivered"] == 0
    assert adapter.status()["subscribed_devices"] == 0
    assert len(calls) == 1


def test_actual_pywebpush_vapid_and_encryption_are_compatible(
    tmp_path, notifications_module, monkeypatch
):
    """Run real signing/encryption, intercept only the final outbound HTTP call."""
    pytest.importorskip("pywebpush")
    import http_ece
    import requests
    from cryptography.hazmat.primitives.asymmetric import ec

    requests_sent = []

    def intercept(self, method, url, **kwargs):
        requests_sent.append((method, url, kwargs))
        return SimpleNamespace(status_code=201, text="", headers={})

    monkeypatch.setattr(requests.Session, "request", intercept)
    adapter = notifications_module.RemoteNotifications(tmp_path, vault={})
    adapter.subscribe(subscription(), "x" * 43)
    assert adapter.test("x" * 43)["delivered"] == 1
    method, url, sent = requests_sent[0]
    assert method.upper() == "POST"
    assert url == subscription()["endpoint"]
    assert sent["allow_redirects"] is False
    assert sent["timeout"] == 10
    decrypted = http_ece.decrypt(
        sent["data"],
        private_key=ec.derive_private_key(1, ec.SECP256R1()),
        auth_secret=b"0123456789abcdef",
        version="aes128gcm",
    )
    assert json.loads(decrypted)["title"] == "JobPilot needs your attention"
    authorization = sent["headers"].get("Authorization") or sent["headers"].get("authorization")
    assert authorization.startswith("vapid t=")
    assert adapter.public_key() in authorization
