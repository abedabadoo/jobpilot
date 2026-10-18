import json
import threading
import time

import pytest


def test_auth_exchange_expiry_revocation_and_no_plain_device_secret(tmp_path):
    from jobpilot.remote_auth import RemoteAuth

    vault = {}
    auth = RemoteAuth(
        tmp_path,
        vault_get=lambda: vault.get("key"),
        vault_set=lambda value: vault.update(key=value),
    )
    secret = auth.pairing_secret()
    assert len(secret) >= 40
    assert auth.exchange("wrong") is None
    token = auth.exchange(secret)
    assert auth.valid(token) and not auth.valid("wrong")
    assert token not in (tmp_path / "remote-sessions.json").read_text()
    again = RemoteAuth(tmp_path, vault_get=lambda: vault.get("key"), vault_set=lambda value: None)
    assert again.valid(token)
    again.revoke(token)
    assert not again.valid(token)


def test_broker_rejects_unknown_cases_and_arbitrary_execution(tmp_path):
    from jobpilot.interventions import InterventionBroker

    broker = InterventionBroker(tmp_path)
    assert broker.list_cases() == []
    with pytest.raises(KeyError):
        broker.command("missing", {"kind": "text", "text": "secret"})


def test_pause_inputs_run_on_browser_thread_and_do_not_persist_secrets(tmp_path):
    from playwright.sync_api import sync_playwright

    from jobpilot.interventions import InterventionBroker

    broker = InterventionBroker(tmp_path)
    result = {}

    def browser_thread():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.goto(
                'data:text/html,<label>Verification code<input autocomplete="one-time-code" id="code"></label>'
            )
            result["outcome"] = broker.pause(
                page,
                {"id": 1, "company": "Fixture", "title": "Engineer"},
                kind="code",
                note="Enter verification code",
                ready=lambda: page.locator("#code").input_value() == "Secret8Z",
                timeout_seconds=12,
            )
            result["input"] = page.locator("#code").input_value()
            browser.close()

    thread = threading.Thread(target=browser_thread)
    thread.start()
    deadline = time.monotonic() + 8
    case = None
    while time.monotonic() < deadline:
        cases = broker.list_cases()
        if cases and cases[0].get("view_id"):
            case = cases[0]
            break
        time.sleep(0.03)
    assert case is not None
    frame = broker.frame(case["id"])
    assert frame["png"].startswith(b"\x89PNG")
    with pytest.raises(ValueError):
        broker.command(case["id"], {"kind": "evaluate", "script": "steal()"})
    with pytest.raises(ValueError):
        broker.command(case["id"], {"kind": "text", "text": "secret", "view_id": "stale"})
    broker.command(case["id"], {"kind": "code", "code": "Secret8Z", "view_id": frame["view_id"]})
    broker.command(case["id"], {"kind": "resume", "view_id": frame["view_id"]})
    thread.join(10)
    assert not thread.is_alive()
    assert result == {"outcome": "resume", "input": "Secret8Z"}
    history = (tmp_path / "remote-interventions.json").read_text()
    assert "Secret8Z" not in history and "png" not in history and "commands" not in history
    assert broker.get_case(case["id"])["state"] == "completed"
    with pytest.raises(ValueError):
        broker.frame(case["id"])


def test_restart_marks_waiting_tickets_interrupted(tmp_path):
    from jobpilot.interventions import InterventionBroker

    (tmp_path / "remote-interventions.json").write_text(
        json.dumps([{"id": "case", "state": "waiting", "created_at": "2026-10-15"}])
    )
    broker = InterventionBroker(tmp_path)
    assert broker.get_case("case")["state"] == "interrupted"
