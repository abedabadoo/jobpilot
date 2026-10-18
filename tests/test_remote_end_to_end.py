"""A paired second device drives the actual retained local worker browser."""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest
from fastapi.testclient import TestClient

from jobpilot import browser
from jobpilot.interventions import InterventionBroker
from jobpilot.remote import create_remote_app
from jobpilot.remote_auth import RemoteAuth

ORIGIN = "http://127.0.0.1:8766"
PASSWORD = "local-fixture-password-482913"
CODE_VALUE = "TEST4829"
CSS = "<style>body{margin:0;font:20px sans-serif}h1{position:absolute;left:30px;top:15px}label{position:absolute;left:30px;top:90px}input{display:block;width:400px;height:44px;font-size:20px}button{position:absolute;left:30px;top:190px;width:180px;height:48px}</style>"
LOGIN = (
    CSS
    + '<h1>Sign in to apply</h1><form method="post" action="/login"><label>Password<input name="password" type="password" required></label><button type="submit">Sign in</button></form>'
)
FORM = '<h1>Security Engineer</h1><form method="post" action="/jobs/1/submit"><label>Email<input name="email" type="email" required></label><label>Resume<input name="resume" type="file" required></label><button type="submit">Submit application</button></form>'
CODE = (
    CSS
    + '<h1>Security verification</h1><form method="post" action="/jobs/1/verify"><label>Verification code<input name="code" autocomplete="one-time-code" required></label><button type="submit">Verify code</button></form>'
)
RECEIPT = "<h1>Your application has been received.</h1>"


@pytest.fixture
def employer():
    state = {"login": False, "verify": False, "final_clicks": 0, "verifications": 0, "sign_ins": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def html(self, html):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

        def do_GET(self):
            if self.path == "/feed":
                self.html("<h1>Your account</h1><button>Sign out</button>")
            elif self.path.startswith("/jobs/1"):
                self.html(
                    LOGIN
                    if state["login"] and "fixture_auth=yes" not in self.headers.get("Cookie", "")
                    else FORM
                )
            else:
                self.send_error(404)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode(
                errors="replace"
            )
            values = parse_qs(raw)
            if self.path == "/login":
                if values.get("password") != [PASSWORD]:
                    self.html(LOGIN)
                    return
                state["sign_ins"] += 1
                self.send_response(303)
                self.send_header("Set-Cookie", "fixture_auth=yes; HttpOnly; Path=/; SameSite=Lax")
                self.send_header("Location", "/feed")
                self.end_headers()
            elif self.path == "/jobs/1/submit":
                state["final_clicks"] += 1
                self.html(CODE if state["verify"] else RECEIPT)
            elif self.path == "/jobs/1/verify":
                if values.get("code") == [CODE_VALUE]:
                    state["verifications"] += 1
                    self.html(RECEIPT)
                else:
                    self.html(CODE)
            else:
                self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/jobs/1"
    yield state
    server.shutdown()
    server.server_close()


def until(predicate, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.04)
    raise AssertionError("The local remote-intervention fixture did not reach the expected state")


def launch_worker(employer, tmp_path):
    stop = threading.Event()
    broker = InterventionBroker(tmp_path / "broker", stop_event=stop)
    vault = {}
    auth = RemoteAuth(
        tmp_path / "auth",
        vault_get=lambda: vault.get("pair"),
        vault_set=lambda value: vault.update(pair=value),
    )
    result = {}
    checkpoints = []
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 local test fixture")

    def work():
        try:
            result["application"] = browser.apply(
                {
                    "id": 1,
                    "url": employer["url"],
                    "title": "Security Engineer",
                    "company": "Local fixture employer",
                },
                {"name": "Fixture Candidate", "email": "fixture@example.com"},
                {},
                {"resume_pdf": str(resume)},
                {
                    "data_dir": str(tmp_path / "worker"),
                    "_fixture_mode": True,
                    "browser_headless": True,
                    "receipt_wait_seconds": 0.5,
                    "intervention_timeout_seconds": 20,
                },
                checkpoint=lambda info: checkpoints.append(info),
                intervention_handler=broker.pause,
            )
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return broker, auth, result, checkpoints, stop, thread


def paired_client(broker, auth):
    client = TestClient(create_remote_app(broker, auth), base_url=ORIGIN)
    response = client.post(
        "/api/pair", json={"secret": auth.pairing_secret()}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    return client


def active_case(client):
    return next(
        (
            case
            for case in client.get("/api/cases").json()["cases"]
            if case["state"] == "waiting" and case["view_id"]
        ),
        None,
    )


def send(client, case, kind, **payload):
    response = client.post(
        f"/api/cases/{case['id']}/input",
        json={"kind": kind, "view_id": case["view_id"], **payload},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text


def assert_private_inputs_not_durable(tmp_path, auth, client):
    secrets = [PASSWORD, CODE_VALUE, auth.pairing_secret(), client.cookies.get("jobpilot_remote")]
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".txt"}:
            data = path.read_bytes()
            assert all(secret.encode() not in data for secret in secrets if secret), path


def test_remote_login_resumes_the_same_application_and_submits_exactly_once(employer, tmp_path):
    employer["login"] = True
    broker, auth, result, checkpoints, stop, thread = launch_worker(employer, tmp_path)
    try:
        with paired_client(broker, auth) as client:
            case = until(lambda: active_case(client))
            assert case["kind"] == "authentication" and case["submitted"] is False
            frame = client.get(f"/api/cases/{case['id']}/frame")
            assert frame.status_code == 200 and frame.content.startswith(b"\x89PNG")
            send(client, case, "click", x=70, y=130)
            send(client, case, "text", text=PASSWORD)
            send(client, case, "key", key="Enter")
            case = until(
                lambda: next(
                    (
                        item
                        for item in client.get("/api/cases").json()["cases"]
                        if item["state"] == "waiting" and item["url"].endswith("/feed")
                    ),
                    None,
                )
            )
            send(client, case, "resume")
            thread.join(15)
            assert not thread.is_alive(), result
            assert "error" not in result, result
            assert result["application"]["status"] == "confirmed", result
            assert employer["sign_ins"] == employer["final_clicks"] == 1
            assert len(checkpoints) == 1
            assert broker.list_cases()[0]["state"] == "completed"
            assert_private_inputs_not_durable(tmp_path, auth, client)
    finally:
        stop.set()
        broker.changed.set()
        thread.join(5)


def test_remote_code_yields_a_receipt_without_a_second_automated_final_click(employer, tmp_path):
    employer["verify"] = True
    broker, auth, result, checkpoints, stop, thread = launch_worker(employer, tmp_path)
    try:
        with paired_client(broker, auth) as client:
            case = until(lambda: active_case(client))
            assert case["kind"] == "verification" and case["submitted"] is True
            assert employer["final_clicks"] == 1
            send(client, case, "code", code=CODE_VALUE)
            send(client, case, "key", key="Enter")
            thread.join(15)
            assert not thread.is_alive(), result
            assert "error" not in result, result
            assert result["application"]["status"] == "confirmed", result
            assert employer["final_clicks"] == employer["verifications"] == 1
            assert len(checkpoints) == 1
            assert broker.list_cases()[0]["state"] == "completed"
            assert_private_inputs_not_durable(tmp_path, auth, client)
    finally:
        stop.set()
        broker.changed.set()
        thread.join(5)
