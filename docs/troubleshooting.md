# Troubleshooting

## A resume or cover letter needs updating

Review the saved profile and the role's job description. Open **Review** to inspect extracted keywords, then regenerate the documents. Generation runs in the background; other roles and external links stay usable. Existing document versions remain on disk.

The resume contains saved experience plus a tailored skills section. New job terms can appear in the skills and cover-letter draft even when they are absent from the saved profile. Review the exports and edit them before applying.

## Opening a job link

Use the posting link in the role's Review view. JobPilot opens it in your default browser using that browser's saved sessions. This does not need the document worker or a separate automated browser. If the browser does not open, copy the visible posting link and check the Windows default browser association.

## Gmail is not connected

Save your Gmail address and a Google app password in Email, then use **Connect & test**. A successful save does not verify inbox access. **Sync now** reports the actual check time, messages read, links found, and jobs imported. An unsuccessful test shows an action to take; no normal account password is required.

If a scan checks fewer messages than the inbox contains in the chosen date window, increase the limit under Advanced or shorten the window. Messages remain unread, and JobPilot does not send or delete email. EML import remains available.

## Search or document preparation fails

Open **Problems** for a plain-language explanation and a link to the affected role. Import the public employer posting when a board omits the description or blocks a fetch. Resolve a problem after addressing it. Technical diagnostics remain in local logs for development.

Local-model failures use deterministic fact ranking rather than preventing document preparation. Check Ollama and the configured model if you want local ranking restored.

## Tracking applications

Use **Applied?** when you submit an application yourself. The role moves to Applied and retains its documents and fit score. Undo the applied mark to return it to Opportunities. No employer receipt is required for manual tracking.

Automatic submission and remote access are dormant. Older enabled preferences do not reactivate them in assistant mode.

## Desktop or local service will not start

Run `JobPilot.exe --diagnose --report diagnosis.json`, or run the source launcher with the same options. The diagnostic report contains local paths, so review it before sharing. Check `logs/desktop.log`, `logs/service.err.log`, and `logs/ollama.err.log` under the data directory.

Only run one copy at a time. The launcher reuses services on ports `8765` and `11436`. Back up the data directory and repair code using the original data path rather than deleting application history.

## Removing jobs

Use **Remove** on an individual opportunity. The listing is excluded from later searches and imports. The existing **Remove jobs 7+ days old** control previews eligible old listings before deletion. Unknown or future posting dates and active document work are kept. Saved document files stay on disk; this is not a disk cleanup tool.
