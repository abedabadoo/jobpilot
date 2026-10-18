"""Small authenticated portal for the retained application browser only.

The companion deliberately has no dependency on, or routes from, the main app.
Adapters own durable sessions, browser-thread dispatch, and push validation.
"""

from __future__ import annotations

import ipaddress
import math
import re
import threading
import time
from collections import OrderedDict, deque
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .assets import asset_directory

_COOKIE = "jobpilot_remote"
_ASSETS = asset_directory("remote_web")
_CASE_FIELDS = frozenset(
    {
        "id",
        "job_id",
        "title",
        "company",
        "kind",
        "note",
        "submitted",
        "state",
        "created_at",
        "updated_at",
        "expires_at",
        "url",
        "last_error",
        "view_id",
        "width",
        "height",
    }
)
_KEYS = frozenset(
    {
        "Tab",
        "Shift+Tab",
        "Enter",
        "Backspace",
        "Delete",
        "Escape",
        "ArrowLeft",
        "ArrowRight",
        "ArrowUp",
        "ArrowDown",
        "Home",
        "End",
        "Space",
        "Control+A",
    }
)
_VIEW = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")
_BODY_LIMIT = 32768
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
    "connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


class _Limiter:
    def __init__(self, count: int, seconds: float):
        self.count, self.seconds = count, seconds
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def blocked(self, key, *, record=False):
        now = time.monotonic()
        with self.lock:
            queue = self.entries.setdefault(key, deque())
            self.entries.move_to_end(key)
            while queue and queue[0] <= now - self.seconds:
                queue.popleft()
            blocked = len(queue) >= self.count
            if record and not blocked:
                queue.append(now)
            while len(self.entries) > 1024:
                self.entries.popitem(last=False)
            return blocked


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def _public_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        if parsed.port:
            host += f":{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return ""


def _case_metadata(case):
    result = {key: value for key, value in case.items() if key in _CASE_FIELDS}
    result["url"] = _public_url(result.get("url"))
    return result


