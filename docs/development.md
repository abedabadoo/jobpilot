# Development

Use Windows and Python 3.13. Follow [setup](setup.md) to create `.venv`, install `requirements.lock` and download Playwright Chromium. Keep a dedicated `JOBPILOT_DATA_DIR` for development, with a fictional profile and searches paused.

Install the development and build extras, then run checks from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Browser tests use local HTTP fixtures and temporary data. Configure `PLAYWRIGHT_BROWSERS_PATH` to the directory where Chromium was installed. Tests that use Windows tray, credential-vault or startup APIs need Windows.

## Working boundaries

- Keep test data fictional. Do not commit profiles, credentials, resumes, application evidence, browser state, pairing links, `installed_paths.json`, downloaded runtimes or build output.
- Add regression tests for preparation queues, manual application tracking, removal tombstones, keyword extraction, email status, and external links while the worker is busy.
- Exercise assistant workflows against local fixtures. Keep the dormant submission and remote regression tests passing; live submissions and remote sessions are not release smoke tests.
- Keep local assets in `web/` and `remote_web/`. Preserve the loopback API boundary and the isolated remote companion.
- Validate model-selected fact IDs against the saved profile. Include relevant role tools in editable drafts without inventing employers, dates, credentials, or numerical achievements. Render and inspect both PDF and Word exports when changing document layouts.

## Build

`scripts/Build-JobPilot.ps1` builds the desktop launcher from `.venv` into `build/desktop-dist/JobPilot`. Use `-BuildPython` for another build environment. The installer combines that output with service source and assets; see [setup](setup.md). Review [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) when changing dependencies or bundled tools.

Build and check the Python distributions separately:

```powershell
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe scripts/smoke-wheel.py
```

The wheel check installs into a temporary directory and verifies the bundled dashboard and remote portal with fictional data. It does not start workers or open employer sites.

Contribution and disclosure procedures are in [CONTRIBUTING.md](../CONTRIBUTING.md) and [SECURITY.md](../SECURITY.md).
