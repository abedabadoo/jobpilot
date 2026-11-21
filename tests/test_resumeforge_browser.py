import json
from urllib.parse import urlsplit

from playwright.sync_api import expect
from test_dashboard_actions import dashboard as dashboard


def test_role_opens_resumeforge_and_lists_its_checked_pdf(dashboard):
    page = dashboard["page"]
    calls = []

    def forge_api(route):
        path = urlsplit(route.request.url).path
        if path.endswith("/status"):
            result = {"status": "ready", "attached": False}
        elif path.endswith("/open"):
            calls.append("open")
            result = {"opened": True, "message": "Opened this opportunity in ResumeForge."}
        elif path.endswith("/use"):
            calls.append("use")
            dashboard["state"]["jobs"][0]["documents"]["resumeforge_pdf"] = (
                "C:/JobPilot-fixture/applications/resumeforge.pdf"
            )
            result = {"attached": True, "message": "Checked ResumeForge PDF added to this role."}
        else:
            raise AssertionError(path)
        route.fulfill(content_type="application/json", body=json.dumps(result))

    page.route("**/api/jobs/1/resumeforge/**", forge_api)
    page.get_by_role("button", name="Review", exact=True).click()
    open_button = page.get_by_role("button", name="Open in ResumeForge", exact=True)
    use_button = page.get_by_role("button", name="Sync ResumeForge PDFs", exact=True)
    expect(open_button).to_be_visible()
    expect(use_button).to_be_enabled()
    open_button.click()
    assert "open" in calls
    use_button.click()
    assert "use" in calls
    expect(page.get_by_role("button", name="Open Resume PDF", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Open Resume PDF", exact=True)).to_have_count(1)


def test_changed_posting_hides_older_resumeforge_pdf(dashboard):
    page = dashboard["page"]
    job = dashboard["state"]["jobs"][0]
    job["documents"]["resumeforge_pdf"] = "C:/JobPilot-fixture/applications/older.pdf"
    job["resumeforge"] = {"current": False}
    page.get_by_role("button", name="Review", exact=True).click()
    expect(page.get_by_role("button", name="Open Resume PDF", exact=True)).to_have_count(0)
