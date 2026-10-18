"""Pair devices without putting reusable device credentials on disk."""

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path


class RemoteAuth:
    session_max_age = 7 * 24 * 60 * 60

    def __init__(self, data_dir, vault_get=None, vault_set=None):
        self.path = Path(data_dir) / "remote-sessions.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        if vault_get is None or vault_set is None:
            if os.name == "nt":
                from keyring.backends.Windows import WinVaultKeyring

                vault = WinVaultKeyring()
            else:
                import keyring

                vault = keyring

            def vault_get():
                return vault.get_password("JobPilot.Remote", "pairing-key")

            def vault_set(value):
                vault.set_password("JobPilot.Remote", "pairing-key", value)

        self._secret = vault_get()
        if not self._secret:
            self._secret = secrets.token_urlsafe(32)
            vault_set(self._secret)
        try:
            self.sessions = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.sessions, dict):
                self.sessions = {}
        except (OSError, ValueError):
            self.sessions = {}

    def pairing_secret(self):
        return self._secret

    @staticmethod
    def _hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def _save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.sessions), encoding="utf-8")
        temporary.replace(self.path)

    def exchange(self, secret):
        if (
            not isinstance(secret, str)
            or not secret.isascii()
            or len(secret) > 200
            or not secrets.compare_digest(secret, self._secret)
        ):
            return None
        token = secrets.token_urlsafe(32)
        with self.lock:
            now = time.time()
            self.sessions = {
                key: value
                for key, value in self.sessions.items()
                if isinstance(value, (int, float)) and value > now
            }
            if len(self.sessions) >= 20:
                del self.sessions[min(self.sessions, key=self.sessions.get)]
            self.sessions[self._hash(token)] = now + self.session_max_age
            self._save()
        return token

    def valid(self, token):
        if not isinstance(token, str) or not token.isascii() or len(token) > 200 or not token:
            return False
        with self.lock:
            expiry = self.sessions.get(self._hash(token), 0)
            return isinstance(expiry, (int, float)) and expiry > time.time()

    def revoke(self, token):
        with self.lock:
            self.sessions.pop(self._hash(token or ""), None)
            self._save()

    def valid_hash(self, digest):
        with self.lock:
            expiry = self.sessions.get(digest, 0)
            return isinstance(expiry, (int, float)) and expiry > time.time()

    def revoke_all(self):
        with self.lock:
            self.sessions.clear()
            self._save()
