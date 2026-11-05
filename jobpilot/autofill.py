"""Narrow, origin-bound Chrome profile and prepared-document access.

The dashboard credential is never accepted on extension consumer routes. Only
digests of short-lived pairing codes and independent bearer tokens are saved.
"""

import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

PREFIX = "/api/extension/"
MAX_BODY = 4096
MAX_DOCUMENT = 5 * 1024 * 1024
DOCUMENT_TYPES = {
    "resume_pdf": (".pdf", "application/pdf"),
    "resume_docx": (
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "cover_pdf": (".pdf", "application/pdf"),
    "cover_docx": (
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}
TEXT_FIELDS = (
    "name first_name last_name email phone location address_line1 address_line2 city state "
    "postal_code country linkedin website github portfolio current_employer current_title "
    "salary_expectation salary_currency available_date years_experience"
).split()
BOOL_FIELDS = ("work_authorized", "requires_sponsorship", "willing_to_relocate")
LIST_FIELDS = ("skills", "certifications", "interests")
EXPERIENCE_FIELDS = ("company", "title", "start", "end", "location", "description")
EDUCATION_FIELDS = ("institution", "degree", "field_of_study", "start", "end", "gpa")


def utc_now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def project_profile(source):
    """Copy only typed, explicitly supported values, including nested rows."""
    source = source if isinstance(source, dict) else {}
    result = {key: source[key] for key in TEXT_FIELDS if isinstance(source.get(key), str)}
    for key in ("salary_expectation", "years_experience"):
        if type(source.get(key)) in (int, float):
            result[key] = source[key]
    for key in BOOL_FIELDS:
        result[key] = source.get(key) if type(source.get(key)) is bool else None
    for key in LIST_FIELDS:
        values = source.get(key)
        result[key] = (
            [item for item in values if isinstance(item, str)] if isinstance(values, list) else []
        )
    for key, fields in (("experience", EXPERIENCE_FIELDS), ("education", EDUCATION_FIELDS)):
        result[key] = []
        rows = source.get(key)
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            projected = {field: row[field] for field in fields if isinstance(row.get(field), str)}
            if key == "experience" and not projected.get("description"):
                facts = row.get("facts")
                projected["description"] = (
                    "\n".join(
                        fact["text"]
                        for fact in facts
                        if isinstance(fact, dict) and isinstance(fact.get("text"), str)
                    )
                    if isinstance(facts, list)
                    else ""
                )
            result[key].append(projected)
    return result


class ExtensionAPI:
    def __init__(self, store, data, dashboard_token):
        self.store = store
        self.data = Path(data)
        self.dashboard_token = dashboard_token
        # Store's RLock makes read/consume/write atomic across concurrent requests.
        self.lock = store.lock
        self.rates = {}
        self.router = APIRouter(prefix="/api/extension")
        self.router.add_api_route("/pairing", self.issue, methods=["POST"])
        self.router.add_api_route("/pair", self.pair, methods=["POST"])
        # Chromium omits Origin on extension GET fetches. POST read aliases keep
        # strict origin binding while allowing the browser to supply Origin.
        self.router.add_api_route("/profile", self.profile, methods=["GET", "POST"])
        self.router.add_api_route("/documents", self.documents, methods=["GET", "POST"])
        self.router.add_api_route(
            "/documents/{job_id}/{kind}", self.document, methods=["GET", "POST"]
        )
        self.router.add_api_route("/pairings", self.pairings, methods=["GET"])
        self.router.add_api_route("/pairings/{pairing_id}/revoke", self.revoke, methods=["POST"])
        self.router.add_api_route("/disconnect", self.disconnect, methods=["POST"])

    def _state(self):
        state = self.store.get("_extension_connections", {"pending": [], "pairings": []})
        now = utc_now().isoformat()
        return {
            key: [row for row in state.get(key, []) if row.get("expires_at", "") > now]
            for key in ("pending", "pairings")
        }

    def _save(self, state):
        self.store.set("_extension_connections", state)

    def _known_origin(self, origin):
        if not origin or not re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
            return False
        with self.lock:
            state = self._state()
            return any(row["origin"] == origin for rows in state.values() for row in rows)

    @staticmethod
    def _route(path):
        if path == PREFIX + "pair":
            return ("POST",), False
        if path in (PREFIX + "profile", PREFIX + "documents") or re.fullmatch(
            re.escape(PREFIX)
            + r"documents/[1-9][0-9]*/(?:resume_pdf|resume_docx|cover_pdf|cover_docx)",
            path,
        ):
            return ("GET", "POST"), False
        if path == PREFIX + "disconnect":
            return ("POST",), False
        if path == PREFIX + "pairing" or re.fullmatch(
            re.escape(PREFIX) + r"pairings/[^/]+/revoke", path
        ):
            return ("POST",), True
        if path == PREFIX + "pairings":
            return ("GET",), True
        return None

    def _rate_allowed(self, request):
        now = time.monotonic()
        window = int(now // 60)
        identity = request.headers.get("origin", "dashboard")
        pairing = request.url.path == PREFIX + "pair"
        with self.lock:
            self.rates = {key: value for key, value in self.rates.items() if value[0] == window}
            # Global cap also bounds memory when arbitrary extension IDs are sent.
            keys = [("all", 600), ((identity, pairing), 10 if pairing else 120)]
            for key, limit in keys:
                if self.rates.get(key, (window, 0))[1] >= limit:
                    return False
            for key, _ in keys:
                self.rates[key] = (window, self.rates.get(key, (window, 0))[1] + 1)
        return True

    def _authenticate(self, request):
        origin = request.headers.get("origin")
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) > 256:
            raise HTTPException(403, "Extension connection required.")
        hashed = digest(authorization[7:])
        with self.lock:
            for row in self._state()["pairings"]:
                if row["origin"] == origin and secrets.compare_digest(row["token_digest"], hashed):
                    return row
        raise HTTPException(403, "Extension connection required.")

    async def security(self, request, call_next):
        """Called only for this namespace; no dashboard allowlist is broadened."""
        origin = request.headers.get("origin")
        route = self._route(request.url.path)
        if not route:
            return JSONResponse({"detail": "Extension route not found."}, status_code=404)
        methods, dashboard = route
        cors = False
        try:
            if dashboard:
                if origin and (
                    origin.startswith("chrome-extension:") or not self._local_origin(origin)
                ):
                    raise HTTPException(403, "Dashboard session required.")
                if request.method not in methods or not secrets.compare_digest(
                    request.headers.get("X-JobPilot-Token", ""), self.dashboard_token
                ):
                    raise HTTPException(403, "Dashboard session token required.")
            else:
                if not self._known_origin(origin):
                    raise HTTPException(403, "Extension origin is not paired or pending.")
                cors = True
                if request.method == "OPTIONS":
                    headers = {
                        value.strip().lower()
                        for value in request.headers.get(
                            "access-control-request-headers", ""
                        ).split(",")
                        if value.strip()
                    }
                    if request.headers.get(
                        "access-control-request-method"
                    ) not in methods or not headers <= {"authorization", "content-type"}:
                        raise HTTPException(403, "Unsupported extension preflight.")
                    return Response(
                        status_code=204,
                        headers={
                            "Access-Control-Allow-Origin": origin,
                            "Access-Control-Allow-Methods": ", ".join(methods),
                            "Access-Control-Allow-Headers": "Authorization, Content-Type",
                            "Vary": "Origin",
                        },
                    )
                if request.method not in methods:
                    raise HTTPException(403, "Unsupported extension method.")
                if request.url.path != PREFIX + "pair":
                    request.state.extension_pairing = self._authenticate(request)
            if not self._rate_allowed(request):
                raise HTTPException(429, "Too many extension requests. Try again in a minute.")
            if request.method == "POST":
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BODY:
                        raise HTTPException(413, "Extension request is too large.")
                try:
                    parsed = json.loads(body) if body else {}
                except (ValueError, UnicodeDecodeError) as exc:
                    raise HTTPException(400, "Expected a JSON object.") from exc
                if not isinstance(parsed, dict):
                    raise HTTPException(400, "Expected a JSON object.")
                request.state.extension_body = parsed
            response = await call_next(request)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if cors:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @staticmethod
    def _local_origin(origin):
        from urllib.parse import urlsplit

        try:
            parsed = urlsplit(origin)
            return parsed.scheme in ("http", "https") and parsed.hostname in (
                "127.0.0.1",
                "localhost",
                "::1",
                "testserver",
            )
        except ValueError:
            return False

    def issue(self, request: Request):
        extension_id = request.state.extension_body.get("extension_id")
        if not isinstance(extension_id, str) or not re.fullmatch("[a-p]{32}", extension_id):
            raise HTTPException(400, "Enter a valid Chrome extension ID.")
        code = secrets.token_urlsafe(24)
        expires = (utc_now() + timedelta(minutes=5)).isoformat()
        origin = "chrome-extension://" + extension_id
        with self.lock:
            state = self._state()
            state["pending"] = [row for row in state["pending"] if row["origin"] != origin]
            state["pending"].append(
                {"origin": origin, "code_digest": digest(code), "expires_at": expires}
            )
            self._save(state)
        return {"code": code, "expires_at": expires}

    def pair(self, request: Request):
        code = request.state.extension_body.get("code")
        if not isinstance(code, str) or not code or len(code) > 128:
            raise HTTPException(403, "Invalid or expired pairing code.")
        with self.lock:
            state = self._state()
            match = next(
                (
                    row
                    for row in state["pending"]
                    if row["origin"] == request.headers.get("origin")
                    and secrets.compare_digest(row["code_digest"], digest(code))
                ),
                None,
            )
            if match is None:
                raise HTTPException(403, "Invalid or expired pairing code.")
            state["pending"].remove(match)
            token = secrets.token_urlsafe(48)
            pairing_id = secrets.token_urlsafe(18)
            expires = (utc_now() + timedelta(days=90)).isoformat()
            state["pairings"].append(
                {
                    "pairing_id": pairing_id,
                    "origin": match["origin"],
                    "extension_id": match["origin"].split("://")[1],
                    "token_digest": digest(token),
                    "created_at": utc_now().isoformat(),
                    "expires_at": expires,
                }
            )
            self._save(state)
        return {"token": token, "pairing_id": pairing_id, "expires_at": expires}

    def profile(self):
        return {"schema_version": 1, "profile": project_profile(self.store.get("profile", {}))}

    def _document_target(self, job, kind):
        if kind not in DOCUMENT_TYPES:
            raise HTTPException(404, "Prepared document not found.")
        documents = job.get("documents")
        value = documents.get(kind) if isinstance(documents, dict) else None
        if not isinstance(value, str) or not value or "\x00" in value:
            raise HTTPException(404, "Prepared document not found.")
        try:
            applications = self.data.resolve() / "applications"
            base = applications.resolve()
            target = Path(value).resolve()
            if base != applications or not target.is_relative_to(base):
                raise HTTPException(403, "Document is outside prepared applications.")
            if target.suffix.lower() != DOCUMENT_TYPES[kind][0]:
                raise HTTPException(403, "Unsupported document file.")
            if not target.is_file():
                raise HTTPException(404, "Prepared document is missing.")
            if target.stat().st_size > MAX_DOCUMENT:
                raise HTTPException(413, "Documents must be 5 MiB or smaller.")
            return target
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(404, "Prepared document is unavailable.") from exc

    def documents(self):
        documents = []
        for job in self.store.jobs():
            for kind in DOCUMENT_TYPES:
                try:
                    target = self._document_target(job, kind)
                except HTTPException:
                    continue
                documents.append(
                    {
                        "job_id": job["id"],
                        "title": job.get("title", ""),
                        "company": job.get("company", ""),
                        "kind": kind,
                        "name": target.name,
                        "download_path": f"{PREFIX}documents/{job['id']}/{kind}",
                    }
                )
        return {"documents": documents}

    def document(self, job_id: int, kind: str):
        job = self.store.get_job(job_id)
        if not job:
            raise HTTPException(404, "Prepared document not found.")
        target = self._document_target(job, kind)
        return FileResponse(target, filename=target.name, media_type=DOCUMENT_TYPES[kind][1])

    def pairings(self):
        with self.lock:
            return {
                "pairings": [
                    {
                        key: row[key]
                        for key in ("pairing_id", "extension_id", "created_at", "expires_at")
                    }
                    for row in self._state()["pairings"]
                ]
            }

    def _revoke(self, pairing_id):
        with self.lock:
            state = self._state()
            state["pairings"] = [
                row for row in state["pairings"] if row["pairing_id"] != pairing_id
            ]
            self._save(state)
        return {"ok": True}

    def revoke(self, pairing_id: str):
        return self._revoke(pairing_id)

    def disconnect(self, request: Request):
        return self._revoke(request.state.extension_pairing["pairing_id"])
