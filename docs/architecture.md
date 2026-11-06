# Architecture

JobPilot has native Windows and macOS desktop shells, a loopback API, persistent search and document workers, and an optional Chrome autofill extension. The shell can exit while the workers continue.

| Component | Responsibility |
| --- | --- |
| `launcher.py` | Start services, enforce one desktop window, provide tray controls and optional startup |
| `jobpilot/platforms.py` | OS-specific data paths, startup, process discovery, singleton signaling and sleep control |
| `jobpilot/autofill.py` | Scoped extension credentials, profile export and prepared-document access |
| `extension/` | Editable offline profile, user-triggered form filling, resume attachment and undo |
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

`JOBPILOT_DATA_DIR` selects the data directory. Windows installed paths can be recorded in `installed_paths.json`; an unconfigured source run uses `%LOCALAPPDATA%\JobPilot` on Windows or `~/Library/Application Support/JobPilot` on Mac. The directory includes SQLite state, application documents, logs, browser runtimes, and optional model files. The system credential vault stores inbox credentials.

The API listens on loopback port `8765`; local Ollama uses `11436`. Public searches, employer-page fetches, and encrypted inbox reads use external connections. Active assistant mode does not start a remote tunnel or submit forms.

## Chrome connection

The extension works independently from a saved Chrome-local profile. Its optional connection uses a five-minute, one-use code created in dashboard Settings, bound to the exact extension ID. The resulting independent bearer credential lasts up to 90 days; the service stores its digest, supports revocation, and requires the matching extension Origin on every protected request. It never exports the dashboard session token or general settings.

Profile exports use a recursive field allowlist. Prepared documents are restricted to known PDF/Word keys under the application's document directory, with resolved-path checks and a 5 MiB limit. Protected reads have POST aliases because privileged Chrome GET fetches can omit Origin. Dashboard APIs reject originless cross-context browser requests using Fetch Metadata while allowing same-origin dashboard traffic and native local clients.

The shipping MV3 manifest has `activeTab`, `scripting`, `storage`, and loopback-only host access. Profile storage and pairing credentials are restricted to trusted extension contexts. Explicit Autofill passes only the profile to an isolated filling engine in the chosen tab; explicit Attach additionally passes the selected resume. No page submission, background scanning of unrelated sites, or third-party profile service is involved.
