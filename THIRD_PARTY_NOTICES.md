# Third-party software

The MIT license in this repository covers JobPilot's first-party source. Dependencies, browser binaries, model weights and downloaded tools retain their own licenses. They are installed separately and are not vendored in this repository.

| Component | Purpose | Upstream |
| --- | --- | --- |
| FastAPI and Uvicorn | Local HTTP services | [FastAPI](https://github.com/fastapi/fastapi), [Uvicorn](https://github.com/encode/uvicorn) |
| Playwright | Browser automation and fixture tests | [Microsoft Playwright](https://github.com/microsoft/playwright-python) |
| pywebview and pystray | Windows window and system tray | [pywebview](https://github.com/r0x0r/pywebview), [pystray](https://github.com/moses-palmer/pystray) |
| JobSpy | Job-board discovery | [JobSpy](https://github.com/speedyapply/JobSpy) |
| ReportLab and python-docx | Application document export | [ReportLab](https://www.reportlab.com/), [python-docx](https://github.com/python-openxml/python-docx) |
| keyring | OS credential storage | [keyring](https://github.com/jaraco/keyring) |
| pywebpush and cryptography | Web Push encryption and delivery | [pywebpush](https://github.com/web-push-libs/pywebpush), [cryptography](https://github.com/pyca/cryptography) |
| Ollama and Qwen3.5 | Optional local document fact selection | [Ollama](https://github.com/ollama/ollama), [Qwen model](https://ollama.com/library/qwen3.5:9b) |
| cloudflared | Optional outbound HTTPS tunnel | [Cloudflare cloudflared](https://github.com/cloudflare/cloudflared) |

See each installed distribution's metadata and upstream license for its terms. PyInstaller-built distributions also contain their runtime dependencies and must retain the license files included by the build tools. Microsoft WebView2 and Chromium have separate distribution terms. Model weights are downloaded by Ollama; review the model's license before redistributing them.
