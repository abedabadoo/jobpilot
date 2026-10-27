import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .core import BUCKET_LABELS, TZ, canonical_url, freshness, parse_date, rank_key


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as c:
            c.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, canonical TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS removed_job_identities (
                    kind TEXT NOT NULL, identity TEXT NOT NULL, job_id INTEGER NOT NULL,
                    PRIMARY KEY(kind, identity));
                CREATE TABLE IF NOT EXISTS job_id_sequence (
                    id INTEGER PRIMARY KEY CHECK(id=1), highwater INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS problems (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
            """)
            c.execute("INSERT OR IGNORE INTO job_id_sequence(id,highwater) VALUES(1,0)")
            self._preserve_job_ids(c)

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def get(self, key, default=None):
        with self.lock, self.connect() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.lock, self.connect() as c:
            c.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    @staticmethod
    def _preserve_job_ids(connection):
        # INTEGER PRIMARY KEY otherwise reuses the largest deleted row ID.
        # Evidence and intervention URLs must never refer to a different job.
        connection.execute("""UPDATE job_id_sequence SET highwater=MAX(highwater,
            COALESCE((SELECT MAX(id) FROM jobs),0),
            COALESCE((SELECT MAX(job_id) FROM removed_job_identities),0)) WHERE id=1""")

    @staticmethod
    def _identity_keys(payload, canonical=None):
        identities = {
            ("url", canonical_url(payload[key]))
            for key in ["url", "source_url", "apply_url"]
            if payload.get(key)
        }
        if canonical:
            identities.add(("url", canonical))
        requisition = str(payload.get("requisition_id") or "").strip()
        company = str(payload.get("company") or "").strip().casefold()
        if requisition and company:
            identities.add(
                ("requisition", json.dumps([company, requisition], separators=(",", ":")))
            )
        return identities

    @staticmethod
    def _remember_removed(connection, job_id, identities):
        connection.executemany(
            "INSERT OR IGNORE INTO removed_job_identities(kind,identity,job_id) VALUES(?,?,?)",
            [(kind, identity, job_id) for kind, identity in identities],
        )

    def add_job(self, job):
        payload = dict(job)
        url = canonical_url(payload.get("url", ""))
        if not url.startswith(("http://", "https://")):
            raise ValueError("A valid job URL is required.")
        payload.setdefault("created_at", self.now())
        payload.setdefault("status", "queued")
        payload.setdefault("fit", 0)
        payload.setdefault("attempts", 0)
        payload.setdefault("note", "")
        payload.setdefault("source", "Manual")
        payload.setdefault("posted_at", None)
        with self.lock, self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            identities = self._identity_keys(payload, url)
            removed_id = None
            for kind, identity in identities:
                row = c.execute(
                    "SELECT job_id FROM removed_job_identities WHERE kind=? AND identity=?",
                    (kind, identity),
                ).fetchone()
                if row:
                    removed_id = row[0]
                    break
            if removed_id is not None:
                # A new discovery route can reveal another alias of the same
                # removed requisition. Retain only that minimal identity.
                self._remember_removed(c, removed_id, identities)
                return None
            incoming_urls = {
                canonical_url(payload[key])
                for key in ["url", "source_url", "apply_url"]
                if payload.get(key)
            }
            for existing_id, raw in c.execute("SELECT id,payload FROM jobs"):
                existing = json.loads(raw)
                existing_urls = {
                    canonical_url(existing[key])
                    for key in ["url", "source_url", "apply_url"]
                    if existing.get(key)
                }
                if incoming_urls & existing_urls:
                    return self._refresh(c, existing_id, existing, payload)
            # Requisition links occasionally differ by source tracking URLs.
            req = str(payload.get("requisition_id", "")).strip()
            if req:
                for existing_id, raw in c.execute("SELECT id,payload FROM jobs"):
                    existing = json.loads(raw)
                    if (
                        existing.get("requisition_id") == req
                        and existing.get("company", "").casefold()
                        == payload.get("company", "").casefold()
                    ):
                        return self._refresh(c, existing_id, existing, payload)
            self._preserve_job_ids(c)
            next_id = c.execute("SELECT highwater+1 FROM job_id_sequence WHERE id=1").fetchone()[0]
            inserted = c.execute(
                "INSERT OR IGNORE INTO jobs(id,canonical,payload) VALUES(?,?,?)",
                (next_id, url, json.dumps(payload)),
            ).rowcount
            if inserted:
                c.execute("UPDATE job_id_sequence SET highwater=? WHERE id=1", (next_id,))
            row = c.execute("SELECT id,payload FROM jobs WHERE canonical=?", (url,)).fetchone()
            return (
                self.decorate(row[0], json.loads(row[1]))
                if inserted
                else self._refresh(c, row[0], json.loads(row[1]), payload)
            )

    def _refresh(self, connection, job_id, existing, incoming):
        # Discovery can improve the exact requisition route even after a resume
        # has been prepared. State and receipt evidence remain authoritative.
        for key in ["source_url", "apply_url"]:
            if incoming.get(key):
                existing[key] = incoming[key]
        if (
            existing.get("documents")
            or existing.get("uncertain")
            or (
                existing.get("status") == "skipped"
                and existing.get("note") == "Skipped in dashboard."
            )
            or existing.get("status")
            in ["confirmed", "manually_verified", "applied", "submitting", "applying", "preparing"]
        ):
            connection.execute(
                "UPDATE jobs SET payload=? WHERE id=?", (json.dumps(existing), job_id)
            )
            return self.decorate(job_id, existing)
        # Older email digests assigned the subject's first role to every URL.
        # Repair those saved rows once from per-card metadata, without changing
        # jobs that already have application evidence or an active handoff.
        handoff = existing.get("browser_handoff") or {}
        manual_active = (
            handoff.get("mode") == "default_browser" and handoff.get("state") != "closed"
        )
        if (
            incoming.get("source") == existing.get("source") == "email"
            and incoming.get("alert_metadata_version", 0)
            > existing.get("alert_metadata_version", 0)
            and not existing.get("attempts")
            and not manual_active
        ):
            for key in [
                "title",
                "company",
                "location",
                "description",
                "description_missing",
                "alert_subject",
                "alert_received_at",
                "alert_from",
                "alert_metadata_version",
                "status",
                "note",
                "fit",
                "review_reason",
            ]:
                if key in incoming:
                    existing[key] = incoming[key]
            connection.execute(
                "UPDATE jobs SET payload=? WHERE id=?", (json.dumps(existing), job_id)
            )
            return self.decorate(job_id, existing)
        was_incomplete = (
            not existing.get("description")
            or not existing.get("company")
            or existing.get("description_missing")
        )
        for key in ["title", "company", "location", "posted_at", "requisition_id"]:
            if not existing.get(key) and incoming.get(key):
                existing[key] = incoming[key]
        if was_incomplete and incoming.get("title"):
            existing["title"] = incoming["title"]
        if len(str(incoming.get("description", ""))) > len(str(existing.get("description", ""))):
            existing["description"] = incoming["description"]
            existing["description_missing"] = incoming.get("description_missing", False)
            existing["fit"] = incoming.get("fit", existing.get("fit", 0))
        handoff = existing.get("browser_handoff") or {}
        manual_active = (
            handoff.get("mode") == "default_browser" and handoff.get("state") != "closed"
        )
        if (
            was_incomplete
            and not manual_active
            and not existing.get("attempts")
            and all(existing.get(k) for k in ["title", "company", "description"])
        ):
            existing["status"] = incoming.get("status", existing.get("status", "needs_review"))
            existing["note"] = incoming.get("note", "")
        connection.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(existing), job_id))
        return self.decorate(job_id, existing)

    def decorate(self, job_id, payload):
        p = dict(payload, id=job_id)
        p["bucket"] = freshness(p.get("posted_at"))
        p["bucket_label"] = BUCKET_LABELS[p["bucket"]]
        return p

    def jobs(self):
        with self.lock, self.connect() as c:
            rows = c.execute("SELECT id,payload FROM jobs").fetchall()
        return sorted([self.decorate(i, json.loads(p)) for i, p in rows], key=rank_key)

    def get_job(self, job_id):
        with self.lock, self.connect() as c:
            row = c.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self.decorate(job_id, json.loads(row[0])) if row else None

    def update_job(self, job_id, **changes):
        with self.lock, self.connect() as c:
            row = c.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            payload = json.loads(row[0])
            payload.update(changes)
            payload["updated_at"] = self.now()
            c.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(payload), job_id))
            return self.decorate(job_id, payload)

    def mark_applied(self, job_id, applied):
        with self.lock, self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            payload = json.loads(row[0])
            if payload.get("status") in ["preparing", "applying", "submitting"] or (
                payload.get("review_session") or {}
            ).get("state") in ["opening", "opened"]:
                raise ValueError("Wait for this job's active work to finish.")
            if applied:
                if payload.get("status") != "applied":
                    payload["applied_prior_status"] = payload.get("status", "queued")
                    payload["applied_prior_uncertain"] = payload.get("uncertain", False)
                payload.update(
                    applied=True,
                    status="applied",
                    uncertain=False,
                    applied_at=payload.get("applied_at") or self.now(),
                )
                handoff = payload.get("browser_handoff") or {}
                if handoff.get("mode") == "default_browser":
                    payload["browser_handoff"] = {
                        **handoff,
                        "state": "closed",
                        "outcome": "applied",
                    }
            else:
                previous = payload.pop("applied_prior_status", payload.get("status"))
                if previous not in ["queued", "prepared", "needs_review", "error", "skipped"]:
                    previous = "prepared" if payload.get("documents") else "queued"
                payload.update(
                    applied=False,
                    applied_at=None,
                    status=previous,
                    uncertain=payload.pop(
                        "applied_prior_uncertain", payload.get("uncertain", False)
                    ),
                )
                if payload.get("preparation_prior_status") == "applied":
                    payload["preparation_prior_status"] = previous
            payload["updated_at"] = self.now()
            c.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(payload), job_id))
            return self.decorate(job_id, payload)

    def remove_job(self, job_id):
        with self.lock, self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT canonical,payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            payload = json.loads(row[1])
            if self._cleanup_protected(payload):
                raise ValueError(
                    "Finish this job's active work or browser handoff before removing it."
                )
            self._preserve_job_ids(c)
            self._remember_removed(c, job_id, self._identity_keys(payload, row[0]))
            c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        return {"deleted_count": 1, "deleted_ids": [job_id], "skipped_count": 0}

    @staticmethod
    def problem_url(value):
        try:
            parts = urlsplit(str(value or ""))
            if (
                parts.scheme not in ["http", "https"]
                or not parts.hostname
                or parts.username
                or parts.password
            ):
                return ""
            safe_keys = {"jk", "jobid", "job_id", "requisitionid", "gh_jid", "lang"}
            query = urlencode(
                [(key, value) for key, value in parse_qsl(parts.query) if key.lower() in safe_keys]
            )
            return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
        except ValueError:
            return ""

    def add_problem(self, message, *, category="worker", job=None, url=None):
        job = job or {}
        payload = {
            "message": str(message)[:600],
            "title": str(job.get("title") or "")[:180],
            "company": str(job.get("company") or "")[:180],
            "url": self.problem_url(url or job.get("url") or job.get("apply_url")),
            "created_at": self.now(),
            "resolved": False,
            "category": category,
        }
        with self.lock, self.connect() as c:
            for problem_id, raw in c.execute("SELECT id,payload FROM problems ORDER BY id DESC"):
                previous = json.loads(raw)
                if not previous.get("resolved") and all(
                    previous.get(key) == payload[key]
                    for key in ["message", "title", "company", "url", "category"]
                ):
                    return {**previous, "id": problem_id}
            result = c.execute("INSERT INTO problems(payload) VALUES(?)", (json.dumps(payload),))
            return {**payload, "id": result.lastrowid}

    def problems(self):
        with self.lock, self.connect() as c:
            rows = c.execute("SELECT id,payload FROM problems ORDER BY id DESC").fetchall()
        return [{**json.loads(raw), "id": problem_id} for problem_id, raw in rows]

    def resolve_problem(self, problem_id):
        with self.lock, self.connect() as c:
            row = c.execute("SELECT payload FROM problems WHERE id=?", (problem_id,)).fetchone()
            if not row:
                raise KeyError(problem_id)
            payload = json.loads(row[0])
            payload.update(resolved=True, resolved_at=self.now())
            c.execute("UPDATE problems SET payload=? WHERE id=?", (json.dumps(payload), problem_id))
            return {**payload, "id": problem_id}

    @staticmethod
    def _cleanup_cutoff(cutoff):
        if not isinstance(cutoff, datetime) or cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("Cleanup requires a timezone-aware datetime cutoff.")
        return cutoff.astimezone(timezone.utc)

    @staticmethod
    def _cleanup_protected(payload):
        handoff = payload.get("browser_handoff") or {}
        review = payload.get("review_session") or {}
        return (
            payload.get("status") in ["preparing", "applying", "submitting"]
            or (handoff.get("mode") == "default_browser" and handoff.get("state") != "closed")
            or review.get("state") in ["opening", "opened"]
        )

    def cleanup_preview(self, cutoff):
        cutoff = self._cleanup_cutoff(cutoff)
        now = parse_date(self.now())
        eligible, protected, unknown = [], 0, 0
        with self.lock, self.connect() as c:
            for job_id, raw in c.execute("SELECT id,payload FROM jobs"):
                payload = json.loads(raw)
                posted = parse_date(payload.get("posted_at"))
                if posted is None:
                    unknown += 1
                elif posted <= cutoff and posted <= now:
                    if self._cleanup_protected(payload):
                        protected += 1
                    else:
                        eligible.append(self.decorate(job_id, payload))
        return {
            "jobs": sorted(eligible, key=rank_key),
            "protected_count": protected,
            "unknown_date_count": unknown,
        }

    def delete_old_jobs(self, cutoff, job_ids):
        cutoff = self._cleanup_cutoff(cutoff)
        if not isinstance(job_ids, list) or any(
            type(job_id) is not int or job_id <= 0 for job_id in job_ids
        ):
            raise ValueError("Cleanup job IDs must be a list of positive integers.")
        requested = list(dict.fromkeys(job_ids))
        deleted = []
        with self.lock, self.connect() as c:
            # Reserve the write transaction before reading eligibility, also
            # protecting this check from another Store/database connection.
            c.execute("BEGIN IMMEDIATE")
            self._preserve_job_ids(c)
            now = parse_date(self.now())
            for job_id in requested:
                row = c.execute(
                    "SELECT canonical,payload FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
                if not row:
                    continue
                payload = json.loads(row[1])
                posted = parse_date(payload.get("posted_at"))
                if (
                    posted is None
                    or posted > cutoff
                    or posted > now
                    or self._cleanup_protected(payload)
                ):
                    continue
                self._remember_removed(c, job_id, self._identity_keys(payload, row[0]))
                c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
                deleted.append(job_id)
        return {
            "deleted_count": len(deleted),
            "deleted_ids": deleted,
            "skipped_count": len(requested) - len(deleted),
        }

    def event(self, message, level="info"):
        with self.lock, self.connect() as c:
            c.execute(
                "INSERT INTO events(at,level,message) VALUES(?,?,?)",
                (self.now(), level, str(message)[:2000]),
            )
            c.execute(
                "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 1000)"
            )

    def events(self):
        with self.lock, self.connect() as c:
            rows = c.execute(
                "SELECT at,level,message FROM events ORDER BY id DESC LIMIT 80"
            ).fetchall()
        return [dict(zip(["at", "level", "message"], row)) for row in rows]

    def recover(self):
        for job in self.jobs():
            if job.get("review_session", {}).get("state") in ["opening", "opened"]:
                self.update_job(
                    job["id"],
                    review_session={
                        **job["review_session"],
                        "state": "closed",
                        "closed_at": self.now(),
                        "interrupted": True,
                    },
                )
            if job["status"] == "submitting":
                self.update_job(
                    job["id"],
                    status="needs_review",
                    uncertain=True,
                    note="Submission outcome uncertain after interruption. Verify receipt before any retry.",
                )
            elif job["status"] == "preparing":
                review = job.get("preparation_prior_status") == "needs_review"
                applied = job.get("applied") or job.get("preparation_prior_status") == "applied"
                self.update_job(
                    job["id"],
                    status="applied" if applied else ("needs_review" if review else "queued"),
                    preparation_requested=True,
                    note=(
                        job.get("preparation_prior_note", "")
                        + " Preparation interrupted; review retained."
                    )
                    if review
                    else "Preparation interrupted; safely requeued.",
                )
            elif job["status"] == "applying":
                self.update_job(
                    job["id"],
                    status="prepared" if job.get("documents") else "queued",
                    note="Form inspection interrupted before submission checkpoint; safely requeued.",
                )

    def metrics(self):
        jobs = self.jobs()
        today = datetime.now(timezone.utc).astimezone(TZ).date()
        confirmed = [j for j in jobs if j["status"] == "confirmed"]
        applied = [j for j in jobs if j.get("applied") or j["status"] == "applied"]
        errors = [j for j in jobs if j["status"] == "error"]

        def local_today(value):
            d = parse_date(value)
            return bool(d and d.astimezone(TZ).date() == today)

        total = len(confirmed) + len(errors)
        return {
            "confirmed": len(confirmed),
            "applied": len(applied),
            "errors": len(errors),
            "success_rate": round(len(confirmed) / total * 100, 1) if total else None,
            "applied_today": sum(local_today(j.get("applied_at")) for j in applied)
            + sum(local_today(j.get("confirmed_at")) for j in confirmed if not j.get("applied")),
            "queued": sum(j["status"] in ["queued", "preparing", "prepared"] for j in jobs),
            "review": sum(j["status"] == "needs_review" for j in jobs),
            "manually_verified": sum(j["status"] == "manually_verified" for j in jobs),
            "discovered_today": sum(local_today(j.get("created_at")) for j in jobs),
        }
