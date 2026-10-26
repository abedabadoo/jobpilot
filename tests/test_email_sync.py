from email.message import EmailMessage

import pytest

from jobpilot import collectors


@pytest.fixture
def mailbox(monkeypatch):
    mail = EmailMessage()
    mail["Subject"] = "Security Engineer at Northstar Systems"
    mail.set_content(
        "Security Engineer at Northstar Systems https://www.linkedin.com/comm/jobs/view/12345/?trk=email"
    )
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

        def uid(self, command, *args):
            calls.append((command, *args))
            if command == "search":
                return "OK", [b"1 2"]
            return "OK", [(b"RFC822", mail.as_bytes())]

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
    assert all(call[-1] == "(BODY.PEEK[])" for call in mailbox if call[0] == "fetch")


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
