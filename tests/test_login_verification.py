"""Authentication evidence and login-close lifecycle, without external login."""

import threading

import playwright.sync_api
import pytest

from jobpilot import browser


@pytest.fixture
def page():
    with playwright.sync_api.sync_playwright() as runtime:
        chromium = runtime.chromium.launch(headless=True)
        context = chromium.new_context(service_workers="block")
        context.route(
            "**/*",
            lambda route: route.fulfill(
                body="<html><body><main>Fixture page</main></body></html>", content_type="text/html"
            ),
        )
        tab = context.new_page()
        yield tab
        context.close()
        chromium.close()


def linkedin_cookie(page, value="fixture-only-session"):
    page.context.add_cookies(
        [
            {
                "name": "li_at",
                "value": value,
                "domain": ".linkedin.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            }
        ]
    )


def test_generic_url_change_does_not_verify_login(page):
    page.goto("https://employer.example/dashboard")
    assert browser._login_verified(page, "employer", "https://employer.example/login") is False


@pytest.mark.parametrize(
    "control", ['<a href="/logout">Sign out</a>', '<button aria-label="Log out">Account</button>']
)
def test_visible_signout_control_verifies_target_session(page, control):
    page.goto("https://employer.example/dashboard")
    page.set_content(control)
    assert browser._login_verified(page, "employer", "https://employer.example/login") is True


def test_hidden_logout_control_does_not_verify_session(page):
    page.goto("https://employer.example/dashboard")
    page.set_content('<a href="/logout" style="display:none">Log out</a>')
    assert browser._login_verified(page, "employer", "https://employer.example/login") is False


def test_other_origin_signout_does_not_verify_requested_employer(page):
    page.goto("https://other.example/dashboard")
    page.set_content("<button>Sign out</button>")
    assert browser._login_verified(page, "employer", "https://employer.example/login") is False


def test_linkedin_feed_without_session_cookie_is_not_verified(page):
    page.goto("https://www.linkedin.com/feed/")
    assert browser._login_verified(page, "linkedin", "https://www.linkedin.com/login") is False


def test_linkedin_own_session_cookie_and_feed_verify_login(page):
    linkedin_cookie(page)
    page.goto("https://www.linkedin.com/feed/")
    assert browser._login_verified(page, "linkedin", "https://www.linkedin.com/login") is True


def test_linkedin_cookie_on_login_url_does_not_verify_login(page):
    linkedin_cookie(page)
    page.goto("https://www.linkedin.com/login")
    assert browser._login_verified(page, "linkedin", "https://www.linkedin.com/login") is False


def test_linkedin_empty_cookie_does_not_verify_login(page):
    linkedin_cookie(page, "")
    page.goto("https://www.linkedin.com/feed/")
    assert browser._login_verified(page, "linkedin", "https://www.linkedin.com/login") is False


@pytest.mark.parametrize(
    "challenge",
    [
        '<label>Password<input type="password"></label>',
        "<h1>Enter the verification code</h1>",
        "<h1>Request Blocked</h1><p>You have been blocked.</p>",
        '<div class="g-recaptcha">Verify you are human</div>',
    ],
)
def test_linkedin_session_cookie_does_not_override_visible_auth_challenge(page, challenge):
    linkedin_cookie(page)
    page.goto("https://www.linkedin.com/feed/")
    page.set_content(challenge + '<a href="/logout">Sign out</a>')
    assert browser._login_verified(page, "linkedin", "https://www.linkedin.com/login") is False


def test_unrelated_site_cannot_verify_linkedin_login(page):
    linkedin_cookie(page)
    page.goto("https://other.example/feed/")
    page.set_content("<button>Log out</button>")
    assert browser._login_verified(page, "linkedin", "https://www.linkedin.com/login") is False


@pytest.fixture
def controlled_login(monkeypatch):
    """Replace browser transport, leaving open_login's thread/lock real."""
    session = {"polls": 0, "proof": [False], "closed": False}

    class Page:
        url = ""

        def goto(self, url, **kwargs):
            self.url = url

        def is_closed(self):
            return session["closed"]

        def wait_for_timeout(self, ms):
            session["polls"] += 1
            if session["polls"] >= len(session["proof"]):
                session["closed"] = True
                context.pages = []

    class Context:
        def __init__(self):
            self.pages = [Page()]

        def close(self):
            session["closed"] = True
            self.pages = []

    class Manager:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            pass

    context = Context()
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: Manager())
    monkeypatch.setattr(browser, "_launch", lambda *args: context)
    monkeypatch.setattr(browser, "validate_public_url", lambda url, **kwargs: url)
    monkeypatch.setattr(
        browser,
        "_login_verified",
        lambda *args: session["proof"][min(session["polls"], len(session["proof"]) - 1)],
        raising=False,
    )
    yield session
    thread = browser._login_threads.get("linkedin")
    if thread:
        thread.join(2)


def test_login_close_callback_is_once_after_lock_release(controlled_login):
    controlled_login["proof"] = [True]
    done, callbacks = threading.Event(), []

    def callback(payload):
        acquired = browser._session_lock.acquire(blocking=False)
        if acquired:
            browser._session_lock.release()
        callbacks.append((payload, acquired))
        done.set()

    browser.open_login("linkedin", on_closed=callback)
    assert done.wait(2)
    assert callbacks == [
        ({"platform": "linkedin", "url": "https://www.linkedin.com/login", "verified": True}, True)
    ]


def test_login_close_without_proof_is_unverified(controlled_login):
    done, callbacks = threading.Event(), []
    browser.open_login(
        "linkedin", on_closed=lambda payload: (callbacks.append(payload), done.set())
    )
    assert done.wait(2)
    assert len(callbacks) == 1
    assert callbacks[0]["verified"] is False


def test_verification_observed_while_open_is_retained_after_later_unverified_page(controlled_login):
    controlled_login["proof"] = [True, False]
    done, callbacks = threading.Event(), []
    browser.open_login(
        "linkedin", on_closed=lambda payload: (callbacks.append(payload), done.set())
    )
    assert done.wait(2)
    assert callbacks[0]["verified"] is True


def test_callback_exception_never_leaves_session_lock_held(controlled_login):
    called = threading.Event()

    def callback(payload):
        called.set()
        raise RuntimeError("fixture recording failure")

    browser.open_login("linkedin", on_closed=callback)
    assert called.wait(2)
    browser._login_threads["linkedin"].join(2)
    assert browser._session_lock.acquire(blocking=False)
    browser._session_lock.release()


def test_browser_launch_failure_closes_unverified_after_lock_release(controlled_login, monkeypatch):
    def fail(*args):
        raise RuntimeError("fixture browser missing")

    monkeypatch.setattr(browser, "_launch", fail)
    done, callbacks = threading.Event(), []
    result = browser.open_login(
        "linkedin", on_closed=lambda payload: (callbacks.append(payload), done.set())
    )
    assert result["status"] == "error"
    assert done.wait(2)
    assert callbacks[0]["verified"] is False
    assert browser._session_lock.acquire(blocking=False)
    browser._session_lock.release()
