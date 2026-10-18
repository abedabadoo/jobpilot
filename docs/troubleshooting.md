# Troubleshooting

## The dashboard is running but applications are not moving

Check submission readiness and the recorded reason on each held job. Worker activity, document preparation and a confirmed application are different states. Search and submissions have separate controls. Missing job details, unsupported forms, authentication and unknown required questions each need a different correction.

Replace the fictional initial profile and save your actual career facts. Supply only screening answers you can confirm; exact employer questions can be entered in the advanced answers editor. Changing saved answers can release applicable unanswered-field holds, but cannot clear an uncertain submission. Sign-in must be verified before related authentication holds can resume.

## A submission is uncertain

Open the job's evidence and inspect the employer portal or receipt email. Use the recorded-outcome control only after verifying either the receipt or that no application was submitted. Manually verified outcomes are listed separately from automated receipt confirmations. Do not repeatedly retry or delete an uncertain record to clear its hold.

## Desktop or local service will not start

Run `JobPilot.exe --diagnose --report diagnosis.json` from the installation directory, or `.\.venv\Scripts\python.exe launcher.py --diagnose --report diagnosis.json` from a checkout. The report contains local paths; review it before sharing. Check `logs/desktop.log`, `logs/service.err.log` and `logs/ollama.err.log` under the data directory. A source run needs its own installed Python dependencies, Chromium and WebView2.

Only run one copy at a time. The launcher reuses local services at `127.0.0.1:8765` and `127.0.0.1:11436`. A port conflict can otherwise connect a source dashboard to a different running copy. Reinstall code using the original data path rather than deleting the database.

## Local model unavailable

Check that Ollama is installed and `qwen3.5:9b` exists in JobPilot's model store, not only another Ollama instance. Use the host and model-directory variables in [setup](setup.md). The launcher uses port `11436`. Preparation falls back to deterministic selection of saved facts when local inference is unavailable or invalid; it does not create missing qualifications.

## Search, sign-in or remote access fails

Search sites can rate-limit or block collection. Check activity, retry later or import the public employer posting. A successful login to one site does not establish a session on every employer portal.

For remote access, keep the PC awake and connected, check the local remote-access status and use its current pairing link. Quick Tunnel hostnames are temporary. Notification permission and delivery are separate from pairing; use the portal's notification test. See [remote access](remote-access.md).

## Remove old jobs

Use **Remove old jobs** in the pipeline and inspect the preview before confirming permanent deletion. It lists jobs posted at least seven days ago. Unknown or future posting dates, active applications and open verification sessions are kept. The preview expires after five minutes and eligibility is checked again when deleting.

Deletion removes the listed job and application records, including any outcomes in that list. Saved files stay on disk, and matching listings found again are ignored. Export or back up history you need before confirming. This action is not a receipt-resolution or disk-cleanup tool.
