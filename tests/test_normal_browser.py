"""Human handoff uses the normal browser without sharing worker profiles."""

import socket
import webbrowser

import pytest

from jobpilot import browser


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )


def test_windows_handoff_dispatches_exact_url_without_playwright_or_profile_lock(monkeypatch):
    calls = []
    url = "https://careers.example.com/jobs/123/apply?source=jobpilot"
    monkeypatch.setattr(browser.os, "startfile", lambda value: calls.append(value), raising=False)
    monkeypatch.setattr(
        browser, "_launch", lambda *args, **kwargs: pytest.fail("No isolated browser should launch")
    )
    monkeypatch.setattr(
        browser, "_data_dir", lambda *args: pytest.fail("No profile should be accessed")
    )
    monkeypatch.setattr(
        webbrowser,
        "open_new_tab",
        lambda *args: pytest.fail("Windows must use its URL association"),
    )
    assert browser._session_lock.acquire(blocking=False)
    try:
        with monkeypatch.context() as platform:
            platform.setattr(browser.os, "name", "nt")
            result = browser.open_browser_tab(url)
    finally:
        browser._session_lock.release()
    assert calls == [url]
    assert result["status"] == "opened"
    assert result["mode"] == "default_browser"
    assert result["receipt_tracking"] == "manual"
    assert result["url"] == url
    assert "default browser" in result["note"]
    assert "receipt" in result["note"].lower()


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Users/Example/private.txt",
        "javascript:alert(1)",
        "https://user:password@careers.example.com/jobs/1",
        "http://127.0.0.1/jobs/1",
        "http://192.168.1.1/jobs/1",
        "https://localhost/jobs/1",
    ],
)
def test_invalid_or_private_urls_never_reach_an_os_dispatcher(monkeypatch, url):
    monkeypatch.setattr(
        browser.os,
        "startfile",
        lambda *args: pytest.fail("Rejected URL reached Windows"),
        raising=False,
    )
    monkeypatch.setattr(
        webbrowser, "open_new_tab", lambda *args: pytest.fail("Rejected URL reached a browser")
    )
    result = browser.open_browser_tab(url)
    assert result["status"] == "error"


def test_windows_dispatch_failure_does_not_claim_a_tab_opened(monkeypatch):
    def fail(_url):
        raise OSError("No default browser is registered")

    monkeypatch.setattr(browser.os, "startfile", fail, raising=False)
    with monkeypatch.context() as platform:
        platform.setattr(browser.os, "name", "nt")
        result = browser.open_browser_tab("https://careers.example.com/jobs/1")
    assert result["status"] == "error"
    assert "No default browser is registered" in result["note"]


@pytest.mark.parametrize("accepted", [True, False])
def test_non_windows_dispatch_requires_browser_acceptance(monkeypatch, accepted):
    calls = []
    url = "https://careers.example.com/jobs/1"
    monkeypatch.setattr(webbrowser, "open_new_tab", lambda value: calls.append(value) or accepted)
    monkeypatch.setattr(
        browser.os,
        "startfile",
        lambda *args: pytest.fail("Non-Windows must use webbrowser"),
        raising=False,
    )
    with monkeypatch.context() as platform:
        platform.setattr(browser.os, "name", "posix")
        result = browser.open_browser_tab(url)
    assert calls == [url]
    assert result["status"] == ("opened" if accepted else "error")
