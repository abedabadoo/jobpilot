"""The SQLite context manager must release file handles, not just commit."""

import sqlite3

import jobpilot.store as store_module
from jobpilot.store import Store


def test_every_store_connection_closes_even_during_repeated_rescoring(tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    connections = []

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            self.closed_by_store = True
            super().close()

    def tracked_connect(*args, **kwargs):
        conn = real_connect(*args, factory=TrackedConnection, **kwargs)
        connections.append(conn)  # Keep references: GC cannot mask missing close calls.
        return conn

    monkeypatch.setattr(store_module.sqlite3, "connect", tracked_connect)
    store = Store(tmp_path / "jobpilot.sqlite")
    job = store.add_job(
        {
            "url": "https://example.com/jobs/one",
            "title": "Security Engineer",
            "company": "Example",
            "fit": 85,
        }
    )

    for score in range(120):
        store.update_job(job["id"], fit=score)
        assert store.get_job(job["id"])["fit"] == score

    assert len(connections) > 240
    assert all(getattr(conn, "closed_by_store", False) for conn in connections)
    assert store.get_job(job["id"])["fit"] == 119


def test_store_rolls_back_and_closes_on_error(tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    tracked = []

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            self.closed_by_store = True
            super().close()

    def tracked_connect(*args, **kwargs):
        conn = real_connect(*args, factory=TrackedConnection, **kwargs)
        tracked.append(conn)
        return conn

    monkeypatch.setattr(store_module.sqlite3, "connect", tracked_connect)
    store = Store(tmp_path / "jobpilot.sqlite")

    try:
        with store.connect() as conn:
            conn.execute("INSERT INTO settings(key,value) VALUES(?,?)", ("partial", '"value"'))
            raise RuntimeError("Synthetic failure before commit")
    except RuntimeError:
        pass

    assert store.get("partial") is None
    assert all(getattr(conn, "closed_by_store", False) for conn in tracked)
