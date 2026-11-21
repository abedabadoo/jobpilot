"""Local profile import tests use fictional data, never a real applicant profile."""

import json

import pytest

from jobpilot.local_profile import adopt_local_profile, read_local_profile


def _draft(tmp_path):
    master = tmp_path / "master"
    master.mkdir()
    draft = {
        "profile": {
            "name": "Casey Example",
            "contact": (
                "+1 (202) 555-0130 | casey@example.org | Cincinnati, OH, USA "
                "| linkedin.com/in/casey"
            ),
            "roles": [
                {
                    "id": "role-1",
                    "company": "Acme",
                    "title": "Security Engineer",
                    "dates": "July 2024 - July 2026",
                    "bullets": [
                        {"id": "bullet-1", "text": "Automated Python security scans on AWS."}
                    ],
                }
            ],
            "facts": [
                {
                    "id": "fact-1",
                    "role_id": "role-1",
                    "confirmed": True,
                    "text": "Reviewed additional security evidence.",
                }
            ],
            "skills": ["AWS", "Python"],
            "certifications": "CompTIA Security+ | Google Cybersecurity Certificate",
            "education": [
                {
                    "institution": "Example University",
                    "degree": "BS",
                    "dates": "August 2017 - May 2021",
                }
            ],
        },
    }
    (master / "draft.json").write_text(json.dumps(draft), encoding="utf-8")
    return master


def test_saved_profile_maps_to_jobpilot(tmp_path):
    profile = read_local_profile(_draft(tmp_path))
    assert profile["name"] == "Casey Example"
    assert profile["sample_profile"] is False
    assert profile["email"] == "casey@example.org"
    assert profile["first_name"] == "Casey"
    assert profile["experience"][0]["start"] == "July 2024"
    assert profile["experience"][0]["end"] == "July 2026"
    assert len(profile["experience"][0]["facts"]) == 2
    assert profile["skills"] == ["AWS", "Python"]
    assert profile["certifications"] == ["CompTIA Security+", "Google Cybersecurity Certificate"]


def test_bootstrap_replaces_sample_and_rescores_without_overwriting_user(tmp_path):
    class Store:
        def __init__(self):
            self.values = {"profile": {"sample_profile": True, "name": "Jordan Morgan"}}
            self.rows = [
                {"id": 1, "title": "Security Engineer", "status": "queued", "fit": 15},
                {
                    "id": 2,
                    "title": "Security Engineer",
                    "status": "skipped",
                    "fit": 15,
                    "note": "Fit is below the configured search threshold.",
                },
            ]
            self.events = []

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

        def jobs(self):
            return self.rows

        def update_job(self, job_id, **changes):
            next(row for row in self.rows if row["id"] == job_id).update(changes)

        def event(self, note):
            self.events.append(note)

    store = Store()

    def score(job, profile, settings):
        return 85 if "Python" in profile["skills"] else 10

    master = _draft(tmp_path)
    assert adopt_local_profile(store, master, score, {"min_fit": 40}) is True
    assert store.get("profile")["name"] == "Casey Example"
    assert [row["fit"] for row in store.rows] == [85, 85]
    assert store.rows[1]["status"] == "queued"
    assert adopt_local_profile(store, master, score, {"min_fit": 40}) is False
    store.set("profile", {"sample_profile": False, "name": "Custom User"})
    assert adopt_local_profile(store, master, score, {"min_fit": 40}) is False
    assert store.get("profile")["name"] == "Custom User"


def test_missing_master_keeps_fictional_seed(tmp_path):
    assert read_local_profile(tmp_path) is None
    master = _draft(tmp_path)
    (master / "draft.json").write_text(
        '{"profile":{"name":"Morgan Example"}}',
        encoding="utf-8",
    )
    assert read_local_profile(master) is None


def test_interrupted_initial_rescore_retries_without_partial_profile_commit(tmp_path):
    class InterruptingStore:
        def __init__(self):
            self.values = {"profile": {"sample_profile": True, "name": "Jordan Morgan"}}
            self.rows = [
                {"id": 1, "title": "Security Engineer", "status": "queued", "fit": 15},
                {"id": 2, "title": "Cloud Security Engineer", "status": "queued", "fit": 15},
            ]
            self.fail_second_update = True

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

        def jobs(self):
            return self.rows

        def update_job(self, job_id, **changes):
            if job_id == 2 and self.fail_second_update:
                self.fail_second_update = False
                raise OSError("Simulated temporary SQLite resource exhaustion")
            next(row for row in self.rows if row["id"] == job_id).update(changes)

        def event(self, message):
            pass

    store = InterruptingStore()
    def score(job, profile, settings):
        return 90

    with pytest.raises(OSError, match="temporary SQLite"):
        adopt_local_profile(store, _draft(tmp_path), score, {"min_fit": 40})
    assert store.get("profile")["sample_profile"] is True
    assert store.rows[0]["fit"] == 90
    assert store.rows[1]["fit"] == 15

    # A subsequent launch retries rather than incorrectly treating the import as complete.
    assert adopt_local_profile(store, tmp_path / "master", score, {"min_fit": 40}) is True
    assert store.get("profile")["sample_profile"] is False
    assert [row["fit"] for row in store.rows] == [90, 90]
