"""Local Chromium fixtures for retained human intervention; no real applications."""

import inspect
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from jobpilot import browser

FORM = (
    '<form id="application" method="post" action="/jobs/1/submit">'
    '<label>Email<input type="email" name="email" required></label>'
    '<label>Resume<input type="file" name="resume" required></label>'
    '<button type="submit">Submit application</button></form>'
)
LOGIN = '<h1>Sign in to apply</h1><label>Password<input type="password" required></label>'
CODE = (
    '<h1>Security verification</h1><form method="post" action="/jobs/1/verify">'
    '<label>Verification code<input name="code" autocomplete="one-time-code" required></label>'
    '<button type="submit">Verify code</button></form>'
)
RECEIPT = "<h1>Your application has been received.</h1>"


@pytest.fixture
def site():
    state = {"page": FORM, "response": RECEIPT, "posts": [], "gets": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def response(self, html):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

        def do_GET(self):
            state["gets"].append(self.path)
            if self.path == "/feed":
                self.response("<h1>Your account</h1><button>Sign out</button>")
            elif self.path.endswith("/receipt"):
                self.response(RECEIPT)
            else:
                self.response(state["page"])

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["posts"].append((self.path, raw))
            self.response(RECEIPT if self.path == "/jobs/1/verify" else state["response"])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/jobs/1"
    yield state
    server.shutdown()
    server.server_close()


def run(site, tmp_path, handler, checkpoint_enabled=True, **settings):
    assert "intervention_handler" in inspect.signature(browser.apply).parameters
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture")
    checkpoints = []
    result = browser.apply(
        {"id": 1, "url": site["url"], "title": "Security Engineer"},
        {"name": "Fixture Candidate", "email": "fixture@example.com"},
        {},
        {"resume_pdf": str(resume)},
        {
            "data_dir": str(tmp_path / "data"),
            "_fixture_mode": True,
            "browser_headless": True,
            "receipt_wait_seconds": 0.5,
            "intervention_timeout_seconds": 2,
            **settings,
        },
        checkpoint=(lambda info: checkpoints.append(info)) if checkpoint_enabled else None,
        intervention_handler=handler,
    )
    return result, checkpoints


def test_prelogin_human_resume_returns_to_job_and_submits_once(site, tmp_path):
    site["page"] = LOGIN
    owner = threading.get_ident()
    contexts = []

    def human(page, job, **options):
        assert threading.get_ident() == owner
        contexts.append(page.context)
        assert options["submitted"] is False and options["auto_resume"] is False
        assert options["kind"] == "authentication"
        assert options["ready"]() is False
        page.get_by_label("Password").fill("fixture-password-not-for-evidence")
        site["page"] = FORM
        page.goto(site["url"].replace("/jobs/1", "/feed"))
        assert options["ready"]() is True
        return "resume"

    result, checkpoints = run(site, tmp_path, human)
    assert result["status"] == "confirmed", result
    assert len(contexts) == 1
    assert [path for path, _ in site["posts"]] == ["/jobs/1/submit"]
    assert len(checkpoints) == 1
    assert site["gets"].count("/jobs/1") == 2
    for path in result["evidence"]:
        assert b"fixture-password-not-for-evidence" not in Path(path).read_bytes()


def test_human_completes_application_during_prelogin_pause_without_another_submit(site, tmp_path):
    site["page"] = LOGIN

    def human(page, job, **options):
        page.evaluate("html => document.body.innerHTML=html", FORM)
        page.get_by_label("Email").fill("fixture@example.com")
        page.get_by_label("Resume").set_input_files(str(tmp_path / "resume.pdf"))
        page.get_by_role("button", name="Submit application").click()
        assert options["ready"]() is True
        return "resume"

    result, checkpoints = run(site, tmp_path, human)
    assert result["status"] == "confirmed", result
    assert result["submitted"] is True
    assert result["evidence"]
    assert checkpoints == []
    assert [path for path, _ in site["posts"]] == ["/jobs/1/submit"]


def test_same_job_solved_captcha_is_not_reloaded(site, tmp_path):
    site["page"] = '<h1>Verify you are human</h1><button id="challenge">Complete CAPTCHA</button>'

    def human(page, job, **options):
        assert options["kind"] == "captcha"
        assert options["ready"]() is False
        page.evaluate("html => document.body.innerHTML=html", FORM)
        assert options["ready"]() is True
        return "resume"

    result, _ = run(site, tmp_path, human)
    assert result["status"] == "confirmed", result
    assert site["gets"].count("/jobs/1") == 1
    assert [path for path, _ in site["posts"]] == ["/jobs/1/submit"]


def test_postsubmit_code_retains_page_and_confirms_without_second_final_click(site, tmp_path):
    site["response"] = CODE
    calls = []

    def human(page, job, **options):
        calls.append(options)
        assert options["submitted"] is True and options["auto_resume"] is True
        assert options["kind"] == "verification"
        assert page.url.endswith("/jobs/1/submit")
        assert options["ready"]() is False
        page.get_by_label("Verification code").fill("fixture-code-482913")
        page.get_by_role("button", name="Verify code").click()
        assert options["ready"]() is True
        return "resume"

    result, checkpoints = run(site, tmp_path, human)
    assert result["status"] == "confirmed", result
    assert result["submitted"] is True
    assert len(calls) == len(checkpoints) == 1
    assert [path for path, _ in site["posts"]] == ["/jobs/1/submit", "/jobs/1/verify"]
    for path in result["evidence"]:
        assert b"fixture-code-482913" not in Path(path).read_bytes()


def test_submit_click_timeout_with_live_code_gate_retains_intervention(site, tmp_path, monkeypatch):
    site["response"] = CODE
    visible_button = browser._visible_button

    def click_times_out_after_navigation(scope, pattern):
        control, caption = visible_button(scope, pattern)
        if control is None or pattern is not browser._FINAL:
            return control, caption

        class DelayedClick:
            def click(self):
                control.click()
                raise TimeoutError("Fixture timeout after navigation to verification")

            def __getattr__(self, name):
                return getattr(control, name)

        return DelayedClick(), caption

    monkeypatch.setattr(browser, "_visible_button", click_times_out_after_navigation)

    def human(page, job, **options):
        assert options["submitted"] is True
        page.get_by_label("Verification code").fill("fixture-code")
        page.get_by_role("button", name="Verify code").click()
        return "resume"

    result, checkpoints = run(site, tmp_path, human)
    assert result["status"] == "confirmed", result
    assert len(checkpoints) == 1
    assert [path for path, _ in site["posts"]] == ["/jobs/1/submit", "/jobs/1/verify"]


@pytest.mark.parametrize("outcome", ["cancelled", "expired", "closed", "interrupted"])
def test_ending_postsubmit_intervention_preserves_uncertainty(site, tmp_path, outcome):
    site["response"] = CODE

    def human(page, job, **options):
        page.get_by_label("Verification code").fill("do-not-persist-this-code")
        if outcome == "closed":
            page.close()
        return outcome

    result, checkpoints = run(site, tmp_path, human)
    assert result["status"] == "needs_review"
    assert result["submitted"] is True
    assert outcome in result["note"].lower()
    assert len(checkpoints) == 1
    assert [path for path, _ in site["posts"]] == ["/jobs/1/submit"]
    for path in result["evidence"]:
        assert b"do-not-persist-this-code" not in Path(path).read_bytes()


def test_wrong_job_receipt_cannot_release_postsubmit_intervention(site, tmp_path):
    site["response"] = CODE

    def human(page, job, **options):
        page.goto(site["url"].replace("/jobs/1", "/jobs/2/receipt"))
        assert options["ready"]() is False
        return "resume"  # A faulty adapter cannot bypass the browser's own receipt guard.

    result, checkpoints = run(site, tmp_path, human)
    assert result["status"] == "needs_review"
    assert result["submitted"] is True
    assert len(checkpoints) == 1
    assert [path for path, _ in site["posts"]] == ["/jobs/1/submit"]


def test_receipt_query_cannot_switch_job_identity_during_intervention(site, tmp_path):
    site["url"] += "?job_id=1"
    site["response"] = CODE

    def human(page, job, **options):
        page.evaluate(
            'html => {document.body.innerHTML=html;history.replaceState(null,"","/jobs/1/receipt?job_id=2")}',
            RECEIPT,
        )
        assert options["ready"]() is False
        return "resume"

    result, checkpoints = run(site, tmp_path, human)
    assert result["status"] == "needs_review" and result["submitted"] is True
    assert len(checkpoints) == 1
    assert [path for path, _ in site["posts"]] == ["/jobs/1/submit"]


def test_existing_receipt_during_prelogin_cannot_become_a_new_confirmation(site, tmp_path):
    site["page"] = LOGIN + RECEIPT

    def human(page, job, **options):
        page.evaluate("html => document.body.innerHTML=html", RECEIPT)
        return "resume"

    result, checkpoints = run(site, tmp_path, human)
    assert result["status"] == "needs_review" and result["submitted"] is False
    assert site["posts"] == checkpoints == []


def test_unverified_prelogin_resume_does_not_automatically_submit(site, tmp_path):
    site["page"] = LOGIN
    result, checkpoints = run(site, tmp_path, lambda page, job, **options: "resume")
    assert result["status"] == "needs_review"
    assert result["submitted"] is False
    assert site["posts"] == checkpoints == []


def test_remote_handler_error_never_echoes_input_in_outcome(site, tmp_path):
    site["response"] = CODE

    def human(page, job, **options):
        raise ValueError("sensitive-input-fixture-credential")

    result, _ = run(site, tmp_path, human)
    assert result["status"] == "needs_review" and result["submitted"] is True
    assert "sensitive-input-fixture-credential" not in str(result)


def test_remote_resume_still_cannot_submit_without_checkpoint(site, tmp_path):
    site["page"] = LOGIN

    def human(page, job, **options):
        page.evaluate("html => document.body.innerHTML=html", FORM)
        return "resume"

    result, checkpoints = run(site, tmp_path, human, checkpoint_enabled=False)
    assert result["status"] == "needs_review" and result["submitted"] is False
    assert "checkpoint missing" in result["note"].lower()
    assert site["posts"] == checkpoints == []


def test_remote_auth_query_is_absent_from_metadata_and_evidence(site, tmp_path):
    site["url"] += "?code=private-query-code-fixture#private-fragment-fixture"
    site["page"] = LOGIN
    result, _ = run(site, tmp_path, lambda page, job, **options: "expired")
    assert result["status"] == "needs_review"
    assert "private-query-code-fixture" not in str(result)
    assert "private-fragment-fixture" not in str(result)
    for path in result["evidence"]:
        assert b"private-query-code-fixture" not in Path(path).read_bytes()


def test_solved_captcha_query_is_not_persisted_in_submit_checkpoint(site, tmp_path):
    site["page"] = "<h1>Verify you are human</h1>"

    def human(page, job, **options):
        page.evaluate(
            'html => {document.body.innerHTML=html;history.replaceState(null,"","?code=secret-query-code")}',
            FORM,
        )
        return "resume"

    result, checkpoints = run(site, tmp_path, human)
    assert result["status"] == "confirmed", result
    assert len(checkpoints) == 1
    assert "secret-query-code" not in str(checkpoints)


def test_cleared_postsubmit_challenge_without_receipt_remains_uncertain(site, tmp_path):
    site["response"] = CODE

    def human(page, job, **options):
        page.evaluate('() => document.body.innerHTML="<h1>Verification complete</h1>"')
        assert options["ready"]() is False
        return "resume"

    result, checkpoints = run(site, tmp_path, human)
    assert result["status"] == "needs_review" and result["submitted"] is True
    assert len(checkpoints) == 1
    assert [path for path, _ in site["posts"]] == ["/jobs/1/submit"]


@pytest.mark.parametrize(
    ("receipt_path", "wanted_status"),
    [
        ("/jobs/1/receipt", "confirmed"),
        ("/jobs/2/receipt", "needs_review"),
    ],
)
def test_open_review_remote_human_only_observes_new_receipt(
    site, tmp_path, receipt_path, wanted_status
):
    assert "intervention_handler" in inspect.signature(browser.open_review).parameters
    owner = threading.get_ident()
    finished, outcomes = threading.Event(), []

    def human(page, job, **options):
        assert threading.get_ident() != owner
        assert options["submitted"] is True and options["auto_resume"] is True
        assert options["ready"]() is False
        page.goto(site["url"].replace("/jobs/1", receipt_path))
        assert options["ready"]() is (wanted_status == "confirmed")
        return "resume"

    def closed(outcome):
        assert browser._session_lock.acquire(blocking=False)
        browser._session_lock.release()
        outcomes.append(outcome)
        finished.set()

    result = browser.open_review(
        {"id": 1, "url": site["url"], "uncertain": True},
        {},
        {},
        {},
        {
            "data_dir": str(tmp_path / "data"),
            "_fixture_mode": True,
            "review_hold_seconds": 1,
            "intervention_timeout_seconds": 2,
        },
        on_closed=closed,
        intervention_handler=human,
    )
    assert result["status"] == "opened"
    assert finished.wait(10)
    assert outcomes[0]["status"] == wanted_status
    assert outcomes[0]["submitted"] is False
    assert site["posts"] == []
