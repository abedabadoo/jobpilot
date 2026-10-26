import pytest
from test_api import api


@pytest.fixture
def state_api(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    from jobpilot import keywords, service

    calls = []

    def extract(job, profile):
        calls.append((dict(job), profile))
        term = job.get("description") or job.get("title") or "Example"
        return {"terms": [term], "tools": [], "skills": [], "matched": [], "suggested": [term]}

    monkeypatch.setattr(keywords, "extract_keywords", extract)
    return service, client, calls


def add(service, slug, **changes):
    return service.store.add_job(
        {
            "url": f"https://example.com/jobs/{slug}",
            "title": "Security Engineer",
            "description": "Python and AWS",
            "company": "Example",
            **changes,
        }
    )


def test_state_reuses_keywords_across_polls_and_duplicate_postings(state_api):
    service, client, calls = state_api
    first = add(service, "one")
    add(service, "two")
    for _ in range(3):
        assert client.get("/api/state").status_code == 200
    assert client.get(f"/api/jobs/{first['id']}/keywords").status_code == 200
    assert len(calls) == 1


def test_state_invalidates_keywords_when_posting_or_profile_changes(state_api):
    service, client, calls = state_api
    job = add(service, "one")
    client.get("/api/state")
    service.store.update_job(job["id"], description="Terraform and Azure")
    client.get("/api/state")
    service.store.update_job(job["id"], title="Cloud Engineer")
    client.get("/api/state")
    profile = service.store.get("profile")
    profile["skills"].append("Terraform")
    service.store.set("profile", profile)
    client.get("/api/state")
    assert len(calls) == 4
    assert "Terraform" in calls[-1][1]["skills"]


def test_keyword_response_mutation_cannot_change_cached_keywords(state_api):
    service, _, calls = state_api
    job = add(service, "one")
    result = service.state()
    result["jobs"][0]["keywords"]["terms"].append("Changed outside the cache")
    direct = service.job_keywords(job)
    assert direct["terms"] == ["Python and AWS"]
    assert len(calls) == 1


def test_state_loads_one_profile_snapshot_for_all_jobs(state_api, monkeypatch):
    service, client, _ = state_api
    for slug in range(5):
        add(service, str(slug))
    original_get = service.store.get
    reads = []

    def get(key, default=None):
        if key == "profile":
            reads.append(key)
        return original_get(key, default)

    monkeypatch.setattr(service.store, "get", get)
    response = client.get("/api/state")
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 5
    assert len(reads) == 1
