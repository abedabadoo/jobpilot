# Contributing

Start with [development setup](docs/development.md). Open an issue before changing application state transitions, receipt detection, browser ownership, or remote authentication.

Keep changes focused. Include a regression test for a bug fix and describe how you checked the result. Browser tests use local fixture sites and isolated databases. Tests must not submit real applications, use saved browser profiles, or depend on a live job board.

Before opening a pull request:

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
npm ci
npm run format:check
```

Comments should explain constraints or decisions that the code cannot show on its own. Use plain language in user-facing copy. Keep personal data, logs, local paths, and generated application files out of commits.
