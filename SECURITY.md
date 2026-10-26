# Security

Report suspected vulnerabilities privately through [GitHub security advisories](https://github.com/abedabadoo/jobpilot/security/advisories/new). Include the affected version, a minimal reproduction, and the impact. Keep credentials, applicant documents, screenshots of private pages, and pairing links out of issues and reports.

The dashboard listens on loopback port 8765. Do not expose that port through a reverse proxy or tunnel. Assistant mode disables automated submissions and remote access, including settings carried over from older installations. Legacy remote modules remain for regression testing and are outside the active workflow.

Application state, documents, browser profiles, and logs belong outside the repository. Windows Credential Manager stores mailbox credentials. Gmail checks use a read-only mailbox session and do not send, delete, or mark messages read. Keep your browser, Python dependencies, and model runtime updated.
