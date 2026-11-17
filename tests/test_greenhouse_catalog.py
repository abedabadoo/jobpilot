import json
from datetime import datetime, timedelta, timezone

from jobpilot import collectors
from jobpilot.core import rank_key, role_assessment, score_job


def test_catalog_covers_reported_employers():
    boards = collectors.greenhouse_boards()
    assert len(boards) > 5000
    assert {"cobaltio", "guidepointsecurity", "calahealth"} <= set(boards)


def test_greenhouse_scan_loads_promising_details_and_advances_cursor(monkeypatch):
    boards = ["cobaltio", "guidepointsecurity", "calahealth"]
    titles = ["Associate Security Researcher", "Application Security Engineer", "Security Engineer"]
    ids = [8924332002, 6220720004, 6251147004]
    dates = ["2026-10-30T17:29:33-04:00", "2026-10-08T12:00:00-04:00", "2026-11-05T19:30:48-05:00"]
    calls = []

    def get(url):
        calls.append(url)
        board = next(board for board in boards if f"/{board}/" in url)
        index = boards.index(board)
        row = {
            "id": ids[index],
            "internal_job_id": ids[index] - 1,
            "absolute_url": f"https://job-boards.greenhouse.io/{board}/jobs/{ids[index]}",
            "title": titles[index],
            "company_name": ["Cobalt", "GuidePoint Security", "Cala Health"][index],
            "location": {"name": "Remote, United States"},
            "first_published": dates[index],
        }
        if url.endswith("/jobs"):
            return json.dumps(
                {"jobs": [row, {**row, "id": ids[index] + 1, "title": "Retail Sales Manager"}]}
            ), url
        return json.dumps(
            {
                **row,
                "content": "&lt;p&gt;3+ years of experience in AWS, Python, DevSecOps and security.&lt;/p&gt;",
            }
        ), url

    monkeypatch.setattr(collectors, "_get_public", get)
    monkeypatch.setattr(collectors, "greenhouse_boards", lambda: boards)
    monkeypatch.setattr(collectors, "GREENHOUSE_BATCH_SIZE", 3)
    jobs = collectors.discover(
        {
            "sources": [],
            "ats_boards": [],
            "greenhouse_discovery": True,
            "_greenhouse_cursor": 0,
            "target_roles": ["DevOps Engineer", "Security Engineer"],
            "location": "Cincinnati, OH",
            "remote": True,
        },
        {},
    )
    assert {job["requisition_id"] for job in jobs} == set(map(str, ids))
    assert all("3+ years" in job["description"] for job in jobs)
    assert all("&lt;" not in job["description"] for job in jobs)
    assert jobs[0]["company"] == "Cobalt"
    assert [job["posted_at"] for job in jobs] == dates
    assert len(calls) == 6
    assert collectors.get_last_search_result()["greenhouse_next_cursor"] == 0


def test_recent_three_year_role_ranks_above_today_senior_role():
    now = datetime.now(timezone.utc)
    suitable = {
        "id": 1,
        "title": "Security Engineer",
        "fit": 78,
        "description": "3+ years of experience in cloud security.",
        "posted_at": (now - timedelta(days=2)).isoformat(),
    }
    senior = {
        "id": 2,
        "title": "Senior Security Engineer",
        "fit": 92,
        "description": "7+ years of experience in cloud security.",
        "posted_at": (now - timedelta(hours=1)).isoformat(),
    }
    assert sorted([senior, suitable], key=rank_key)[0] is suitable
    assert score_job(
        suitable, {"skills": ["cloud security"]}, {"target_roles": ["Security Engineer"]}
    ) > score_job(senior, {"skills": ["cloud security"]}, {"target_roles": ["Security Engineer"]})


def test_related_security_research_and_configured_platform_roles_are_eligible():
    settings = {
        "target_roles": [
            "Security Engineer",
            "DevOps Engineer",
            "Cloud Engineer",
            "Platform Engineer",
            "Forward Deployed Engineer",
        ]
    }
    for title in [
        "Associate Security Researcher",
        "DevOps Specialist",
        "Cloud Infrastructure Engineer",
        "Site Reliability Engineer",
        "Forward Deployed Engineer",
    ]:
        assert role_assessment({"title": title}, {}, settings)[0] != "excluded"
