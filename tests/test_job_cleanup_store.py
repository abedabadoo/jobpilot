import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from jobpilot.store import Store

NOW = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(days=7)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, "now", staticmethod(lambda: NOW.isoformat()))
    return Store(tmp_path / "jobs.sqlite")


def add(store, suffix, posted_at=CUTOFF.isoformat(), **changes):
    return store.add_job(
        {
            "url": "https://example.com/jobs/" + suffix,
            "title": "Security Engineer",
            "company": "Example",
            "posted_at": posted_at,
            **changes,
        }
    )


def test_cleanup_cutoff_is_inclusive_and_compares_actual_instants(store):
    before = add(store, "before", (CUTOFF - timedelta(microseconds=1)).isoformat())
    exact = add(store, "exact", "2026-10-11T14:00:00-04:00")
    after = add(store, "after", (CUTOFF + timedelta(microseconds=1)).isoformat())
    preview = store.cleanup_preview(CUTOFF)
    assert {job["id"] for job in preview["jobs"]} == {before["id"], exact["id"]}
    assert all("bucket_label" in job for job in preview["jobs"])
    assert preview["protected_count"] == 0
    result = store.delete_old_jobs(CUTOFF, [before["id"], exact["id"], after["id"]])
    assert result["deleted_count"] == 2
    assert set(result["deleted_ids"]) == {before["id"], exact["id"]}
    assert result["skipped_count"] == 1
    assert store.get_job(after["id"]) is not None


def test_unknown_malformed_and_future_dates_are_kept_even_for_future_cutoff(store):
    kept = [
        add(store, "unknown", None),
        add(store, "empty", ""),
        add(store, "malformed", "not-a-date"),
        add(store, "object", {"invalid": True}),
        add(store, "future", (NOW + timedelta(days=1)).isoformat()),
    ]
    preview = store.cleanup_preview(NOW + timedelta(days=10))
    assert preview["jobs"] == []
    assert preview["unknown_date_count"] == 4
    result = store.delete_old_jobs(NOW + timedelta(days=10), [job["id"] for job in kept])
    assert result == {"deleted_count": 0, "deleted_ids": [], "skipped_count": 5}
    assert len(store.jobs()) == 5


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "preparing"},
        {"status": "applying"},
        {"status": "submitting"},
        {"browser_handoff": {"mode": "default_browser", "state": "opened"}},
        {"browser_handoff": {"mode": "default_browser", "state": "opening"}},
        {"browser_handoff": {"mode": "default_browser"}},
        {"review_session": {"state": "opening"}},
        {"review_session": {"state": "opened"}},
    ],
)
def test_cleanup_protects_in_progress_work(store, changes):
    job = add(store, "active", **changes)
    preview = store.cleanup_preview(CUTOFF)
    assert preview["jobs"] == []
    assert preview["protected_count"] == 1
    assert store.delete_old_jobs(CUTOFF, [job["id"]]) == {
        "deleted_count": 0,
        "deleted_ids": [],
        "skipped_count": 1,
    }
    assert store.get_job(job["id"]) is not None


def test_closed_handoffs_and_past_uncertainty_can_be_removed_without_deleting_files(
    store, tmp_path
):
    artifact = tmp_path / "receipt.txt"
    artifact.write_text("Keep application evidence", encoding="utf-8")
    job = add(
        store,
        "closed",
        status="needs_review",
        uncertain=True,
        browser_handoff={"mode": "default_browser", "state": "closed"},
        review_session={"state": "closed"},
        evidence=[str(artifact)],
    )
    assert [row["id"] for row in store.cleanup_preview(CUTOFF)["jobs"]] == [job["id"]]
    assert store.delete_old_jobs(CUTOFF, [job["id"]])["deleted_count"] == 1
    assert store.get_job(job["id"]) is None
    assert artifact.read_text(encoding="utf-8") == "Keep application evidence"
    with store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_commit_only_deletes_snapshot_ids_and_rechecks_changed_jobs(store):
    original = add(store, "original")
    changed_date = add(store, "changed-date")
    changed_status = add(store, "changed-status")
    snapshot = [job["id"] for job in store.cleanup_preview(CUTOFF)["jobs"]]
    arrival = add(store, "new-old-arrival")
    store.update_job(changed_date["id"], posted_at=NOW.isoformat())
    store.update_job(changed_status["id"], review_session={"state": "opened"})
    result = store.delete_old_jobs(CUTOFF, snapshot + [9999, original["id"]])
    assert result == {"deleted_count": 1, "deleted_ids": [original["id"]], "skipped_count": 3}
    assert {job["id"] for job in store.jobs()} == {
        changed_date["id"],
        changed_status["id"],
        arrival["id"],
    }


