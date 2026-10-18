import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from jobpilot import browser


@pytest.fixture
def site():
    state = {"posts": [], "page": ""}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(state.get("pages", {}).get(self.path, state["page"]).encode())

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            state["posts"].append(raw)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                state.get("receipt", "<h1>Your application has been received.</h1>").encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/jobs/1"
    yield state
    server.shutdown()
    server.server_close()


def form(extra=""):
    return (
        '<form method="post" enctype="multipart/form-data">'
        '<label>Full name<input name="name" required></label>'
        '<label>Email<input type="email" name="email" required></label>'
        '<label>Resume<input type="file" name="resume" required></label>'
        + extra
        + '<button type="submit">Submit application</button></form>'
    )


def run(site, tmp_path, answers=None, checkpoint=lambda info: None):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture-resume")
    return browser.apply(
        {"id": 1, "url": site["url"], "source": "employer", "title": "Engineer"},
        {"name": "Jordan Morgan", "email": "jordan.morgan@example.com", "phone": "+1 202 555 0142"},
        answers or {},
        {"resume_pdf": str(resume)},
        {
            "data_dir": str(tmp_path / "data"),
            "_fixture_mode": True,
            "browser_headless": True,
            "receipt_wait_seconds": 0.6,
        },
        checkpoint,
    )


def test_fills_contact_uploads_resume_and_requires_positive_receipt(site, tmp_path):
    site["page"] = form()
    checkpoints = []
    result = run(
        site, tmp_path, checkpoint=lambda info: checkpoints.append((info, len(site["posts"])))
    )
    assert result["status"] == "confirmed"
    assert result["submitted"] is True
    assert len(site["posts"]) == 1
    assert b"Jordan Morgan" in site["posts"][0]
    assert b"fixture-resume" in site["posts"][0]
    assert checkpoints[0][1] == 0
    assert checkpoints[0][0]["url"] == site["url"]
    assert all(Path(path).is_file() for path in result["evidence"])


def test_cookie_overlay_declines_optional_tracking_before_application(site, tmp_path):
    site["page"] = (
        form()
        + """<div role="dialog" aria-label="Cookie Consent" data-ui="cookie-consent"
      style="position:fixed;inset:0;background:white;z-index:999">
      <p>This website uses cookies</p><button onclick="this.parentElement.remove()">Decline all</button>
      <button onclick="throw Error('must not accept tracking')">Accept all</button></div>"""
    )
    result = run(site, tmp_path)
    assert result["status"] == "confirmed", result
    assert len(site["posts"]) == 1


def test_explicit_employer_application_url_precedes_source_login_wall(site, tmp_path):
    site["pages"] = {
        "/jobs/1": '<form><input type="password" required><button>Log in</button></form>',
        "/apply/1": form(),
    }
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture-resume")
    result = browser.apply(
        {
            "id": 1,
            "url": site["url"],
            "apply_url": site["url"].replace("/jobs/", "/apply/"),
            "source": "linkedin",
        },
        {"name": "Jordan Morgan", "email": "jordan.morgan@example.com"},
        {},
        {"resume_pdf": str(resume)},
        {
            "data_dir": str(tmp_path / "data"),
            "_fixture_mode": True,
            "browser_headless": True,
            "receipt_wait_seconds": 0.6,
        },
        lambda info: None,
    )
    assert result["status"] == "confirmed"
    assert len(site["posts"]) == 1


def test_unknown_required_screening_answer_blocks_submission(site, tmp_path):
    site["page"] = form(
        "<label>Are you legally authorized to work in the United States?"
        '<select required name="work_auth"><option value="">Choose</option>'
        "<option>Yes</option><option>No</option></select></label>"
    )
    result = run(site, tmp_path)
    assert result["status"] == "needs_review"
    assert result["submitted"] is False
    assert site["posts"] == []
    assert "authorized" in result["note"].lower()


