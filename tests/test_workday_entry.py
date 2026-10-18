"""Workday entry fixtures intercept every request; no employer is contacted."""

import json

import pytest
from playwright.sync_api import sync_playwright

from jobpilot import browser

WORKDAY_URL = "https://fixture.myworkdayjobs.com/en-US/Careers/job/security/apply"
APPLICATION = (
    '<form id="application" method="post" action="/submitted">'
    '<label>Email<input name="email" type="email" required></label>'
    '<label>Resume<input name="resume" type="file"></label>'
    '<button type="submit">Submit application</button></form>'
)


def entry(
    button_type="button",
    automation="applyManually",
    caption="Apply Manually",
    target="/application",
):
    return (
        "<h1>Security Engineer</h1>"
        '<button type="button" data-automation-id="autofillWithResume" '
        "onclick=\"fetch('/autofill',{method:'POST'})\">Autofill with Resume</button>"
        f'<button type="{button_type}" data-automation-id="{automation}" '
        f"onclick=\"location.href='{target}'\">{caption}</button>"
    )


def route_fixture(context, markup, form=APPLICATION, application_url="/application"):
    requests = []

    def route(request):
        method = request.request.method
        requests.append((method, request.request.url))
        body = form if application_url in request.request.url else markup
        request.fulfill(status=200, content_type="text/html", body=body)

    context.route("**/*", route)
    return requests


@pytest.fixture
def page():
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(headless=True)
        context = chromium.new_context()
        page = context.new_page()
        page.set_default_timeout(1000)
        yield page
        context.close()
        chromium.close()


def test_workday_manual_entry_opens_form_without_submission_or_autofill(page, tmp_path):
    requests = route_fixture(page.context, entry())
    page.goto(WORKDAY_URL)
    result = {"status": "needs_review", "submitted": False, "evidence": []}
    returned, note = browser._enter_application(page, "employer", {}, result, None, tmp_path, 1)
    assert returned.url == "https://fixture.myworkdayjobs.com/application"
    assert browser._scope(returned).get_attribute("id") == "application"
    assert note is None
    assert result["submitted"] is False
    assert not [request for request in requests if request[0] != "GET"]


def test_actual_workday_manual_anchor_navigates_href_without_click_handlers(
    page, tmp_path, monkeypatch
):
    destination = WORKDAY_URL + "/applyManually"
    markup = (
        "<h1>Security Engineer</h1>"
        f'<a role="button" data-automation-id="applyManually" href="{destination}" '
        "onclick=\"fetch('/unexpected-submit',{method:'POST'})\">Apply Manually</a>"
    )
    requests = route_fixture(page.context, markup, application_url="/apply/applyManually")
    # Public URL validation has separate tests; the fake host is entirely intercepted here.
    monkeypatch.setattr(browser, "validate_public_url", lambda url, **kwargs: url)
    page.goto(WORKDAY_URL)
    assert page.locator('[data-automation-id="applyManually"]').evaluate("el => el.tagName") == "A"
    result = {"status": "needs_review", "submitted": False, "evidence": []}
    returned, note = browser._enter_application(page, "employer", {}, result, None, tmp_path, 1)
    assert returned.url == destination
    assert browser._scope(returned).get_attribute("id") == "application"
    assert note is None
    assert result["submitted"] is False
    assert not [request for request in requests if request[0] != "GET"]


@pytest.mark.parametrize(
    ("url", "markup"),
    [
        ("https://careers.example.com/job", entry()),
        ("https://fixture.myworkdayjobs.com.evil.example/job", entry()),
        (WORKDAY_URL, entry(automation="otherApply")),
        (WORKDAY_URL, entry(caption="Autofill with Resume")),
    ],
)
def test_manual_entry_lookalikes_are_not_clicked(page, tmp_path, url, markup):
    requests = route_fixture(page.context, markup)
    page.goto(url)
    result = {"status": "needs_review", "submitted": False, "evidence": []}
    browser._enter_application(page, "employer", {}, result, None, tmp_path, 1)
    assert page.url == url
    assert not [request for request in requests if request[0] != "GET"]
    assert result["submitted"] is False


def test_submit_type_workday_manual_entry_is_held(page, tmp_path):
    requests = route_fixture(page.context, entry(button_type="submit"))
    page.goto(WORKDAY_URL)
    result = {"status": "needs_review", "submitted": False, "evidence": []}
    _, note = browser._enter_application(page, "employer", {}, result, None, tmp_path, 1)
    assert page.url == WORKDAY_URL
    assert note and "review" in note.lower()
    assert result["submitted"] is False
    assert not [request for request in requests if request[0] != "GET"]


@pytest.mark.parametrize(
    ("application", "expected_note"),
    [
        (APPLICATION, "checkpoint missing"),
        (
            APPLICATION.replace(
                '<button type="submit">',
                '<label>Will you require sponsorship?<select name="sponsorship" required>'
                '<option value="">Choose</option><option>Yes</option><option>No</option></select></label>'
                '<button type="submit">',
            ),
            "saved answers",
        ),
        ('<h1>Sign in to apply</h1><input type="password" required>', "Login"),
    ],
)
def test_workday_entry_stops_at_final_submit_unknowns_or_login(
    tmp_path, monkeypatch, application, expected_note
):
    requests = []
    launch = browser._launch

    def fixture_launch(playwright, settings, platform, headless):
        context = launch(playwright, settings, platform, headless)
        observed = route_fixture(context, entry(), application)
        # Keep the same list updated by the intercepted request handler.
        requests.append(observed)
        return context

    monkeypatch.setattr(browser, "_launch", fixture_launch)
    # Validation is covered separately; all fixture network requests are fulfilled locally.
    monkeypatch.setattr(browser, "validate_public_url", lambda url, **kwargs: url)
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture")
    result = browser.apply(
        {"id": 1, "url": WORKDAY_URL, "source": "employer"},
        {"name": "Fixture Candidate", "email": "fixture@example.com"},
        {},
        {"resume_pdf": str(resume)},
        {"data_dir": str(tmp_path / "data"), "_fixture_mode": True, "browser_headless": True},
        checkpoint=None,
    )
    assert result["status"] == "needs_review", json.dumps(result)
    assert expected_note.casefold() in result["note"].casefold()
    assert result["submitted"] is False
    assert not [request for batch in requests for request in batch if request[0] != "GET"]
