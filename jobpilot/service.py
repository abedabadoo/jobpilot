"""Authenticated loopback API and independently scheduled persistent workers."""

import argparse
import csv
import ctypes
import io
import json
import os
import re
import secrets
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .assets import asset_directory
from .core import eligibility, facts_map, role_assessment, score_job
from .documents import local_endpoint, prepare
from .remote_runtime import RemoteRuntime
from .store import Store

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(
    os.environ.get(
        "JOBPILOT_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", ROOT)) / "JobPilot")
    )
).resolve()
DATA.mkdir(parents=True, exist_ok=True)
store = Store(DATA / "jobpilot.sqlite")
seed = json.loads((ROOT / "jobpilot/candidate.json").read_text(encoding="utf-8"))
DEFAULTS = {
    "target_roles": [
        "Security Engineer",
        "Cloud Security Engineer",
        "Information Security Analyst",
        "GRC Analyst",
        "Security Analyst",
    ],
    "location": "Cincinnati, OH",
    "remote": True,
    "search_interval_minutes": 30,
    "min_fit": 40,
    "search_enabled": False,
    "submission_enabled": False,
    "keep_awake": False,
    "startup": False,
    "remote_intervention_enabled": False,
    "intervention_timeout_seconds": 28800,
    "ollama_url": "http://127.0.0.1:11436",
    "model": "qwen3.5:9b",
    "sources": ["linkedin", "indeed"],
    "results_per_source": 12,
    "hours_old": 168,
    "ats_boards": [
        {"source": "greenhouse", "board": "cloudflare"},
        {"source": "greenhouse", "board": "datadog"},
    ],
}
for key, default in [("settings", DEFAULTS), ("profile", seed), ("answers", {})]:
    if store.get(key) is None:
        store.set(key, default)
if os.environ.get("JOBPILOT_DESKTOP_EXE"):
    store.set("desktop_exe", os.environ["JOBPILOT_DESKTOP_EXE"])
TOKEN = store.get("_session_token") or secrets.token_urlsafe(32)
store.set("_session_token", TOKEN)
stop_event = threading.Event()
remote_runtime = RemoteRuntime(DATA, stop_event, vapid_subject="mailto:" + seed["email"])
search_requested = threading.Event()
application_lock = threading.RLock()
cleanup_previews = {}
cleanup_preview_lock = threading.RLock()
server_instance = None
worker = {
    "searching": False,
    "submitting": False,
    "heartbeat": None,
    "current": None,
    "last_search": store.get("last_search"),
    "last_error": None,
    "model_status": "Checking local model",
    "email_status": "Not configured",
}


def settings():
    return {**DEFAULTS, **store.get("settings", {}), "data_dir": str(DATA)}


def report_error(message):
    worker["last_error"] = str(message)[:1000]
    store.event(message, "error")


def classify_job(job, profile, conf):
    fields = {
        "url",
        "source_url",
        "apply_url",
        "title",
        "company",
        "source",
        "location",
        "description",
        "posted_at",
        "requisition_id",
        "is_remote",
        "salary_min",
        "salary_max",
        "description_missing",
        "needs_description_review",
    }
    job = {k: v for k, v in job.items() if k in fields}
    job["status"] = "queued"
    job["fit"] = 0
    if job.get("company", "").casefold() in [
        x.casefold() for x in conf.get("excluded_companies", [])
    ]:
        job.update(status="skipped", note="Company is excluded in preferences.")
        return job
    role_status, role_note = role_assessment(job, profile, conf)
    if role_status == "excluded":
        job.update(status="skipped", note=role_note)
        return job
    job["fit"] = score_job(job, profile, conf)
    geo, reason = eligibility(job, conf)
    if geo == "excluded":
        job.update(status="skipped", note=reason)
        return job
    missing = (
        job.get("description_missing")
        or len(str(job.get("description", "")).strip()) < 80
        or not job.get("company")
        or not job.get("title")
    )
    if missing:
        job.update(
            status="needs_review",
            note="The source did not provide a usable job description or employer. Import the employer listing before applying.",
        )
        return job
    if job["fit"] < conf["min_fit"]:
        job.update(status="skipped", note="Fit is below the configured search threshold.")
        return job
    if role_status == "review" or geo == "review":
        job.update(
            status="needs_review",
            note=" ".join(
                value
                for value in [
                    role_note if role_status == "review" else "",
                    reason if geo == "review" else "",
                ]
                if value
            ),
            review_reason="role_review" if role_status == "review" else "location_review",
        )
    return job


def discover_once():
    from . import collectors

    worker["searching"] = True
    conf = settings()
    conf["search_titles"] = conf["target_roles"]
    conf["locations"] = [conf["location"]]
    profile = store.get("profile")
    try:
        before = len(store.jobs())
        jobs = collectors.discover(conf, profile)
        for job in jobs:
            if not job.get("url") or not job.get("title"):
                continue
            job = classify_job(job, profile, conf)
            if job.get("status") == "skipped":
                continue
            store.add_job(job)
        worker["last_search"] = store.now()
        store.set("last_search", worker["last_search"])
        store.event(
            f"Search finished: {len(store.jobs()) - before} new matching opportunities; {len(jobs)} source records checked."
        )
        for error in getattr(collectors, "get_last_errors", lambda: [])():
            report_error(
                f"{error.get('source', 'Source').title()}: {error.get('note', '')}"
                if isinstance(error, dict)
                else str(error)
            )
    except Exception as exc:
        report_error(f"Discovery failed: {type(exc).__name__}: {exc}")
    finally:
        worker["searching"] = False


