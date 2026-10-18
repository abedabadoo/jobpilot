"""Optional encrypted Web Push for paired devices, with generic payloads only.

Call notify on a background thread: network delivery never belongs on the
Playwright owner thread. Session tokens and VAPID private keys stay out of JSON.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import socket
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

_SERVICE = "JobPilot/RemotePush"
_MAX_SUBSCRIPTIONS = 32
_MAX_FILE_BYTES = 256 * 1024
_MAX_SEEN_CASES = 1024
_PAYLOAD = {
    "title": "JobPilot needs your attention",
    "body": "An application needs your help. Open JobPilot Remote to continue.",
    "url": "/",
    "tag": "jobpilot-intervention",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value, length):
    if (
        not isinstance(value, str)
        or len(value) > 128
        or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value)
    ):
        raise ValueError("Invalid push subscription key")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise ValueError("Invalid push subscription key") from None
    if len(raw) != length:
        raise ValueError("Invalid push subscription key")
    return raw


def _endpoint(value, *, resolve=True):
    if (
        not isinstance(value, str)
        or not 10 <= len(value) <= 2048
        or any(ord(char) < 33 or ord(char) > 126 for char in value)
        or "\\" in value
    ):
        raise ValueError("Invalid push service endpoint")
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        allowed = host in ("fcm.googleapis.com", "web.push.apple.com") or (
            host.endswith(".push.services.mozilla.com") and bool(re.fullmatch(r"[a-z0-9.-]+", host))
        )
        if (
            parts.scheme != "https"
            or not allowed
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
            or parts.fragment
            or not parts.path
            or parts.path == "/"
        ):
            raise ValueError
    except ValueError:
        raise ValueError("Use an HTTPS endpoint from a supported browser push service") from None
    if resolve:
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses or any(
                not ipaddress.ip_address(item[4][0]).is_global for item in addresses
            ):
                raise ValueError
        except (OSError, ValueError):
            raise ValueError("Push service must resolve to public internet addresses") from None
    return value


def _subscription(value, *, resolve=True):
    if not isinstance(value, dict):
        raise ValueError("Invalid push subscription")
    try:
        if len(json.dumps(value, ensure_ascii=True, allow_nan=False)) > 8192:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Invalid or oversized push subscription") from None
    endpoint = _endpoint(value.get("endpoint"), resolve=resolve)
    keys = value.get("keys")
    if not isinstance(keys, dict):
        raise ValueError("Invalid push subscription keys")
    public, auth = _decode(keys.get("p256dh"), 65), _decode(keys.get("auth"), 16)
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:
        raise RuntimeError("Web Push cryptography dependency is unavailable") from None
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
    except ValueError:
        raise ValueError("Invalid push subscription public key") from None
    return {"endpoint": endpoint, "keys": {"p256dh": _encode(public), "auth": _encode(auth)}}


def _session_hash(token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{32,512}", token):
        raise ValueError("Invalid paired-device session")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _push_session():
    import requests

    class PushSession(requests.Session):
        def request(self, method, url, **kwargs):
            if method.upper() != "POST":
                raise ValueError("Only push delivery is supported")
            _endpoint(url)
            kwargs["allow_redirects"] = False
            kwargs.setdefault("timeout", 10)
            return super().request(method, url, **kwargs)

    session = PushSession()
    session.trust_env = False
    return session


def _webpush(**kwargs):
    try:
        from pywebpush import webpush
    except ImportError:
        raise RuntimeError("Web Push dependency is unavailable") from None
    return webpush(**kwargs)


class RemoteNotifications:
    def __init__(
        self,
        data_dir,
        *,
        vault=None,
        sender=None,
        vapid_subject="mailto:jobpilot@localhost.localdomain",
        session_active=None,
    ):
        self._directory = Path(data_dir) / "remote"
        self._path = self._directory / "push-subscriptions.json"
        self._vault = vault
        self._vault_key = (
            "vapid-" + hashlib.sha256(str(Path(data_dir).resolve()).encode()).hexdigest()
        )
        self._sender = sender or _webpush
        self._session_active = session_active
        if (
            not isinstance(vapid_subject, str)
            or len(vapid_subject) > 254
            or any(ord(char) < 33 or ord(char) > 126 for char in vapid_subject)
            or not vapid_subject.startswith(("mailto:", "https://"))
        ):
            raise ValueError("Invalid VAPID contact")
        self._subject = vapid_subject
        self._lock = threading.RLock()
        self._private = self._public = None
        self._subscriptions = {}
        self._seen = []
        self._last_error = self._last_delivery = None
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            if self._path.stat().st_size > _MAX_FILE_BYTES:
                raise ValueError
            saved = json.loads(self._path.read_text(encoding="utf-8"))
            records = saved.get("subscriptions", {})
            if not isinstance(records, dict) or len(records) > _MAX_SUBSCRIPTIONS:
                raise ValueError
            for digest, value in records.items():
                if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                    continue
                try:
                    self._subscriptions[digest] = _subscription(value, resolve=False)
                except (ValueError, RuntimeError):
                    self._last_error = "A saved notification subscription is invalid"
            seen = saved.get("notified_cases", [])
            if isinstance(seen, list):
                self._seen = [
                    item
                    for item in seen[-_MAX_SEEN_CASES:]
                    if isinstance(item, str) and re.fullmatch(r"[a-f0-9]{64}", item)
                ]
        except (OSError, ValueError, TypeError, AttributeError):
            self._last_error = "Notification storage is unavailable or invalid"

    def _save(self):
        temporary = self._directory / (".push-" + uuid.uuid4().hex + ".tmp")
        try:
            self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            data = json.dumps(
                {"version": 1, "subscriptions": self._subscriptions, "notified_cases": self._seen},
                separators=(",", ":"),
            )
            if len(data.encode("utf-8")) > _MAX_FILE_BYTES:
                raise ValueError
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self._path)
        except (OSError, ValueError):
            self._last_error = "Notification storage is unavailable"
            raise RuntimeError(self._last_error) from None
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _key_material(self):
        with self._lock:
            if self._private is not None:
                return self._private, self._public
            try:
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.asymmetric import ec
            except ImportError:
                raise RuntimeError("Web Push cryptography dependency is unavailable") from None
            try:
                if self._vault is None:
                    if os.name != "nt":
                        raise RuntimeError
                    from keyring.backends.Windows import WinVaultKeyring

                    self._vault = WinVaultKeyring()
                stored = (
                    self._vault.get(self._vault_key)
                    if isinstance(self._vault, dict)
                    else self._vault.get_password(_SERVICE, self._vault_key)
                )
                if stored:
                    if not isinstance(stored, str) or len(stored) > 1024:
                        raise ValueError
                    key = serialization.load_der_private_key(
                        base64.urlsafe_b64decode(stored + "=" * (-len(stored) % 4)), password=None
                    )
                    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
                        key.curve, ec.SECP256R1
                    ):
                        raise ValueError
                else:
                    key = ec.generate_private_key(ec.SECP256R1())
                    stored = _encode(
                        key.private_bytes(
                            serialization.Encoding.DER,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption(),
                        )
                    )
                    if isinstance(self._vault, dict):
                        self._vault[self._vault_key] = stored
                    else:
                        self._vault.set_password(_SERVICE, self._vault_key, stored)
                self._public = _encode(
                    key.public_key().public_bytes(
                        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
                    )
                )
                self._private = stored
            except Exception:
                raise RuntimeError(
                    "Windows credential storage for Web Push is unavailable"
                ) from None
            return self._private, self._public

    def public_key(self):
        return self._key_material()[1]

    def subscribe(self, subscription, session_token):
        digest, clean = _session_hash(session_token), _subscription(subscription)
        self.public_key()
        with self._lock:
            if digest not in self._subscriptions and len(self._subscriptions) >= _MAX_SUBSCRIPTIONS:
                raise ValueError("Paired notification device limit reached")
            self._subscriptions = {
                key: value
                for key, value in self._subscriptions.items()
                if value["endpoint"] != clean["endpoint"]
            }
            self._subscriptions[digest] = clean
            self._save()
        return {"ok": True, "subscribed": True}

    def unsubscribe(self, session_token):
        with self._lock:
            self._subscriptions.pop(_session_hash(session_token), None)
            self._save()
        return {"ok": True, "subscribed": False}

    def _active(self, digest=None):
        with self._lock:
            result, changed = [], False
            for key, subscription in list(self._subscriptions.items()):
                if digest is not None and key != digest:
                    continue
                if self._session_active is not None:
                    try:
                        active = self._session_active(key)
                    except Exception:
                        self._last_error = "Paired device authorization is unavailable"
                        continue
                    if not active:
                        self._subscriptions.pop(key, None)
                        changed = True
                        continue
                result.append((key, dict(subscription)))
            if changed:
                self._save()
            return result

    def status(self):
        active = self._active()
        with self._lock:
            return {
                "subscribed_devices": len(active),
                "last_delivery": self._last_delivery,
                "last_error": self._last_error,
            }

    def _deliver(self, recipients):
        delivered = failed = 0
        for digest, subscription in recipients:
            prune = False
            try:
                clean = _subscription(subscription)
                private, _ = self._key_material()
                with _push_session() as session:
                    response = self._sender(
                        subscription_info=clean,
                        data=json.dumps(_PAYLOAD),
                        vapid_private_key=private,
                        vapid_claims={"sub": self._subject},
                        content_encoding="aes128gcm",
                        ttl=3600,
                        timeout=10,
                        verbose=False,
                        requests_session=session,
                    )
                status = getattr(response, "status_code", None)
                if not isinstance(status, int) or not 200 <= status <= 202:
                    error = RuntimeError()
                    error.status_code = status
                    raise error
                delivered += 1
                with self._lock:
                    self._last_error = None
            except Exception as error:
                failed += 1
                response = getattr(error, "response", None)
                status = getattr(error, "status_code", None)
                if status is None and response is not None:
                    status = getattr(response, "status_code", None)
                valid_status = isinstance(status, int) and 100 <= status <= 599
                prune = status in (404, 410) or isinstance(error, ValueError)
                with self._lock:
                    self._last_error = (
                        f"Push service rejected delivery (HTTP {status})"
                        if valid_status
                        else "Push notification delivery failed; check the paired device and connection"
                    )
            with self._lock:
                self._last_delivery = _now()
                # Never remove a new subscription that replaced this one in flight.
                if prune and self._subscriptions.get(digest) == subscription:
                    self._subscriptions.pop(digest, None)
                    self._save()
        return {
            "ok": failed == 0,
            "delivered": delivered,
            "failed": failed,
            "subscribed": bool(recipients),
        }

    def test(self, session_token):
        return self._deliver(self._active(_session_hash(session_token)))

    def notify(self, case):
        if (
            not isinstance(case, dict)
            or case.get("state") != "waiting"
            or not isinstance(case.get("id"), str)
            or not 1 <= len(case["id"]) <= 256
        ):
            return {"ok": True, "delivered": 0, "failed": 0, "skipped": True}
        digest = hashlib.sha256(case["id"].encode("utf-8")).hexdigest()
        with self._lock:
            if digest in self._seen:
                return {"ok": True, "delivered": 0, "failed": 0, "skipped": True}
            self._seen = (self._seen + [digest])[-_MAX_SEEN_CASES:]
            try:
                self._save()
            except RuntimeError:
                return {
                    "ok": False,
                    "delivered": 0,
                    "failed": 0,
                    "error": "Notification storage is unavailable",
                }
        return self._deliver(self._active())


PushNotifications = RemoteNotifications
