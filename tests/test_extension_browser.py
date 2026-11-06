"""Real MV3 fixture tests; test-only localhost grant simulates Chrome action activeTab.

The shipping manifest has only loopback API host access. Headless browser automation
cannot click Chrome's toolbar, so a copied manifest grants only this fixture origin.
"""

import functools
import http.server
import importlib
import json
import os
import shutil
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from playwright.sync_api import sync_playwright

EXTENSION = Path(__file__).resolve().parents[1] / "extension"
PROFILE = {
    "first_name": "Ada",
    "last_name": "Example",
    "email": "ada@example.test",
    "country": "United States",
    "city": "Exampleville",
    "phone": "+1 202 555 0142",
    "requires_sponsorship": False,
    "experience": [
        {"company": "Fictional One", "title": "Engineer"},
        {"company": "Fictional Two", "title": "Analyst"},
    ],
}


@pytest.fixture
def extension_api_server(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path / "service"))
    monkeypatch.setenv("JOBPILOT_TESTING", "1")
    import jobpilot.service as service

    service = importlib.reload(service)
    service.store.set(
        "profile", {**PROFILE, "first_name": "Imported", "password": "must-not-export"}
    )
    document = tmp_path / "service" / "applications" / "fixture" / "fictional.pdf"
    document.parent.mkdir(parents=True)
    document.write_bytes(b"%PDF-1.4 fictional prepared resume")
    job = service.store.add_job(
        {
            "url": "https://example.test/jobs/fixture",
            "company": "Fictional Co",
            "title": "Engineer",
            "documents": {"resume_pdf": str(document)},
        }
    )
    seen = []

    async def recording_app(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            seen.append((scope["method"], scope["path"], headers.get(b"origin", b"").decode()))
        await service.app(scope, receive, send)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            recording_app, host="127.0.0.1", port=port, log_level="error", lifespan="off"
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}", service, seen, job
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


