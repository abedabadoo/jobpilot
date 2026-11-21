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
| `jobpilot/resumeforge_bridge.py` | Create separate ResumeForge role workspaces, run the bundled engine, and verify checked PDFs before attachment |
| `resumeforge/` | Analyze the full posting, write tailored content, fit the page, and render every application PDF |
| `jobpilot/links.py` | Open specific job URLs in the default browser without waiting for the worker |
| `jobpilot/store.py` | Persist jobs, applied history, settings, problems, and removal exclusions in SQLite |
| `web/` | Opportunities, Applied, Problems, profile, email, and preferences interface |
| `jobpilot/browser.py`, `remote*.py`, `interventions.py`, `remote_web/` | Dormant legacy form automation and remote assistance |

## Active workflow

Assistant mode is the default. Existing submission and remote-access flags are neutralized in this mode. Public settings do not switch back to the legacy automation mode. Search and document preparation remain available, and the user submits applications in their browser.

Document requests enter a queue and return immediately. External-link requests never acquire the application preparation lock. Marking a role applied stores a manual timestamp and moves it out of the opportunity list; undoing that action restores it. Removed URLs are tombstoned to prevent rediscovery from recreating them.

Problems have a readable message, category, optional role and employer, and the exact affected URL. Technical details are written to local logs rather than the dashboard. A problem can be marked resolved.

## Documents

JobPilot's lightweight keyword extraction is independent of local model availability and supplies the role-detail display. At 80% fit, JobPilot queues the complete posting for ResumeForge; it does not promote those quick lexical matches to reviewed writing priorities. ResumeForge performs the contextual requirement ranking, content planning, one-page fitting, quality review, and PDF rendering. It is the sole application-document generator, and automatic work never creates a cover letter.

The bundled ResumeForge editor uses its existing `--data-dir` argument. JobPilot seeds a role workspace from the saved ResumeForge profile and settings, then reads only the latest run. A checked PDF is accepted after its report marks the run ready, geometry and content checks pass, and its SHA-256 matches. An unchanged ready run is reused; transient failures retry with a bounded delay. Missing profile or model setup enters a stable setup-required state instead of a hot retry loop. Generation is serialized so the constrained Intel Mac does not load competing writers. None of these states changes the role's applied status.

## Storage and network

`JOBPILOT_DATA_DIR` selects the data directory. Windows installed paths can be recorded in `installed_paths.json`; an unconfigured source run uses `%LOCALAPPDATA%\JobPilot` on Windows or `~/Library/Application Support/JobPilot` on Mac. The directory includes SQLite state, checked ResumeForge references, and logs. ResumeForge keeps its profile, role workspaces, and model settings in its own application-support directory. The system credential vault stores inbox credentials.

The API listens on loopback port `8765`. Public searches, employer-page fetches, and encrypted inbox reads use external connections. Active assistant mode does not start a remote tunnel, an automation browser, a second model service, or form submission. A ResumeForge model endpoint is contacted only when its saved configuration requests one.

## Chrome connection

The extension works independently from a saved Chrome-local profile. Its optional connection uses a five-minute, one-use code created in dashboard Settings, bound to the exact extension ID. The resulting independent bearer credential lasts up to 90 days; the service stores its digest, supports revocation, and requires the matching extension Origin on every protected request. It never exports the dashboard session token or general settings.

Profile exports use a recursive field allowlist. Prepared documents are restricted to known ResumeForge PDF keys under approved directories, with resolved-path checks and a 15 MiB service limit. A resume imported directly into the extension has its separate 5 MiB local-storage limit. Protected reads have POST aliases because privileged Chrome GET fetches can omit Origin. Dashboard APIs reject originless cross-context browser requests using Fetch Metadata while allowing same-origin dashboard traffic and native local clients.

The shipping MV3 manifest has `activeTab`, `scripting`, `storage`, and loopback-only host access. Profile storage and pairing credentials are restricted to trusted extension contexts. Explicit Autofill passes only the profile to an isolated filling engine in the chosen tab; explicit Attach additionally passes the selected resume. No page submission, background scanning of unrelated sites, or third-party profile service is involved.
