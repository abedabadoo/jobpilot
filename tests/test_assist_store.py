from jobpilot.store import Store


def test_applied_status_is_idempotent_and_survives_source_refresh(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    job = store.add_job({"url": "https://example.com/jobs/1", "status": "queued"})
    marked = store.mark_applied(job["id"], True)
    again = store.mark_applied(job["id"], True)
    assert again["applied_at"] == marked["applied_at"]
    assert again["applied_prior_status"] == "queued"
    updated = store.add_job(
        {
            "url": job["url"],
            "title": "Security",
            "company": "Example",
            "description": "New listing metadata",
            "status": "queued",
        }
    )
    assert updated["status"] == "applied" and updated["applied"] is True
    assert Store(store.path).mark_applied(job["id"], False)["status"] == "queued"


def test_problems_persist_and_strip_authentication_material_from_urls(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    first = store.add_problem(
        "The listing could not be read.",
        category="fetch",
        job={
            "title": "Engineer",
            "company": "Example",
            "url": "https://example.com/job?jk=123&token=secret#private",
        },
    )
    assert first["url"] == "https://example.com/job?jk=123"
    duplicate = store.add_problem(
        "The listing could not be read.",
        category="fetch",
        job={"title": "Engineer", "company": "Example", "url": first["url"]},
    )
    assert duplicate["id"] == first["id"]
    restarted = Store(store.path)
    assert len(restarted.problems()) == 1
    assert restarted.resolve_problem(first["id"])["resolved"] is True
    newer = restarted.add_problem(
        "The listing could not be read.",
        category="fetch",
        job={"title": "Engineer", "company": "Example", "url": first["url"]},
    )
    assert newer["id"] != first["id"]
    assert len(Store(store.path).problems()) == 2


def test_interrupted_regeneration_keeps_manual_applied_state_and_requeues_documents(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    job = store.add_job(
        {
            "url": "https://example.com/jobs/2",
            "status": "preparing",
            "applied": True,
            "applied_at": "2026-10-26T12:00:00Z",
            "preparation_prior_status": "applied",
        }
    )
    store.recover()
    current = store.get_job(job["id"])
    assert current["status"] == "applied" and current["applied"] is True
    assert current["applied_at"] == job["applied_at"]
    assert current["preparation_requested"] is True


def test_repeated_unmark_keeps_the_original_review_state(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    job = store.add_job(
        {
            "url": "https://example.com/jobs/review",
            "status": "needs_review",
            "documents": {"resume_pdf": "fixture.pdf"},
            "uncertain": True,
        }
    )
    store.mark_applied(job["id"], True)
    store.mark_applied(job["id"], False)
    repeated = store.mark_applied(job["id"], False)
    assert repeated["status"] == "needs_review"
    assert repeated["uncertain"] is True