def discovery_loop():
    next_search = time.monotonic() + 5
    while not stop_event.wait(1):
        worker["heartbeat"] = store.now()
        conf = settings()
        requested = search_requested.is_set()
        if requested or (conf["search_enabled"] and time.monotonic() >= next_search):
            search_requested.clear()
            discover_once()
            next_search = time.monotonic() + conf["search_interval_minutes"] * 60


def prepare_job(job_id, preserve_review=False):
    with application_lock:
        job = store.get_job(job_id)
        if (
            not job
            or job.get("uncertain")
            or _manual_handoff_active(job)
            or job["status"]
            in ["confirmed", "manually_verified", "applying", "submitting", "skipped"]
        ):
            return
        preserve_review = preserve_review or job["status"] == "needs_review"
        review_note = (
            (job.get("preparation_prior_note") or job.get("note", "")) if preserve_review else ""
        )
        worker["current"] = job["title"]
        store.update_job(
            job_id,
            status="preparing",
            preparation_prior_status="needs_review" if preserve_review else "queued",
            preparation_prior_note=review_note,
            note="Selecting verified career facts and creating application documents.",
        )
        try:
            documents = prepare(job, store.get("profile"), DATA / "applications", settings())
            final_status = "needs_review" if preserve_review else "prepared"
            job = store.update_job(
                job_id,
                status=final_status,
                documents=documents,
                application={
                    "documents": documents,
                    "status": final_status,
                    "note": documents["generation_note"],
                },
                note=review_note + " Application documents ready. " + documents["generation_note"],
                preparation_prior_status=None,
                preparation_prior_note=None,
            )
            store.event(
                f"Prepared {job['title']} at {job.get('company', '')} using {documents['generation_mode']} selection."
            )
            return job
        except Exception as exc:
            store.update_job(
                job_id,
                status="error",
                note=f"Document preparation failed: {type(exc).__name__}: {exc}",
            )
            report_error(f"Document preparation failed for job {job_id}: {exc}")
        finally:
            worker["current"] = None


def apply_job(job_id):
    from . import browser

    with application_lock:
        job = store.get_job(job_id)
        if (
            not job
            or job.get("uncertain")
            or _manual_handoff_active(job)
            or job["status"] not in ["queued", "prepared"]
        ):
            return
        role_status, role_note = role_assessment(job, store.get("profile"), settings())
        if role_status != "eligible":
            store.update_job(
                job_id,
                status="skipped" if role_status == "excluded" else "needs_review",
                note=role_note,
                review_reason="role_review",
                auth_platform=None,
                auth_url=None,
            )
            store.event(f"Role assessment held {job['title']}: {role_note}")
            return
        geo_status, geo_note = eligibility(job, settings())
        if geo_status != "eligible":
            store.update_job(
                job_id,
                status="skipped" if geo_status == "excluded" else "needs_review",
                note=geo_note,
                review_reason="location_review",
                auth_platform=None,
                auth_url=None,
            )
            store.event(f"Location assessment held {job['title']}: {geo_note}")
            return
        if browser.login_in_progress():
            return
        if not job.get("documents"):
            job = prepare_job(job_id)
        if not job or not settings()["submission_enabled"] or browser.login_in_progress():
            return
        worker["submitting"] = True
        worker["current"] = job["title"]
        store.update_job(
            job_id,
            status="applying",
            attempts=job.get("attempts", 0) + 1,
            note="Inspecting application form.",
        )
        paused_before_click = False
        approved_answers = store.get("answers", {})
        candidate = store.get("profile")

        def checkpoint(info=None):
            nonlocal paused_before_click
            current = store.get_job(job_id)
            if not settings()["submission_enabled"] or current["status"] not in [
                "applying",
                "submitting",
            ]:
                paused_before_click = True
                raise RuntimeError(
                    "Submissions paused before the final click; no new submission attempted."
                )
            store.update_job(
                job_id,
                status="submitting",
                submission_checkpoint_at=store.now(),
                uncertain=True,
                application={
                    "documents": job["documents"],
                    "status": "submitting",
                    "evidence": (info or {}).get("evidence", []),
                    "answers_supplied": approved_answers,
                    "profile_snapshot": candidate,
                },
                note="Submission click checkpoint saved; awaiting employer confirmation.",
            )

        try:
            remote_options = (
                {"intervention_handler": remote_runtime.broker.pause}
                if settings()["remote_intervention_enabled"]
                and remote_runtime.status()["listening"]
                else {}
            )
            result = browser.apply(
                job,
                candidate,
                approved_answers,
                job["documents"],
                settings(),
                checkpoint=checkpoint,
                **remote_options,
            )
            status = result.get("status", "needs_review")
            if status not in ["confirmed", "needs_review", "error"]:
                status = "needs_review"
            submitted = bool(result.get("submitted"))
            if (
                not submitted
                and result.get("note") == "Close the JobPilot login browser before applying"
            ):
                status = "prepared"
                result["note"] = (
                    "Waiting for the interactive sign-in browser to close; application remains queued."
                )
            if paused_before_click and not submitted:
                status = "prepared"
                result["note"] = (
                    "Submissions paused before the final click; package retained for resuming."
                )
            evidence = result.get("evidence", [])
            if status == "confirmed" and (not evidence or not submitted):
                status = "needs_review"
                result["note"] = (
                    "Adapter did not provide a submitted receipt with evidence; verify manually."
                )
            review_metadata = {
                key: result.get(key) for key in ["review_reason", "auth_platform", "auth_url"]
            }
            with store.lock:
                waiting_for_answers = result.get("review_reason") == "unanswered_fields" or str(
                    result.get("note", "")
                ).startswith("Fields need saved answers or review:")
                if (
                    status == "needs_review"
                    and not submitted
                    and waiting_for_answers
                    and store.get("answers", {}) != approved_answers
                ):
                    status = "prepared"
                    result["note"] = (
                        "Screening answers changed during form inspection; requeued once with the current saved answers."
                    )
                updates = {
                    "status": status,
                    "note": result.get("note", ""),
                    "uncertain": submitted and status != "confirmed",
                    **review_metadata,
                    "application": {
                        "status": status,
                        "note": result.get("note", ""),
                        "documents": job["documents"],
                        "evidence": evidence,
                        "answers_supplied": approved_answers,
                        "profile_snapshot": candidate,
                        **review_metadata,
                    },
                }
                if status == "confirmed":
                    updates["confirmed_at"] = store.now()
                store.update_job(job_id, **updates)
            store.event(
                f"{status.replace('_', ' ').title()}: {job['title']} at {job.get('company', '')}. {result.get('note', '')}",
                "error" if status == "error" else "info",
            )
        except Exception as exc:
            current = store.get_job(job_id)
            uncertain = current["status"] == "submitting" or current.get("uncertain", False)
            final_status = (
                "needs_review" if uncertain else ("prepared" if paused_before_click else "error")
            )
            store.update_job(
                job_id,
                status=final_status,
                uncertain=uncertain,
                note=f"{'Submission outcome uncertain. ' if uncertain else ''}{type(exc).__name__}: {exc}",
            )
            report_error(f"Application job {job_id}: {type(exc).__name__}: {exc}")
        finally:
            worker["submitting"] = False
            worker["current"] = None


