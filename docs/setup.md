# Windows setup

## Prerequisites

Install 64-bit Python 3.13 and [Ollama for Windows](https://ollama.com/download/windows). The desktop window uses Microsoft Edge WebView2; the installer checks for it and runs Microsoft's bootstrapper if needed. A source run needs WebView2 already available, or you can use the local dashboard in a normal browser.

Run commands from the repository root in PowerShell. Use a regular Windows user account. Stop any other JobPilot instance before starting this checkout: the launcher reuses services on ports `8765` and `11436`.

## Run from source

Create an environment and download Chromium into a separate source-run data directory:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
$env:JOBPILOT_DATA_DIR = Join-Path $env:LOCALAPPDATA 'JobPilot-Source\data'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $env:JOBPILOT_DATA_DIR 'browsers'
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe launcher.py --service-only
```

The launcher starts or reuses local Ollama and the worker, writing logs under the data directory. Download the supported model into the same model store, then open the desktop:

```powershell
$env:OLLAMA_HOST = '127.0.0.1:11436'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_MODELS = Join-Path $env:JOBPILOT_DATA_DIR 'ollama-models'
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3.5:9b
.\.venv\Scripts\python.exe launcher.py
```

Keep `JOBPILOT_DATA_DIR` consistent in later shells. Without that override, a source launch uses `%LOCALAPPDATA%\JobPilot`. It uses the Python executable that runs `launcher.py`; it does not require an installed runtime or `installed_paths.json`.

For a browser-only session, run `.\.venv\Scripts\python.exe -m jobpilot.service --port 8765` and open `http://127.0.0.1:8765`. This command does not start Ollama. Document preparation can use the verified-fact template fallback while the model is unavailable.

## Build and install

The build uses the checkout's `.venv` and writes to `build\desktop-dist\JobPilot`. Install from that output and the source checkout:

```powershell
.\scripts\Build-JobPilot.ps1
.\scripts\Install-JobPilot.ps1 -Python (py -3.13 -c "import sys; print(sys.executable)") -Launch
```

Pass an explicit Python 3.13 executable if the Python launcher is unavailable. `-BuildPython`, `-WorkRoot` and `-SourceRoot` override build locations. The installer accepts `-BuildRoot`, `-InstallRoot` and `-DataRoot`; its defaults are `%LOCALAPPDATA%\Programs\JobPilot` and that installation's `data` subdirectory. It creates a separate Python runtime, installs dependencies and Chromium, downloads the model and verified tunnel helper, and creates desktop and Start-menu shortcuts. Downloads require internet access and can take time.

The PyInstaller output contains the desktop launcher; installing also supplies the service source and its Python environment. It is not a standalone worker runtime.

## First use

1. Replace the fictional profile with your contact details and career history.
2. Set target roles and location, then enable search or import a posting.
3. Use **Review** to inspect fit, job-description keywords, and tailored document exports.
4. Open the job in your usual browser and apply there. Click **Applied?** when finished; the role moves to Applied.

Closing the desktop window hides it to the tray. **Quit dashboard** leaves the worker running. **Stop worker** stops background work without deleting the queue. Windows sign-in startup is available after installation, through Preferences. The installed recovery task checks every five minutes and at sign-in, and starts services only when the saved startup setting is enabled. Automatic submission and remote access remain disabled in assistant mode, even when older saved preferences enabled them.

## Email alerts

Open **Email**, enter your Gmail address and a [Google app password](https://myaccount.google.com/apppasswords), and select **Connect & test**. Google app passwords require an eligible account with two-step verification; see [Google's instructions](https://support.google.com/accounts/answer/185833). Keep the default host `imap.gmail.com`, encrypted port `993`, and folder `INBOX` unless you intentionally use another IMAP account or folder.

The credential is stored in Windows Credential Manager. A successful connection test confirms that the folder can be opened. Use **Sync now** to read recent messages and import recognized job links. The dashboard shows the last check, message counts, links found, and imported opportunities. If the scan limit is reached, increase it under Advanced or shorten the date window. Reading leaves messages unread; there are no send or delete operations.

Saving an address alone does not authorize inbox access. JobPilot will report an unconnected account until the credential has been supplied and the connection verified. EML alert import is available without a persistent inbox connection.

## Updating and backup

Pause searches and wait for document preparation to finish before maintenance. Back up the data directory while services are stopped, including the SQLite database and its associated files. Rebuild and rerun the installer using the same installation and data paths. Repair switches `-SkipModel`, `-SkipBrowser` and `-SkipDependencies` skip those steps only when the existing components are already usable. Do not overwrite or delete data to repair application code.
