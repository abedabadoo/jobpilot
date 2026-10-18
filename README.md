# JobPilot

[![CI](https://github.com/abedabadoo/jobpilot/actions/workflows/ci.yml/badge.svg)](https://github.com/abedabadoo/jobpilot/actions/workflows/ci.yml)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

JobPilot is a Windows application for finding jobs, preparing application documents from saved career facts, and submitting supported forms with a verified receipt.

![JobPilot dashboard](docs/images/dashboard.png)

Dashboard shown with fictional example data.

The desktop dashboard and worker run locally. Searches and applications have separate pause controls, and the worker can continue while the dashboard is closed to the system tray.

## What it does

- Collects listings through job-board searches, public Greenhouse, Lever and Ashby feeds, job URLs, email alerts and optional IMAP access.
- Assesses roles against saved preferences and prepares PDF and Word resumes and cover letters.
- Uses the local Ollama `qwen3.5:9b` model to select relevant **existing career fact IDs** and identify gaps. Document text comes from saved facts and templates; unavailable or invalid model output falls back to deterministic fact selection.
- Fills recognized application fields using the saved profile and explicitly supplied screening answers.
- Holds unfamiliar forms, missing answers, login challenges and uncertain outcomes for review.
- Offers optional paired-device access to a retained application browser for sign-in, CAPTCHA or verification steps.
- Records application artifacts, activity and CSV reports in local storage.

## Requirements and setup

Use Windows with Python 3.13, Ollama, Playwright Chromium and Microsoft Edge WebView2 for the desktop window. The setup process downloads dependencies, a browser and the model; job searches and employer sites require internet access.

Start with [Windows setup](docs/setup.md). It covers running a source checkout, building the desktop executable and installing it for the current Windows user. Only run one JobPilot installation or source instance at a time: the default service ports are shared.

The initial profile is fictional, and search and submissions start paused. Replace the profile, review the career facts and save your own screening answers before enabling applications. Never use the example profile to submit an application.

## Quick start

With Python 3.13 installed, run in PowerShell:

```powershell
git clone https://github.com/abedabadoo/jobpilot.git
cd jobpilot
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
$env:JOBPILOT_DATA_DIR = Join-Path $env:LOCALAPPDATA 'JobPilot-Source\data'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $env:JOBPILOT_DATA_DIR 'browsers'
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m jobpilot.service --port 8765
```

Open `http://127.0.0.1:8765` in your browser. This starts the dashboard and worker with search and submissions paused. For Ollama setup, the desktop window, installation and recovery, follow [Windows setup](docs/setup.md).

## Application outcomes

Preparing documents or clicking a submit control does not confirm an application. JobPilot requires a new employer receipt associated with the application to mark an automated submission **confirmed**. A possible submission without that receipt stays **uncertain** and is held against automatic retries. Outcomes verified manually are tracked separately.

Unknown eligibility or sensitive answers are not inferred. Supported forms can still change, reject automation or require your attention. Search availability depends on upstream sites and their access restrictions; JobPilot cannot guarantee listings, submissions, interviews or hiring outcomes.

## Data and remote access

Profiles, screening answers, browser sessions, documents and application history are stored on the PC. Employer sites receive the information submitted to them. Optional remote access sends the application browser view through a temporary Cloudflare Quick Tunnel, and optional notifications use the paired browser's push service. Treat pairing links and the data directory as private.

See [remote access](docs/remote-access.md), [troubleshooting](docs/troubleshooting.md), [architecture](docs/architecture.md) and [development](docs/development.md). Report vulnerabilities using [SECURITY.md](SECURITY.md).

License terms are in [LICENSE](LICENSE). Dependency and bundled-tool attribution is recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