def application_loop():
    while not stop_event.wait(2):
        if settings()["submission_enabled"]:
            job = next(
                (
                    j
                    for j in store.jobs()
                    if not j.get("uncertain")
                    and not _manual_handoff_active(j)
                    and j["status"] in ["queued", "prepared"]
                ),
                None,
            )
            if job:
                apply_job(job["id"])


def health_loop():
    awake = False
    while not stop_event.is_set():
        conf = settings()
        try:
            if os.name == "nt":
                # Request sleep prevention only on AC and only while enabled.
                class PowerStatus(ctypes.Structure):
                    _fields_ = [
                        ("ACLineStatus", ctypes.c_byte),
                        ("BatteryFlag", ctypes.c_byte),
                        ("BatteryLifePercent", ctypes.c_byte),
                        ("SystemStatusFlag", ctypes.c_byte),
                        ("BatteryLifeTime", ctypes.c_ulong),
                        ("BatteryFullLifeTime", ctypes.c_ulong),
                    ]

                power = PowerStatus()
                ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power))
                awake = conf["keep_awake"] and power.ACLineStatus == 1
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if awake else 0x80000000)
            with httpx.Client(timeout=3, trust_env=False) as client:
                tags = (
                    client.get(conf["ollama_url"].rstrip("/") + "/api/tags")
                    .raise_for_status()
                    .json()
                )
                names = {m.get("name") for m in tags.get("models", [])}
                worker["model_status"] = (
                    "qwen3.5:9b ready locally"
                    if conf["model"] in names
                    else "Local model download pending"
                )
        except Exception:
            worker["model_status"] = (
                "Local model service unavailable; verified template fallback active"
            )
        worker["keep_awake"] = awake
        worker["email_status"] = (
            "Configured" if conf.get("email", {}).get("enabled") else "Not configured"
        )
        stop_event.wait(20)
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


@asynccontextmanager
async def lifespan(app):
    store.recover()
    stop_event.clear()
    if os.environ.get("JOBPILOT_TESTING") != "1":
        store.event("JobPilot service started. Durable queue restored.")
        for name, target in [
            ("discovery", discovery_loop),
            ("applications", application_loop),
            ("health", health_loop),
        ]:
            threading.Thread(target=target, name=name, daemon=True).start()
        if settings()["remote_intervention_enabled"]:
            remote_runtime.start_async()
    yield
    stop_event.set()
    remote_runtime.stop()


app = FastAPI(title="JobPilot", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
)


