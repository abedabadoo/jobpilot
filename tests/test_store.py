from jobpilot.store import Store


def test_discovery_enrichment_keeps_active_normal_browser_handoff_held(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    saved = s.add_job(
        {
            "url": "https://example.com/job/manual",
            "status": "needs_review",
            "browser_handoff": {"mode": "default_browser", "state": "opened"},
            "note": "Manual application in progress",
        }
    )
    updated = s.add_job(
        {
            "url": saved["url"],
            "title": "Security Engineer",
            "company": "Fixture",
            "description": "New description from employer discovery",
            "status": "queued",
        }
    )
    assert updated["status"] == "needs_review"
    assert updated["note"] == saved["note"]
    assert updated["description"]
    s.recover()
    assert s.get_job(saved["id"])["status"] == "needs_review"


def test_persistence_dedup_and_metrics(tmp_path):
    path = tmp_path / "db.sqlite"
    s = Store(path)
    a = s.add_job(
        {
            "title": "Security Engineer",
            "company": "Test",
            "url": "https://example.com/job/1?utm_source=a",
            "fit": 90,
        }
    )
    b = s.add_job(
        {
            "title": "Security Engineer",
            "company": "Test",
            "url": "https://example.com/job/1",
            "fit": 90,
        }
    )
    assert a["id"] == b["id"]
    assert len(Store(path).jobs()) == 1
    s.update_job(a["id"], status="confirmed", confirmed_at=s.now())
    s.add_job(
        {
            "title": "Other",
            "company": "Test",
            "url": "https://example.com/job/2",
            "status": "needs_review",
        }
    )
    assert s.metrics()["success_rate"] == 100.0
    assert s.metrics()["confirmed"] == 1
    assert s.metrics()["review"] == 1


def test_uncertain_submission_recovers_to_review(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    j = s.add_job({"title": "Role", "company": "Test", "url": "https://example.com/1"})
    s.update_job(j["id"], status="submitting")
    s.recover()
    assert s.get_job(j["id"])["status"] == "needs_review"
    assert "uncertain" in s.get_job(j["id"])["note"].lower()


def test_restart_releases_stale_review_session_without_retrying_uncertainty(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    j = s.add_job(
        {
            "title": "Role",
            "company": "Test",
            "url": "https://example.com/1",
            "status": "needs_review",
            "uncertain": True,
            "submission_checkpoint_at": "original",
            "review_session": {"nonce": "old-session", "state": "opened"},
        }
    )
    s.recover()
    current = s.get_job(j["id"])
    assert current["review_session"]["state"] == "closed"
    assert current["uncertain"] and current["status"] == "needs_review"
    assert current["submission_checkpoint_at"] == "original"


def test_setting_round_trip(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    s.set("answers", {"sponsorship": "No"})
    assert Store(tmp_path / "db.sqlite").get("answers")["sponsorship"] == "No"


def test_duplicate_source_can_fill_missing_metadata_without_clearing_attempted_review(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    first = s.add_job(
        {
            "url": "https://example.com/job/1",
            "title": "Job from email",
            "company": "",
            "description": "",
            "status": "needs_review",
        }
    )
    better = s.add_job(
        {
            "url": "https://example.com/job/1?utm_source=email",
            "title": "Security Engineer",
            "company": "Example",
            "description": "AWS role details",
            "status": "queued",
            "fit": 80,
        }
    )
    assert better["id"] == first["id"]
    assert better["company"] == "Example"
    assert better["status"] == "queued"
    s.update_job(
        first["id"], status="needs_review", attempts=1, note="Unknown required screening answer."
    )
    again = s.add_job(
        {
            "url": "https://example.com/job/1",
            "title": "Security Engineer",
            "company": "Example",
            "description": "AWS full job description updated.",
            "status": "queued",
        }
    )
    assert again["status"] == "needs_review"
    assert again["note"] == "Unknown required screening answer."


def test_verified_route_upgrade_matches_original_source_and_preserves_submission_state(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    first = s.add_job(
        {
            "url": "https://linkedin.com/jobs/view/123",
            "title": "Security Engineer",
            "company": "Acme",
        }
    )
    s.update_job(
        first["id"],
        status="needs_review",
        uncertain=True,
        attempts=1,
        documents={"resume_pdf": "original.pdf"},
        note="Receipt uncertain",
    )
    upgraded = s.add_job(
        {
            "url": "https://example.com/careers/123",
            "apply_url": "https://example.com/careers/123",
            "source_url": "https://www.linkedin.com/jobs/view/123/?utm_source=search",
            "title": "Security Engineer",
            "company": "Acme",
            "status": "queued",
        }
    )
    assert upgraded["id"] == first["id"]
    assert len(s.jobs()) == 1
    assert upgraded["apply_url"] == "https://example.com/careers/123"
    assert upgraded["uncertain"] is True
    assert upgraded["status"] == "needs_review"
    assert upgraded["attempts"] == 1
    assert upgraded["documents"] == {"resume_pdf": "original.pdf"}
    assert upgraded["note"] == "Receipt uncertain"
