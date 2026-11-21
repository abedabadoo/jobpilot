# Development

Use Python 3.13. Follow [Windows setup](setup.md) or [macOS setup](macos.md) to create `.venv` and install platform dependencies. Keep a dedicated `JOBPILOT_DATA_DIR` for development, with a fictional profile and searches paused. Mac installs resolve `pyproject.toml`; the frozen Windows lock is not a Mac dependency lock.

Install the development and build extras, then run checks from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Browser tests use local HTTP fixtures and temporary data. Configure `PLAYWRIGHT_BROWSERS_PATH` to the directory where Chromium was installed. Tests that use Windows tray, credential-vault or startup APIs need Windows.

For Chrome extension checks, run `npm ci`, `npm run test:extension` and `npm run format:check`. The Python suite includes real Chromium extension tests with disposable fictional profiles. Their copied test manifest grants access to localhost fixtures to simulate Chrome's toolbar gesture; that permission never ships. No user browser profile is opened by tests.

## Working boundaries

- Keep test data fictional. Do not commit profiles, credentials, resumes, application evidence, browser state, pairing links, `installed_paths.json`, downloaded runtimes or build output.
- Add regression tests for preparation queues, manual application tracking, removal tombstones, keyword extraction, email status, and external links while the worker is busy.
- Exercise assistant workflows against local fixtures. Keep the dormant submission and remote regression tests passing; live submissions and remote sessions are not release smoke tests.
- Keep local assets in `web/` and `remote_web/`. Preserve the loopback API boundary and the isolated remote companion.
- Keep JobPilot's lexical keyword display separate from ResumeForge's contextual requirement ranking. Generated inspiration may introduce editable role-specific accomplishments, but must not invent employers, dates, or credentials. Render and inspect the ResumeForge PDF when changing content planning or document layouts.

## Build

`scripts/Build-JobPilot.ps1` builds the desktop launcher from `.venv` into `build/desktop-dist/JobPilot`. Use `-BuildPython` for another build environment. The installer combines that output with service source and assets; see [setup](setup.md). Review [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) when changing dependencies or bundled tools.

Build and check the Python distributions separately:

```powershell
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe scripts/smoke-wheel.py
```

The wheel check installs into a temporary directory and verifies the bundled dashboard and remote portal with fictional data. It does not start workers or open employer sites.

Build the native Intel Mac package with `python scripts/build_macos.py --output dist/macos --dmg` on an `x86_64` Mac. The macOS CI job runs the regression suite, builds that architecture, then exercises the frozen service, PDF preparation, extension pairing, and a visible Cocoa dashboard with native menu closure. See [Mac build details](macos.md#build-and-verify).

Build the Chrome ZIP with `python scripts/package_extension.py`. The archive contains only the runtime allowlist. Load its extracted folder through `chrome://extensions` to use or inspect it; there is no compilation step.

Contribution and disclosure procedures are in [CONTRIBUTING.md](../CONTRIBUTING.md) and [SECURITY.md](../SECURITY.md).
