import threading
import time

import pytest
from test_api import api


@pytest.fixture
def documents(tmp_path, monkeypatch):
    client = api(tmp_path, monkeypatch)
    from jobpilot import service

    folder = tmp_path / "applications" / "example-role"
    folder.mkdir(parents=True)
    headers = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    return service, client, headers, folder


@pytest.mark.parametrize("name", ["resume.pdf", "cover-letter.docx"])
def test_open_document_uses_default_app_and_does_not_wait_for_worker(documents, monkeypatch, name):
    service, client, headers, folder = documents
    target = folder / name
    target.write_bytes(b"document fixture")
    opened = []
    monkeypatch.setattr("os.startfile", lambda path: opened.append(str(path)))
    entered, release = threading.Event(), threading.Event()

    def busy_worker():
        with service.application_lock:
            entered.set()
            release.wait(5)

    thread = threading.Thread(target=busy_worker)
    thread.start()
    assert entered.wait(2)
    try:
        started = time.monotonic()
        response = client.post("/api/artifact/open", headers=headers, json={"path": str(target)})
        assert time.monotonic() - started < 1.5
        assert response.status_code == 200
        assert response.json() == {"ok": True, "opened": True, "name": name}
        assert opened == [str(target.resolve())]
        assert not release.is_set()
    finally:
        release.set()
        thread.join(5)


def test_open_document_requires_token(documents, monkeypatch):
    _, client, _, folder = documents
    target = folder / "resume.pdf"
    target.write_bytes(b"document")
    opened = []
    monkeypatch.setattr("os.startfile", lambda path: opened.append(path))
    assert client.post("/api/artifact/open", json={"path": str(target)}).status_code == 403
    assert opened == []


@pytest.mark.parametrize("name", ["run.exe", "page.html", "report.pdf.cmd", "script.py"])
def test_open_document_cannot_execute_other_artifacts(documents, monkeypatch, name):
    _, client, headers, folder = documents
    target = folder / name
    target.write_text("fixture", encoding="utf-8")
    opened = []
    monkeypatch.setattr("os.startfile", lambda path: opened.append(path))
    response = client.post("/api/artifact/open", headers=headers, json={"path": str(target)})
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]
    assert opened == []


def test_open_document_rejects_missing_file_and_path_escape(documents, tmp_path, monkeypatch):
    _, client, headers, folder = documents
    outside = tmp_path / "private.pdf"
    outside.write_text("private", encoding="utf-8")
    opened = []
    monkeypatch.setattr("os.startfile", lambda path: opened.append(path))
    for path, status in [(outside, 403), (folder / "missing.pdf", 404)]:
        response = client.post("/api/artifact/open", headers=headers, json={"path": str(path)})
        assert response.status_code == status
        assert str(tmp_path) not in response.text
    assert opened == []


@pytest.mark.parametrize("path", [None, {}, [], 42, "bad\x00path"])
def test_open_document_invalid_path_is_a_friendly_error(documents, path):
    _, client, headers, _ = documents
    response = client.post("/api/artifact/open", headers=headers, json={"path": path})
    assert response.status_code == 400
    assert response.json()["detail"]


def test_default_app_failure_suggests_download_without_exposing_paths(documents, monkeypatch):
    _, client, headers, folder = documents
    target = folder / "resume.pdf"
    target.write_bytes(b"document")

    def fail(_):
        raise OSError(f"System failure at {target}")

    monkeypatch.setattr("os.startfile", fail)
    response = client.post("/api/artifact/open", headers=headers, json={"path": str(target)})
    assert response.status_code == 503
    assert "Download" in response.json()["detail"]
    assert str(target) not in response.text


def test_download_still_returns_attachment_with_original_filename(documents):
    _, client, _, folder = documents
    target = folder / "resume.pdf"
    target.write_bytes(b"%PDF-document fixture")
    response = client.get("/api/artifact", params={"path": str(target)})
    assert response.status_code == 200
    assert response.content == target.read_bytes()
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="resume.pdf"'
