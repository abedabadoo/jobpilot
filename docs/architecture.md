# Architecture

JobPilot has a Windows desktop shell, a loopback API, and persistent search and document workers. The shell can exit while the workers continue.

| Component | Responsibility |
| --- | --- |
| `launcher.py` | Start services, enforce one desktop window, provide tray controls and optional startup |
| `jobpilot/service.py` | Serve the dashboard, queue document work, expose manual application tracking and email controls |
| `jobpilot/collectors.py` | Discover public postings, parse alerts, verify and read an inbox without modifying mail |
| `jobpilot/keywords.py` | Extract role tools, disciplines, and phrases for the detail view and document tailoring |
| `jobpilot/core.py` | Assess role and location eligibility and calculate fit |
| `jobpilot/documents.py` | Rank saved experience and render tailored PDF and Word application documents |
| `jobpilot/links.py` | Open specific job URLs in the default browser without waiting for the worker |
| `jobpilot/store.py` | Persist jobs, applied history, settings, problems, and removal exclusions in SQLite |
| `web/` | Opportunities, Applied, Problems, profile, email, and preferences interface |
| `jobpilot/browser.py`, `remote*.py`, `interventions.py`, `remote_web/` | Dormant legacy form automation and remote assistance |

## Active workflow

Assistant mode is the default. Existing submission and remote-access flags are neutralized in this mode. Public settings do not switch back to the legacy automation mode. Search and document preparation remain available, and the user submits applications in their browser.

Document requests enter a queue and return immediately. External-link requests never acquire the application preparation lock. Marking a role applied stores a manual timestamp and moves it out of the opportunity list; undoing that action restores it. Removed URLs are tombstoned to prevent rediscovery from recreating them.

Problems have a readable message, category, optional role and employer, and the exact affected URL. Technical details are written to local logs rather than the dashboard. A problem can be marked resolved.

## Documents

Keyword extraction is independent of local model availability. Extracted terms appear in the role detail and tailor the skills and cover-letter draft. Saved historical achievements remain tied to the profile. PDF and Word exports share the document structure; the renderer uses readable type sizes and allows another page when the content needs it.

## Storage and network

`JOBPILOT_DATA_DIR` selects the data directory. Installed paths are recorded in `installed_paths.json`; an unconfigured source run uses `%LOCALAPPDATA%\JobPilot`. The directory includes SQLite state, application documents, logs, browser runtimes, and optional model files. Windows Credential Manager stores inbox credentials.

The API listens on loopback port `8765`; local Ollama uses `11436`. Public searches, employer-page fetches, and encrypted inbox reads use external connections. Active assistant mode does not start a remote tunnel or submit forms.
