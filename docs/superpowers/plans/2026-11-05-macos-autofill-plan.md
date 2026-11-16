# macOS and Chrome autofill implementation plan

> For agentic workers: use subagent-driven-development. Follow ownership boundaries and record evidence in the private task ledger. Do not revert another worker's changes.

**Goal:** Deliver native Mac JobPilot packages and a usable Chrome application autofill extension.

**Architecture:** Existing Python service and dashboard remain; portable desktop lifecycle is isolated in a platform module. A standalone MV3 extension connects through a narrowly scoped authenticated local API.

**Tech stack:** Python 3.13, FastAPI, pywebview, PyInstaller; Manifest V3 and plain JavaScript; pytest/Playwright and Node test runner; GitHub Actions native macOS builds.

**Spec:** docs/superpowers/specs/2026-11-05-macos-autofill-design.md

## Constraints and review focus

- Retain assistant mode, manual submissions and Windows behavior. Never include personal data in source, fixtures or public packages.
- Extension pairing must not open the dashboard API to extension origins. Test website origins, token theft/reuse, expiry and revocation.
- Frozen Mac resource paths and child launching must not assume installed Python or writable application directories. Test both bundle architectures natively.
- Autofill must preserve user-entered values and avoid a yes/no negation error, consent click or form submission. Test actual form behavior, not string snapshots alone.
- Offline sync failure must preserve a useful local profile. Resume access must not permit filesystem traversal or reveal token values to page scripts.

## Task 1 macOS desktop and packaging

Owner: Mac implementer. Files: launcher.py, new jobpilot/platforms.py, pyproject.toml, platform dependency lock markers as needed, new scripts/build_macos.py and scripts/Install-JobPilot-macOS.command, docs/macos.md, tests/test_platforms.py, tests/test_launcher.py, tests/test_release_scripts.py, platform-only corrections in tests/test_artifact_access.py.

Interface: jobpilot.platforms.application_data_dir() -> Path is shared by launcher and service. Build command python scripts/build_macos.py --output <dir> produces JobPilot-<arch>.app.zip (DMG optional). It must support a native bundled service child and --diagnose without Win32 imports. Root owns service.py; coordinate the single data-path import rather than editing that file.

- [ ] Add platform-focused tests for missing LOCALAPPDATA, Darwin data path, frozen resources, startup launch-agent content, singleton signaling, native webview selection and fallback behavior; watch failures.
- [ ] Implement portable lifecycle and native bundle/service launch. Preserve existing Windows assertions.
- [ ] Add native install/build commands with resource inclusion and clear signing behavior.
- [ ] Run owned tests and report exact commands/results. Do not claim native Mac success from mocked Windows tests.

## Task 2 scoped extension API

Owner: Backend implementer. Files: new jobpilot/autofill.py, jobpilot/service.py, tests/test_extension_api.py and related new unit tests only. Export application_data_dir from Task1 through service; no launcher edits.

Interface: implement exact routes, auth, document metadata and exported profile schema in the spec. Root dashboard and extension worker consume these response keys. Pending pairing binds extension_id; return ISO UTC expires_at strings and opaque pairing_id. Connection lifespan 90 days; pairing code five minutes, single use. Restrict document size to 5 MiB.

- [ ] Write failing tests for pairing success, invalid/expired/reused code, wrong Origin, missing/bad/revoked bearer and dashboard-route denial.
- [ ] Implement scoped auth and recursive profile projection; test unknown nested secrets never escape.
- [ ] Add guarded document list/download and traversal/symlink/non-document/oversize tests.
- [ ] Run new and existing API/security suites. Report red/green evidence and any integration requirements.

## Task 3 Chrome extension

Owner: Extension implementer. Files: extension/** including manifest, popup, profile options, service worker, autofill core/content code, fictional fixtures and Node tests; new tests/test_extension_browser.py if needed. Root owns package.json/format scripts and main docs.

Interface: consume backend contract unchanged. Store profile and selected resume locally; secrets only in trusted extension contexts. Connect deep link carries runtime.id. User confirms explicit JobPilot profile replacement; import offline JSON as standalone alternative. Use protected routes for documents, never dashboard session/state.

- [ ] Add meaningful failing matcher/profile tests before core implementation.
- [ ] Build popup/options and content engine for supported fields, controlled inputs, DOM-added fields, preservation, undo and explicit file attachment.
- [ ] Implement scoped pairing, import/export and offline behavior, with readable errors and no personal logging.
- [ ] Test in real bundled Chromium on local application fixtures; verify no submit/next/consent actions. Document supported controls and limits.

## Task 4 dashboard, CI and release integration

Owner: root. Files: web/index.html, web/app.js, web/styles.css or new isolated extension settings module/styles, .github/workflows/**, README.md, docs/setup/development/architecture as appropriate, package.json, package script and new dashboard integration tests.

- [ ] Add dashboard pairing/status/revoke controls with explicit connect flow; native sign-in labels become platform-neutral.
- [ ] Add Node tests and native Mac CI matrix, platform service/wheel smoke and architecture-specific bundle artifacts.
- [ ] Package load-unpacked Chrome ZIP with versioned README; ensure generated archives exclude profile/token files. Prepare private user profile import separately if useful.
- [ ] Run complete Python, extension, formatting, wheel and local integration checks. Fix actual regressions.
- [ ] Obtain independent security/correctness review and address material findings.
- [ ] Build native Mac artifacts using existing authorized GitHub repository workflow, then deliver verified downloads with precise remaining signing/install steps.
