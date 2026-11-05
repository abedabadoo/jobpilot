# JobPilot macOS and Chrome autofill

## Intent

Ship the existing discovery, email, document preparation and manual tracking app for macOS, and a Chrome extension that fills application forms in the user's normal signed-in browser. The user asked for implementation and has previously requested autonomous work without clarification pauses. The choices below are implementation decisions, not additional user requirements.

## Architecture

Keep the Python/FastAPI dashboard and native pywebview launcher. Add a small platform module for user data paths, startup and desktop lifecycle. Build macOS application bundles natively on GitHub's Apple Silicon and Intel runners. Preserve Windows behavior and its installed data. No existing installation is replaced during development.

Build a Manifest V3 extension using local HTML/CSS/JavaScript. Clicking Autofill grants current-tab access. The extension stores an editable profile in chrome.storage.local and remains useful while JobPilot is offline. It can explicitly import a profile and prepared documents from a paired loopback-only JobPilot service. It uses the user's existing Chrome tab rather than a separate browser session.

## macOS behavior

- Source and native bundle both launch the dashboard and loopback service.
- Default user data is ~/Library/Application Support/JobPilot, overridable by JOBPILOT_DATA_DIR. Windows retains its existing data location.
- Native bundle launches a bundled service-child command; it does not require a separately installed Python to use the shipped app.
- Use Cocoa pywebview and a compatible main-thread/menu lifecycle. Avoid importing Win32 APIs on Darwin.
- Single-instance behavior, opening the existing dashboard, native document opening, optional sign-in startup and logs have platform-aware implementations.
- Discover local Ollama through explicit configuration, PATH and normal macOS application locations. A missing optional model cannot prevent discovery, email, manual tracking or fallback document generation from opening.
- Build script produces an architecture-specific .app archive (and DMG if available), with fictional starter data only. Signing/notarization is optional when real Apple credentials are provided; unsigned artifacts must be described accurately.
- Provide Mac installation, source-run and local model setup instructions. Install platform-marked dependencies, never the Windows-only frozen lock on Mac.

## Chrome autofill behavior

- Profile editor/import/export for contact, address, links, explicit work-authorization answers, optional preferences, experience, education and skills. Unknown values remain blank. No guessing demographic or authorization answers from a name or location.
- Generic label/autocomplete/ARIA/name matching, including native text, textarea, selects and explicit yes/no groups; use controlled-input events for React-style forms. Handle dynamically added pages when Autofill is clicked again, same-origin frames and open shadow roots where possible.
- Preserve nonempty answers by default, with explicit replacement option. Never fill passwords, national IDs, payment fields, consent/attestation controls or click submit/next. Support undo for the last fill.
- Show filled, preserved and unanswered fields in plain language. Avoid promises of universal ATS support.
- Upload a user-selected local or paired JobPilot resume only on an explicit Attach action, with a 5 MiB limit. Keep file bytes and credentials inside trusted extension contexts until passing only the selected document to a file input.
- Permissions: activeTab, scripting, storage and loopback host access. No permanent all-sites access or remote code. Never send profile information to a third-party server.
- The extension may fill user-approved forms but does not restore JobPilot's dormant automatic submission or remote-access features.

## Pairing contract

All extension routes are under /api/extension/. Existing dashboard origin and mutation-token checks remain unchanged for every other route. The extension never gets the dashboard token or /api/state/settings/email data.

1. POST /api/extension/pairing, dashboard token, body {extension_id}: generates one-use code bound to exact chrome-extension://id, expires in five minutes.
2. POST /api/extension/pair, matching extension Origin, body {code}: consumes code and returns independent bearer token, pairing_id, expires_at. Store token digest, not plaintext.
3. GET /api/extension/profile, bearer and matching Origin: {schema_version:1, profile:{...}}. Recursive explicit allowlist; no generic settings or saved-answer export.
4. GET /api/extension/documents, same auth: {documents:[{job_id,title,company,kind,name,download_path}]}. Supported kinds resume_pdf/resume_docx/cover_pdf/cover_docx. No absolute filesystem paths.
5. GET /api/extension/documents/{job_id}/{kind}, same auth: authenticated attachment restricted to DATA/applications and stored job document keys. Reject traversal/symlink escapes and oversized files.
6. GET /api/extension/pairings, dashboard token even though GET: active connection metadata only. POST /api/extension/pairings/{id}/revoke is dashboard-only. POST /api/extension/disconnect revokes the requesting extension's token.

Chrome options' Connect button opens http://127.0.0.1:8765/?extension_id=<runtime-id>#settings. Dashboard prepopulates this ID but pairing requires a user click; it does not authorize from URL data alone. Copy the generated code into the extension. Extension profile import explicitly replaces the local profile after confirmation; failure preserves it. CORS is route-specific and exact-origin, never global wildcard. Unpaired website/null/extension origins cannot read protected data.

Exported profile fields: name, first_name, last_name, email, phone, location, address_line1, address_line2, city, state, postal_code, country, linkedin, website, github, portfolio, current_employer, current_title, work_authorized (bool/null), requires_sponsorship (bool/null), willing_to_relocate (bool/null), salary_expectation, salary_currency, available_date, years_experience, skills, certifications, interests, experience:[{company,title,start,end,location,description}], education:[{institution,degree,field_of_study,start,end,gpa}]. Convert known saved fact text to descriptions, never spread arbitrary nested objects. Additional ordinary form answers may be added only as explicit profile fields, not inferred credentials or arbitrary backend answers.

## Acceptance

Windows regression suite remains green. New platform, pairing/security and autofill tests pass. Native Mac builds and smoke tests run on Apple Silicon and Intel. Extension is loaded in real bundled Chromium for local fixture testing, including controlled inputs, selects, repeat fields, blocked/sensitive fields, preserved answers, resume attachment, undo and offline use. Dashboard pairing and revocation are exercised. Downloadable extension ZIP and Mac archives contain code and fictional defaults only; personal imports live outside the repository and release ZIPs.