def _command(body):
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("view_id"), str)
        or not _VIEW.fullmatch(body["view_id"])
    ):
        raise HTTPException(422, "Refresh the browser view before using its controls.")
    kind = body.get("kind")
    fields = {
        "click": {"x", "y"},
        "scroll": {"delta_y"},
        "key": {"key"},
        "text": {"text"},
        "code": {"code"},
        "resume": set(),
        "cancel": set(),
    }
    if (
        not isinstance(kind, str)
        or kind not in fields
        or set(body) != {"kind", "view_id"} | fields[kind]
    ):
        raise HTTPException(422, "That browser control is not available.")
    if kind in {"click", "scroll"}:
        for field in fields[kind]:
            value = body[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise HTTPException(422, "Use a valid position in the browser view.")
            if kind == "click" and not 0 <= value <= 16384:
                raise HTTPException(422, "Use a position inside the browser view.")
            if kind == "scroll" and not -2000 <= value <= 2000:
                raise HTTPException(422, "Scroll a smaller distance.")
    elif kind == "key" and (not isinstance(body["key"], str) or body["key"] not in _KEYS):
        raise HTTPException(422, "That key is not available.")
    elif kind in {"text", "code"}:
        value = body[kind]
        limit = 4096 if kind == "text" else 32
        if not isinstance(value, str) or not 1 <= len(value) <= limit or "\x00" in value:
            raise HTTPException(422, "Enter a shorter value and try again.")
    return body


async def _read_bounded_body(request):
    """Stop receiving before buffering an unbounded public request body."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            length = int(declared)
        except ValueError:
            raise HTTPException(400, "Use a valid request.") from None
        if length < 0:
            raise HTTPException(400, "Use a valid request.")
        if length > _BODY_LIMIT:
            raise HTTPException(413, "That request is too large.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _BODY_LIMIT:
            raise HTTPException(413, "That request is too large.")
        chunks.append(chunk)
    # Starlette's cached request forwards this bounded body to the JSON route.
    request._body = b"".join(chunks)


def create_remote_app(broker, auth, notifications=None) -> FastAPI:
    """Build the isolated companion using the documented duck-typed adapters."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    pair_failures = _Limiter(5, 60)
    controls = _Limiter(40, 10)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if request.url.scheme != "https" and not _loopback(request.url.hostname):
            response = JSONResponse({"detail": "Open the secure JobPilot link."}, status_code=400)
        elif (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.headers.get("origin") != f"{request.url.scheme}://{request.url.netloc}"
        ):
            response = JSONResponse(
                {"detail": "Open JobPilot directly to use these controls."}, status_code=403
            )
        else:
            response = None
            if request.method == "POST":
                try:
                    await _read_bounded_body(request)
                except HTTPException as exc:
                    response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            if response is None:
                response = await call_next(request)
        response.headers.update(
            {
                "Content-Security-Policy": _CSP,
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Cross-Origin-Resource-Policy": "same-origin",
                "Cross-Origin-Opener-Policy": "same-origin",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            }
        )
        return response

    def session(request):
        token = request.cookies.get(_COOKIE, "")
        if not token or not auth.valid(token):
            raise HTTPException(401, "Pair this device to continue.")
        return token

    async def json_body(request):
        try:
            value = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Use a valid request.") from None
        if not isinstance(value, dict):
            raise HTTPException(422, "Use a valid request.")
        return value

    def unavailable(exc):
        if isinstance(exc, KeyError):
            return HTTPException(404, "This application is no longer available.")
        if "stale" in str(exc).lower():
            return HTTPException(409, "The browser changed. Wait for the new view and try again.")
        return HTTPException(409, "This browser is not ready. Refresh the view and try again.")

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.post("/api/pair")
    async def pair(request: Request):
        address = request.client.host if request.client else "unknown"
        if pair_failures.blocked(address):
            raise HTTPException(
                429,
                "Too many attempts. Wait a minute and try again.",
                headers={"Retry-After": "60"},
            )
        body = await json_body(request)
        secret = body.get("secret")
        token = (
            auth.exchange(secret)
            if isinstance(secret, str) and 32 <= len(secret) <= 256 and set(body) == {"secret"}
            else None
        )
        if not token:
            pair_failures.blocked(address, record=True)
            raise HTTPException(
                401, "This pairing link is invalid or has expired. Open a new link from JobPilot."
            )
        response = JSONResponse({"ok": True})
        response.set_cookie(
            _COOKIE,
            token,
            max_age=int(getattr(auth, "session_max_age", 604800)),
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/",
        )
        return response

    @app.post("/api/logout")
    def logout(request: Request):
        auth.revoke(session(request))
        response = JSONResponse({"ok": True})
        response.delete_cookie(
            _COOKIE,
            path="/",
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
        )
        return response

    @app.get("/api/cases")
    def cases(request: Request):
        session(request)
        return {"cases": [_case_metadata(case) for case in broker.list_cases()]}

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str, request: Request):
        session(request)
        try:
            return _case_metadata(broker.get_case(case_id))
        except (KeyError, ValueError) as exc:
            raise unavailable(exc) from None

    @app.get("/api/cases/{case_id}/frame")
    def frame(case_id: str, request: Request):
        session(request)
        try:
            current = broker.frame(case_id)
            view_id = str(current["view_id"])
            if not _VIEW.fullmatch(view_id):
                raise ValueError("invalid view")
            return Response(
                current["png"],
                media_type="image/png",
                headers={
                    "X-View-Id": view_id,
                    "X-Browser-Width": str(int(current["width"])),
                    "X-Browser-Height": str(int(current["height"])),
                },
            )
        except (KeyError, ValueError) as exc:
            raise unavailable(exc) from None

    @app.post("/api/cases/{case_id}/input")
    async def control(case_id: str, request: Request):
        token = session(request)
        if controls.blocked(token, record=True):
            raise HTTPException(
                429, "Pause briefly before using another control.", headers={"Retry-After": "10"}
            )
        body = _command(await json_body(request))
        try:
            return broker.command(case_id, body)
        except (KeyError, ValueError) as exc:
            raise unavailable(exc) from None

    def push_adapter(request):
        token = session(request)
        if notifications is None:
            raise HTTPException(503, "Notifications are not available yet.")
        return token

    @app.get("/api/push/key")
    def push_key(request: Request):
        push_adapter(request)
        return {"public_key": notifications.public_key()}

    @app.post("/api/push/subscribe")
    async def push_subscribe(request: Request):
        token = push_adapter(request)
        try:
            return notifications.subscribe(await json_body(request), token)
        except ValueError:
            raise HTTPException(422, "This notification subscription is not valid.") from None

    @app.post("/api/push/unsubscribe")
    def push_unsubscribe(request: Request):
        token = push_adapter(request)
        return notifications.unsubscribe(token)

    @app.post("/api/push/test")
    def push_test(request: Request):
        token = push_adapter(request)
        return notifications.test(token)

    for route, filename, media in [
        ("/", "index.html", "text/html"),
        ("/app.js", "app.js", "text/javascript"),
        ("/style.css", "style.css", "text/css"),
        ("/sw.js", "sw.js", "text/javascript"),
        ("/manifest.webmanifest", "manifest.webmanifest", "application/manifest+json"),
        ("/icons/icon.svg", "icons/icon.svg", "image/svg+xml"),
        ("/icons/icon-192.png", "icons/icon-192.png", "image/png"),
        ("/icons/icon-512.png", "icons/icon-512.png", "image/png"),
    ]:
        # Empty parameter signatures prevent accidental path/query overrides.
        def make_asset(path, content_type):
            def serve():
                return FileResponse(path, media_type=content_type)

            return serve

        app.add_api_route(
            route, make_asset(_ASSETS / filename, media), methods=["GET"], include_in_schema=False
        )
    return app
