"""Check a built wheel in an isolated target without starting worker threads."""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE = r"""
import os
import sys
from pathlib import Path

import jobpilot
from fastapi.testclient import TestClient
from jobpilot import service
from jobpilot.assets import asset_directory
from jobpilot.interventions import InterventionBroker
from jobpilot.remote import create_remote_app
from jobpilot.remote_auth import RemoteAuth

target, data = (Path(value).resolve() for value in sys.argv[1:])
package = Path(jobpilot.__file__).resolve().parent
assert package.is_relative_to(target), f"Imported outside wheel target: {package}"
assert Path(service.__file__).resolve().is_relative_to(target)
assert service.DATA == data, "Service did not use isolated smoke data"
assert os.environ["JOBPILOT_TESTING"] == "1"

for name in ("web", "remote_web"):
    assert asset_directory(name).is_relative_to(package), f"Unbundled {name} assets"

# No context manager: lifespan is deliberately not entered, so workers never start.
dashboard = TestClient(service.app, base_url="http://127.0.0.1:8765")
try:
    response = dashboard.get("/api/state")
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["profile"]["sample_profile"] is True, "Seed is not marked fictional"
    assert state["profile"]["email"].endswith("@example.com")
    assert state["jobs"] == []
    for key in ("search_enabled", "submission_enabled", "remote_intervention_enabled"):
        assert state["settings"][key] is False, f"Unsafe first-run setting: {key}"
    for route, content_type in (
        ("/", "text/html"),
        ("/style.css", "text/css"),
        ("/app.js", "text/javascript"),
    ):
        response = dashboard.get(route)
        assert response.status_code == 200, f"Dashboard {route}: {response.status_code}"
        assert response.content, f"Empty dashboard {route}"
        assert response.headers["content-type"].startswith(content_type)
finally:
    dashboard.close()

# Exercise the real portal routes; the vault is memory-only and no browser is opened.
vault = {}
auth = RemoteAuth(data / "portal", vault_get=lambda: vault.get("secret"),
                  vault_set=lambda value: vault.update(secret=value))
broker = InterventionBroker(data / "portal")
portal = TestClient(create_remote_app(broker, auth), base_url="http://127.0.0.1:8766")
try:
    for route, content_type in (
        ("/", "text/html"),
        ("/app.js", "text/javascript"),
        ("/style.css", "text/css"),
        ("/sw.js", "text/javascript"),
        ("/manifest.webmanifest", "application/manifest+json"),
        ("/icons/icon.svg", "image/svg+xml"),
        ("/icons/icon-192.png", "image/png"),
        ("/icons/icon-512.png", "image/png"),
    ):
        response = portal.get(route)
        assert response.status_code == 200, f"Portal {route}: {response.status_code}"
        assert response.content, f"Empty portal {route}"
        assert response.headers["content-type"].startswith(content_type)
finally:
    portal.close()

print("Wheel smoke passed: isolated import, fictional paused profile, dashboard and portal assets.")
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "wheel", nargs="?", type=Path, help="Wheel to check; defaults to dist/*.whl"
    )
    args = parser.parse_args()
    if args.wheel:
        wheel = args.wheel.resolve()
    else:
        wheels = list((Path(__file__).resolve().parents[1] / "dist").glob("*.whl"))
        if len(wheels) != 1:
            parser.error("Pass a wheel path or leave exactly one wheel in dist/.")
        wheel = wheels[0]
    if not wheel.is_file() or wheel.suffix != ".whl":
        parser.error(f"Wheel not found: {wheel}")

    with tempfile.TemporaryDirectory(prefix="jobpilot-wheel-") as temporary:
        scratch = Path(temporary)
        target, data = scratch / "installed", scratch / "data"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--no-deps",
                "--target",
                str(target),
                str(wheel),
            ],
            cwd=scratch,
            check=True,
            timeout=120,
        )
        env = os.environ.copy()
        env.update(
            PYTHONPATH=str(target),
            PYTHONNOUSERSITE="1",
            JOBPILOT_TESTING="1",
            JOBPILOT_DATA_DIR=str(data),
        )
        env.pop("JOBPILOT_DESKTOP_EXE", None)
        env.pop("PYTHONOPTIMIZE", None)
        subprocess.run(
            [sys.executable, "-c", PROBE, str(target), str(data)],
            cwd=scratch,
            env=env,
            check=True,
            timeout=45,
        )


if __name__ == "__main__":
    main()
