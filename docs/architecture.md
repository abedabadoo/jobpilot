# Architecture

JobPilot has a local desktop shell, a loopback API and persistent background workers. The shell can exit while the worker continues.

| Component | Responsibility |
| --- | --- |
| `launcher.py` | Start local services, enforce one desktop window per Windows session, provide tray controls and startup registration |
| `jobpilot/service.py` | Serve the dashboard on `127.0.0.1:8765`, validate mutations and schedule search and application work |
| `jobpilot/collectors.py` | Discover and import public postings and email alerts; validate fetched URLs |
| `jobpilot/core.py` | Assess role and location eligibility, score fit and select verified career facts |
| `jobpilot/documents.py` | Select saved facts with local Ollama or deterministic fallback; write application documents and provenance manifests |
| `jobpilot/browser.py` | Inspect recognized forms, fill known answers, checkpoint submission attempts and verify employer receipts |
| `jobpilot/store.py` | Persist settings, profile, jobs, events, receipt evidence and cleanup exclusions in SQLite |
| `jobpilot/remote*.py`, `interventions.py` | Pair devices, expose an isolated companion portal on loopback port `8766`, and pause the owning browser thread for human input |
| `web/`, `remote_web/` | Local dashboard and paired-device interface, with local static assets |

## Submission boundaries

Application browser work is serialized. Preparation uses a snapshot of saved facts and answers. A durable checkpoint records a possible submission before an automated final action. A new receipt must match the job before the application becomes confirmed. Missing receipts, interrupted submissions and failed verification remain held for review rather than being automatically repeated.

Remote intervention keeps the browser context on its original Playwright thread. Human commands are queued to that thread. Before submission, the worker resumes only after the challenge clears; after a submission attempt it waits for a matching new receipt and does not repeat the final action.

## Storage and network

`JOBPILOT_DATA_DIR` selects the data directory. An installed copy records its paths in `installed_paths.json`; an unconfigured source run uses `%LOCALAPPDATA%\JobPilot`. The directory includes the database, application packages, evidence, browser sessions, logs, Chromium and Ollama models. Windows Credential Manager stores supported credentials and remote signing secrets; the database and document files are not an encrypted vault.

Ollama listens on loopback port `11436`. The model receives job text and saved fact IDs for selection, not permission to create career claims or control the browser. Public searches, employer pages, optional email collection, dependency downloads, optional Cloudflare tunneling and Web Push require external connections. The remote tunnel targets only the companion portal, not the dashboard API.
