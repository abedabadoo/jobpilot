"""The extension credential must never grant access to dashboard or private files."""

import importlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

EXTENSION = "a" * 32
ORIGIN = "chrome-extension://" + EXTENSION


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBPILOT_TESTING", "1")
    import jobpilot.service as service

    service = importlib.reload(service)
    return TestClient(service.app), service


def dashboard(service):
    return {"X-JobPilot-Token": service.TOKEN}


def issue(client, service, extension_id=EXTENSION):
    result = client.post(
        "/api/extension/pairing", json={"extension_id": extension_id}, headers=dashboard(service)
    )
    assert result.status_code == 200, result.text
    return result.json()


def pair(client, service):
    code = issue(client, service)["code"]
    result = client.post("/api/extension/pair", json={"code": code}, headers={"Origin": ORIGIN})
    assert result.status_code == 200, result.text
    return result.json()


def auth(connection, origin=ORIGIN):
    return {"Origin": origin, "Authorization": "Bearer " + connection["token"]}


def test_pairing_is_one_use_origin_bound_and_digest_only(api):
    client, service = api
    pending = issue(client, service)
    expires = datetime.fromisoformat(pending["expires_at"])
    assert 290 < (expires - datetime.now(timezone.utc)).total_seconds() <= 300
    assert (
        client.post(
            "/api/extension/pair",
            json={"code": pending["code"]},
            headers={"Origin": "chrome-extension://" + "b" * 32},
        ).status_code
        == 403
    )
    response = client.post(
        "/api/extension/pair", json={"code": pending["code"]}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    connection = response.json()
    assert connection["pairing_id"] and len(connection["token"]) >= 40
    assert (
        89.99
        < (
            datetime.fromisoformat(connection["expires_at"]) - datetime.now(timezone.utc)
        ).total_seconds()
        / 86400
        <= 90
    )
    assert (
        client.post(
            "/api/extension/pair", json={"code": pending["code"]}, headers={"Origin": ORIGIN}
        ).status_code
        == 403
    )
    with service.store.connect() as db:
        saved = db.execute(
            "SELECT value FROM settings WHERE key='_extension_connections'"
        ).fetchone()[0]
    assert connection["token"] not in saved and pending["code"] not in saved


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize(
    "origin", [None, "null", "https://example.com", ORIGIN + "/", "chrome-extension://" + "b" * 32]
)
def test_profile_rejects_wrong_origin_even_with_token(api, origin, method):
    client, service = api
    connection = pair(client, service)
    headers = auth(connection)
    if origin is None:
        headers.pop("Origin")
    else:
        headers["Origin"] = origin
    assert client.request(method, "/api/extension/profile", headers=headers).status_code == 403


@pytest.mark.parametrize("site", ["none", "cross-site", "same-site"])
@pytest.mark.parametrize("mode", ["cors", "no-cors"])
def test_originless_browser_fetch_cannot_read_dashboard_even_with_extension_bearer(api, site, mode):
    client, service = api
    connection = pair(client, service)
    headers = {
        "Sec-Fetch-Site": site,
        "Sec-Fetch-Mode": mode,
        "Authorization": "Bearer " + connection["token"],
    }
    for path in ["/api/session", "/api/state", "/api/health", "/api/report"]:
        response = client.get(path, headers=headers)
        assert response.status_code == 403, path
        assert service.TOKEN not in response.text


def test_native_and_same_origin_dashboard_reads_continue_to_work(api):
    client, service = api
    for headers in [
        {},
        {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"},
        {"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate"},
    ]:
        assert client.get("/api/session", headers=headers).json() == {"token": service.TOKEN}


def test_post_read_aliases_keep_strict_origin_bearer_and_empty_body_support(api, tmp_path):
    client, service = api
    connection = pair(client, service)
    root = tmp_path / "applications"
    root.mkdir()
    resume = root / "resume.pdf"
    resume.write_bytes(b"%PDF-test")
    job = service.store.add_job(
        {"url": "https://example.com/post-read", "documents": {"resume_pdf": str(resume)}}
    )
    for path in [
        "/api/extension/profile",
        "/api/extension/documents",
        f"/api/extension/documents/{job['id']}/resume_pdf",
    ]:
        expected = client.get(path, headers=auth(connection))
        response = client.post(path, headers=auth(connection))
        assert response.status_code == 200, response.text
        assert response.content == expected.content
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert (
            client.post(
                path, headers={"Authorization": "Bearer " + connection["token"]}
            ).status_code
            == 403
        )
        assert client.post(path, headers={"Origin": ORIGIN}).status_code == 403
        assert (
            client.options(
                path,
                headers={
                    "Origin": ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization",
                },
            ).status_code
            == 204
        )


def test_extension_cannot_read_dashboard_or_authorize_connections(api):
    client, service = api
    connection = pair(client, service)
    for path in [
        "/api/session",
        "/api/state",
        "/api/health",
        "/api/artifact?path=x",
        "/api/extension/pairings",
    ]:
        assert client.get(path, headers=auth(connection)).status_code == 403, path
    assert (
        client.post(
            "/api/extension/pairing",
            json={"extension_id": EXTENSION},
            headers={**auth(connection), **dashboard(service)},
        ).status_code
        == 403
    )
    assert client.get("/api/extension/pairings").status_code == 403
    metadata = client.get("/api/extension/pairings", headers=dashboard(service)).json()
    assert metadata["pairings"][0]["pairing_id"] == connection["pairing_id"]
    assert "token" not in json.dumps(metadata)


@pytest.mark.parametrize("origin", ["chrome-extension://localhost", "chrome-extension://127.0.0.1"])
def test_extension_scheme_never_uses_dashboard_localhost_allowlist(api, origin):
    client, service = api
    assert client.get("/api/session", headers={"Origin": origin}).status_code == 403
    assert (
        client.get("/api/state", headers={"Origin": origin, **dashboard(service)}).status_code
        == 403
    )


def test_connection_survives_service_reload_but_dashboard_token_is_not_a_bearer(api):
    client, service = api
    connection = pair(client, service)
    service = importlib.reload(service)
    client = TestClient(service.app)
    assert client.get("/api/extension/profile", headers=auth(connection)).status_code == 200
    assert (
        client.get(
            "/api/extension/profile",
            headers={"Origin": ORIGIN, "Authorization": "Bearer " + service.TOKEN},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/extension/pairings", headers={"Authorization": "Bearer " + connection["token"]}
        ).status_code
        == 403
    )


def test_profile_projection_never_spreads_nested_secrets_or_guesses_booleans(api):
    client, service = api
    connection = pair(client, service)
    service.store.set(
        "profile",
        {
            "name": "Example Person",
            "email": "example@example.com",
            "password": "SECRET",
            "phone": {"password": "SECRET"},
            "work_authorized": "yes",
            "requires_sponsorship": False,
            "willing_to_relocate": 1,
            "skills": ["Python", {"password": "SECRET"}],
            "experience": [
                {
                    "company": "Example",
                    "title": "Engineer",
                    "credentials": "SECRET",
                    "facts": [
                        {"id": "SECRET", "text": "Built tools", "token": "SECRET"},
                        {"text": {"password": "SECRET"}},
                    ],
                }
            ],
            "education": [{"institution": "College", "degree": "BS", "token": "SECRET"}],
        },
    )
    service.store.set("answers", {"work_authorized": True, "password": "SECRET"})
    response = client.get("/api/extension/profile", headers=auth(connection))
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    exported = response.json()
    assert exported["schema_version"] == 1
    profile = exported["profile"]
    assert profile["name"] == "Example Person" and profile["skills"] == ["Python"]
    assert profile["requires_sponsorship"] is False
    assert profile.get("work_authorized") is None and profile.get("willing_to_relocate") is None
    assert profile["experience"][0]["description"] == "Built tools"
    assert "SECRET" not in response.text and "password" not in response.text


def test_missing_bad_revoked_and_expired_credentials(api, monkeypatch):
    client, service = api
    connection = pair(client, service)
    for headers in [{"Origin": ORIGIN}, {"Origin": ORIGIN, "Authorization": "Bearer wrong"}]:
        assert client.get("/api/extension/profile", headers=headers).status_code == 403
    response = client.post(
        f"/api/extension/pairings/{connection['pairing_id']}/revoke", headers=dashboard(service)
    )
    assert response.status_code == 200
    assert client.get("/api/extension/profile", headers=auth(connection)).status_code == 403
    connection = pair(client, service)
    from jobpilot import autofill

    monkeypatch.setattr(
        autofill, "utc_now", lambda: datetime.now(timezone.utc) + timedelta(days=91)
    )
    assert client.get("/api/extension/profile", headers=auth(connection)).status_code == 403
    assert client.get("/api/extension/pairings", headers=dashboard(service)).json() == {
        "pairings": []
    }


def test_expired_code_and_concurrent_consumption(api, monkeypatch):
    client, service = api
    pending = issue(client, service)
    from jobpilot import autofill

    now = datetime.now(timezone.utc)
    monkeypatch.setattr(autofill, "utc_now", lambda: now + timedelta(minutes=6))
    assert (
        client.post(
            "/api/extension/pair", json={"code": pending["code"]}, headers={"Origin": ORIGIN}
        ).status_code
        == 403
    )
    monkeypatch.setattr(autofill, "utc_now", lambda: now)
    pending = issue(client, service)

    def exchange(_):
        return client.post(
            "/api/extension/pair", json={"code": pending["code"]}, headers={"Origin": ORIGIN}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(exchange, range(2))) == [200, 403]


def test_disconnect_revokes_only_requesting_connection(api):
    client, service = api
    first, second = pair(client, service), pair(client, service)
    assert client.post("/api/extension/disconnect", headers=auth(first)).status_code == 200
    assert client.get("/api/extension/profile", headers=auth(first)).status_code == 403
    assert client.get("/api/extension/profile", headers=auth(second)).status_code == 200


def test_cors_preflight_is_exact_route_method_and_known_origin(api):
    client, service = api
    headers = {
        "Origin": ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    assert client.options("/api/extension/pair", headers=headers).status_code == 403
    issue(client, service)
    response = client.options("/api/extension/pair", headers=headers)
    assert response.status_code == 204 and response.headers["access-control-allow-origin"] == ORIGIN
    assert client.options("/api/state", headers=headers).status_code == 403
    assert client.options("/api/extension/pairings", headers=headers).status_code == 403
    assert (
        client.options(
            "/api/extension/profile", headers={**headers, "Access-Control-Request-Method": "DELETE"}
        ).status_code
        == 403
    )
    response = client.options(
        "/api/extension/pair",
        headers={**headers, "Access-Control-Request-Headers": "x-jobpilot-token"},
    )
    assert response.status_code == 403


def test_body_validation_and_pair_attempt_rate_limit(api, monkeypatch):
    client, service = api
    from jobpilot import autofill

    monkeypatch.setattr(autofill, "time", SimpleNamespace(monotonic=lambda: 10.0))
    assert (
        client.post(
            "/api/extension/pairing", json={"extension_id": "not-an-id"}, headers=dashboard(service)
        ).status_code
        == 400
    )
    issue(client, service)
    assert (
        client.post(
            "/api/extension/pair", content="x" * 5000, headers={"Origin": ORIGIN}
        ).status_code
        == 413
    )
    results = [
        client.post(
            "/api/extension/pair", json={"code": "invalid"}, headers={"Origin": ORIGIN}
        ).status_code
        for _ in range(12)
    ]
    assert 429 in results


def test_pair_rate_limit_covers_rolling_minute_across_clock_bucket_boundary(api, monkeypatch):
    client, service = api
    from jobpilot import autofill

    clock = [59.95]
    monkeypatch.setattr(autofill, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    issue(client, service)
    for _ in range(10):
        response = client.post(
            "/api/extension/pair", json={"code": "invalid"}, headers={"Origin": ORIGIN}
        )
        assert response.status_code == 403
        clock[0] += 0.01
    assert (
        client.post(
            "/api/extension/pair", json={"code": "invalid"}, headers={"Origin": ORIGIN}
        ).status_code
        == 429
    )
    clock[0] += 60
    assert (
        client.post(
            "/api/extension/pair", json={"code": "invalid"}, headers={"Origin": ORIGIN}
        ).status_code
        == 403
    )


def test_documents_list_and_download_exclude_private_or_oversized_paths(api, tmp_path):
    client, service = api
    connection = pair(client, service)
    root = tmp_path / "applications" / "1"
    root.mkdir(parents=True)
    resume = root / "Resume.pdf"
    resume.write_bytes(b"%PDF-safe-resume")
    secret = tmp_path / "receipts" / "receipt.pdf"
    secret.parent.mkdir()
    secret.write_bytes(b"private-receipt")
    huge = root / "big.docx"
    with huge.open("wb") as stream:
        stream.truncate(5 * 1024 * 1024 + 1)
    text = root / "secret.txt"
    text.write_text("private")
    job = service.store.add_job(
        {
            "url": "https://example.com/job",
            "title": "Engineer",
            "company": "Example",
            "documents": {
                "resume_pdf": str(resume),
                "cover_pdf": str(secret),
                "resume_docx": str(huge),
                "cover_docx": str(text),
                "evidence": str(secret),
            },
        }
    )
    response = client.get("/api/extension/documents", headers=auth(connection))
    assert response.status_code == 200
    assert response.json() == {
        "documents": [
            {
                "job_id": job["id"],
                "title": "Engineer",
                "company": "Example",
                "kind": "resume_pdf",
                "name": "Resume.pdf",
                "download_path": f"/api/extension/documents/{job['id']}/resume_pdf",
            }
        ]
    }
    assert str(tmp_path) not in response.text
    downloaded = client.get(
        f"/api/extension/documents/{job['id']}/resume_pdf", headers=auth(connection)
    )
    assert (
        downloaded.content == b"%PDF-safe-resume"
        and "attachment" in downloaded.headers["content-disposition"]
    )
    for kind in ["cover_pdf", "cover_docx", "evidence", "receipts", "../../receipts/receipt.pdf"]:
        assert client.get(
            f"/api/extension/documents/{job['id']}/{kind}", headers=auth(connection)
        ).status_code in {403, 404}
    assert (
        client.get(
            f"/api/extension/documents/{job['id']}/resume_docx", headers=auth(connection)
        ).status_code
        == 413
    )


def test_stored_symlink_document_cannot_escape_applications(api, tmp_path):
    client, service = api
    connection = pair(client, service)
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    private = private_dir / "resume.pdf"
    private.write_bytes(b"private")
    root = tmp_path / "applications"
    root.mkdir()
    link = root / "linked"
    directory_link(link, private_dir)
    job = service.store.add_job(
        {
            "url": "https://example.com/link",
            "title": "Engineer",
            "documents": {"resume_pdf": str(link / "resume.pdf")},
        }
    )
    assert client.get("/api/extension/documents", headers=auth(connection)).json() == {
        "documents": []
    }
    assert (
        client.get(
            f"/api/extension/documents/{job['id']}/resume_pdf", headers=auth(connection)
        ).status_code
        == 403
    )


def directory_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def test_applications_root_link_cannot_expose_receipts(api, tmp_path):
    client, service = api
    connection = pair(client, service)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "receipt.pdf").write_bytes(b"private receipt")
    root = tmp_path / "applications"
    directory_link(root, receipts)
    job = service.store.add_job(
        {
            "url": "https://example.com/root-link",
            "title": "Engineer",
            "documents": {"resume_pdf": str(root / "receipt.pdf")},
        }
    )
    assert client.get("/api/extension/documents", headers=auth(connection)).json() == {
        "documents": []
    }
    assert (
        client.get(
            f"/api/extension/documents/{job['id']}/resume_pdf", headers=auth(connection)
        ).status_code
        == 403
    )
