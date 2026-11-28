# Third-party software

The MIT license in this repository covers JobPilot's first-party source. Dependencies, browser binaries, model weights and downloaded tools retain their own licenses. Native application builds bundle some dependencies; the Liberation Sans font license is included with the bundled font files.

| Component | Purpose | Upstream |
| --- | --- | --- |
| FastAPI and Uvicorn | Local HTTP services | [FastAPI](https://github.com/fastapi/fastapi), [Uvicorn](https://github.com/encode/uvicorn) |
| Playwright | Browser automation and fixture tests | [Microsoft Playwright](https://github.com/microsoft/playwright-python) |
| pywebview, PyObjC and pystray | Native desktop windows, Cocoa bridge and Windows system tray | [pywebview](https://github.com/r0x0r/pywebview), [PyObjC](https://github.com/ronaldoussoren/pyobjc), [pystray](https://github.com/moses-palmer/pystray) |
| JobSpy | Job-board discovery | [JobSpy](https://github.com/speedyapply/JobSpy) |
| open-jobs board directory (CC0-1.0) | Seed list of public Greenhouse board slugs | [open-jobs](https://github.com/elliottdehn/open-jobs/blob/main/slugs.json) |
| ReportLab | ResumeForge PDF export | [ReportLab](https://www.reportlab.com/) |
| PySide6 Essentials and PDFium | ResumeForge editor and PDF preview | [Qt for Python](https://doc.qt.io/qtforpython-6/), [PDFium](https://pdfium.googlesource.com/pdfium/) |
| keyring | OS credential storage | [keyring](https://github.com/jaraco/keyring) |
| pywebpush and cryptography | Web Push encryption and delivery | [pywebpush](https://github.com/web-push-libs/pywebpush), [cryptography](https://github.com/pyca/cryptography) |
| llama.cpp, Ollama and Qwen3.5 | Configurable local ResumeForge inference; the Intel default is Qwen3.5 4B Q4 through llama.cpp | [llama.cpp](https://github.com/ggml-org/llama.cpp), [Ollama](https://github.com/ollama/ollama), [Qwen](https://huggingface.co/Qwen) |
| cloudflared | Optional outbound HTTPS tunnel | [Cloudflare cloudflared](https://github.com/cloudflare/cloudflared) |

See each installed distribution's metadata and upstream license for its terms. PyInstaller-built distributions also contain their runtime dependencies and must retain the license files included by the build tools. Microsoft WebView2 and Chromium have separate distribution terms. Local model weights are configured separately and are not bundled; review a model's license before redistributing it.
