import pytest

from jobpilot import links


def test_link_uses_existing_default_browser_and_preserves_job_url(monkeypatch):
    opened = []
    monkeypatch.setattr(links.os, "startfile", opened.append, raising=False)
    monkeypatch.setattr(links, "_windows", lambda: True)
    url = "https://www.linkedin.com/jobs/view/123456/?currentJobId=123456"
    result = links.open_external_url(url)
    assert opened == [url]
    assert result["opened"] is True
    assert result["url"] == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/system.ini",
        "javascript:alert(1)",
        "http://localhost/",
        "http://127.0.0.1/",
        "https://user:password@example.com/jobs/1",
        "https://example.com/\nunsafe",
    ],
)
def test_external_link_rejects_invalid_targets_before_opening(url, monkeypatch):
    monkeypatch.setattr(
        links.os, "startfile", lambda value: pytest.fail("Invalid link opened"), raising=False
    )
    with pytest.raises(ValueError):
        links.open_external_url(url)


def test_link_validation_never_waits_for_dns(monkeypatch):
    monkeypatch.setattr(links, "_windows", lambda: True)
    monkeypatch.setattr(links.os, "startfile", lambda value: None, raising=False)
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *args: pytest.fail("Link opening must not resolve DNS")
    )
    assert links.open_external_url("https://careers.example.com/jobs/42")["opened"]
