# Windows setup

## Prerequisites

Install 64-bit Python 3.13. The desktop window uses Microsoft Edge WebView2; the installer checks for it and runs Microsoft's bootstrapper if needed. A source run needs WebView2 already available, or you can use the local dashboard in a normal browser. A model service is optional and is configured inside the bundled ResumeForge editor, not as a JobPilot prerequisite.

Run commands from the repository root in PowerShell. Use a regular Windows user account. Stop any other JobPilot instance before starting this checkout: the launcher reuses the loopback service on port `8765`.

## Run from source

Create an environment and use a separate source-run data directory:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
$env:JOBPILOT_DATA_DIR = Join-Path $env:LOCALAPPDATA 'JobPilot-Source\data'
.\.venv\Scripts\python.exe launcher.py --service-only
```

The launcher starts or reuses the worker and writes logs under the data directory. Open the desktop with the same environment:

```powershell
.\.venv\Scripts\python.exe launcher.py
```

Keep `JOBPILOT_DATA_DIR` consistent in later shells. Without that override, a source launch uses `%LOCALAPPDATA%\JobPilot`. It uses the Python executable that runs `launcher.py`; it does not require an installed runtime or `installed_paths.json`.

For a browser-only session, run `.\.venv\Scripts\python.exe -m jobpilot.service --port 8765` and open `http://127.0.0.1:8765`. ResumeForge can use its offline writing path until you configure a model in its editor.

## Build and install

The build uses the checkout's `.venv` and writes to `build\desktop-dist\JobPilot`. Install from that output and the source checkout:

```powershell
.\scripts\Build-JobPilot.ps1
.\scripts\Install-JobPilot.ps1 -Python (py -3.13 -c "import sys; print(sys.executable)") -Launch
```

Pass an explicit Python 3.13 executable if the Python launcher is unavailable. `-BuildPython`, `-WorkRoot` and `-SourceRoot` override build locations. The installer accepts `-BuildRoot`, `-InstallRoot` and `-DataRoot`; its defaults are `%LOCALAPPDATA%\Programs\JobPilot` and that installation's `data` subdirectory. It creates a separate Python runtime, installs the application dependencies and creates desktop and Start-menu shortcuts. ResumeForge model installation and configuration remain separate, optional actions.

The PyInstaller output contains the desktop launcher; installing also supplies the service source and its smaller resident-service environment. Build and test packages, the ResumeForge Qt editor, and dormant browser/remote dependencies are not duplicated into that environment. It is not a standalone worker runtime.

## First use

1. Replace the fictional profile with your contact details and career history.
2. Set target roles and location, then select **Start monitoring** above the opportunities. Choose a check interval; the next check and results from each source appear in that panel. **Search now** runs a single check even while monitoring is paused.
3. Roles at 80% fit or above automatically enter the ResumeForge queue. Use **Review** to inspect fit, job-description keywords, and the checked resume PDF.
4. Open the job in your usual browser and apply there. Click **Applied?** when finished; the role moves to Applied.

### Using ResumeForge for a role

Choose **ResumeForge profile** in JobPilot and save your source profile first. ResumeForge is bundled into the same application; a separate installation is unnecessary. A role with a full description starts building automatically when its fit reaches 80%. Select **Open in ResumeForge** to inspect or edit its dedicated workspace. The first open copies your saved ResumeForge profile and model settings into that workspace.

ResumeForge analyzes the complete posting, ranks its requirements, writes the tailored content, and performs the measured PDF checks. When the status says **Checked PDF ready**, the ResumeForge PDF appears with Open and Download controls. ResumeForge is the only document generator; JobPilot does not keep a second resume or Word export.

Reopening the same posting keeps edits in its role workspace. If the posting changes, JobPilot opens a fresh workspace. Your main ResumeForge workspace remains intact. The editor starts on demand and closes independently, so Qt and the writing model do not remain resident while JobPilot is only monitoring jobs.

Closing the desktop window hides it to the tray. **Quit dashboard** leaves the worker running. **Stop worker** stops background work without deleting the queue. Windows sign-in startup is available after installation, through Preferences. The installed recovery task checks every five minutes and at sign-in, and starts services only when the saved startup setting is enabled. Automatic submission and remote access remain disabled in assistant mode, even when older saved preferences enabled them.

### Cover letters

Open **Review** for a role with a checked resume and choose **Generate Cover Letter**. ResumeForge offers the same action. A local ResumeForge model is required. The writer uses the checked PDF for that posting, and each initial generation or **Fresh AI draft** attempts to verify public company research. Add an official company website or article in the editor if automatic discovery comes up empty. When a recruiter or hiring manager cannot be verified from the posting, the greeting is **Dear Hiring Team,**.

The preview shows the saved one-page PDF. **Save edits and update PDF** keeps your wording and checks the same fixed page geometry. If the text needs further edits, the previous PDF stays available and the draft is marked as needing an update. **Fresh AI draft** requires confirmation before it can replace an existing letter. Use **Research sources** to review the URLs and dates. If the resume changes, the editor identifies the older letter and offers a fresh draft.

Both files live under `~/Downloads/JobPilot RF Docs/<Company> - <Position>/<posting-id>/` as `Alnajjar_Resume.pdf` and `Alnajjar_CoverLetter.pdf`. ResumeForge saves editable wording and source metadata in the posting workspace.

The fixed-header business-letter design and evidence-led paragraphs follow [MIT’s career guidance](https://capd.mit.edu/resources/how-to-write-an-effective-cover-letter/) and [Harvard’s cover letter guidance](https://careerservices.fas.harvard.edu/resources/hes-create-impactful-resumes-and-cover-letters/).


## Email alerts

Open **Email**, enter your Gmail address and a [Google app password](https://myaccount.google.com/apppasswords), and select **Connect & test**. Google app passwords require an eligible account with two-step verification; see [Google's instructions](https://support.google.com/accounts/answer/185833). Keep the default host `imap.gmail.com`, encrypted port `993`, and folder `INBOX` unless you intentionally use another IMAP account or folder.

JobPilot stores the credential in macOS Keychain or Windows Credential Manager. **Connect & test** verifies the folder. **Sync now** scans it on demand. With automatic scanning enabled, JobPilot checks for new alerts every 15 minutes while the service runs, independently of job-board searches. A limited scan picks up where the last one left off. It checks the headers first in Inbox and leaves messages and their read status untouched.

JobPilot reads public posting details from employer pages and the Greenhouse and Lever job-board APIs. It scores the verified posting against your profile and preferences. Alerts with incomplete details stay available for research and review. Open an alert and choose **Research posting** to retry its public link. Resumes at the 80% threshold are queued only once the full posting is available.

Saving an address alone does not authorize inbox access. JobPilot will report an unconnected account until the credential has been supplied and the connection verified. EML alert import is available without a persistent inbox connection.

## Updating and backup

Pause searches, stop the worker, and wait for ResumeForge preparation to finish before maintenance. Back up the data directory while services are stopped, including the SQLite database and its associated files. Rebuild and rerun the installer using the same installation and data paths. A normal upgrade stages and validates a clean service runtime before replacing the old one, replaces only application-owned code/binary folders, and preserves `DataRoot`. `-SkipDependencies` explicitly reuses an existing compatible runtime during a repair. Do not overwrite or delete data to repair application code.
