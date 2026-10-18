import importlib

import pytest
from test_api import api


@pytest.mark.parametrize("name", ["web", "remote_web"])
def test_source_checkout_uses_adjacent_asset_directories(tmp_path, monkeypatch, name):
    assets = importlib.import_module("jobpilot.assets")
    monkeypatch.setattr(assets, "__file__", str(tmp_path / "jobpilot" / "assets.py"))
    source = tmp_path / name
    source.mkdir()
    assert assets.asset_directory(name) == source


@pytest.mark.parametrize("name", ["web", "remote_web"])
def test_packaged_assets_take_precedence_over_unrelated_neighbor(tmp_path, monkeypatch, name):
    assets = importlib.import_module("jobpilot.assets")
    monkeypatch.setattr(assets, "__file__", str(tmp_path / "jobpilot" / "assets.py"))
    (tmp_path / name).mkdir()
    packaged = tmp_path / "jobpilot" / "_assets" / name
    packaged.mkdir(parents=True)
    assert assets.asset_directory(name) == packaged


@pytest.mark.parametrize("name", ["web", "remote_web"])
def test_installed_package_falls_back_to_bundled_assets(tmp_path, monkeypatch, name):
    assets = importlib.import_module("jobpilot.assets")
    monkeypatch.setattr(assets, "__file__", str(tmp_path / "jobpilot" / "assets.py"))
    packaged = tmp_path / "jobpilot" / "_assets" / name
    packaged.mkdir(parents=True)
    assert assets.asset_directory(name) == packaged


def test_dashboard_serves_the_installed_asset_fallback(tmp_path, monkeypatch):
    assets = importlib.import_module("jobpilot.assets")
    monkeypatch.setattr(assets, "__file__", str(tmp_path / "package" / "assets.py"))
    web = tmp_path / "package" / "_assets" / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text("<h1>Installed dashboard</h1>", encoding="utf-8")
    response = api(tmp_path / "data", monkeypatch).get("/")
    assert response.status_code == 200
    assert response.text == "<h1>Installed dashboard</h1>"