def test_removed_identity_persists_and_blocks_each_route_and_requisition(store):
    job = add(
        store,
        "removed?utm_source=search",
        source_url="https://source.example/job/123",
        apply_url="https://employer.example/apply/123",
        requisition_id="REQ-123",
        description="Private full description that must not remain in tombstones",
    )
    assert store.delete_old_jobs(CUTOFF, [job["id"]])["deleted_count"] == 1
    reopened = Store(store.path)
    for route in [
        job["url"],
        "https://example.com/jobs/removed",
        job["source_url"],
        job["apply_url"],
    ]:
        assert reopened.add_job({"url": route, "company": "Example"}) is None
    assert (
        reopened.add_job(
            {
                "url": "https://new.example/jobs/123",
                "company": "EXAMPLE",
                "requisition_id": "REQ-123",
            }
        )
        is None
    )
    assert reopened.add_job({"url": "https://new.example/jobs/123", "company": "Example"}) is None
    assert reopened.jobs() == []
    assert (
        reopened.add_job(
            {
                "url": "https://other.example/jobs/123",
                "company": "Other",
                "requisition_id": "REQ-123",
            }
        )
        is not None
    )
    with reopened.connect() as connection:
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'jobs'"
        ):
            rows = connection.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall()
            assert "Private full description" not in json.dumps(rows)


def test_job_ids_are_never_reused_after_all_jobs_are_deleted_and_store_reopens(store):
    first = add(store, "first")
    second = add(store, "second")
    assert store.delete_old_jobs(CUTOFF, [first["id"], second["id"]])["deleted_count"] == 2
    reopened = Store(store.path)
    third = add(reopened, "third")
    assert third["id"] > second["id"]
    assert reopened.delete_old_jobs(CUTOFF, [second["id"]])["deleted_count"] == 0
    assert reopened.get_job(third["id"]) is not None
    reopened.delete_old_jobs(CUTOFF, [third["id"]])
    assert add(Store(store.path), "fourth")["id"] > third["id"]


def test_existing_database_ids_initialize_the_persistent_high_watermark(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, "now", staticmethod(lambda: NOW.isoformat()))
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE jobs (id INTEGER PRIMARY KEY, canonical TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO jobs VALUES(?,?,?)",
            (
                77,
                "https://example.com/legacy",
                json.dumps(
                    {
                        "url": "https://example.com/legacy",
                        "posted_at": CUTOFF.isoformat(),
                        "status": "queued",
                    }
                ),
            ),
        )
    legacy = Store(path)
    assert legacy.delete_old_jobs(CUTOFF, [77])["deleted_count"] == 1
    assert add(Store(path), "next")["id"] > 77


@pytest.mark.parametrize("cutoff", [datetime(2026, 10, 11), "2026-10-11"])
def test_cleanup_requires_an_aware_datetime_cutoff(store, cutoff):
    job = add(store, "keep")
    with pytest.raises(ValueError, match="timezone-aware"):
        store.cleanup_preview(cutoff)
    with pytest.raises(ValueError, match="timezone-aware"):
        store.delete_old_jobs(cutoff, [job["id"]])
    assert store.get_job(job["id"]) is not None