@app.middleware("http")
async def local_security(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname not in ["127.0.0.1", "localhost", "::1", "testserver"]:
        return JSONResponse(
            {"detail": "Only the local dashboard may access this service."}, status_code=403
        )
    if request.method in ["POST", "PUT", "PATCH", "DELETE"] and not secrets.compare_digest(
        request.headers.get("X-JobPilot-Token", ""), TOKEN
    ):
        return JSONResponse({"detail": "Dashboard session token required."}, status_code=403)
    response = await call_next(request)
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {"ok": True, "version": "1.0.0", "pid": os.getpid(), "data_dir": str(DATA)}


@app.get("/api/session")
def session():
    return {"token": TOKEN}


@app.get("/api/state")
def state():
    return {
        "metrics": store.metrics(),
        "worker": dict(worker),
        "jobs": store.jobs(),
        "events": store.events(),
        "settings": {k: v for k, v in settings().items() if k != "data_dir"},
        "profile": store.get("profile"),
        "answers": store.get("answers", {}),
        "remote_access": remote_runtime.status(),
    }


@app.post("/api/remote/setup")
def remote_setup(body: dict | None = None):
    import base64

    link = remote_runtime.pairing_link()
    qr = ""
    if link:
        import qrcode

        image = qrcode.make(link)
        output = io.BytesIO()
        image.save(output, format="PNG")
        qr = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    return {
        "status": remote_runtime.status(),
        "pairing_link": link,
        "qr": qr,
        "cases": remote_runtime.broker.list_cases(),
    }


@app.post("/api/remote/control")
def remote_control(body: dict):
    action = body.get("action")
    if action not in ["enable", "disable", "revoke_devices"]:
        raise HTTPException(400, "Choose enable, disable or revoke_devices.")
    if action == "revoke_devices":
        if remote_runtime.auth:
            remote_runtime.auth.revoke_all()
        return {"ok": True}
    if action == "disable" and any(
        case["state"] == "waiting" for case in remote_runtime.broker.list_cases()
    ):
        raise HTTPException(
            409, "Complete or cancel the waiting browser session before disabling remote access."
        )
    conf = store.get("settings", {})
    conf["remote_intervention_enabled"] = action == "enable"
    store.set("settings", conf)
    if action == "enable":
        remote_runtime.start_async()
    else:
        remote_runtime.stop()
    store.event("Remote intervention " + ("enabled." if action == "enable" else "disabled."))
    return {"ok": True}


@app.post("/api/control")
def control(body: dict):
    conf = store.get("settings", {})
    if body.get("action") == "shutdown":
        from . import browser

        if browser.login_in_progress():
            raise HTTPException(
                409,
                "Close the JobPilot sign-in or verification browser before restarting the service.",
            )
        if (
            worker["searching"]
            or worker["submitting"]
            or worker["current"]
            or not application_lock.acquire(blocking=False)
        ):
            raise HTTPException(
                409, "Wait for the current application or search before restarting the service."
            )
        try:
            conf.update(search_enabled=False, submission_enabled=False)
            store.set("settings", conf)
            store.event("Service gracefully stopped for maintenance; queue retained.")
            if server_instance:

                def finish():
                    time.sleep(0.5)
                    server_instance.should_exit = True

                threading.Thread(target=finish, daemon=True).start()
            return {"ok": True}
        finally:
            application_lock.release()
    if body.get("action") == "stop":
        conf.update(search_enabled=False, submission_enabled=False)
    elif body.get("action") == "start":
        conf.update(search_enabled=True, submission_enabled=True)
    elif body.get("action") == "search":
        search_requested.set()
    for key in ["search_enabled", "submission_enabled"]:
        if key in body:
            conf[key] = bool(body[key])
    store.set("settings", conf)
    store.event(
        "Worker controls updated: searching "
        + ("enabled" if conf.get("search_enabled") else "paused")
        + ", submissions "
        + ("enabled" if conf.get("submission_enabled") else "paused")
        + "."
    )
    return {"ok": True}


@app.post("/api/settings")
def save_settings(body: dict):
    conf = settings()
    allowed = (set(DEFAULTS) - {"remote_intervention_enabled", "intervention_timeout_seconds"}) | {
        "excluded_companies"
    }
    update = {k: v for k, v in body.items() if k in allowed}
    for key, low, high in [
        ("search_interval_minutes", 5, 1440),
        ("min_fit", 0, 100),
        ("results_per_source", 1, 50),
        ("hours_old", 1, 720),
    ]:
        if key in update:
            try:
                update[key] = max(low, min(high, int(update[key])))
            except (ValueError, TypeError):
                raise HTTPException(400, f"{key} must be a number.")
    if "target_roles" in update and (
        not isinstance(update["target_roles"], list)
        or not update["target_roles"]
        or any(not isinstance(x, str) for x in update["target_roles"])
    ):
        raise HTTPException(400, "Target roles must be a nonempty list of role names.")
    if "ollama_url" in update and not local_endpoint(update["ollama_url"]):
        raise HTTPException(400, "Inference must use a local HTTP Ollama endpoint.")
    if "model" in update and update["model"] != "qwen3.5:9b":
        raise HTTPException(400, "Only the installed local qwen3.5:9b model is enabled.")
    for key in ["remote", "search_enabled", "submission_enabled", "keep_awake", "startup"]:
        if key in update and not isinstance(update[key], bool):
            raise HTTPException(400, f"{key} must be true or false.")
    old_startup = conf.get("startup")
    conf.update(update)
    conf.pop("data_dir", None)
    if conf.get("startup") != old_startup:
        desktop_exe = store.get("desktop_exe")
        if desktop_exe and Path(desktop_exe).is_file():
            result = subprocess.run(
                [desktop_exe, "--startup", "enable" if conf["startup"] else "disable"],
                capture_output=True,
                timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                raise HTTPException(
                    400, "Windows startup registration failed; settings were not saved."
                )
        elif conf["startup"]:
            raise HTTPException(
                400, "Launch the installed desktop executable before enabling logon startup."
            )
    store.set("settings", conf)
    store.event("Search and operation preferences saved.")
    return {"ok": True}


def setup_review_reason(job):
    """Recognize only the two setup gates that can safely be reconsidered."""
    if (
        job.get("uncertain")
        or _manual_handoff_active(job)
        or job.get("status") not in ["needs_review", "review_required"]
    ):
        return None
    application = job.get("application") or {}
    reasons = [
        job.get("review_reason"),
        job.get("blocker_reason"),
        job.get("blocker_category"),
        application.get("review_reason"),
        application.get("blocker_reason"),
        application.get("blocker_category"),
    ]
    if "uncertain_submission" in reasons:
        return None
    reason = next((value for value in reasons if value), None)
    if reason:
        return {
            "unanswered_fields": "unanswered_fields",
            "unanswered": "unanswered_fields",
            "auth_required": "auth_required",
            "authentication": "auth_required",
        }.get(reason)
    note = str(job.get("note") or application.get("note") or "").strip().casefold()
    if "uncertain submission" in note or "submission outcome uncertain" in note:
        return None
    if note.startswith(
        (
            "fields need saved answers or review:",
            "unknown required screening answer",
            "unanswered required",
        )
    ):
        return "unanswered_fields"
    if note.startswith("login, captcha or verification requires your review") or re.match(
        r"^(?:sign[ -]?in|log[ -]?in).*\brequired\b", note
    ):
        return "auth_required"
    return None


def login_site(platform, url=None):
    host = (urlsplit(str(url or "")).hostname or "").casefold()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin", "linkedin.com"
    if host == "indeed.com" or host.endswith(".indeed.com"):
        return "indeed", "indeed.com"
    if host:
        return "employer", host
    platform = str(platform).casefold()
    return platform, f"{platform}.com" if platform in ["linkedin", "indeed"] else None


def retry_setup_reviews(reason, platform=None, url=None):
    """Requeue held forms atomically without changing active or receipt states."""
    target = login_site(platform, url) if reason == "auth_required" else None
    count = 0
    with store.lock:
        for job in store.jobs():
            if setup_review_reason(job) != reason:
                continue
            if target:
                application = job.get("application") or {}
                auth_platform = job.get("auth_platform") or application.get("auth_platform")
                auth_url = job.get("auth_url") or application.get("auth_url")
                if auth_platform and str(auth_platform).casefold() != target[0]:
                    continue
                actual = login_site(
                    auth_platform or job.get("source", "employer"),
                    auth_url or job.get("apply_url") or job.get("url"),
                )
                if actual != target or (target[0] == "employer" and not target[1]):
                    continue
            store.update_job(
                job["id"],
                status="prepared" if job.get("documents") else "queued",
                note=(
                    "Saved screening answers changed"
                    if reason == "unanswered_fields"
                    else "Sign-in verified"
                )
                + "; safely requeued for application form checks.",
            )
            count += 1
    return count


@app.post("/api/answers")
def save_answers(body: dict):
    answers = body.get("answers", {})
    if not isinstance(answers, dict) or any(
        not isinstance(k, str) or not isinstance(v, (str, bool, int, float))
        for k, v in answers.items()
    ):
        raise HTTPException(400, "Answers must map exact question text to a saved answer.")
    with store.lock:
        changed = store.get("answers", {}) != answers
        if changed:
            store.set("answers", answers)
            requeued = retry_setup_reviews("unanswered_fields")
        else:
            requeued = 0
    message = (
        f"Screening answers saved. {requeued} held opportunities requeued for form checks."
        if changed
        else "Saved screening answers are unchanged; no applications requeued."
    )
    if changed:
        store.event(message)
    return {"ok": True, "changed": changed, "requeued": requeued, "message": message}


@app.post("/api/profile")
def save_profile(body: dict):
    if not all(
        isinstance(body.get(k), str) and body[k].strip() for k in ["name", "email", "phone"]
    ):
        raise HTTPException(400, "Name, email and phone are required.")
    try:
        if not facts_map(body):
            raise ValueError()
        for e in body["experience"]:
            if not e.get("company") or not e.get("title"):
                raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(
            400, "Profile needs employers, titles and career facts with unique IDs and text."
        )
    store.set("profile", body)
    store.event("Candidate profile updated.")
    return {"ok": True}


@app.post("/api/import")
def import_job(body: dict):
    from . import collectors

    if body.get("eml"):
        if len(body["eml"]) > 2000000:
            raise HTTPException(400, "Email import is too large.")
        jobs = collectors.import_eml(body["eml"])
    else:
        if not body.get("url"):
            raise HTTPException(400, "A job URL or email message is required.")
        try:
            if body.get("title") and body.get("company"):
                # Collector validation prevents dangerous URLs before worker navigation.
                validate = getattr(collectors, "validate_public_url", None)
                if validate:
                    for route_key in ["url", "apply_url", "source_url"]:
                        if body.get(route_key):
                            validate(body[route_key])
                jobs = [dict(body)]
            else:
                jobs = [collectors.fetch_job(body["url"])]
        except Exception as exc:
            raise HTTPException(400, f"Job import failed: {exc}")
    result = []
    ignored = 0
    for job in jobs:
        job = classify_job(job, store.get("profile"), settings())
        saved = store.add_job(job)
        if saved is None:
            ignored += 1
        else:
            result.append(saved)
    store.event(f"Imported {len(result)} job records.")
    return {"ok": True, "jobs": result, "ignored": ignored}


def require_job(job_id):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job


def guard_job_mutation(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        if not application_lock.acquire(blocking=False):
            raise HTTPException(
                409, "Wait for the active application before changing its queue or receipt state."
            )
        try:
            return function(*args, **kwargs)
        finally:
            application_lock.release()

    return guarded


def _cleanup_now():
    return datetime.now(timezone.utc)


def _cleanup_clock():
    return time.monotonic()


def _cleanup_busy():
    from . import browser

    if worker["submitting"] or worker["current"] or browser.login_in_progress():
        return True
    if not application_lock.acquire(blocking=False):
        return True
    application_lock.release()
    return False


@app.get("/api/jobs/cleanup/preview")
def preview_old_jobs():
    cutoff = _cleanup_now() - timedelta(days=7)
    preview = store.cleanup_preview(cutoff)
    token = secrets.token_urlsafe(32)
    now = _cleanup_clock()
    with cleanup_preview_lock:
        for key in list(cleanup_previews):
            if cleanup_previews[key]["deadline"] <= now:
                del cleanup_previews[key]
        while len(cleanup_previews) >= 32:
            del cleanup_previews[next(iter(cleanup_previews))]
        cleanup_previews[token] = {
            "ids": [job["id"] for job in preview["jobs"]],
            "cutoff": cutoff,
            "deadline": now + 300,
        }
    fields = ["id", "title", "company", "posted_at", "status"]
    return {
        "jobs": [{key: job.get(key) for key in fields} for job in preview["jobs"]],
        "count": len(preview["jobs"]),
        "protected_count": preview["protected_count"],
        "unknown_date_count": preview["unknown_date_count"],
        "cutoff": cutoff.isoformat(),
        "token": token,
        "expires_at": (_cleanup_now() + timedelta(minutes=5)).isoformat(),
        "busy": _cleanup_busy(),
    }


@app.post("/api/jobs/cleanup")
@guard_job_mutation
def delete_old_jobs(body: dict):
    if body.get("confirm") is not True:
        raise HTTPException(400, "Confirm permanent deletion in the cleanup preview first.")
    if _cleanup_busy():
        raise HTTPException(
            409, "Finish the active application or verification browser before removing jobs."
        )
    token = body.get("token")
    if not isinstance(token, str) or len(token) > 200:
        raise HTTPException(409, "Reopen the cleanup preview before deleting jobs.")
    with cleanup_preview_lock:
        preview = cleanup_previews.get(token)
        if not preview or preview["deadline"] <= _cleanup_clock():
            cleanup_previews.pop(token, None)
            raise HTTPException(
                409, "The cleanup preview expired. Reopen it to check the current jobs."
            )
        result = store.delete_old_jobs(preview["cutoff"], preview["ids"])
        del cleanup_previews[token]
    store.event(
        f"Permanently removed {result['deleted_count']} jobs posted at least seven days ago; {result['skipped_count']} changed or protected records retained."
    )
    return {"ok": True, **result}


def _normal_browser_tab(url):
    from . import browser

    result = browser.open_browser_tab(url)
    if result.get("status") != "opened":
        raise HTTPException(400, result.get("note") or "Could not open the default browser.")
    return result


def _manual_handoff_active(job):
    handoff = job.get("browser_handoff") or {}
    return handoff.get("mode") == "default_browser" and handoff.get("state") != "closed"


def _job_browser_url(job, purpose):
    application = job.get("application") or {}
    reason = job.get("review_reason") or application.get("review_reason")
    auth_url = (
        (job.get("auth_url") or application.get("auth_url"))
        if reason in ["auth_required", "verification_required"]
        else None
    )

    def linkedin(url):
        host = (urlsplit(str(url or "")).hostname or "").lower()
        return host == "linkedin.com" or host.endswith(".linkedin.com")

    # Authentication redirects captured by the isolated worker are not the
    # destination for a browser that is already signed in to LinkedIn.
    if auth_url and linkedin(auth_url):
        auth_url = None
    candidates = (
        [job.get("url"), job.get("source_url")]
        if purpose == "posting"
        else [auth_url, job.get("apply_url"), job.get("url"), job.get("source_url")]
    )
    for url in candidates:
        if not url:
            continue
        if linkedin(url):
            found = re.fullmatch(r"/jobs/view/(?:[^/]+-)?(\d+)(?:/.*)?", urlsplit(url).path)
            if not found:
                continue
            return f"https://www.linkedin.com/jobs/view/{found[1]}/"
        return url
    raise HTTPException(
        409,
        "This opportunity has no specific job link. Import its original employer or LinkedIn job URL.",
    )


@app.post("/api/browser-tab")
def browser_tab(body: dict):
    defaults = {
        "linkedin": "https://www.linkedin.com/jobs/",
        "indeed": "https://secure.indeed.com/account/login",
    }
    platform = body.get("platform", "employer")
    if platform not in ["linkedin", "indeed", "employer"]:
        raise HTTPException(400, "Choose LinkedIn, Indeed or employer.")
    url = body.get("url") or defaults.get(platform)
    if not url:
        raise HTTPException(400, "Provide the employer application or sign-in URL.")
    return _normal_browser_tab(url)


@app.post("/api/jobs/{job_id}/browser-tab")
@guard_job_mutation
def job_browser_tab(job_id: int, body: dict):
    job = require_job(job_id)
    purpose = body.get("purpose", "application")
    if purpose not in ["application", "posting"]:
        raise HTTPException(400, "Choose application or posting.")
    if purpose == "application" and job["status"] in ["preparing", "applying", "submitting"]:
        raise HTTPException(
            409, "Wait for the active application before opening a manual application tab."
        )
    url = _job_browser_url(job, purpose)
    result = _normal_browser_tab(url)
    # Never change an uncertain attempt or call the automation's login/review
    # callbacks. A regular browser tab has no trusted receipt observer.
    if (
        purpose == "application"
        and not job.get("uncertain")
        and job["status"] not in ["confirmed", "manually_verified", "skipped"]
    ):
        changes = {
            "status": "needs_review",
            "browser_handoff": {
                "mode": "default_browser",
                "state": "opened",
                "receipt_tracking": "manual",
                "opened_at": store.now(),
                "url": result.get("url", url),
            },
        }
        if job["status"] in ["queued", "prepared", "error"]:
            changes.update(
                status="needs_review",
                review_reason="manual_application",
                note="Application opened in your regular browser. Finish it there and record the verified outcome here; automation is held for this opportunity.",
            )
        store.update_job(job_id, **changes)
    return result


@app.post("/api/jobs/{job_id}/prepare")
@guard_job_mutation
def prepare_action(job_id: int):
    job = require_job(job_id)
    if (
        job.get("uncertain")
        or _manual_handoff_active(job)
        or job["status"]
        in ["confirmed", "manually_verified", "applying", "submitting", "preparing", "skipped"]
    ):
        raise HTTPException(409, "This application is already complete, skipped, or busy.")
    store.update_job(
        job_id,
        status="preparing",
        preparation_prior_status=job["status"],
        preparation_prior_note=job.get("note", ""),
    )
    threading.Thread(
        target=prepare_job, args=(job_id, job["status"] == "needs_review"), daemon=True
    ).start()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
@guard_job_mutation
def retry_action(job_id: int):
    job = require_job(job_id)
    if (
        job.get("uncertain")
        or _manual_handoff_active(job)
        or job["status"]
        in ["confirmed", "manually_verified", "applying", "submitting", "preparing"]
    ):
        raise HTTPException(
            409, "Verify the uncertain receipt before retrying, or wait for the active application."
        )
    store.update_job(
        job_id,
        status="prepared" if job.get("documents") else "queued",
        note="Requeued after review.",
    )
    return {"ok": True}


def _review_artifacts(paths, folders):
    if not isinstance(paths, list) or not paths:
        return False
    for value in paths:
        try:
            path = Path(value).resolve()
            if not path.is_file() or not any(
                path.is_relative_to((DATA / folder).resolve()) for folder in folders
            ):
                return False
        except (TypeError, ValueError, OSError):
            return False
    return True


@app.post("/api/jobs/{job_id}/review")
@guard_job_mutation
def review_action(job_id: int, body: dict | None = None):
    mode = (body or {}).get("mode", "default_browser")
    if mode == "default_browser":
        return job_browser_tab(job_id, {"purpose": "application"})
    if mode not in ["isolated", "remote"]:
        raise HTTPException(400, "Choose default_browser, isolated or remote.")
    if mode == "remote" and not (
        settings()["remote_intervention_enabled"] and remote_runtime.status()["listening"]
    ):
        raise HTTPException(
            409, "Enable remote access before opening a remote verification session."
        )
    from . import browser

    job = require_job(job_id)
    application = job.get("application") or {}
    reason = job.get("review_reason") or application.get("review_reason")
    legacy = not reason and re.match(
        r"^(?:CAPTCHA challenge|Email verification) requires your review after submit was attempted\b",
        str(job.get("note", "")),
        re.I,
    )
    documents = job.get("documents", application.get("documents")) or {}
    prior_evidence = application.get("evidence", [])
    if (
        job["status"] != "needs_review"
        or not job.get("uncertain")
        or not job.get("submission_checkpoint_at")
        or not (reason == "verification_required" or legacy)
        or not _review_artifacts(prior_evidence, ["evidence", "receipts"])
        or not _review_artifacts([documents.get("resume_pdf")], ["applications"])
    ):
        raise HTTPException(
            409,
            "Only a recorded post-submit verification hold can open this browser. Review the existing receipt evidence first.",
        )
    if browser.login_in_progress() or job.get("review_session", {}).get("state") in [
        "opening",
        "opened",
    ]:
        raise HTTPException(409, "A JobPilot sign-in or verification browser is already open.")
    nonce = secrets.token_urlsafe(18)
    checkpoint = job["submission_checkpoint_at"]
    session = {"nonce": nonce, "state": "opening", "opened_at": store.now()}
    store.update_job(job_id, review_session=session)

    def on_closed(outcome):
        with store.lock:
            current = store.get_job(job_id)
            active = current.get("review_session") or {}
            if (
                current["status"] != "needs_review"
                or not current.get("uncertain")
                or current.get("submission_checkpoint_at") != checkpoint
                or active.get("nonce") != nonce
                or active.get("state") not in ["opening", "opened"]
            ):
                return
            outcome = outcome if isinstance(outcome, dict) else {}
            receipts = outcome.get("evidence", [])
            old_evidence = current.get("application", {}).get("evidence", [])
            fresh = isinstance(receipts, list) and any(
                path not in old_evidence for path in receipts
            )
            confirmed = (
                outcome.get("status") == "confirmed"
                and outcome.get("submitted") is False
                and isinstance(outcome.get("receipt"), str)
                and bool(browser._RECEIPT.search(outcome["receipt"]))
                and fresh
                and _review_artifacts(receipts, ["evidence", "receipts"])
            )
            combined = (
                list(dict.fromkeys(old_evidence + receipts))
                if _review_artifacts(receipts, ["evidence", "receipts"])
                else old_evidence
            )
            note = (
                (
                    "Employer receipt verified after user-assisted verification: "
                    + outcome["receipt"]
                )
                if confirmed
                else "Verification browser closed without a new receipt; original uncertain attempt retained. "
                + str(outcome.get("note", ""))[:300]
            )
            changes = {
                "review_session": {**active, "state": "closed", "closed_at": store.now()},
                "note": note,
                "application": {
                    **current.get("application", {}),
                    "note": note,
                    "evidence": combined,
                },
            }
            if confirmed:
                changes.update(
                    status="confirmed",
                    uncertain=False,
                    confirmed_at=store.now(),
                    verification_method="user_assisted_receipt",
                )
                changes["application"]["status"] = "confirmed"
            store.update_job(job_id, **changes)
            store.event(
                f"{'Confirmed' if confirmed else 'Review retained'}: {job.get('title', '')} at {job.get('company', '')}. {note}"
            )

    original_answers = application.get("answers_supplied")
    original_profile = application.get("profile_snapshot") or store.get("profile")
    try:
        remote_options = (
            {"intervention_handler": remote_runtime.broker.pause} if mode == "remote" else {}
        )
        result = browser.open_review(
            job,
            original_profile,
            original_answers if isinstance(original_answers, dict) else store.get("answers", {}),
            documents,
            settings(),
            on_closed,
            **remote_options,
        )
    except Exception as exc:
        result = {
            "status": "error",
            "note": f"Could not open verification browser: {type(exc).__name__}: {str(exc)[:200]}",
        }
    with store.lock:
        current = store.get_job(job_id)
        active = current.get("review_session") or {}
        if active.get("nonce") == nonce and active.get("state") == "opening":
            store.update_job(
                job_id,
                review_session={
                    **active,
                    "state": "opened" if result.get("status") == "opened" else "closed",
                },
            )
    return result


@app.post("/api/jobs/{job_id}/skip")
@guard_job_mutation
def skip_action(job_id: int):
    job = require_job(job_id)
    if job["status"] in ["confirmed", "manually_verified", "applying", "submitting", "preparing"]:
        raise HTTPException(409, "Active or confirmed applications cannot be skipped.")
    store.update_job(job_id, status="skipped", note="Skipped in dashboard.")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/resolve")
@guard_job_mutation
def resolve_action(job_id: int, body: dict):
    job = require_job(job_id)
    manual_handoff = _manual_handoff_active(job)
    if job["status"] != "needs_review" or not (job.get("uncertain") or manual_handoff):
        raise HTTPException(
            409,
            "Only uncertain submissions or recorded manual application handoffs need receipt resolution.",
        )
    evidence = str(body.get("evidence", "")).strip()
    if not evidence:
        raise HTTPException(
            400, "Record the receipt or the reason you verified no submission occurred."
        )
    outcome = body.get("outcome")
    if outcome not in ["confirmed", "not_submitted"]:
        raise HTTPException(400, "Choose confirmed or not_submitted.")
    path = DATA / "receipts" / f"job-{job_id}-{int(time.time())}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(evidence, encoding="utf-8")
    application = job.get("application", {})
    application["evidence"] = application.get("evidence", []) + [str(path)]
    updates = {
        "uncertain": False,
        "status": "manually_verified" if outcome == "confirmed" else "needs_review",
        "note": "Receipt manually verified: " + evidence[:250],
        "application": application,
        "verification_method": "manual",
    }
    if manual_handoff:
        updates["browser_handoff"] = {
            **job["browser_handoff"],
            "state": "closed",
            "outcome": outcome,
            "resolved_at": store.now(),
        }
    if outcome == "confirmed":
        updates["confirmed_at"] = store.now()
    store.update_job(job_id, **updates)
    return {"ok": True}


@app.post("/api/login")
def login(body: dict):
    mode = body.get("mode", "default_browser")
    if mode == "default_browser":
        return browser_tab(body)
    if mode != "isolated":
        raise HTTPException(400, "Choose default_browser or isolated.")
    from . import browser

    platform = body.get("platform", "employer")
    if platform not in ["linkedin", "indeed", "employer"]:
        raise HTTPException(400, "Choose LinkedIn, Indeed or employer.")
    expected_site = login_site(platform, body.get("url"))
    closed = threading.Event()
    callback_lock = threading.Lock()

    def on_closed(outcome):
        with callback_lock:
            if closed.is_set():
                return
            closed.set()
        if not isinstance(outcome, dict) or outcome.get("verified") is not True:
            store.event(
                "Sign-in browser closed without a verified authenticated session; held applications retained."
            )
            return
        actual_site = login_site(outcome.get("platform"), outcome.get("url"))
        if actual_site != expected_site:
            store.event(
                "Sign-in verification did not match the requested site; held applications retained."
            )
            return
        requeued = retry_setup_reviews("auth_required", actual_site[0], outcome.get("url"))
        store.event(
            f"Sign-in verified for {actual_site[0]}; {requeued} authentication-held opportunities requeued for form checks."
        )

    try:
        return browser.open_login(
            platform, body.get("url"), settings=settings(), on_closed=on_closed
        )
    except Exception as exc:
        raise HTTPException(400, f"Could not open dedicated login browser: {exc}")


@app.post("/api/email")
def email_config(body: dict):
    from . import collectors

    try:
        config = dict(body)
        config["username"] = body.get("username") or body.get("user") or body.get("email")
        config["mailbox"] = body.get("mailbox") or body.get("folder") or "INBOX"
        safe = collectors.configure_email(config)
    except Exception as exc:
        raise HTTPException(400, f"Email configuration failed: {type(exc).__name__}: {exc}")
    conf = store.get("settings", {})
    conf["email"] = safe
    store.set("settings", conf)
    return {"ok": True}


@app.get("/api/artifact")
def artifact(path: str):
    target = Path(path).resolve()
    allowed = [DATA / "applications", DATA / "receipts", DATA / "evidence"]
    if not any(target.is_relative_to(x.resolve()) for x in allowed):
        raise HTTPException(403, "Only application artifacts may be downloaded.")
    if not target.is_file():
        raise HTTPException(404, "Artifact not found.")
    return FileResponse(target, filename=target.name)


@app.get("/api/report")
def report():
    buffer = io.StringIO(newline="")
    fields = [
        "id",
        "title",
        "company",
        "source",
        "location",
        "posted_at",
        "fit",
        "status",
        "attempts",
        "confirmed_at",
        "url",
        "note",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for job in store.jobs():
        # CSV formulas cannot execute when the export is opened in Excel.
        writer.writerow(
            {
                k: "'" + str(job.get(k, ""))
                if str(job.get(k, "")).startswith(("=", "+", "-", "@"))
                else job.get(k, "")
                for k in fields
            }
        )
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=JobPilot-report.csv"},
    )


dashboard_assets = asset_directory("web")
if dashboard_assets.is_dir():
    app.mount("/", StaticFiles(directory=dashboard_assets, html=True), name="dashboard")


def main():
    global server_instance
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server_instance = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    )
    server_instance.run()


if __name__ == "__main__":
    main()
