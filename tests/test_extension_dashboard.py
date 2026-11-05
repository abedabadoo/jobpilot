import json
from urllib.parse import urlsplit

from playwright.sync_api import expect
from test_dashboard_actions import dashboard as dashboard


def extension_routes(page):
    requests = []
    pairings = []

    def route_api(route):
        path = urlsplit(route.request.url).path
        requests.append((path, route.request.method, route.request.headers))
        if path == "/api/extension/pairing":
            assert route.request.headers.get("x-jobpilot-token") == "fixture-token"
            assert route.request.post_data_json == {"extension_id": "a" * 32}
            result = {"code": "one-use-fixture-code", "expires_at": "2099-11-05T12:00:00Z"}
        elif path.endswith("/revoke"):
            pairings.clear()
            result = {"ok": True}
        else:
            assert route.request.headers.get("x-jobpilot-token") == "fixture-token"
            result = {"pairings": pairings}
        route.fulfill(content_type="application/json", body=json.dumps(result))

    page.route("**/api/extension/**", route_api)
    return requests, pairings


def test_extension_connection_requires_click_before_creating_pairing(dashboard):
    page = dashboard["page"]
    requests, _ = extension_routes(page)
    page.goto(page.url.split("?")[0].split("#")[0] + "?extension_id=" + "a" * 32 + "#settings")
    expect(page.locator("#extensionPanel")).to_be_visible()
    expect(page.locator("#extensionId")).to_have_value("a" * 32)
    assert not any(path.endswith("/pairing") for path, _, _ in requests)
    page.get_by_role("button", name="Create pairing code", exact=True).click()
    expect(page.locator("#extensionPairingCode")).to_have_value("one-use-fixture-code")
    expect(page.locator("#extensionPairingHelp")).to_contain_text("Chrome")


def test_invalid_extension_link_is_not_authorized(dashboard):
    page = dashboard["page"]
    requests, _ = extension_routes(page)
    page.goto(page.url.split("?")[0].split("#")[0] + "?extension_id=not-an-id#settings")
    expect(page.get_by_role("button", name="Create pairing code", exact=True)).to_be_disabled()
    assert not any(path.endswith("/pairing") for path, _, _ in requests)


def test_dashboard_can_revoke_extension_without_exposing_tokens(dashboard):
    page = dashboard["page"]
    requests, pairings = extension_routes(page)
    pairings.append(
        {
            "pairing_id": "fixture-connection",
            "extension_id": "a" * 32,
            "created_at": "2026-11-05T12:00:00Z",
            "expires_at": "2099-11-05T12:00:00Z",
        }
    )
    page.goto(page.url.split("#")[0] + "#settings")
    page.get_by_role("button", name="Disconnect", exact=True).click()
    expect(page.locator("#extensionConnections")).to_contain_text("No Chrome connections")
    assert any(path.endswith("/fixture-connection/revoke") for path, _, _ in requests)
    assert "fixture-token" not in page.locator("#extensionPanel").inner_text()
