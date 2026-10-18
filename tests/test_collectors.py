import json
from email.message import EmailMessage

import pytest

from jobpilot import collectors


def test_alert_deduplicates_job_links_without_inventing_posted_date():
    mail = EmailMessage()
    mail["Date"] = "Mon, 12 Oct 2026 08:00:00 -0400"
    mail["Subject"] = "Security jobs for you"
    mail.set_content(
        "Security Engineer https://www.linkedin.com/jobs/view/12345/\n"
        "https://www.linkedin.com/jobs/view/12345/?trackingId=abc\n"
        "https://example.com/unsubscribe"
    )
    jobs = collectors.import_eml(mail.as_string())
    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://www.linkedin.com/jobs/view/12345/"
    assert jobs[0]["posted_at"] is None
    assert jobs[0]["source"] == "email"


def test_alert_extracts_html_title_and_ignores_private_link():
    mail = EmailMessage()
    mail.set_content("Open the HTML version")
    mail.add_alternative(
        '<a href="https://jobs.lever.co/acme/abc">Cloud Security Engineer</a>'
        '<a href="http://127.0.0.1/jobs/secret">Private</a>',
        subtype="html",
    )
    jobs = collectors.import_eml(mail.as_string())
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Cloud Security Engineer"


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/system.ini",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/",
        "http://[::1]/",
        "https://user:password@example.com/jobs/1",
    ],
)
def test_imported_url_rejects_local_and_credential_targets(url):
    with pytest.raises(ValueError):
        collectors.fetch_job(url)


def test_fetch_job_parses_nested_jsonld(monkeypatch):
    posting = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "JobPosting",
                "title": "Security Engineer",
                "datePosted": "2026-10-11",
                "hiringOrganization": {"name": "Acme"},
                "jobLocation": {
                    "address": {"addressLocality": "Cincinnati", "addressRegion": "OH"}
                },
                "description": "<p>Secure our cloud.</p>",
            }
        ],
    }
    monkeypatch.setattr(
        collectors,
        "_get_public",
        lambda url: (
            '<script type="application/ld+json">' + json.dumps(posting) + "</script>",
            url,
        ),
    )
    job = collectors.fetch_job("https://example.com/jobs/1")
    assert job["title"] == "Security Engineer"
    assert job["company"] == "Acme"
    assert job["location"] == "Cincinnati, OH"
    assert job["posted_at"] == "2026-10-11"
    assert job["description"] == "Secure our cloud."


def test_email_configuration_never_returns_password(monkeypatch):
    secrets = {}
    monkeypatch.setattr(
        collectors.keyring,
        "set_password",
        lambda service, account, secret: secrets.update({account: secret}),
    )
    monkeypatch.setattr(collectors, "_validate_host", lambda host: None)
    config = collectors.configure_email(
        {
            "host": "imap.example.com",
            "username": "jordan.morgan@example.com",
            "password": "private-app-password",
            "enabled": True,
        }
    )
    assert "password" not in config
    assert "private-app-password" not in json.dumps(config)
    assert list(secrets.values()) == ["private-app-password"]
    assert config["credential_saved"] is True


def test_failed_source_does_not_remove_other_source_jobs(monkeypatch):
    def search(**kwargs):
        if kwargs["site_name"] == ["linkedin"]:
            raise RuntimeError("Source blocked")
        return [
            {
                "site": "indeed",
                "job_url": "https://www.indeed.com/viewjob?jk=abc",
                "title": "Security Engineer",
                "company": "Acme",
                "location": "Remote",
                "description": "Protect systems",
                "date_posted": None,
            }
        ]

    monkeypatch.setattr(collectors, "_jobspy_search", search)
    jobs = collectors.discover(
        {
            "sources": ["linkedin", "indeed"],
            "target_roles": ["Security Engineer"],
            "locations": ["Remote"],
            "ats_boards": [],
            "email": {},
        },
        {},
    )
    assert len(jobs) == 1
    assert jobs[0]["company"] == "Acme"
    assert collectors.get_last_errors()[0]["source"] == "linkedin"