def test_saved_exact_screening_answer_is_used(site, tmp_path):
    site["page"] = form(
        "<label>Are you legally authorized to work in the United States?"
        '<select required name="work_auth"><option value="">Choose</option>'
        "<option>Yes</option><option>No</option></select></label>"
    )
    result = run(site, tmp_path, {"Are you legally authorized to work in the United States?": "No"})
    assert result["status"] == "confirmed"
    assert b"\r\nNo\r\n" in site["posts"][0]


def test_unknown_required_consent_is_not_checked(site, tmp_path):
    site["page"] = form(
        '<label><input type="checkbox" name="agree" required>'
        "I consent to the terms and privacy policy</label>"
    )
    result = run(site, tmp_path)
    assert result["status"] == "needs_review"
    assert site["posts"] == []


def test_successful_click_without_receipt_is_uncertain_and_never_retried(site, tmp_path):
    site["page"] = form()
    site["receipt"] = "<h1>Please wait</h1>"
    result = run(site, tmp_path)
    assert result["status"] == "needs_review"
    assert result["submitted"] is True
    assert len(site["posts"]) == 1


def test_challenge_after_submit_is_recorded_without_claiming_receipt(site, tmp_path):
    site["page"] = form()
    site["receipt"] = '<h1>Submitting...</h1><div class="cf-turnstile">Verify you are human</div>'
    result = run(site, tmp_path)
    assert result["status"] == "needs_review", result
    assert result["submitted"] is True
    assert result["review_reason"] == "verification_required"
    assert "CAPTCHA" in result["note"]
    assert len(site["posts"]) == 1


def test_checkpoint_failure_prevents_submit(site, tmp_path):
    site["page"] = form()

    def checkpoint(info):
        raise RuntimeError("disk full")

    result = run(site, tmp_path, checkpoint=checkpoint)
    assert result["status"] == "error"
    assert result["submitted"] is False
    assert site["posts"] == []


def test_missing_checkpoint_fills_only(site, tmp_path):
    site["page"] = form()
    result = run(site, tmp_path, checkpoint=None)
    assert result["status"] == "needs_review"
    assert site["posts"] == []


def test_visible_captcha_blocks_submission(site, tmp_path):
    site["page"] = form('<div class="g-recaptcha">Verify you are human</div>')
    result = run(site, tmp_path)
    assert result["status"] == "needs_review"
    assert result["submitted"] is False
    assert site["posts"] == []


def test_production_browser_rejects_private_network_before_opening(tmp_path):
    result = browser.apply(
        {"url": "http://127.0.0.1/jobs/1"},
        {},
        {},
        {},
        {"data_dir": str(tmp_path)},
        checkpoint=lambda info: None,
    )
    assert result["status"] == "error"
    assert result["submitted"] is False


def test_prefilled_unknown_required_answer_still_requires_review(site, tmp_path):
    site["page"] = form(
        '<label>Expected annual salary<input required name="salary" value="50000"></label>'
    )
    result = run(site, tmp_path)
    assert result["status"] == "needs_review", result
    assert result["submitted"] is False
    assert site["posts"] == []


def test_exact_saved_consent_can_be_checked(site, tmp_path):
    site["page"] = form(
        '<label><input type="checkbox" name="agree" required>'
        "I consent to the terms and privacy policy</label>"
    )
    result = run(site, tmp_path, {"I consent to the terms and privacy policy": True})
    assert result["status"] == "confirmed", result
    assert b'name="agree"' in site["posts"][0]


def test_sensitive_question_cannot_fall_back_to_contact_field_name(site, tmp_path):
    site["page"] = form('<label>Previous employer name<input required name="full_name"></label>')
    result = run(site, tmp_path)
    assert result["status"] == "needs_review", result
    assert site["posts"] == []


def test_required_radio_uses_exact_saved_group_answer(site, tmp_path):
    site["page"] = form(
        "<fieldset><legend>Will you require sponsorship?</legend>"
        '<label><input type="radio" name="sponsorship" value="yes" required>Yes</label>'
        '<label><input type="radio" name="sponsorship" value="no" required>No</label></fieldset>'
    )
    result = run(site, tmp_path, {"Will you require sponsorship?": "No"})
    assert result["status"] == "confirmed", result
    assert b"\r\nno\r\n" in site["posts"][0]


