import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jobpilot import browser


@pytest.fixture
def review_site(monkeypatch):
    state = {"posts": [], "html": "", "receipt_ready": threading.Event()}
    original_launch = browser._launch

    def launch_context(*args, **kwargs):
        context = original_launch(*args, **kwargs)
        # Fixture locator waits are short; navigation needs its own CI startup bound.
        context.on("page", lambda page: page.set_default_navigation_timeout(10000))
        for page in context.pages:
            page.set_default_navigation_timeout(10000)
        return context

    monkeypatch.setattr(browser, "_launch", launch_context)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/receipt-ready":
                ready = state["receipt_ready"].wait(15)
                self.send_response(200 if ready else 503)
                self.end_headers()
                return
            time.sleep(state.get("navigation_delay", 0))
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(state["html"].encode())

        def do_POST(self):
            state["posts"].append(self.path)
            self.send_response(200)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/jobs/1"
    yield state
    state["receipt_ready"].set()
    server.shutdown()
    server.server_close()


FORM = """<form method="post"><label>Full name<input name="name" required></label>
<label>Email<input type="email" name="email" required></label>
<label>Resume<input type="file" name="resume" required></label>
<button type="submit">Submit application</button></form>"""


def launch(site, tmp_path, duration=1):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fixture")
    closed = threading.Event()
    outcomes = []

    def callback(outcome):
        assert browser._session_lock.acquire(blocking=False), (
            "Release the browser before recording its outcome"
        )
        browser._session_lock.release()
        outcomes.append(outcome)
        closed.set()

    result = browser.open_review(
        {"id": 1, "url": site["url"]},
        {"name": "Jordan", "email": "jordan.morgan@example.com"},
        {},
        {"resume_pdf": str(resume)},
        {
            "data_dir": str(tmp_path / "data"),
            "_fixture_mode": True,
            "browser_headless": True,
            "review_hold_seconds": duration,
        },
        callback,
    )
    return result, closed, outcomes


def test_review_prepares_but_never_clicks_submit(review_site, tmp_path):
    review_site["html"] = FORM
    result, closed, outcomes = launch(review_site, tmp_path)
    assert result["status"] == "opened", result
    assert closed.wait(8)
    assert review_site["posts"] == []
    assert len(outcomes) == 1 and outcomes[0]["status"] == "needs_review"
    assert outcomes[0]["submitted"] is False
    assert not browser.login_in_progress()


def test_review_allows_slow_navigation_before_its_observation_window(review_site, tmp_path):
    review_site["html"] = FORM
    review_site["navigation_delay"] = 1.25
    result, closed, outcomes = launch(review_site, tmp_path)
    assert result["status"] == "opened", result
    assert closed.wait(8)
    assert review_site["posts"] == []
    assert outcomes[0]["status"] == "needs_review"
    assert outcomes[0]["submitted"] is False


def test_new_matching_receipt_is_observed_without_an_automatic_submit(review_site, tmp_path):
    review_site["html"] = (
        FORM
        + """<script>fetch('/receipt-ready').then(response=>{
      if(response.ok) document.body.insertAdjacentHTML('beforeend',
      '<h1>Your application has been received.</h1>')})</script>"""
    )
    result, closed, outcomes = launch(review_site, tmp_path, 2)
    assert result["status"] == "opened", result
    review_site["receipt_ready"].set()
    assert closed.wait(8)
    assert review_site["posts"] == []
    assert outcomes[0]["status"] == "confirmed"
    assert outcomes[0]["receipt"] and outcomes[0]["evidence"]
    assert outcomes[0]["submitted"] is False


def test_existing_receipt_is_not_treated_as_new(review_site, tmp_path):
    review_site["html"] = "<h1>Your application has been received.</h1>" + FORM
    result, closed, outcomes = launch(review_site, tmp_path)
    assert result["status"] == "opened", result
    assert closed.wait(8)
    assert outcomes[0]["status"] == "needs_review"
    assert review_site["posts"] == []


def test_receipt_for_a_different_job_is_not_counted(review_site, tmp_path):
    review_site["html"] = (
        FORM
        + """<script>fetch('/receipt-ready').then(response=>{if(response.ok){
      history.replaceState(null,'','/jobs/different');
      document.body.innerHTML='<h1>Your application has been received.</h1>'}})</script>"""
    )
    result, closed, outcomes = launch(review_site, tmp_path, 1.5)
    assert result["status"] == "opened", result
    review_site["receipt_ready"].set()
    assert closed.wait(8)
    assert outcomes[0]["status"] == "needs_review"
    assert review_site["posts"] == []


def test_review_refuses_a_concurrent_browser_without_starting_another(tmp_path):
    assert browser._session_lock.acquire(blocking=False)
    try:
        result = browser.open_review(
            {"url": "http://127.0.0.1/jobs/1"},
            {},
            {},
            {},
            {"data_dir": str(tmp_path), "_fixture_mode": True},
        )
        assert result["status"] == "needs_review"
    finally:
        browser._session_lock.release()
