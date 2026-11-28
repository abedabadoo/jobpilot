import json
import time
from email.message import EmailMessage
from pathlib import Path

import pytest
from pypdf import PdfReader
from test_api import api

from jobpilot import collectors


@pytest.fixture
def messages():
    mail = EmailMessage()
    mail["Subject"] = "Security Engineer at Northstar Systems"
    mail.set_content(
        "Security Engineer at Northstar Systems https://www.linkedin.com/comm/jobs/view/12345/?trk=email"
    )
    return {1: mail.as_bytes(), 2: mail.as_bytes()}


@pytest.fixture
def mailbox(monkeypatch, messages):
    calls = []

    class Inbox:
        def __init__(self, *args, **kwargs):
            calls.append(("connect", args, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, username, password):
            calls.append(("login", username))
            return "OK", []

        def select(self, folder, readonly=False):
            calls.append(("select", folder, readonly))
            return "OK", [b"2"]

        def response(self, name):
            assert name == "UIDVALIDITY"
            return name, [b"10"]

        def uid(self, command, *args):
            calls.append((command, *args))
            if command == "search":
                return "OK", [" ".join(str(uid) for uid in messages).encode()]
            body = messages[int(args[0])]
            return ("OK", [(b"RFC822", body)]) if body is not None else ("NO", [b"Unavailable"])

    monkeypatch.setattr(collectors, "_validate_host", lambda host: None)
    monkeypatch.setattr(collectors.keyring, "get_password", lambda *args: "saved-app-password")
    monkeypatch.setattr(collectors.imaplib, "IMAP4_SSL", Inbox)
    return calls


def config(**values):
    return {
        "host": "imap.gmail.com",
        "username": "jordan@example.com",
        "mailbox": "INBOX",
        **values,
    }


def test_gmail_sync_is_read_only_counts_messages_and_deduplicates_links(mailbox):
    result = collectors.sync_email(config())
    assert result["messages_checked"] == 2
    assert result["links_found"] == 1
    assert result["checked_at"]
    assert collectors.get_last_email_result()["messages_checked"] == 2
    assert "jobs" not in collectors.get_last_email_result()
    assert result["jobs"][0]["url"] == "https://www.linkedin.com/jobs/view/12345/"
    assert result["jobs"][0]["company"] == "Northstar Systems"
    assert ("select", "INBOX", True) in mailbox
    assert all(call[-1].startswith("(BODY.PEEK[") for call in mailbox if call[0] == "fetch")
    assert mailbox[0][2]["ssl_context"].check_hostname
    assert result["checkpoint"] == {"validity": 10, "uid": 2}


def test_verified_gmail_alert_builds_only_a_checked_resume(
    tmp_path, monkeypatch, mailbox, messages
):
    client = api(tmp_path / "data", monkeypatch)
    from jobpilot import resumeforge_bridge, service

    description = (
        "Build AWS infrastructure as code and automated test environments. Own CI/CD pipelines "
        "with GitHub Actions, implement production monitoring and incident response, and build "
        "Python utilities and REST APIs to improve release reliability."
    )
    posting = "https://job-boards.greenhouse.io/signalorchard/jobs/12345"
    mail = EmailMessage()
    mail["Subject"] = "Your job alert: Platform Engineer at Signal Orchard Studio"
    mail.set_content(f"Platform Engineer at Signal Orchard Studio\n{posting}")
    messages.update({1: mail.as_bytes(), 2: mail.as_bytes()})

    def public_posting(url):
        assert (
            url
            == "https://boards-api.greenhouse.io/v1/boards/signalorchard/jobs/12345?pay_transparency=true"
        )
        return json.dumps(
            {
                "id": 12345,
                "title": "Platform Engineer",
                "company_name": "Signal Orchard Studio",
                "location": {"name": "Cincinnati, OH"},
                "content": f"<p>{description}</p>",
            }
        ), url

    monkeypatch.setattr(collectors, "_get_public", public_posting)
    service.store.set(
        "settings",
        {
            **service.settings(),
            "email": {"username": "fixture@example.invalid", "enabled": True},
            "target_roles": ["Platform Engineer"],
            "location": "Cincinnati, OH",
        },
    )
    service.store.set(
        "profile",
        {
            **service.store.get("profile"),
            "skills": ["AWS", "GitHub Actions", "Python", "incident response"],
        },
    )
    source = Path(resumeforge_bridge.__file__).parents[1] / "resumeforge/data/abu.profile.json"
    profile = json.loads(source.read_text(encoding="utf-8"))
    profile["name"] = "Fictional QA Candidate"
    master = tmp_path / "master"
    master.mkdir()
    (master / "draft.json").write_text(
        json.dumps({"profile": profile, "settings": {"provider": "none"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(resumeforge_bridge, "master_workspace", lambda: master)
    monkeypatch.setattr(
        resumeforge_bridge, "downloads_folder", lambda job: service.DATA / "applications"
    )

    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    assert client.post("/api/email/sync", headers=headers, json={}).status_code == 202
    deadline = time.monotonic() + 10
    while service.email_task_running.is_set() and time.monotonic() < deadline:
        time.sleep(0.02)
    status = client.get("/api/email/status").json()
    assert status["state"] == "connected"
    assert status["messages_checked"] == 2 and status["imported"] == status["researched"] == 1
    assert service.store.get("_email_checkpoint")["cursor"] == {"validity": 10, "uid": 2}
    assert ("select", "INBOX", True) in mailbox
    (job,) = service.store.jobs()
    assert job["posting_source"] == "greenhouse"
    assert job["description"] == description and job["fit"] == 80
    assert not service._automatic_resume_due({**job, "fit": 79})

    service.process_document_queue()
    job = service.store.get_job(job["id"])
    assert job["resumeforge"]["status"] == "ready"
    assert set(job["documents"]) == {"resumeforge_pdf"}
    pdf = Path(job["documents"]["resumeforge_pdf"])
    assert list(pdf.parent.glob("*.pdf")) == [pdf]
    (page,) = PdfReader(pdf).pages
    contents = page.extract_text()
    assert "Fictional QA Candidate" in contents and "AWS" in contents
    assert not service._automatic_resume_due(job)


def test_incremental_scan_reads_new_headers_and_retries_a_failed_uid(mailbox, messages):
    unrelated = EmailMessage()
    unrelated["Subject"] = "Your utility bill"
    unrelated.set_content("A misleading reference https://example.com/jobs/private-referral")
    messages.update({2: unrelated.as_bytes(), 3: None, 4: messages[1]})
    first = collectors.sync_email(config(limit=1))
    assert first["truncated"] and first["checkpoint"] == {"validity": 10, "uid": 1}
    mailbox.clear()
    second = collectors.sync_email(config(checkpoint=first["checkpoint"]))
    assert second["non_alerts"] == 1
    assert second["scan_interrupted"]
    assert second["checkpoint"] == {"validity": 10, "uid": 2}
    assert not any(
        uid == "4" or "BODY.PEEK[]" in command
        for kind, uid, command in (call for call in mailbox if call[0] == "fetch")
    )
    messages[3] = messages[1]
    third = collectors.sync_email(config(checkpoint=second["checkpoint"]))
    assert third["messages_checked"] == 2
    assert third["checkpoint"] == {"validity": 10, "uid": 4}
    reset = collectors.sync_email(config(limit=1, checkpoint={"validity": 11, "uid": 999}))
    assert reset["checkpoint"] == {"validity": 10, "uid": 1}


def test_connection_check_reads_no_message_bodies(mailbox):
    result = collectors.check_email_connection(config())
    assert result["ok"] is True
    assert result["messages_available"] == 2
    assert not any(call[0] == "fetch" for call in mailbox)


def test_missing_gmail_credential_has_actionable_message(mailbox, monkeypatch):
    monkeypatch.setattr(collectors.keyring, "get_password", lambda *args: None)
    with pytest.raises(collectors.EmailConnectionError, match="app password"):
        collectors.sync_email(config())
    assert not any(call[0] == "connect" for call in mailbox)


def test_rejected_login_never_exposes_raw_server_details(mailbox, monkeypatch):
    def rejected(*args):
        raise collectors.imaplib.IMAP4.error("bad saved-app-password C:/Users/private/secret")

    class Rejected:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        login = rejected

    monkeypatch.setattr(collectors.imaplib, "IMAP4_SSL", lambda *args, **kwargs: Rejected())
    with pytest.raises(collectors.EmailConnectionError) as failure:
        collectors.sync_email(config())
    assert "app password" in str(failure.value)
    assert "saved-app-password" not in str(failure.value)
    assert "C:/" not in str(failure.value)


def test_google_alert_redirect_preserves_exact_job_without_tracking_or_instructions():
    mail = EmailMessage()
    mail["Subject"] = "Cloud Security Engineer at Harbor Digital"
    mail.set_content("HTML version")
    mail.add_alternative(
        '<a href="https://www.google.com/url?q=https%3A%2F%2Fjobs.lever.co%2Fharbor%2Fabcd&amp;sa=D">Cloud Security Engineer at Harbor Digital</a>',
        subtype="html",
    )
    jobs = collectors.import_eml(mail.as_bytes())
    assert jobs[0]["url"] == "https://jobs.lever.co/harbor/abcd"
    assert jobs[0]["title"] == "Cloud Security Engineer"
    assert jobs[0]["company"] == "Harbor Digital"
    assert jobs[0]["posted_at"] is None


def test_oversize_message_is_counted_but_not_imported(mailbox, monkeypatch):
    monkeypatch.setattr(collectors, "_MAX_BODY", 20)
    result = collectors.sync_email(config())
    assert result["messages_checked"] == 2
    assert result["links_found"] == 0
    assert result["messages_skipped"] == 2


def test_multipart_digest_matches_each_link_to_its_own_job_card():
    mail = EmailMessage()
    mail["Subject"] = "Information Security Analyst job at Harbor Digital - Actively recruiting"
    mail.set_content(
        "Recent jobs https://www.linkedin.com/comm/jobs/view/101/?trk=email "
        "https://www.linkedin.com/comm/jobs/view/202/?trk=email"
    )
    mail.add_alternative(
        """<table><tbody>
        <tr><td><a href="https://www.linkedin.com/comm/jobs/view/101/?trk=logo"><img></a></td>
        <td><a href="https://www.linkedin.com/comm/jobs/view/101/?trk=card"><table><tbody>
        <tr><td><a href="https://www.linkedin.com/comm/jobs/view/101/?trk=title">Information Security Analyst</a></td></tr>
        <tr><td><p>Harbor Digital · United States (Remote)</p></td></tr>
        <tr><td><p>Actively recruiting</p></td></tr></tbody></table></a></td></tr>
        <tr><td><a href="https://www.linkedin.com/comm/jobs/view/202/?trk=logo"><img></a></td>
        <td><a href="https://www.linkedin.com/comm/jobs/view/202/?trk=card"><table><tbody>
        <tr><td><a href="https://www.linkedin.com/comm/jobs/view/202/?trk=title">Cloud Security Engineer</a></td></tr>
        <tr><td><p>Northstar Systems · Cincinnati, OH (Hybrid)</p></td></tr>
        <tr><td><p>Actively recruiting</p></td></tr></tbody></table></a></td></tr>
        </tbody></table>""",
        subtype="html",
    )
    jobs = collectors.import_eml(mail.as_bytes())
    assert [(j["url"], j["title"], j["company"], j["location"]) for j in jobs] == [
        (
            "https://www.linkedin.com/jobs/view/101/",
            "Information Security Analyst",
            "Harbor Digital",
            "United States (Remote)",
        ),
        (
            "https://www.linkedin.com/jobs/view/202/",
            "Cloud Security Engineer",
            "Northstar Systems",
            "Cincinnati, OH (Hybrid)",
        ),
    ]
    assert all(j["description_missing"] is True for j in jobs)
    assert "Northstar" not in jobs[0]["description"]
    assert "Harbor" not in jobs[1]["description"]


def test_greenhouse_support_links_are_not_job_opportunities():
    mail = EmailMessage()
    mail["Subject"] = "Manage your job applications"
    mail.set_content(
        "Visit https://support.greenhouse.io/hc/en-us/articles/12345 or https://support.greenhouse.io/hc/en-us"
    )
    assert collectors.import_eml(mail.as_bytes()) == []


def test_card_call_to_action_does_not_replace_the_role_title():
    mail = EmailMessage()
    mail["Subject"] = "Your new job alerts"
    mail.set_content("HTML version")
    mail.add_alternative(
        '<article><a href="https://example.com/jobs/123">Security Engineer</a>'
        '<a href="https://example.com/jobs/123">View job</a></article>',
        subtype="html",
    )
    jobs = collectors.import_eml(mail.as_bytes())
    assert jobs[0]["title"] == "Security Engineer"


@pytest.mark.parametrize(
    "protected",
    [
        {"status": "applied"},
        {"status": "confirmed"},
        {"status": "prepared", "documents": {"resume": "saved.pdf"}},
        {"status": "needs_review", "uncertain": True},
        {"status": "needs_review", "attempts": 1},
        {
            "status": "needs_review",
            "browser_handoff": {"mode": "default_browser", "state": "opened"},
        },
    ],
)
def test_email_metadata_repair_preserves_application_work(tmp_path, protected):
    from jobpilot.store import Store

    store = Store(tmp_path / "email.sqlite")
    original = store.add_job(
        {
            "url": "https://example.com/jobs/123",
            "source": "email",
            "title": "Original title",
            "company": "Original Employer",
            "description": "Original posting",
            "alert_subject": "Your jobs",
            **protected,
        }
    )
    refreshed = store.add_job(
        {
            "url": original["url"],
            "source": "email",
            "alert_metadata_version": 1,
            "title": "Security Engineer",
            "company": "Corrected Employer",
            "description": "New alert card",
            "description_missing": True,
            "status": "needs_review",
            "alert_subject": "Your jobs",
        }
    )
    assert refreshed["id"] == original["id"]
    assert refreshed["title"] == original["title"]
    assert refreshed["company"] == original["company"]
    for key, value in protected.items():
        assert refreshed[key] == value


def test_email_metadata_repair_preserves_an_explicit_dashboard_skip(tmp_path):
    from jobpilot.store import Store

    store = Store(tmp_path / "email.sqlite")
    original = store.add_job(
        {
            "url": "https://example.com/jobs/123",
            "source": "email",
            "title": "Software Engineer",
            "company": "First Employer",
            "description": "Original whole-email digest. " * 5,
            "status": "skipped",
            "note": "Skipped in dashboard.",
        }
    )
    refreshed = store.add_job(
        {
            "url": original["url"],
            "source": "email",
            "alert_metadata_version": 1,
            "title": "Security Engineer",
            "company": "Corrected Employer",
            "description": "A corrected alert card.",
            "description_missing": True,
            "status": "needs_review",
            "note": "Full posting needs review.",
        }
    )
    assert refreshed["status"] == "skipped"
    assert refreshed["note"] == "Skipped in dashboard."