def test_multistep_form_preserves_contact_and_upload(site, tmp_path):
    site["page"] = (
        '<form method="post" enctype="multipart/form-data">'
        '<label>Email<input name="email" type="email" required></label>'
        '<button type="button" onclick="this.parentNode.innerHTML += '
        "'<label>Resume<input type=file name=resume required></label>"
        "<button type=submit>Submit application</button>'; this.remove();\">Continue</button></form>"
    )
    result = run(site, tmp_path)
    assert result["status"] == "confirmed", result
    assert b"jordan.morgan@example.com" in site["posts"][0]
    assert b"fixture-resume" in site["posts"][0]


def test_saved_radio_answer_not_offered_blocks_checked_required_default(site, tmp_path):
    site["page"] = form(
        "<fieldset><legend>Will you require sponsorship?</legend>"
        '<label><input type="radio" name="sponsorship" value="yes" checked required>Yes</label>'
        '<label><input type="radio" name="sponsorship" value="na" required>Not applicable</label>'
        "</fieldset>"
    )
    result = run(site, tmp_path, {"Will you require sponsorship?": "No"})
    assert result["status"] == "needs_review", result
    assert result["submitted"] is False
    assert site["posts"] == []
    assert "not offered" in result["note"].lower()


@pytest.mark.parametrize("hidden", [False, True])
def test_optional_radio_default_without_approved_answer_requires_review(site, tmp_path, hidden):
    style = ' style="display:none"' if hidden else ""
    site["page"] = form(
        f"<fieldset{style}><legend>Will you require sponsorship?</legend>"
        '<label><input type="radio" name="sponsorship" value="yes" checked>Yes</label>'
        '<label><input type="radio" name="sponsorship" value="no">No</label></fieldset>'
    )
    result = run(site, tmp_path)
    assert result["status"] == "needs_review", result
    assert result["submitted"] is False
    assert site["posts"] == []


def test_saved_radio_answer_overrides_offered_site_default(site, tmp_path):
    site["page"] = form(
        "<fieldset><legend>Will you require sponsorship?</legend>"
        '<label><input type="radio" name="sponsorship" value="yes" checked required>Yes</label>'
        '<label><input type="radio" name="sponsorship" value="no" required>No</label></fieldset>'
    )
    result = run(site, tmp_path, {"Will you require sponsorship?": "No"})
    assert result["status"] == "confirmed", result
    assert b"\r\nno\r\n" in site["posts"][0]
    assert b"\r\nyes\r\n" not in site["posts"][0]


def test_optional_radio_unselected_without_saved_answer_is_omitted(site, tmp_path):
    site["page"] = form(
        "<fieldset><legend>Will you require sponsorship?</legend>"
        '<label><input type="radio" name="sponsorship" value="yes">Yes</label>'
        '<label><input type="radio" name="sponsorship" value="no">No</label></fieldset>'
    )
    result = run(site, tmp_path)
    assert result["status"] == "confirmed", result
    assert b'name="sponsorship"' not in site["posts"][0]


@pytest.mark.parametrize(
    "field",
    [
        '<label>Expected salary<input name="salary" value="50000"></label>',
        '<label>Work authorization<select name="work_auth"><option value="yes">Yes</option><option>No</option></select></label>',
        '<label><input name="consent" type="checkbox" checked>I agree to the terms</label>',
        '<input name="salary" type="hidden" value="50000">',
        '<label style="display:none">Expected salary<input name="salary" value="50000"></label>',
        '<label style="display:none"><input name="consent" type="checkbox" checked>I agree to the terms</label>',
    ],
)
def test_optional_unapproved_site_defaults_require_review(site, tmp_path, field):
    site["page"] = form(field)
    result = run(site, tmp_path)
    assert result["status"] == "needs_review", result
    assert result["submitted"] is False
    assert site["posts"] == []


