from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect
from test_dashboard_actions import dashboard as dashboard


def test_monitoring_controls_save_cadence_start_and_pause_without_running_manual_search(dashboard):
    page = dashboard["page"]
    panel = page.get_by_role("region", name="Job monitoring", exact=True)
    expect(panel).to_be_visible()
    panel.get_by_role("combobox", name="Check every").select_option("10")
    expect(panel.get_by_role("combobox", name="Check every")).to_have_value("10")
    assert ("/api/settings", {"search_interval_minutes": 10}) in dashboard["calls"]
    panel.get_by_role("button", name="Start monitoring", exact=True).click()
    expect(panel.get_by_role("button", name="Pause monitoring", exact=True)).to_be_visible()
    expect(panel).to_contain_text("Every 10 minutes")
    assert ("/api/control", {"search_enabled": True}) in dashboard["calls"]
    panel.get_by_role("button", name="Pause monitoring", exact=True).click()
    expect(panel.get_by_role("button", name="Start monitoring", exact=True)).to_be_visible()
    assert ("/api/control", {"search_enabled": False}) in dashboard["calls"]
    page.get_by_role("button", name="Search now", exact=True).click()
    expect(page.locator("#toast")).to_contain_text("Search requested")
    assert ("/api/control", {"action": "search"}) in dashboard["calls"]
    assert dashboard["state"]["settings"]["search_enabled"] is False


def test_monitoring_shows_results_and_source_failures_without_hiding_successes(dashboard):
    page = dashboard["page"]
    page.set_viewport_size({"width": 1440, "height": 1000})
    now = datetime.now(UTC)
    dashboard["state"]["search_monitor"] = {
        "enabled": True,
        "interval_minutes": 15,
        "last_search_at": (now - timedelta(minutes=2)).isoformat(),
        "next_search_at": (now + timedelta(minutes=12)).isoformat(),
        "last_result": {
            "checked": 25,
            "imported": 3,
            "existing": 7,
            "filtered": 15,
            "sources": [
                {
                    "source": "Indeed",
                    "status": "ok",
                    "checked": 25,
                    "imported": 3,
                    "existing": 7,
                    "filtered": 15,
                    "message": "",
                },
                {
                    "source": "LinkedIn",
                    "status": "error",
                    "checked": 0,
                    "imported": 0,
                    "existing": 0,
                    "filtered": 0,
                    "message": "Sign in required.",
                },
                {"source": "Gmail", "status": "ok", "checked": 10, "imported": 1},
                {"source": "Google", "status": "ok", "checked": 10, "imported": 1},
                {"source": "Employer", "status": "ok", "checked": 10, "imported": 1},
            ],
        },
    }
    page.reload(wait_until="networkidle")
    panel = page.get_by_role("region", name="Job monitoring", exact=True)
    expect(panel.get_by_role("combobox", name="Check every")).to_have_value("15")
    expect(page.locator("#lastSearch")).to_contain_text("2m ago")
    expect(page.locator("#nextSearch")).to_contain_text("In 12m")
    expect(page.locator("#monitorResult")).to_contain_text("3 new opportunities")
    expect(page.locator("#monitorResult")).to_contain_text("15 filtered")
    expect(panel.locator("summary")).to_contain_text("Source results")
    expect(panel.locator("summary")).to_contain_text("1 source needs attention")
    expect(panel.get_by_role("table", name="Latest results by source")).to_be_hidden()
    expect(page.locator("#jobsBody tr").first).to_be_in_viewport(ratio=1)
    panel.locator("summary").click()
    source = panel.get_by_role("row").filter(has_text="Indeed")
    expect(source).to_contain_text("25")
    expect(source).to_contain_text("3")
    expect(panel.get_by_role("row").filter(has_text="LinkedIn")).to_contain_text("Sign in required")
    expect(panel.get_by_role("button", name="Pause monitoring", exact=True)).to_be_visible()
    dashboard["hold_poll"]()
    dashboard["state"]["search_monitor"]["last_result"]["sources"][0]["checked"] = 26
    dashboard["release_poll"]()
    expect(source).to_contain_text("26")
    expect(panel.get_by_role("table", name="Latest results by source")).to_be_visible()


def test_failed_monitoring_change_keeps_previous_state_and_allows_retry(dashboard):
    page = dashboard["page"]
    dashboard["settings_status"] = 500
    panel = page.get_by_role("region", name="Job monitoring", exact=True)
    panel.get_by_role("button", name="Start monitoring", exact=True).click()
    expect(page.locator("#toast")).to_contain_text("Please try again")
    expect(panel.get_by_role("button", name="Start monitoring", exact=True)).to_be_enabled()
    panel.get_by_role("combobox", name="Check every").select_option("5")
    expect(page.locator("#toast")).to_contain_text("Please try again")
    expect(panel.get_by_role("combobox", name="Check every")).to_have_value("30")


def test_filtering_opportunities_explains_hidden_jobs_and_can_clear_filters(dashboard):
    page = dashboard["page"]
    dashboard["state"]["jobs"].append(
        {
            **dashboard["state"]["jobs"][0],
            "id": 2,
            "title": "Job alert",
            "source": "Gmail",
        }
    )
    page.reload(wait_until="networkidle")
    page.get_by_role("combobox", name="Filter by source").select_option("Employer")
    expect(page.locator("#visibleCount")).to_contain_text("1 of 2 opportunities")
    page.get_by_role("button", name="Clear filters", exact=True).click()
    expect(page.locator("#jobsBody tr")).to_have_count(2)
    expect(page.get_by_role("button", name="Clear filters", exact=True)).to_be_hidden()


def test_email_results_explain_links_filtered_and_already_saved(dashboard):
    page = dashboard["page"]
    dashboard["state"]["email_sync"] = {
        "state": "connected",
        "checked_at": "2026-10-27T14:00:00+00:00",
        "messages_checked": 10,
        "links_found": 25,
        "imported": 3,
        "existing": 7,
        "filtered": 15,
    }
    page.reload(wait_until="networkidle")
    page.get_by_role("button", name="Email & alerts", exact=True).click()
    stats = page.locator("#emailSyncStats")
    expect(stats.locator("div").filter(has_text="Already saved")).to_contain_text("7")
    expect(stats.locator("div").filter(has_text="Filtered")).to_contain_text("15")
