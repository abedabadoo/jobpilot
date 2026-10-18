"""Real Chromium checks for volatile auxiliary frames and challenge semantics."""

import html

import pytest
from playwright.sync_api import sync_playwright

from jobpilot import browser

APPLICATION = (
    '<form id="application"><label>Email<input name="email" type="email"></label>'
    '<label>Resume<input name="resume" type="file"></label>'
    "<button>Submit application</button></form>"
)


@pytest.fixture
def page():
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(headless=True)
        context = chromium.new_context()
        tab = context.new_page()
        tab.set_default_timeout(1000)
        yield tab
        context.close()
        chromium.close()


class FrameSnapshot:
    """Keep the actual old frame object to model a frame-list race."""

    def __init__(self, page, frames):
        self.page, self.old_frames = page, frames
        self.reads = 0

    @property
    def frames(self):
        self.reads += 1
        return self.old_frames if self.reads == 1 else self.page.frames

    def __getattr__(self, name):
        return getattr(self.page, name)


def test_scope_skips_detached_auxiliary_frame_and_preserves_application(page):
    page.set_content(APPLICATION + '<iframe id="aux" srcdoc="<p>Auxiliary widget</p>"></iframe>')
    old_frames = list(page.frames)
    page.locator("#aux").evaluate("el => el.remove()")
    assert old_frames[-1].is_detached()
    scope = browser._scope(FrameSnapshot(page, old_frames))
    assert scope is not None
    assert scope.get_attribute("id") == "application"


def test_challenge_skips_detached_auxiliary_frame_without_losing_login_wall(page):
    page.set_content(
        '<h1>Sign in to apply</h1><input type="password" required>'
        '<iframe id="aux" srcdoc="<p>Auxiliary widget</p>"></iframe>'
    )
    old_frames = list(reversed(page.frames))
    page.locator("#aux").evaluate("el => el.remove()")
    reason = browser._challenge(FrameSnapshot(page, old_frames))
    assert reason and "login" in reason.lower()


def test_scope_retries_when_frame_detaches_during_scan_and_is_replaced(page):
    page.set_content('<iframe id="aux" srcdoc="<p>Old widget</p>"></iframe>')
    original = page.frames[-1]

    class ReplacingFrame:
        def __getattr__(self, name):
            return getattr(original, name)

        def locator(self, selector):
            page.locator("#aux").evaluate("el => el.remove()")
            page.evaluate(
                'content => {const f=document.createElement("iframe");'
                " f.srcdoc=content; document.body.appendChild(f)}",
                APPLICATION,
            )
            page.wait_for_timeout(75)
            return original.locator(selector)

    scope = browser._scope(FrameSnapshot(page, [page.main_frame, ReplacingFrame()]))
    assert scope is not None
    assert scope.get_attribute("id") == "application"


def test_scope_does_not_treat_newsletter_as_application(page):
    page.set_content(
        '<form><label>Email<input type="email"></label><button>Subscribe</button></form>'
    )
    assert browser._scope(page) is None


def test_scope_chooses_embedded_application_over_newsletter(page):
    page.set_content(
        '<form><label>Email<input type="email"></label><button>Subscribe</button></form>'
        f'<iframe srcdoc="{html.escape(APPLICATION, quote=True)}"></iframe>'
    )
    scope = browser._scope(page)
    assert scope is not None
    assert scope.get_attribute("id") == "application"


def test_scope_ignores_hidden_inactive_application_frame(page):
    hidden = (
        APPLICATION.replace('id="application"', 'id="inactive"')
        + '<input type="file"><input type="file">'
    )
    page.set_content(
        APPLICATION
        + f'<iframe style="display:none" srcdoc="{html.escape(hidden, quote=True)}"></iframe>'
    )
    assert browser._scope(page).get_attribute("id") == "application"


def test_scope_waits_for_delayed_employer_application_iframe(page):
    page.set_content(
        '<h1>Security Engineer</h1><div id="application-loading">Loading application</div>'
    )
    page.evaluate(
        'content => setTimeout(() => {const f=document.createElement("iframe");'
        " f.srcdoc=content; document.body.appendChild(f)}, 2200)",
        APPLICATION,
    )
    scope = browser._scope(page)
    assert scope is not None
    assert scope.get_attribute("id") == "application"


def test_post_entry_scope_can_wait_even_when_apply_link_remains_visible(page):
    page.set_content('<h1>Security Engineer</h1><a href="#application">Apply now</a>')
    page.evaluate(
        'content => setTimeout(() => {const f=document.createElement("iframe");'
        " f.srcdoc=content; document.body.appendChild(f)}, 500)",
        APPLICATION,
    )
    scope = browser._scope(page, timeout_ms=2000, stop_on_entry=False)
    assert scope is not None
    assert scope.get_attribute("id") == "application"