def test_hidden_csrf_and_requisition_metadata_are_preserved(site, tmp_path):
    site["page"] = form(
        '<input type="hidden" name="csrf_token" value="fixture-token">'
        '<input type="hidden" name="requisition_id" value="job-123">'
    )
    result = run(site, tmp_path)
    assert result["status"] == "confirmed", result
    assert b"fixture-token" in site["posts"][0]
    assert b"job-123" in site["posts"][0]


def test_saved_false_unchecks_optional_consent_default(site, tmp_path):
    site["page"] = form(
        '<label><input type="checkbox" name="marketing" checked>'
        "I consent to marketing email</label>"
    )
    result = run(site, tmp_path, {"I consent to marketing email": False})
    assert result["status"] == "confirmed", result
    assert b'name="marketing"' not in site["posts"][0]


def test_unfamiliar_one_click_entry_button_is_not_clicked(site, tmp_path):
    site["page"] = (
        "<h1>Security Engineer</h1><button onclick=\"fetch('/one-click-application',"
        "{method:'POST'}).then(()=>{document.body.innerHTML='<h1>Your application "
        "has been received.</h1>'})\">Apply now</button>"
    )
    checkpoints = []
    result = run(site, tmp_path, checkpoint=lambda info: checkpoints.append(info))
    assert result["status"] == "needs_review", result
    assert result["submitted"] is False
    assert site["posts"] == []
    assert checkpoints == []


def test_entry_anchor_uses_navigation_without_executing_click_handler(site, tmp_path):
    site["page"] = (
        "<h1>Engineer</h1><a href=\"/apply\" onclick=\"fetch('/one-click',{method:'POST'})\">Apply now</a>"
    )
    site["pages"] = {"/apply": form()}
    result = run(site, tmp_path)
    assert result["status"] == "confirmed", result
    assert len(site["posts"]) == 1
    assert b"fixture-resume" in site["posts"][0]


def test_linkedin_modal_entry_has_checkpoint_before_opening_and_final_submit(
    site, tmp_path, monkeypatch
):
    url = "https://www.linkedin.com/jobs/view/987654321/"
    modal = form().replace("<form ", f'<form action="{site["url"]}" ')
    html = (
        '<h1>Engineer</h1><button type="button" class="jobs-apply-button" onclick=\'document.body.innerHTML = '
        + json.dumps(modal)
        + "'>Easy Apply</button>"
    )
    launch = browser._launch

    def controlled_page(playwright, settings, platform, headless):
        context = launch(playwright, settings, platform, headless)
        context.route(
            url, lambda route: route.fulfill(status=200, content_type="text/html", body=html)
        )
        return context

    monkeypatch.setattr(browser, "_launch", controlled_page)
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture-resume")
    checkpoints = []
    result = browser.apply(
        {"id": 1, "url": url, "source": "linkedin"},
        {"name": "Jordan Morgan", "email": "jordan.morgan@example.com"},
        {},
        {"resume_pdf": str(resume)},
        {
            "data_dir": str(tmp_path / "data"),
            "_fixture_mode": True,
            "browser_headless": True,
            "receipt_wait_seconds": 0.6,
        },
        lambda info: checkpoints.append((info, len(site["posts"]))),
    )
    assert result["status"] == "confirmed", result
    assert checkpoints[0][0].get("entry") is True
    assert checkpoints[0][1] == 0
    assert checkpoints[-1][0]["button"] == "Submit application"
    assert len(site["posts"]) == 1


def test_upload_rerender_cannot_shift_field_identity(site, tmp_path):
    html = form('<label>Phone<input type="tel" name="phone" required></label>')
    html = html.replace(
        'name="resume" required',
        'name="resume" required onchange="this.form.append(this.form.querySelector(\'label\'))"',
    )
    site["page"] = html
    result = run(site, tmp_path)
    assert result["status"] == "confirmed", result
    assert b"+1 202 555 0142" in site["posts"][0]