@pytest.fixture
def extension_browser(tmp_path, request):
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(QuietHandler, directory=str(EXTENSION / "fixtures"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    extension = tmp_path / "extension"
    shutil.copytree(EXTENSION, extension)
    api = (
        request.getfixturevalue("extension_api_server")
        if getattr(request, "param", None) == "live"
        else None
    )
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    manifest["host_permissions"].append("http://127.0.0.1/*")
    if api:
        background = extension / "background.js"
        background.write_text(
            background.read_text(encoding="utf-8").replace("http://127.0.0.1:8765", api[0]),
            encoding="utf-8",
        )
        manifest["content_security_policy"]["extension_pages"] = manifest[
            "content_security_policy"
        ]["extension_pages"].replace("http://127.0.0.1:8765", api[0])
    (extension / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    try:
        with sync_playwright() as runtime:
            context = runtime.chromium.launch_persistent_context(
                str(tmp_path / "chrome"),
                channel="chromium",
                headless=True,
                args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
            )
            worker = (
                context.service_workers[0]
                if context.service_workers
                else context.wait_for_event("serviceworker")
            )
            extension_id = worker.url.split("/")[2]
            options = context.new_page()
            options.goto(f"chrome-extension://{extension_id}/options.html")
            options.evaluate(
                "p => chrome.runtime.sendMessage({type:'saveProfile', profile:p})", PROFILE
            )
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/application.html")
            tab_id = worker.evaluate(
                "async () => (await chrome.tabs.query({})).find(t => t.url?.includes('/application.html')).id"
            )
            yield context, options, page, tab_id, api
            context.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def send(options, tab_id, kind="fill", **extra):
    return options.evaluate(
        "m => chrome.runtime.sendMessage(m)", {"type": kind, "tabId": tab_id, **extra}
    )


def test_extension_fills_controlled_inputs_preserves_answers_and_never_submits(extension_browser):
    _, options, page, tab, _ = extension_browser
    result = send(options, tab)
    assert result["ok"], result
    assert page.locator("#first").input_value() == "Ada"
    assert page.evaluate("fixture.controlledValue") == "Ada"
    assert page.locator("#last").input_value() == "User answer"
    assert page.locator("#email").input_value() == "ada@example.test"
    assert page.locator("#country").input_value() == "US"
    assert page.locator('input[name="sponsor"][value="no"]').is_checked()
    assert page.locator("#ssn").input_value() == ""
    assert page.locator("#password").input_value() == ""
    assert not page.locator("#consent").is_checked()
    assert page.locator("#unknown").input_value() == ""
    assert page.locator("#company1").input_value() == "Fictional One"
    assert page.locator("#company2").input_value() == "Fictional Two"
    assert page.locator("#shadow input").input_value() == "Exampleville"
    assert page.frame_locator("#same").locator("#phone").input_value() == "+1 202 555 0142"
    assert page.evaluate("fixture.submitted + fixture.next") == 0
    assert any("Why this company" in item["label"] for item in result["report"]["unanswered"])
    assert page.locator("#resume").evaluate("e => e.files.length") == 0


def test_extension_explicit_replace_undo_and_dynamic_reclick(extension_browser):
    _, options, page, tab, _ = extension_browser
    assert send(options, tab, replace=True)["ok"]
    assert page.locator("#last").input_value() == "Example"
    # Later user edits should survive Undo.
    page.locator("#email").fill("user@example.test")
    result = send(options, tab, "undo")
    assert result["ok"]
    assert page.locator("#last").input_value() == "User answer"
    assert page.locator("#first").input_value() == ""
    assert page.locator("#email").input_value() == "user@example.test"
    page.evaluate(
        "document.body.insertAdjacentHTML('beforeend', '<label>Website<input id=dynamic></label>')"
    )
    options.evaluate(
        "p => chrome.runtime.sendMessage({type:'saveProfile',profile:p})",
        {**PROFILE, "website": "https://example.test"},
    )
    assert send(options, tab)["ok"]
    assert page.locator("#dynamic").input_value() == "https://example.test"


def test_extension_explicit_resume_attachment_only_and_undo(extension_browser):
    _, options, page, tab, _ = extension_browser
    saved = options.evaluate(
        "async () => chrome.runtime.sendMessage({type:'saveResume', file:{name:'fictional.pdf', data:Array.from(new TextEncoder().encode('%PDF-1.4 fictional fixture'))}})"
    )
    assert saved["ok"], saved
    assert page.locator("#resume").evaluate("e => e.files.length") == 0
    assert send(options, tab, "attach")["ok"]
    assert page.locator("#resume").evaluate("e => e.files[0].name") == "fictional.pdf"
    assert page.locator("#cover").evaluate("e => e.files.length") == 0
    second = send(options, tab, "attach")
    assert second["ok"]
    assert second["report"]["preserved"]
    assert send(options, tab, "undo")["ok"]
    # A no-op Attach leaves the preceding attachment as the last undoable change.
    assert page.locator("#resume").evaluate("e => e.files.length") == 0


def test_extension_storage_secrets_are_not_available_in_content_world(extension_browser):
    context, options, page, tab, _ = extension_browser
    worker = context.service_workers[0]
    worker.evaluate("chrome.storage.local.set({connection:{token:'test-secret'}})")
    send(options, tab)
    result = worker.evaluate(
        """async tabId => {
      const results = await chrome.scripting.executeScript({target:{tabId},func:async()=>{
        try { return await chrome.storage.local.get('connection'); } catch { return 'blocked'; }
      }}); return results[0].result;
    }""",
        tab,
    )
    assert result == "blocked"
    assert page.evaluate("typeof window.JobPilotAutofill") == "undefined"


def test_extension_ambiguous_history_and_custom_controls_stay_manual(extension_browser):
    _, options, page, tab, _ = extension_browser
    page.evaluate("""() => {
      document.querySelectorAll('fieldset').forEach(e => { if (e.querySelector('legend')?.textContent.startsWith('Employment')) e.querySelector('legend').textContent='Employment history'; });
      document.body.insertAdjacentHTML('beforeend','<label>Favorite color<div role="combobox" aria-label="Favorite color" tabindex="0">Choose a color</div></label>');
    }""")
    response = send(options, tab)
    assert response["ok"]
    assert page.locator("#company1").input_value() == ""
    assert page.locator("#company2").input_value() == ""
    assert any("ambiguous" in row["reason"] for row in response["report"]["unanswered"])
    assert any("Favorite color" in row["label"] for row in response["report"]["unanswered"])


def test_extension_rejected_native_value_restores_existing_answer(extension_browser):
    _, options, page, tab, _ = extension_browser
    page.evaluate(
        "document.body.insertAdjacentHTML('beforeend','<label>Salary expectation<input type=number id=salary value=123></label>')"
    )
    options.evaluate(
        "p=>chrome.runtime.sendMessage({type:'saveProfile',profile:p})",
        {**PROFILE, "salary_expectation": "Negotiable"},
    )
    response = send(options, tab, replace=True)
    assert response["ok"]
    assert page.locator("#salary").input_value() == "123"
    assert any("rejected" in row["reason"] for row in response["report"]["unanswered"])


def test_extension_skips_invisible_fields_and_other_people_but_fills_below_fold(extension_browser):
    _, options, page, tab, _ = extension_browser
    page.evaluate("""() => {
      document.body.insertAdjacentHTML('beforeend', `
        <div style="opacity:0"><label>Email address<input id="invisible-ancestor"></label></div>
        <label>Email address<input id="invisible-self" style="opacity:0"></label>
        <div style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0px,0px,0px,0px)"><label>Email address<input id="invisible-clipped"></label></div>
        <div style="opacity:0" id="invisible-shadow"></div>
        <iframe style="opacity:0" id="invisible-frame" title="Hidden form" src="frame.html"></iframe>
        <fieldset><legend>Supervisor information</legend><label>Email address<input id="supervisor-email"></label><label>Phone number<input id="supervisor-phone"></label></fieldset>
        <label>Do you attest you are authorized to work in the United States?<select id="attest"><option value="">Choose</option><option>Yes</option><option>No</option></select></label>
        <label>Are you eligible to work nights and weekends?<select id="schedule"><option value="">Choose</option><option>Yes</option><option>No</option></select></label>
        <div style="margin-top:2500px"><label>Email address<input id="below-fold"></label></div>`);
      document.querySelector('#invisible-shadow').attachShadow({mode:'open'}).innerHTML='<label>Email address<input id="shadow-email"></label>';
    }""")
    page.frame_locator("#invisible-frame").locator("#phone").wait_for(state="attached")
    options.evaluate(
        "p=>chrome.runtime.sendMessage({type:'saveProfile',profile:p})",
        {**PROFILE, "work_authorized": True},
    )
    result = send(options, tab)
    assert result["ok"]
    for selector in [
        "#invisible-ancestor",
        "#invisible-self",
        "#invisible-clipped",
        "#invisible-shadow input",
        "#supervisor-email",
        "#supervisor-phone",
        "#attest",
        "#schedule",
    ]:
        assert page.locator(selector).input_value() == "", selector
    assert page.frame_locator("#invisible-frame").locator("#phone").input_value() == ""
    assert page.locator("#below-fold").input_value() == PROFILE["email"]


def test_extension_popup_and_options_are_readable_and_keyboard_labelled(extension_browser):
    context, options, _, _, _ = extension_browser
    errors = []
    options.on("pageerror", lambda error: errors.append(str(error)))
    options.set_viewport_size({"width": 1020, "height": 920})
    options.reload()
    options.get_by_label("First name", exact=True).wait_for()
    assert options.locator("#first_name").input_value() == "Ada"
    assert options.evaluate("parseFloat(getComputedStyle(document.body).fontSize)") >= 16
    assert options.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshots = (
        Path(os.environ["JOBPILOT_EXTENSION_SCREENSHOTS"])
        if os.environ.get("JOBPILOT_EXTENSION_SCREENSHOTS")
        else None
    )
    if screenshots:
        screenshots.mkdir(parents=True, exist_ok=True)
        options.screenshot(path=str(screenshots / "extension-options.png"))
    options.set_viewport_size({"width": 390, "height": 844})
    assert options.evaluate("document.documentElement.scrollWidth <= innerWidth")
    extension_id = context.service_workers[0].url.split("/")[2]
    popup = context.new_page()
    popup.set_viewport_size({"width": 420, "height": 850})
    popup.on("pageerror", lambda error: errors.append(str(error)))
    popup.goto(f"chrome-extension://{extension_id}/popup.html")
    popup.get_by_role("button", name="Autofill this page").wait_for()
    popup.get_by_text("Local profile · Ada Example", exact=True).wait_for()
    assert popup.get_by_label("Replace existing answers and files").count() == 1
    assert popup.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if screenshots:
        popup.screenshot(path=str(screenshots / "extension-popup.png"))
    assert not errors


def test_extension_options_edit_import_backup_and_invalid_resume_preserve_saved_data(
    extension_browser,
):
    _, options, _, _, _ = extension_browser
    options.reload()
    options.locator("#first_name").fill("Edited")
    options.get_by_role("button", name="Save profile").first.click()
    options.get_by_role("status").filter(has_text="Profile saved locally").wait_for()
    state = options.evaluate("chrome.runtime.sendMessage({type:'getState'})")
    assert state["profile"]["first_name"] == "Edited"
    options.once("dialog", lambda dialog: dialog.accept())
    options.locator("#import").set_input_files(
        {
            "name": "fictional-profile.json",
            "mimeType": "application/json",
            "buffer": b'{"schema_version":1,"profile":{"first_name":"Imported JSON"}}',
        }
    )
    options.get_by_role("status").filter(has_text="JSON profile imported").wait_for()
    assert options.locator("#first_name").input_value() == "Imported JSON"
    options.once("dialog", lambda dialog: dialog.accept())
    options.get_by_role("button", name="Restore previous profile").click()
    options.get_by_role("status").filter(has_text="Previous profile restored").wait_for()
    assert options.locator("#first_name").input_value() == "Edited"
    options.locator("#import").set_input_files(
        {"name": "broken.json", "mimeType": "application/json", "buffer": b"{bad json"}
    )
    options.get_by_role("status").filter(has_text="not valid profile JSON").wait_for()
    assert options.locator("#first_name").input_value() == "Edited"
    options.locator("#resume-file").set_input_files(
        {"name": "fictional.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 fictional"}
    )
    options.get_by_role("status").filter(has_text="Resume saved locally").wait_for()
    options.locator("#resume-file").set_input_files(
        {"name": "bad.pdf", "mimeType": "application/pdf", "buffer": b"not a PDF"}
    )
    options.get_by_role("status").filter(has_text="contents do not match").wait_for()
    state = options.evaluate("chrome.runtime.sendMessage({type:'getState'})")
    assert state["resume"]["name"] == "fictional.pdf"
    assert state["profile"]["first_name"] == "Edited"


def test_extension_explicit_boolean_choices_education_and_file_replacement(extension_browser):
    _, options, page, tab, _ = extension_browser
    page.evaluate("""() => {
      document.body.insertAdjacentHTML('beforeend', `
        <label>Are you legally authorized to work?<select id="authorized"><option value="">Choose</option><option value="Y">Yes</option><option value="N">No</option></select></label>
        <fieldset><legend>Can you work without sponsorship?</legend><label><input type="radio" name="without" value="y">Yes</label><label><input type="radio" name="without" value="n">No</label></fieldset>
        <fieldset><legend>Education 1</legend><label>Institution<input id="school"></label><label>Degree<input id="degree"></label><label>Start date<input id="edu-start" type="month"></label></fieldset>
        <fieldset><legend>Employment 1</legend><label>Description<textarea id="description"></textarea></label></fieldset>`);
    }""")
    response = options.evaluate(
        "p=>chrome.runtime.sendMessage({type:'saveProfile',profile:p})",
        {
            **PROFILE,
            "work_authorized": None,
            "education": [{"institution": "Fictional College", "degree": "BS", "start": "2020-08"}],
            "experience": [
                {"company": "Fictional One", "description": "Built fictional tools."},
                {"company": "Fictional Two"},
            ],
        },
    )
    assert response["ok"]
    assert send(options, tab)["ok"]
    assert page.locator("#authorized").input_value() == ""
    assert page.locator('input[name="without"][value="y"]').is_checked()
    assert page.locator("#school").input_value() == "Fictional College"
    assert page.locator("#degree").input_value() == "BS"
    assert page.locator("#edu-start").input_value() == "2020-08"
    assert page.locator("#description").input_value() == "Built fictional tools."
    page.locator("#resume").set_input_files(
        {
            "name": "user-selected.pdf",
            "mimeType": "application/pdf",
            "buffer": b"%PDF-user selected",
        }
    )
    saved = options.evaluate(
        "chrome.runtime.sendMessage({type:'saveResume',file:{name:'replacement.pdf',data:Array.from(new TextEncoder().encode('%PDF-replacement'))}})"
    )
    assert saved["ok"]
    assert send(options, tab, "attach")["report"]["preserved"]
    assert page.locator("#resume").evaluate("e=>e.files[0].name") == "user-selected.pdf"
    assert send(options, tab, "attach", replace=True)["report"]["filled"]
    assert page.locator("#resume").evaluate("e=>e.files[0].name") == "replacement.pdf"
    assert send(options, tab, "undo")["ok"]
    assert page.locator("#resume").evaluate("e=>e.files[0].name") == "user-selected.pdf"


@pytest.mark.parametrize("extension_browser", ["live"], indirect=True)
def test_extension_pairs_imports_downloads_and_disconnects_over_real_http(extension_browser):
    context, options, page, tab, api = extension_browser
    base, service, seen, job = api
    extension_id = context.service_workers[0].url.split("/")[2]
    pending = httpx.post(
        base + "/api/extension/pairing",
        headers={"X-JobPilot-Token": service.TOKEN},
        json={"extension_id": extension_id},
    )
    assert pending.status_code == 200, pending.text
    paired = options.evaluate(
        "code=>chrome.runtime.sendMessage({type:'pair',code})", pending.json()["code"]
    )
    assert paired["ok"], paired
    imported = options.evaluate(
        "chrome.runtime.sendMessage({type:'importJobPilot',confirmed:true})"
    )
    assert imported["ok"], (imported, seen)
    state = options.evaluate("chrome.runtime.sendMessage({type:'getState'})")
    assert state["profile"]["first_name"] == "Imported"
    assert "password" not in state["profile"]
    assert "token" not in state["connection"]
    docs = options.evaluate("chrome.runtime.sendMessage({type:'listDocuments'})")
    assert docs["ok"] and docs["documents"][0]["name"] == "fictional.pdf", (docs, seen)
    selected = options.evaluate(
        "id=>chrome.runtime.sendMessage({type:'selectDocument',jobId:id,kind:'resume_pdf'})",
        job["id"],
    )
    assert selected["ok"], (selected, seen)
    assert page.locator("#resume").evaluate("e=>e.files.length") == 0
    assert send(options, tab, "attach")["ok"]
    assert page.locator("#resume").evaluate("e=>e.files[0].name") == "fictional.pdf"
    assert options.evaluate("chrome.runtime.sendMessage({type:'disconnect'})")["ok"]
    assert not options.evaluate("chrome.runtime.sendMessage({type:'getState'})")["connection"]
    statuses = context.service_workers[0].evaluate(
        """async base => {
      const results=[];
      for (const path of ['/api/session','/api/state']) {
        const response=await fetch(base+path,{credentials:'omit'});
        results.push(response.status);
      }
      return results;
    }""",
        base,
    )
    assert statuses == [403, 403]
    assert all(not row[2] for row in seen if row[1] in ["/api/session", "/api/state"])
    assert {
        row[2]
        for row in seen
        if row[1].startswith("/api/extension/") and row[1] != "/api/extension/pairing"
    } == {"chrome-extension://" + extension_id}
