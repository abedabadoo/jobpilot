# JobPilot on macOS

The combined JobPilot and ResumeForge app uses a native Cocoa dashboard and a loopback-only background service on Intel Macs. Download the `x86_64` archive. The application includes its Python runtime, ResumeForge editor, and service dependencies; a separate installation of either app is unnecessary.

## Install a native release

1. Extract `JobPilot-<architecture>.app.zip` in Finder.
2. Move `JobPilot.app` to `~/Applications` or `/Applications`, then open it. Keep the app at its installed path if you enable sign-in startup.
3. If macOS blocks an unsigned download, review its source and use **System Settings → Privacy & Security → Open Anyway**, then follow the macOS confirmation. The default CI builds are ad hoc signed, without an Apple Developer ID or notarization. A successful build does not imply Apple notarization.

For an in-place update, keep `Install-JobPilot-macOS.command` beside the app ZIP and open the command file. It finds an existing JobPilot in Applications, waits for its worker, replaces the app, and opens the new version. On a first install it uses `~/Applications`. Save and close any open ResumeForge editor before updating. Your data and profile stay outside the app bundle.

The dashboard opens without Ollama or a model. Discovery, email, manual tracking, and the ResumeForge PDF builder remain available. ResumeForge builds a resume automatically for roles scoring at least 80% fit. Cover letters are optional and created only in its editor after a resume is checked. The app does not download a model or automation browser on first launch. The Chrome autofill extension uses your signed-in Chrome session.

## Data and desktop behavior

Data is stored in `~/Library/Application Support/JobPilot`, outside the app bundle. The combined editor reuses the ResumeForge profile in `~/Library/Application Support/ResumeForge/workspace`. Checked PDFs go below `~/Downloads/JobPilot RF Docs/Company - Role`, with an automatic posting-specific subfolder preventing same-title postings from overwriting one another. Set `JOBPILOT_DATA_DIR` to use another JobPilot data location when starting from Terminal. Logs are under `logs` in that directory.

The native JobPilot menu can open the dashboard. Closing or quitting the dashboard leaves its independent local service running. The next launch reuses the service at `http://127.0.0.1:8765`. A second desktop launch signals the existing dashboard rather than starting another desktop. **Stop worker** in the dashboard stops scheduled work; closing a window does not stop it.

Enable optional sign-in startup from Settings in the installed application. It writes `~/Library/LaunchAgents/com.jobpilot.desktop.plist`, with the installed app executable and separate `--background` argument, for the next sign-in. Disable it in Settings before moving the app. Startup is opt-in and requires the packaged app; a source checkout does not register a Python interpreter as a login item. The keep-awake setting uses macOS `caffeinate -s` while enabled, preventing system idle sleep on AC power. It does not override lid closure or prevent sleep on battery.

For a diagnostic report without opening a dashboard:

```bash
"$HOME/Applications/JobPilot.app/Contents/MacOS/JobPilot" --diagnose --report "$HOME/Desktop/jobpilot-diagnostic.json"
```

The report includes local installation paths. Review it before sharing.

## Optional writing model

Model configuration belongs to ResumeForge. Open **ResumeForge profile**, choose its model settings, and select either offline mode, an Ollama endpoint, or an OpenAI-compatible local endpoint. JobPilot does not start or poll Ollama and does not load a second model for search or fit scoring.

The Intel-laptop runtime, when installed, uses the ResumeForge-tuned Qwen 3.5 4B Q4 model with an 8K context and four CPU threads. ResumeForge starts it only for generation, processes one resume at a time, and lets it sleep after an idle period. This preserves the full writing and review passes without keeping several gigabytes resident during ordinary monitoring. Larger models may be configured on a stronger computer through the same editor; the JobPilot workflow does not change.

## Run from source

Use Python 3.13 or newer on macOS. Install dependencies from the project metadata so Cocoa dependencies are resolved for Mac:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,build]'
python launcher.py
```

`requirements.lock` is the Windows development lock; Mac installs should use `pyproject.toml`. The Mac pywebview dependency brings its native PyObjC/Cocoa/WebKit dependencies. `python launcher.py --service-only` starts or reuses the service without a window; `python -m jobpilot.service` runs it in the foreground. The service binds only to loopback.

## Build and verify

Build on a native Mac of the intended architecture, with the preceding dependencies installed:

```bash
python scripts/build_macos.py --output dist/macos
# Optional disk image:
python scripts/build_macos.py --output dist/macos --dmg
```

The output ZIP contains `JobPilot.app`. The installer is copied next to it. All PyInstaller intermediate files stay below the chosen output directory. The bundle launches its own executable with `--service-child`; it never searches for a user-installed Python. Only repository web assets and fictional starter profiles are included. User data, imported profiles, credentials and `installed_paths.json` are excluded.

By default PyInstaller uses ad hoc signing. Set `JOBPILOT_CODESIGN_IDENTITY` to an installed Apple signing identity to request that identity during packaging. Apple Developer ID signing and notarization require real Apple credentials and are separate release steps. Do not label a build notarized unless it has actually passed Apple's notarization service and the ticket has been stapled and checked.

CI uses a native `macos-15-intel` runner. Native smoke tests exercise the frozen executable's diagnostic command, bundled service child, ResumeForge PDF preparation, scoped extension API, and visible Cocoa dashboard. The packaged app opens its real window and closes through the native menu; the service must remain healthy afterward.

To repeat those checks against a local bundle with disposable fictional data, run `python scripts/smoke_macos.py --app dist/macos/macos-build/dist/JobPilot.app --report dist/macos/smoke.json --gui` from the source checkout. This requires a logged-in Mac desktop with a WindowServer.
