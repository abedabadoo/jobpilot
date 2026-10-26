"""Open job pages in the user's browser independently of document preparation."""

import ipaddress
import os
import webbrowser
from urllib.parse import urlsplit


def _windows():
    return os.name == "nt"


def open_external_url(url):
    if not isinstance(url, str) or len(url) > 8192 or any(c in url for c in "\r\n\\"):
        raise ValueError("This job link is invalid. Import its original posting URL.")
    url = url.strip()
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("This job link is invalid. Import its original posting URL.") from exc
    if (
        parsed.scheme not in {"https", "http"}
        or not host
        or parsed.username
        or parsed.password
        or port not in {None, 80, 443}
        or host == "localhost"
        or host.endswith((".localhost", ".local", ".internal"))
    ):
        raise ValueError("Use the job's public HTTP or HTTPS posting link.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Use the job's public HTTP or HTTPS posting link.")
    if _windows():
        os.startfile(url)
    elif not webbrowser.open_new_tab(url):
        raise OSError("Your default browser could not open this job. Copy its posting link.")
    return {"status": "opened", "opened": True, "mode": "default_browser", "url": url}
