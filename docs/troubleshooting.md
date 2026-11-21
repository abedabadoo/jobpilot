# Troubleshooting

## A resume or cover letter needs updating

Review the saved ResumeForge profile and the role's job description. Open **Review** to inspect JobPilot's quick keyword view, then open the role in ResumeForge to inspect its contextual priorities and regenerate the resume. Generation runs in the background; other roles and external links stay usable. Existing role-workspace revisions remain on disk.

ResumeForge owns the tailored experience, skills, page fitting, and final PDF. Cover letters are optional and must be created explicitly after a checked resume exists; JobPilot never creates one automatically.

## Opening a job link

Use the posting link in the role's Review view. JobPilot opens it in your default browser using that browser's saved sessions. This does not need the document worker or a separate automated browser. If the browser does not open, copy the visible posting link and check the Windows default browser association.

## Gmail is not connected

Save your Gmail address and a Google app password in Email, then use **Connect & test**. A successful save does not verify inbox access. **Sync now** reports the actual check time, messages read, links found, and jobs imported. An unsuccessful test shows an action to take; no normal account password is required.

If a scan checks fewer messages than the inbox contains in the chosen date window, increase the limit under Advanced or shorten the window. Messages remain unread, and JobPilot does not send or delete email. EML import remains available.

## Search or document preparation fails

Check the **Job monitoring** panel for each source's status and new, already saved, and filtered counts. Use **Clear filters** beside the opportunity count if a previous source or text filter is hiding jobs. Email digests can contain several roles; sync results count each distinct link, and alerts outside your preferences do not enter the opportunity list.

LinkedIn may rate limit public searches. JobPilot keeps available cards, pauses further requests to that source for at least 15 minutes, and continues the other sources. Missing descriptions require review on the original posting. A rate limit does not mean Gmail alerts or Indeed searches also failed. Monitoring polls on the chosen interval while this PC is running; it does not receive instant posting notifications from job boards.

Open **Problems** for a plain-language explanation and a link to the affected role. Import the public employer posting when a board omits the description or blocks a fetch. Resolve a problem after addressing it. Technical diagnostics remain in local logs for development.

If a high-fit role says **Setup required**, open **ResumeForge profile** and save a source profile and model choice. Offline mode remains available. For a configured model, test its endpoint from ResumeForge's model settings; JobPilot deliberately does not start or poll a separate model service. Transient generation failures retry with a bounded delay, while content or review failures remain available in the editor for correction.

## Tracking applications

Use **Applied?** when you submit an application yourself. The role moves to Applied and retains its documents and fit score. Undo the applied mark to return it to Opportunities. No employer receipt is required for manual tracking.

Automatic submission and remote access are dormant. Older enabled preferences do not reactivate them in assistant mode.

## Desktop or local service will not start

Run `JobPilot.exe --diagnose --report diagnosis.json`, or run the source launcher with the same options. The diagnostic report contains local paths, so review it before sharing. Check `logs/desktop.log` and `logs/service.err.log` under the JobPilot data directory. A configured ResumeForge local runtime writes its own server log under the ResumeForge application-support directory.

Only run one copy at a time. The launcher reuses the loopback service on port `8765`. Back up the data directory and repair code using the original data path rather than deleting application history.

## Removing jobs

Use **Remove** on an individual opportunity. The listing is excluded from later searches and imports. The existing **Remove jobs 7+ days old** control previews eligible old listings before deletion. Unknown or future posting dates and active document work are kept. Saved document files stay on disk; this is not a disk cleanup tool.
