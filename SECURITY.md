# Security

Report suspected vulnerabilities privately through [GitHub security advisories](https://github.com/abedabadoo/jobpilot/security/advisories/new). Include the affected version, a minimal reproduction, and the impact. Keep credentials, applicant documents, screenshots of private pages, and pairing links out of issues and reports.

The dashboard listens on loopback port 8765. Do not expose that port through a reverse proxy or tunnel. The optional remote portal uses a separate service on loopback port 8766 and requires device pairing. Treat its pairing link as a credential. Revoke paired sessions from the local setup page if a device or link is lost.

Application state, documents, browser profiles, and logs belong outside the repository. Windows Credential Manager stores mailbox credentials and remote private keys. Keep your browser, Python dependencies, model runtime, and tunnel client updated.
