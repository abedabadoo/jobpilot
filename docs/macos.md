# JobPilot on macOS

The combined JobPilot and ResumeForge app uses a native Cocoa dashboard and a loopback-only background service on Intel Macs. Download the `x86_64` archive. The application includes its Python runtime, ResumeForge editor, and service dependencies; a separate installation of either app is unnecessary.

## Install a native release

1. Extract `JobPilot-<architecture>.app.zip` in Finder.
2. Move `JobPilot.app` to `~/Applications` or `/Applications`, then open it. Keep the app at its installed path if you enable sign-in startup.
3. If macOS blocks an unsigned download, review its source and use **System Settings → Privacy & Security → Open Anyway**, then follow the macOS confirmation. The default CI builds are ad hoc signed, without an Apple Developer ID or notarization. A successful build does not imply Apple notarization.

Alternatively, put `Install-JobPilot-macOS.command` alongside the ZIP and run `bash Install-JobPilot-macOS.command` in Terminal. It installs or updates `~/Applications/JobPilot.app` without administrator access. Quit JobPilot before updating. Your data and existing ResumeForge profile remain outside the app bundle.

The dashboard opens without Ollama or a model. Discovery, email, manual tracking, and the ResumeForge PDF builder remain available. ResumeForge builds a resume automatically for roles scoring at least 80% fit. Cover letters are optional and created only in its editor after a resume is checked. The app does not download a model or automation browser on first launch. The Chrome autofill extension uses your signed-in Chrome session.

## Data and desktop behavior

Data is stored in `~/Library/Application Support/JobPilot`, outside the app bundle. The combined editor reuses the ResumeForge profile in `~/Library/Application Support/ResumeForge/workspace`. Checked PDFs go to `~/Downloads/JobPilot RF Docs/Company - Role`. Set `JOBPILOT_DATA_DIR` to use another JobPilot data location when starting from Terminal. Logs are under `logs` in that directory.

The native JobPilot menu can open the dashboard. Closing or quitting the dashboard leaves its independent local service running. The next launch reuses the service at `http://127.0.0.1:8765`. A second desktop launch signals the existing dashboard rather than starting another desktop. **Stop worker** in the dashboard stops scheduled work; closing a window does not stop it.

Enable optional sign-in startup from Settings in the installed application. It writes `~/Library/LaunchAgents/com.jobpilot.desktop.plist`, with the installed app executable and separate `--background` argument, for the next sign-in. Disable it in Settings before moving the app. Startup is opt-in and requires the packaged app; a source checkout does not register a Python interpreter as a login item. The keep-awake setting uses macOS `caffeinate -s` while enabled, preventing system idle sleep on AC power. It does not override lid closure or prevent sleep on battery.

For a diagnostic report without opening a dashboard:

```bash
"$HOME/Applications/JobPilot.app/Contents/MacOS/JobPilot" --diagnose --report "$HOME/Desktop/jobpilot-diagnostic.json"
```

The report includes local installation paths. Review it before sharing.

## Optional local model

Install Ollama separately using its official [Mac download](https://ollama.com/download/mac). JobPilot looks for `JOBPILOT_OLLAMA`, `ollama` on PATH, `/opt/homebrew/bin/ollama`, `/usr/local/bin/ollama`, and the Ollama app under `/Applications` or `~/Applications`.

JobPilot runs its optional Ollama instance on `127.0.0.1:11436` with cloud inference disabled and model storage in its data directory. A normal Ollama instance on the default port `11434` is separate. To install the default model into JobPilot's isolated model directory, first launch JobPilot, then explicitly run:

```bash
OLLAMA_HOST=127.0.0.1:11436 ollama pull qwen3.5:9b
```

This is an optional large download. You can choose another locally available model in Settings. If Ollama was installed after JobPilot started, restart the dashboard to let it discover and start the optional local server. `JOBPILOT_OLLAMA` may be an absolute executable path when PATH does not contain Ollama.

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

The output ZIP contains `JobPilot.app`. The installer is copied next to it. All PyInstaller intermediate files stay below the chosen output directory. The bundle launches its own executable with `--service-child`; it never searches for a user-installed Python. Only repository web assets and the fictional `jobpilot/candidate.json` starter profile are included. User data, imported profiles, credentials and `installed_paths.json` are excluded.

By default PyInstaller uses ad hoc signing. Set `JOBPILOT_CODESIGN_IDENTITY` to an installed Apple signing identity to request that identity during packaging. Apple Developer ID signing and notarization require real Apple credentials and are separate release steps. Do not label a build notarized unless it has actually passed Apple's notarization service and the ticket has been stapled and checked.

CI uses a native `macos-15-intel` runner. Native smoke tests exercise the frozen executable's diagnostic command, bundled service child, ResumeForge PDF preparation, scoped extension API, and visible Cocoa dashboard. The packaged app opens its real window and closes through the native menu; the service must remain healthy afterward.

To repeat those checks against a local bundle with disposable fictional data, run `python scripts/smoke_macos.py --app dist/macos/macos-build/dist/JobPilot.app --report dist/macos/smoke.json --gui` from the source checkout. This requires a logged-in Mac desktop with a WindowServer.
