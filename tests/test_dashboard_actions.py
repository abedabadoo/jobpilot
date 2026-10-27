import copy
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

PDF_BYTES = b"%PDF-1.4\n% JobPilot document download fixture\n%%EOF\n"
RESUME_PATH = "C:/JobPilot-fixture/applications/resume.pdf"
DOCUMENTS = {
    "resume_pdf": RESUME_PATH,
    "resume_docx": "C:/JobPilot-fixture/applications/resume.docx",
    "cover_pdf": "C:/JobPilot-fixture/applications/cover-letter.pdf",
    "cover_docx": "C:/JobPilot-fixture/applications/cover-letter.docx",
}


@pytest.fixture
def dashboard():
    web = Path(__file__).resolve().parents[1] / "web"
    downloads = []

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/api/artifact":
                downloads.append(parse_qs(parsed.query)["path"][0])
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", 'attachment; filename="resume.pdf"')
                self.send_header("Content-Length", str(len(PDF_BYTES)))
                self.end_headers()
                self.wfile.write(PDF_BYTES)
                return
            super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(web)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    now = "2026-10-26T15:00:00+00:00"
    job = {
        "id": 1,
        "title": "Cloud Security Engineer",
        "company": "Northstar Labs",
        "location": "Chicago, IL",
        "source": "Employer",
        "url": "https://careers.example.com/jobs/security",
        "description": "Build security tools with AWS and Python.",
        "posted_at": now,
        "created_at": now,
        "fit": 92,
        "status": "prepared",
        "keywords": {"terms": ["AWS", "Python"]},
        "documents": DOCUMENTS,
    }
    state = {
        "jobs": [job],
        "events": [],
        "metrics": {},
        "worker": {"searching": False, "submitting": False, "heartbeat": now},
        "settings": {"search_enabled": False, "target_roles": ["Security Engineer"]},
        "profile": {
            "name": "Jordan Morgan",
            "email": "jordan@example.com",
            "skills": ["AWS", "Python"],
            "experience": [],
        },
        "answers": {},
    }
    problem = {
        "id": 10,
        "job_id": 1,
        "title": job["title"],
        "company": job["company"],
        "url": job["url"],
        "message": "Documents could not be prepared. Try generating them again.",
        "created_at": now,
        "category": "documents",
        "resolved": False,
    }
    control = {
        "calls": [],
        "held": [],
        "hold_state": False,
        "problem_reads": 0,
        "resolve_status": 200,
        "open_status": 200,
        "downloads": downloads,
        "settings_status": 200,
    }

    def route_api(route):
        path = urlsplit(route.request.url).path
        if path == "/api/artifact":
            route.continue_()
            return
        if path == "/api/state" and control["hold_state"]:
            control["held"].append(route)
            return
        status = 200
        if path == "/api/session":
            result = {"token": "fixture-token"}
        elif path == "/api/state":
            result = state
        elif path == "/api/problems":
            control["problem_reads"] += 1
            # Deliberately stale, as a poll started before resolution can be.
            result = {"problems": [copy.deepcopy(problem)]}
        elif route.request.method == "POST":
            control["calls"].append((path, route.request.post_data_json))
            if path in {"/api/settings", "/api/control"}:
                payload = route.request.post_data_json
                status = control["settings_status"]
                if status == 200:
                    state["settings"].update({k: v for k, v in payload.items() if k != "action"})
                    monitor = state.get("search_monitor")
                    if monitor:
                        monitor["enabled"] = state["settings"].get("search_enabled", False)
                        monitor["interval_minutes"] = state["settings"].get(
                            "search_interval_minutes", 30
                        )
                result = {"ok": True} if status == 200 else {"detail": "Please try again."}
            elif path == "/api/problems/10/resolve":
                status = control["resolve_status"]
                result = {"ok": True} if status == 200 else {"detail": "Please try again."}
            elif path == "/api/artifact/open":
                status = control["open_status"]
                result = (
                    {"opened": True}
                    if status == 200
                    else {"detail": "This document could not be opened. Download it instead."}
                )
            else:
                result = {"ok": True}
        else:
            result = {"ok": True}
        route.fulfill(status=status, content_type="application/json", body=json.dumps(result))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/**", route_api)
        page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
        expect(page.locator("#jobsBody tr")).to_have_count(1)

        def hold_poll():
            control["hold_state"] = True
            page.wait_for_timeout(3200)
            assert control["held"], "The test must hold a real background state request."

        def release_poll():
            control["hold_state"] = False
            held, control["held"] = control["held"], []
            for route in held:
                route.fulfill(content_type="application/json", body=json.dumps(state))

        control.update(page=page, state=state, hold_poll=hold_poll, release_poll=release_poll)
        try:
            yield control
        finally:
            release_poll()
            browser.close()
            server.shutdown()
            server.server_close()
        assert not errors, errors


def test_resolving_problem_updates_immediately_and_ignores_stale_background_poll(dashboard):
    page = dashboard["page"]
    page.get_by_role("button", name="Problems", exact=True).click()
    expect(page.locator("#problemsList .problem-card")).to_have_count(1)
    dashboard["hold_poll"]()
    assert dashboard["problem_reads"] >= 2
    page.get_by_role("button", name="Mark resolved", exact=True).click()
    expect(page.locator("#problemsList .problem-card")).to_have_count(0, timeout=1000)
    expect(page.get_by_role("heading", name="No problems to review")).to_be_visible()
    assert ("/api/problems/10/resolve", {}) in dashboard["calls"]
    dashboard["state"]["worker"]["model_status"] = "Background refresh completed."
    dashboard["release_poll"]()
    expect(page.locator("#workerExtra")).to_contain_text("Background refresh completed.")
    expect(page.locator("#problemsList .problem-card")).to_have_count(0)
    expect(page.locator("#problemsNavCount")).to_be_hidden()


def test_failed_resolution_keeps_the_problem_available_to_retry(dashboard):
    dashboard["resolve_status"] = 500
    page = dashboard["page"]
    page.get_by_role("button", name="Problems", exact=True).click()
    button = page.get_by_role("button", name="Mark resolved", exact=True)
    button.click()
    expect(page.locator("#toast")).to_contain_text("Please try again.")
    expect(page.locator("#problemsList .problem-card")).to_have_count(1)
    expect(button).to_be_enabled()


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("Resume PDF", "resume_pdf"),
        ("Resume Word", "resume_docx"),
        ("Cover letter PDF", "cover_pdf"),
        ("Cover letter Word", "cover_docx"),
    ],
)
def test_opening_each_document_dispatches_without_waiting_for_background_poll(
    dashboard, label, key
):
    page = dashboard["page"]
    page.get_by_role("button", name="Review", exact=True).click()
    dashboard["hold_poll"]()
    button = page.get_by_role("button", name=f"Open {label}", exact=True)
    button.click()
    expect(button).to_be_enabled(timeout=1000)
    assert ("/api/artifact/open", {"path": DOCUMENTS[key]}) in dashboard["calls"]


def test_failed_document_open_shows_a_useful_error_and_keeps_download_available(dashboard):
    dashboard["open_status"] = 500
    page = dashboard["page"]
    page.get_by_role("button", name="Review", exact=True).click()
    button = page.get_by_role("button", name="Open Resume PDF", exact=True)
    button.click()
    expect(page.locator("#modalContent")).to_contain_text("Download it instead.")
    expect(button).to_be_enabled()
    expect(page.get_by_role("link", name="Download Resume PDF", exact=True)).to_be_visible()


def test_resume_download_returns_file_bytes_without_opening_another_tab(dashboard):
    page = dashboard["page"]
    page.get_by_role("button", name="Review", exact=True).click()
    link = page.get_by_role("link", name="Download Resume PDF", exact=True)
    expect(link).to_have_attribute("download", "")
    assert link.get_attribute("target") is None
    with page.expect_download() as download_info:
        link.click()
    download = download_info.value
    assert download.suggested_filename == "resume.pdf"
    assert Path(download.path()).read_bytes() == PDF_BYTES
    assert dashboard["downloads"] == [RESUME_PATH]
    assert len(page.context.pages) == 1