def test_passive_captcha_integration_does_not_block_fillable_application(page):
    page.set_content(
        APPLICATION + '<div class="g-recaptcha" data-sitekey="fixture" data-size="invisible">'
        "protected by reCAPTCHA</div>"
    )
    assert browser._challenge(page) is None


def test_invisible_captcha_badge_frame_does_not_block_fillable_application(page):
    url = "https://www.google.com/recaptcha/api2/anchor?size=invisible"
    page.context.route(
        url,
        lambda route: route.fulfill(
            body="<html><body>Privacy - Terms</body></html>", content_type="text/html"
        ),
    )
    page.set_content(
        APPLICATION + f'<iframe title="reCAPTCHA" src="{url}" width="256" height="60"></iframe>'
    )
    assert browser._challenge(page) is None


def test_active_captcha_checkbox_still_requires_review(page):
    url = "https://www.google.com/recaptcha/api2/anchor?size=normal"
    page.context.route(
        url,
        lambda route: route.fulfill(
            body='<label><input type="checkbox">I am not a robot</label>', content_type="text/html"
        ),
    )
    page.set_content(
        APPLICATION + f'<iframe title="reCAPTCHA" src="{url}" width="300" height="78"></iframe>'
    )
    reason = browser._challenge(page)
    assert reason and "captcha" in reason.lower()


def test_active_cloudflare_checkbox_requires_review(page):
    url = "https://challenges.cloudflare.com/turnstile/v0/widget"
    page.context.route(
        url,
        lambda route: route.fulfill(
            body='<label><input type="checkbox">Verify you are human</label>',
            content_type="text/html",
        ),
    )
    page.set_content(APPLICATION + f'<iframe src="{url}" width="300" height="65"></iframe>')
    reason = browser._challenge(page)
    assert reason and "captcha" in reason.lower()


def test_passive_cloudflare_integration_does_not_block(page):
    page.set_content(
        APPLICATION
        + '<div class="cf-turnstile" data-size="invisible">Protected by Cloudflare</div>'
    )
    assert browser._challenge(page) is None


def test_application_email_security_code_requires_review(page):
    page.set_content(
        APPLICATION
        + "<p>A verification code was sent to jordan.morgan@example.com. To submit your application, enter the 8-character code to confirm you are human.</p>"
        '<label>Security code<input maxlength="1" autocomplete="one-time-code"></label>'
    )
    assert browser._challenge(page) == "Email verification requires your review"


def test_security_code_example_without_active_code_control_does_not_block(page):
    page.set_content(
        APPLICATION
        + "<p>Training example: A verification code was sent to a user. To submit an application, enter the code.</p>"
    )
    assert browser._challenge(page) is None


def test_active_captcha_image_challenge_still_requires_review(page):
    url = "https://www.google.com/recaptcha/api2/bframe"
    page.context.route(
        url,
        lambda route: route.fulfill(
            body="<h2>Select all images with bridges</h2>", content_type="text/html"
        ),
    )
    page.set_content(
        APPLICATION + f'<iframe title="reCAPTCHA" src="{url}" width="400" height="400"></iframe>'
    )
    reason = browser._challenge(page)
    assert reason and "captcha" in reason.lower()


def test_actual_login_wall_still_requires_review(page):
    page.set_content(
        '<h1>Login</h1><form><label>Email<input type="email"></label>'
        '<label>Password<input type="password" required></label><button>Log in</button></form>'
    )
    reason = browser._challenge(page)
    assert reason and "login" in reason.lower()


def test_optional_sidebar_login_does_not_block_guest_application(page):
    page.set_content(
        APPLICATION + '<aside><form><label>Password<input type="password"></label>'
        "<button>Sign in</button></form></aside>"
    )
    assert browser._challenge(page) is None


def test_blocking_login_modal_requires_review_even_with_application_behind_it(page):
    page.set_content(
        APPLICATION + '<div role="dialog" aria-modal="true"><h2>Sign in</h2>'
        '<input type="password" required></div>'
    )
    reason = browser._challenge(page)
    assert reason and "login" in reason.lower()


def test_job_description_about_two_factor_authentication_is_not_a_challenge(page):
    page.set_content(
        "<article><h1>Security Engineer</h1><p>Implement two-factor authentication "
        "and security verification for our customers.</p></article>" + APPLICATION
    )
    assert browser._challenge(page) is None


def test_real_request_block_page_gets_explicit_review_reason(page):
    page.set_content("<h1>Request Blocked</h1><p>You have been blocked. Contact support.</p>")
    reason = browser._challenge(page)
    assert reason and "blocked" in reason.lower()


def test_closed_page_has_no_application_scope(page):
    page.close()
    assert browser._scope(page) is None


def test_closed_page_has_review_reason_instead_of_frame_error(page):
    page.close()
    reason = browser._challenge(page)
    assert reason and "closed" in reason.lower()