def test_ashby_public_board_keeps_missing_date_unknown(monkeypatch):
    data = {
        "jobs": [
            {
                "id": "abc",
                "title": "GRC Analyst",
                "location": "Remote",
                "jobUrl": "https://jobs.ashbyhq.com/acme/abc",
                "descriptionPlain": "Manage risk",
                "isListed": True,
            }
        ]
    }
    monkeypatch.setattr(collectors, "_get_public", lambda url: (json.dumps(data), url))
    jobs = collectors.discover(
        {"sources": [], "ats_boards": [{"source": "ashby", "board": "acme"}], "email": {}}, {}
    )
    assert len(jobs) == 1
    assert jobs[0]["posted_at"] is None
    assert jobs[0]["source"] == "ashby"


def test_jobspy_nan_direct_url_falls_back_to_board_url(monkeypatch):
    monkeypatch.setattr(
        collectors,
        "_jobspy_search",
        lambda **kwargs: [
            {
                "job_url_direct": float("nan"),
                "job_url": "https://www.indeed.com/viewjob?jk=abc",
                "title": "Security Engineer",
                "company": "Acme",
                "location": "Remote",
                "description": "Protect systems",
                "date_posted": None,
            }
        ],
    )
    jobs = collectors.discover(
        {"sources": ["indeed"], "target_roles": ["Engineer"], "locations": ["Remote"]}, {}
    )
    assert jobs[0]["url"] == "https://www.indeed.com/viewjob?jk=abc"


def test_jobspy_preserves_source_and_verified_direct_application_route(monkeypatch):
    monkeypatch.setattr(collectors, "_validate_host", lambda host: None)
    monkeypatch.setattr(
        collectors,
        "_jobspy_search",
        lambda **kwargs: [
            {
                "job_url_direct": "https://example.com/careers/123",
                "job_url": "https://www.linkedin.com/jobs/view/123/",
                "title": "Security Engineer",
                "company": "Acme",
                "description": "Protect systems",
            }
        ],
    )
    jobs = collectors.discover(
        {"sources": ["linkedin"], "target_roles": ["Engineer"], "locations": ["Remote"]}, {}
    )
    assert jobs[0]["url"] == "https://example.com/careers/123"
    assert jobs[0]["apply_url"] == jobs[0]["url"]
    assert jobs[0]["source_url"] == "https://www.linkedin.com/jobs/view/123/"


def test_private_direct_route_is_not_retained(monkeypatch):
    original = collectors._validate_host
    monkeypatch.setattr(
        collectors,
        "_validate_host",
        lambda host: None if host == "www.linkedin.com" else original(host),
    )
    monkeypatch.setattr(
        collectors,
        "_jobspy_search",
        lambda **kwargs: [
            {
                "job_url_direct": "http://127.0.0.1/secret",
                "job_url": "https://www.linkedin.com/jobs/view/123/",
                "title": "Security Engineer",
                "company": "Acme",
                "description": "Protect systems",
            }
        ],
    )
    jobs = collectors.discover(
        {"sources": ["linkedin"], "target_roles": ["Engineer"], "locations": ["Remote"]}, {}
    )
    assert jobs[0]["url"] == "https://www.linkedin.com/jobs/view/123/"
    assert not jobs[0].get("apply_url")


def test_public_fetch_checks_redirect_before_connecting(monkeypatch):
    class Response:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/secret"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class Session:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            assert url == "https://example.com/jobs/1"
            return Response()

    monkeypatch.setattr(collectors.requests, "Session", Session)
    original = collectors._validate_host
    monkeypatch.setattr(
        collectors, "_validate_host", lambda host: None if host == "example.com" else original(host)
    )
    with pytest.raises(ValueError):
        collectors._get_public("https://example.com/jobs/1")
