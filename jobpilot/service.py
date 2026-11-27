"""Authenticated loopback API and independently scheduled persistent workers."""

import argparse
import csv
import ctypes
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache, wraps
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, resumeforge_bridge
from .assets import asset_directory
from .autofill import ExtensionAPI
from .core import canonical_url, eligibility, facts_map, role_assessment, score_job
from .local_profile import adopt_local_profile
from .platforms import SystemSleepInhibitor, application_data_dir
from .store import Store

ROOT = Path(__file__).resolve().parents[1]
DATA = application_data_dir()
DATA.mkdir(parents=True, exist_ok=True)
store = Store(DATA / "jobpilot.sqlite")
seed = json.loads((ROOT / "jobpilot/candidate.json").read_text(encoding="utf-8"))
DEFAULTS = {
    "target_roles": [
        "Security Engineer",
        "Cloud Security Engineer",
        "Information Security Analyst",
        "GRC Analyst",
        "GRC Engineer",
        "Security Analyst",
        "SOC Analyst",
        "Security Advisor",
        "DevOps Engineer",
        "Cloud Engineer",
        "Platform Engineer",
        "Forward Deployed Engineer",
    ],
    "location": "Cincinnati, OH",
    "remote": True,
    "search_interval_minutes": 30,
    "min_fit": 40,
    "search_enabled": False,
    "submission_enabled": False,
    "application_mode": "assist",
    "keep_awake": False,
    "startup": False,
    "remote_intervention_enabled": False,
    "intervention_timeout_seconds": 28800,
    "sources": ["indeed"],
    "results_per_source": 50,
    "hours_old": 72,
    "greenhouse_discovery": True,
    "ats_boards": [
        {"source": "greenhouse", "board": "cloudflare"},
        {"source": "greenhouse", "board": "datadog"},
        {"source": "greenhouse", "board": "cobaltio"},
        {"source": "greenhouse", "board": "guidepointsecurity"},
        {"source": "greenhouse", "board": "calahealth"},
    ],
}
for key, default in [("settings", DEFAULTS), ("profile", seed), ("answers", {})]:
    if store.get(key) is None:
        store.set(key, default)
stored_preferences = store.get("settings", {})
if (
    os.environ.get("JOBPILOT_COMBINED") == "1"
    or stored_preferences.get("application_mode") != "legacy"
):
    stored_preferences.update(
        application_mode="assist", submission_enabled=False, remote_intervention_enabled=False
    )
    store.set("settings", stored_preferences)
if os.environ.get("JOBPILOT_DESKTOP_EXE"):
    store.set("desktop_exe", os.environ["JOBPILOT_DESKTOP_EXE"])
TOKEN = store.get("_session_token") or secrets.token_urlsafe(32)
store.set("_session_token", TOKEN)
stop_event = threading.Event()
sleep_inhibitor = SystemSleepInhibitor()


class _CombinedRemoteBroker:
    def list_cases(self):
        return []

    def pause(self, *_args, **_kwargs):
        raise RuntimeError("Remote application control is unavailable in the combined app.")


class _CombinedRemoteRuntime:
    """Small disabled facade for builds that never ship browser automation."""

    auth = None

    def __init__(self):
        self.broker = _CombinedRemoteBroker()

    def status(self):
        return {
            "starting": False,
            "listening": False,
            "error": "",
            "gateway": {"running": False, "url": "", "error": ""},
            "waiting": 0,
            "notifications": {"subscribed_devices": 0},
        }

    def start_async(self):
        return None

    def stop(self):
        return None

    def pairing_link(self):
        return ""


if os.environ.get("JOBPILOT_COMBINED") == "1":
    remote_runtime = _CombinedRemoteRuntime()
else:
    # Kept for source-only legacy regression coverage. Native combined builds
    # exclude this optional browser-control stack entirely.
    from .remote_runtime import RemoteRuntime

    remote_runtime = RemoteRuntime(DATA, stop_event, vapid_subject="mailto:" + seed["email"])
search_requested = threading.Event()
discovery_lock = threading.Lock()
application_lock = threading.RLock()
cleanup_previews = {}
cleanup_preview_lock = threading.RLock()
email_sync_lock = threading.RLock()
email_task_running = threading.Event()
server_instance = None
worker = {
    "searching": False,
    "submitting": False,
    "heartbeat": None,
    "current": None,
    "last_search": store.get("last_search"),
    "last_error": None,
    "email_status": "Not configured",
}

AUTO_RESUME_MIN_FIT = 80.0
AUTO_RESUME_MAX_RETRIES = 3
AUTO_RESUME_RETRY_BASE_SECONDS = 30


def _resume_attempt_count(value) -> int:
    """Normalize persisted retry state so a damaged row cannot stop the queue."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def settings():
    conf = {**DEFAULTS, **store.get("settings", {}), "data_dir": str(DATA)}
    try:
        conf["min_fit"] = max(0, min(int(AUTO_RESUME_MIN_FIT), int(conf["min_fit"])))
    except (KeyError, TypeError, ValueError):
        conf["min_fit"] = DEFAULTS["min_fit"]
    if os.environ.get("JOBPILOT_COMBINED") == "1" or conf.get("application_mode") != "legacy":
        conf.update(
            application_mode="assist", submission_enabled=False, remote_intervention_enabled=False
        )
    return conf


def report_error(message, *, category="worker", job=None, detail=None, url=None):
    technical = str(message if detail is None else detail)
    friendly = (
        str(message)
        if detail is not None
        else {
            "search": "The job search could not finish. Try again later.",
            "documents": "Documents could not be prepared for this job. Check the profile and try again.",
            "fetch": "The job listing could not be read. Open the posting and try importing it again.",
        }.get(category, "JobPilot could not finish this operation. Try again.")
    )
    logs = DATA / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "problems.log").open("a", encoding="utf-8") as output:
        output.write(
            json.dumps(
                {
                    "at": store.now(),
                    "category": category,
                    "job_id": (job or {}).get("id"),
                    "detail": technical,
                }
            )
            + "\n"
        )
    worker["last_error"] = friendly
    store.event(friendly, "error")
    return store.add_problem(friendly, category=category, job=job, url=url)


@lru_cache(maxsize=2048)
def _cached_job_keywords(title, description, profile_json):
    from .keywords import extract_keywords

    return json.dumps(
        extract_keywords({"title": title, "description": description}, json.loads(profile_json))
    )


def job_keywords(job, profile_json=None):
    if profile_json is None:
        profile_json = json.dumps(store.get("profile"), sort_keys=True, ensure_ascii=False)
    # Cache immutable text so a caller cannot mutate a later response.
    return json.loads(
        _cached_job_keywords(
            str(job.get("title") or ""), str(job.get("description") or ""), profile_json
        )
    )


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
        "alert_subject",
        "alert_received_at",
        "alert_from",
        "alert_metadata_version",
        "alert_title_source",
        "posting_source",
        "alert_research",
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


def _search_clock():
    return datetime.now(timezone.utc)


def search_monitor():
    conf = settings()
    last = store.get("last_search")
    next_check = None
    if not worker["searching"]:
        if search_requested.is_set():
            next_check = _search_clock()
        elif conf["search_enabled"]:
            try:
                previous = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=timezone.utc)
                next_check = previous + timedelta(minutes=conf["search_interval_minutes"])
            except (AttributeError, TypeError, ValueError):
                next_check = _search_clock()
    return {
        "enabled": conf["search_enabled"],
        "interval_minutes": conf["search_interval_minutes"],
        "last_search_at": last,
        "next_search_at": next_check.isoformat() if next_check else None,
        "last_result": store.get("last_search_result"),
    }


def search_due():
    next_check = search_monitor()["next_search_at"]
    return bool(next_check and datetime.fromisoformat(next_check) <= _search_clock())


def discover_once():
    from . import collectors

    if not discovery_lock.acquire(blocking=False):
        return
    worker["searching"] = True
    conf = settings()
    conf["search_titles"] = conf["target_roles"]
    conf["locations"] = [conf["location"]]
    conf["_greenhouse_cursor"] = store.get("greenhouse_cursor", 0)
    conf["_greenhouse_learned_boards"] = store.get("greenhouse_learned_boards", [])
    conf["_search_title_cursor"] = store.get("search_title_cursor", 0)
    profile = store.get("profile")
    count_keys = ["checked", "imported", "existing", "filtered", "removed"]
    source_rows = {}
    result = {"status": "ok"}

    def source_row(source):
        return source_rows.setdefault(
            str(source or "other").lower(),
            {
                "source": str(source or "other").lower(),
                "status": "ok",
                "message": "",
                **dict.fromkeys(count_keys, 0),
            },
        )

    try:
        existing_jobs = store.jobs()
        fit_signature = sha256(
            json.dumps(
                {
                    "version": 2,
                    "roles": conf["target_roles"],
                    "skills": profile.get("skills", []),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if store.get("fit_scoring_signature") != fit_signature:
            for existing in existing_jobs:
                if (
                    existing.get("status") in ("queued", "needs_review", "review_required")
                    and len(str(existing.get("description", ""))) >= 80
                ):
                    updated_fit = score_job(existing, profile, conf)
                    if updated_fit != existing.get("fit"):
                        store.update_job(existing["id"], fit=updated_fit)
            store.set("fit_scoring_signature", fit_signature)
            existing_jobs = store.jobs()
        known_greenhouse = set(conf["_greenhouse_learned_boards"])
        for existing in existing_jobs:
            for route in ("url", "source_url", "apply_url"):
                slug = collectors._greenhouse_slug(existing.get(route))
                if slug:
                    known_greenhouse.add(slug)
        conf["_greenhouse_learned_boards"] = sorted(known_greenhouse)
        if len(known_greenhouse) > len(store.get("greenhouse_learned_boards", [])):
            store.set("greenhouse_learned_boards", conf["_greenhouse_learned_boards"])
        existing_ids = {job["id"] for job in existing_jobs}
        email_routes = {
            canonical_url(existing[key])
            for existing in existing_jobs
            if existing.get("source") == "email"
            for key in ["url", "source_url", "apply_url"]
            if existing.get(key)
        }
        before = len(existing_ids)
        jobs = collectors.discover(conf, profile)
        for job in jobs:
            row = source_row(job.get("source"))
            row["checked"] += 1
            if not job.get("url") or not job.get("title"):
                row["filtered"] += 1
                continue
            job = classify_job(job, profile, conf)
            if job.get("status") == "skipped":
                row["filtered"] += 1
                if job.get("source") == "email" and canonical_url(job["url"]) in email_routes:
                    store.add_job(job)
                continue
            saved = store.add_job(job)
            if saved is None:
                row["removed"] += 1
            elif saved["id"] not in existing_ids:
                row["imported"] += 1
                existing_ids.add(saved["id"])
            else:
                row["existing"] += 1
        details = getattr(collectors, "get_last_search_result", lambda: {})()
        if details.get("greenhouse_next_cursor") is not None:
            store.set("greenhouse_cursor", details["greenhouse_next_cursor"])
        if details.get("search_title_next_cursor") is not None:
            store.set("search_title_cursor", details["search_title_next_cursor"])
        learned = details.get("greenhouse_learned_boards") or []
        if learned:
            store.set(
                "greenhouse_learned_boards",
                sorted(set(conf["_greenhouse_learned_boards"]) | set(learned)),
            )
        for detail in details.get("sources", []):
            row = source_row(detail.get("source"))
            row.update({key: value for key, value in detail.items() if key not in count_keys})
        errors = getattr(collectors, "get_last_errors", lambda: [])()
        for error in errors:
            if not isinstance(error, dict):
                continue
            row = source_row(error.get("source"))
            if row["status"] == "ok":
                row["status"] = (
                    "partial" if "Description unavailable" in error.get("note", "") else "error"
                )
        for row in source_rows.values():
            source_name = {
                "linkedin": "LinkedIn",
                "indeed": "Indeed",
                "email": "Gmail",
                "gmail": "Gmail",
            }.get(row["source"], row["source"].capitalize())
            if row["status"] in ["blocked", "error"]:
                message = (
                    f"{source_name} is temporarily limiting searches. Other sources will continue."
                    if row["status"] == "blocked"
                    else f"{source_name} search is temporarily unavailable. Other sources will continue."
                )
                report_error(
                    message,
                    category="search",
                    detail=row,
                    url=row.get("url")
                    or {
                        "linkedin": "https://www.linkedin.com/jobs/",
                        "indeed": "https://www.indeed.com/jobs",
                    }.get(row["source"]),
                )
            elif row["checked"]:
                old_message = f"{source_name} could not finish its search. Try again later."
                for problem in store.problems():
                    if (
                        not problem.get("resolved")
                        and problem.get("category") == "search"
                        and problem["message"] == old_message
                    ):
                        store.resolve_problem(problem["id"])
        store.event(
            f"Search finished: {len(store.jobs()) - before} new matching opportunities; {len(jobs)} source records checked."
        )
        if any(row["status"] != "ok" for row in source_rows.values()):
            result["status"] = "partial" if jobs else "error"
    except Exception as exc:
        result["status"] = "error"
        report_error(
            "The job search could not finish. Try again later.",
            category="search",
            detail=f"{type(exc).__name__}: {exc}",
        )
    finally:
        finished = _search_clock().isoformat()
        worker["last_search"] = finished
        store.set("last_search", finished)
        result.update(
            finished_at=finished,
            sources=list(source_rows.values()),
            **{key: sum(row[key] for row in source_rows.values()) for key in count_keys},
        )
        store.set("last_search_result", result)
        worker["searching"] = False
        discovery_lock.release()


def discovery_loop():
    while not stop_event.wait(1):
        worker["heartbeat"] = store.now()
        if search_due():
            search_requested.clear()
            discover_once()


def _failed_resume_result(job: dict, workspace: str, result: dict | None = None) -> dict:
    """Add bounded retry state to an engine or exception failure."""
    previous = job.get("resumeforge") if isinstance(job.get("resumeforge"), dict) else {}
    attempts = (
        _resume_attempt_count(previous.get("attempts")) + 1
        if previous.get("workspace") == workspace
        else 1
    )
    retry_after = None
    if attempts < AUTO_RESUME_MAX_RETRIES:
        delay = AUTO_RESUME_RETRY_BASE_SECONDS * (2 ** (attempts - 1))
        retry_after = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    return {
        **(result or {}),
        "status": "failed",
        "workspace": workspace,
        "attempts": attempts,
        "retry_after": retry_after,
    }


def prepare_job(job_id, preserve_review=False):
    with application_lock:
        if stop_event.is_set():
            return
        job = store.get_job(job_id)
        if (
            not job
            or (job.get("applied") and not job.get("preparation_requested"))
            or (job.get("uncertain") and settings()["application_mode"] != "assist")
            or _manual_handoff_active(job)
            or (job.get("review_session") or {}).get("state") in ("opening", "opened")
            or job["status"] in ("skipped", "confirmed", "manually_verified", "preparing")
            or job["status"] in ("applying", "submitting")
        ):
            return
        prior_status = job.get("preparation_prior_status") or job["status"]
        prior_note = job.get("preparation_prior_note") or job.get("note", "")
        keep_review = preserve_review or prior_status == "needs_review"
        keep_applied = job.get("applied") and prior_status == "applied"
        worker["current"] = job["title"]
        store.update_job(
            job_id,
            status="preparing",
            preparation_requested=False,
            preparation_prior_status=prior_status,
            preparation_prior_note=prior_note,
            note="ResumeForge is building the tailored resume.",
        )
        try:
            result = resumeforge_bridge.build_resume(DATA, job)
            if result["status"] == "ready":
                documents = {"resumeforge_pdf": result["path"]}
                current = store.get_job(job_id)
                application = current.get("application")
                extra = (
                    {"application": {**application, "documents": documents}}
                    if isinstance(application, dict)
                    else {}
                )
                store.update_job(
                    job_id,
                    status="applied"
                    if keep_applied
                    else "needs_review"
                    if keep_review
                    else "prepared",
                    documents=documents,
                    resumeforge=result,
                    **extra,
                    note=(prior_note + " ResumeForge resume is ready.").strip()
                    if keep_review
                    else "ResumeForge resume is ready.",
                )
                store.event(f"ResumeForge resume ready for {job['title']} at {job['company']}.")
            else:
                if result["status"] == "failed":
                    workspace = str(
                        result.get("workspace") or resumeforge_bridge.workspace_path(DATA, job).name
                    )
                    result = _failed_resume_result(job, workspace, result)
                store.update_job(
                    job_id,
                    status="needs_review",
                    documents={},
                    resumeforge=result,
                    note=(prior_note + " ResumeForge needs a revision before export.").strip(),
                )
        except Exception as exc:
            try:
                workspace = resumeforge_bridge.workspace_path(DATA, job).name
            except (TypeError, ValueError):
                workspace = ""
            setup_required = isinstance(exc, (FileNotFoundError, ValueError)) and (
                "profile" in str(exc).casefold() or "model settings" in str(exc).casefold()
            )
            failure = _failed_resume_result(job, workspace)
            store.update_job(
                job_id,
                status="needs_review",
                documents={},
                resumeforge={
                    "status": "setup_required" if setup_required else "failed",
                    "workspace": workspace,
                    "attempts": 0 if setup_required else failure["attempts"],
                    "retry_after": None if setup_required else failure["retry_after"],
                    **(
                        {"master_revision": resumeforge_bridge.master_revision()}
                        if setup_required
                        else {}
                    ),
                },
                note=(
                    prior_note
                    + (
                        " Save your ResumeForge profile; this resume will start automatically afterward."
                        if setup_required
                        else " ResumeForge could not finish this resume. Open the role to retry."
                    )
                ).strip(),
            )
            report_error(
                "ResumeForge could not finish this document.",
                category="documents",
                job=job,
                detail=f"{type(exc).__name__}: {exc}",
            )
        finally:
            worker["current"] = None
        return store.get_job(job_id)


def apply_job(job_id):
    if settings()["application_mode"] == "assist":
        return
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


def _automatic_resume_due(job: dict, *, now: datetime | None = None) -> bool:
    """Return whether an unchanged 80%+ role needs one serialized build.

    Successful and editorially blocked runs are stable. A changed posting gets
    a new workspace and therefore one new build. Transient failures retry with
    a short bound; missing first-run profile data waits without burning CPU and
    becomes eligible as soon as the ResumeForge profile is saved.
    """

    if job.get("source") == "email" and (
        job.get("description_missing") or job.get("needs_description_review")
    ):
        return False
    try:
        if float(job.get("fit") or 0) < AUTO_RESUME_MIN_FIT:
            return False
        expected_workspace = resumeforge_bridge.workspace_path(DATA, job).name
    except (TypeError, ValueError):
        return False
    forge = job.get("resumeforge")
    if not isinstance(forge, dict) or forge.get("workspace") != expected_workspace:
        return True
    status = forge.get("status")
    if status == "ready":
        path = (job.get("documents") or {}).get("resumeforge_pdf")
        digest = str(forge.get("sha256") or "")
        return not (
            isinstance(path, str) and digest and resumeforge_bridge.checked_copy(path, digest, DATA)
        )
    if status == "setup_required":
        # Retry only after the user actually changes their saved master draft.
        # An existing but incomplete draft must not trigger a build every loop.
        revision = resumeforge_bridge.master_revision()
        return bool(revision and revision != forge.get("master_revision"))
    if status != "failed":
        # needs_content and needs_review require editorial input, not a hot loop.
        return False
    attempts = _resume_attempt_count(forge.get("attempts"))
    if attempts >= AUTO_RESUME_MAX_RETRIES:
        return False
    retry_after = forge.get("retry_after")
    if not retry_after:
        return True
    try:
        deadline = datetime.fromisoformat(str(retry_after).replace("Z", "+00:00"))
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    return (now or datetime.now(timezone.utc)) >= deadline


def process_document_queue():
    if stop_event.is_set():
        return None
    assist_mode = settings()["application_mode"] == "assist"
    job = next(
        (
            row
            for row in store.jobs()
            if row.get("preparation_requested")
            and (assist_mode or not row.get("uncertain"))
            and not _manual_handoff_active(row)
            and (row.get("review_session") or {}).get("state") not in ["opening", "opened"]
            and row["status"]
            not in [
                "preparing",
                "applying",
                "submitting",
                "confirmed",
                "manually_verified",
                "skipped",
            ]
        ),
        None,
    )
    if job is None:
        job = next(
            (
                row
                for row in store.jobs()
                if row["status"] in ("queued", "prepared", "needs_review")
                and _automatic_resume_due(row)
                and not row.get("uncertain")
                and not row.get("applied")
                and not _manual_handoff_active(row)
                and (row.get("review_session") or {}).get("state") not in ["opening", "opened"]
            ),
            None,
        )
    if job:
        return prepare_job(job["id"])
    return None


def application_loop():
    next_profile_check = 0.0
    while not stop_event.wait(2):
        now = time.monotonic()
        if now >= next_profile_check and os.environ.get("JOBPILOT_TESTING") != "1":
            next_profile_check = now + 10
            try:
                with store.lock:
                    adopt_local_profile(
                        store, resumeforge_bridge.master_workspace(), score_job, settings()
                    )
            except (OSError, sqlite3.OperationalError):
                # The saved profile is committed only after rescoring. A transient
                # error can be retried without taking the dashboard or queue down.
                logging.exception("ResumeForge profile import could not finish; will retry")
                continue
        # Resume creation is independent of the deprecated application-mode
        # switch. Every eligible role is handled by the same serialized
        # ResumeForge queue, while form submission remains disabled in assist
        # mode and is never required for a resume build.
        if process_document_queue() is not None:
            continue
        if settings()["application_mode"] != "assist" and settings()["submission_enabled"]:
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
            else:
                sleep_inhibitor.set_enabled(bool(conf["keep_awake"]))
                awake = bool(sleep_inhibitor.process and sleep_inhibitor.process.poll() is None)
        except Exception:
            # Sleep inhibition is best effort. ResumeForge owns model startup
            # and status, so the always-on JobPilot worker never polls or wakes
            # a language-model service.
            awake = False
        worker["keep_awake"] = awake
        worker["email_status"] = (
            "Configured" if conf.get("email", {}).get("enabled") else "Not configured"
        )
        stop_event.wait(20)
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    sleep_inhibitor.close()


@asynccontextmanager
async def lifespan(app):
    store.recover()
    if settings()["application_mode"] == "assist":
        for job in store.jobs():
            handoff = job.get("browser_handoff") or {}
            if handoff.get("mode") == "default_browser" and handoff.get("state") != "closed":
                store.update_job(
                    job["id"],
                    browser_handoff={
                        **handoff,
                        "state": "closed",
                        "previous_state": handoff.get("state"),
                        "closed_at": store.now(),
                        "closed_reason": "assist_workflow",
                    },
                )
    with email_sync_lock:
        previous_email = store.get("email_sync", {})
        if (
            previous_email.get("state") in ["checking", "syncing", "researching"]
            and not email_task_running.is_set()
        ):
            store.set(
                "email_sync",
                {
                    **previous_email,
                    "state": "error",
                    "message": "The previous Gmail check was interrupted. Use Connect & test or Sync now to try again.",
                },
            )
    stop_event.clear()
    if os.environ.get("JOBPILOT_TESTING") != "1":
        store.event("JobPilot service started. Durable queue restored.")
        for name, target in [
            ("discovery", discovery_loop),
            ("applications", application_loop),
            ("health", health_loop),
            ("email", email_monitor_loop),
        ]:
            threading.Thread(target=target, name=name, daemon=True).start()
        if settings()["remote_intervention_enabled"]:
            remote_runtime.start_async()
    yield
    stop_event.set()
    sleep_inhibitor.close()
    remote_runtime.stop()


app = FastAPI(title="JobPilot", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
)
extension_api = ExtensionAPI(store, DATA, TOKEN)
app.include_router(extension_api.router)


@app.middleware("http")
async def local_security(request: Request, call_next):
    if request.url.path.startswith("/api/extension/"):
        return await extension_api.security(request, call_next)
    origin = request.headers.get("origin")
    # Extension host permissions can omit Origin on GET. Browser-controlled
    # Fetch Metadata still distinguishes those fetches from dashboard requests.
    # CLI/native requests without these headers remain supported.
    if (
        request.url.path.startswith("/api/")
        and not origin
        and request.headers.get("sec-fetch-site") is not None
        and request.headers.get("sec-fetch-site") != "same-origin"
        and request.headers.get("sec-fetch-mode") != "navigate"
    ):
        return JSONResponse(
            {"detail": "Only the local dashboard may access this service."}, status_code=403
        )
    if origin and (
        urlsplit(origin).scheme == "chrome-extension"
        or urlsplit(origin).hostname not in ["127.0.0.1", "localhost", "::1", "testserver"]
    ):
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
    return {"ok": True, "version": __version__, "pid": os.getpid(), "data_dir": str(DATA)}


@app.get("/api/session")
def session():
    return {"token": TOKEN}


@app.get("/api/state")
def state(include_keywords: bool = True):
    profile = store.get("profile")
    profile_json = (
        json.dumps(profile, sort_keys=True, ensure_ascii=False) if include_keywords else ""
    )
    jobs = []
    for job in store.jobs():
        current = dict(job)
        if include_keywords:
            current["keywords"] = job_keywords(job, profile_json)
        forge = job.get("resumeforge")
        if isinstance(forge, dict):
            try:
                active = forge.get("workspace") == resumeforge_bridge.workspace_path(DATA, job).name
            except ValueError:
                active = False
            current["resumeforge"] = {**forge, "current": active}
        jobs.append(current)
    return {
        "metrics": store.metrics(),
        "worker": dict(worker),
        "jobs": jobs,
        "events": store.events(),
        "settings": {k: v for k, v in settings().items() if k != "data_dir"},
        "profile": profile,
        "answers": store.get("answers", {}),
        "remote_access": remote_runtime.status(),
        "problems": store.problems(),
        "email_sync": email_status(),
        "search_monitor": search_monitor(),
    }


@app.post("/api/remote/setup")
def remote_setup(body: dict | None = None):
    if settings()["application_mode"] == "assist":
        raise HTTPException(409, "Remote application control is inactive in assist mode.")
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
    if action == "enable" and settings()["application_mode"] == "assist":
        raise HTTPException(409, "Remote application control is inactive in assist mode.")
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
    was_enabled = conf.get("search_enabled", False)
    if body.get("action") == "shutdown":
        if settings()["application_mode"] != "assist":
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
            stop_event.set()
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
    if settings()["application_mode"] == "assist":
        conf.update(
            application_mode="assist", submission_enabled=False, remote_intervention_enabled=False
        )
    store.set("settings", conf)
    if conf.get("search_enabled") and not was_enabled:
        search_requested.set()
    elif not conf.get("search_enabled") and body.get("action") != "search":
        search_requested.clear()
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
    was_enabled = conf["search_enabled"]
    allowed = (
        set(DEFAULTS)
        - {"remote_intervention_enabled", "intervention_timeout_seconds", "application_mode"}
    ) | {"excluded_companies"}
    update = {k: v for k, v in body.items() if k in allowed}
    for key, low, high in [
        ("search_interval_minutes", 5, 1440),
        ("min_fit", 0, int(AUTO_RESUME_MIN_FIT)),
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
    for key in ["remote", "search_enabled", "submission_enabled", "keep_awake", "startup"]:
        if key in update and not isinstance(update[key], bool):
            raise HTTPException(400, f"{key} must be true or false.")
    old_startup = conf.get("startup")
    conf.update(update)
    if conf.get("application_mode") == "assist":
        conf.update(submission_enabled=False, remote_intervention_enabled=False)
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
    if conf["search_enabled"] and not was_enabled:
        search_requested.set()
    elif not conf["search_enabled"]:
        search_requested.clear()
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
            message = (
                "The job listing could not be read. Open the posting and try importing it again."
            )
            report_error(
                message,
                category="fetch",
                detail=f"{type(exc).__name__}: {exc}",
                url=body.get("url"),
                job={"title": body.get("title"), "company": body.get("company")},
            )
            raise HTTPException(400, message)
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


@app.get("/api/problems")
def problems():
    return {"problems": store.problems()}


@app.post("/api/problems/{problem_id}/resolve")
def resolve_problem(problem_id: int):
    try:
        return {"ok": True, "problem": store.resolve_problem(problem_id)}
    except KeyError:
        raise HTTPException(404, "Problem not found.")


@app.get("/api/jobs/{job_id}/keywords")
def keywords_action(job_id: int):
    return job_keywords(require_job(job_id))


@app.post("/api/jobs/{job_id}/applied")
def applied_action(job_id: int, body: dict):
    if type(body.get("applied")) is not bool:
        raise HTTPException(400, "Choose applied true or false.")
    try:
        job = store.mark_applied(job_id, body["applied"])
    except KeyError:
        raise HTTPException(404, "Job not found.")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True, "job": job}


@app.post("/api/jobs/{job_id}/remove")
def remove_action(job_id: int, body: dict | None = None):
    try:
        return {"ok": True, **store.remove_job(job_id)}
    except KeyError:
        raise HTTPException(404, "Job not found.")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/browser/open_external")
def open_external(body: dict):
    from .links import open_external_url

    url = body.get("url")
    job = None
    if body.get("job_id") is not None:
        job = require_job(body["job_id"])
        url = url or job.get("apply_url") or job.get("url") or job.get("source_url")
    try:
        result = open_external_url(url)
    except (ValueError, OSError) as exc:
        message = (
            "The job page could not be opened. Copy its posting link and open it in your browser."
        )
        report_error(
            message,
            category="links",
            job=job if body.get("job_id") is not None else None,
            url=url,
            detail=str(exc),
        )
        raise HTTPException(400, message)
    if result.get("status") != "opened":
        raise HTTPException(400, result.get("note") or "The job link could not be opened.")
    return result


def _cleanup_now():
    return datetime.now(timezone.utc)


def _cleanup_clock():
    return time.monotonic()


def _cleanup_busy():
    browser_busy = False
    if settings()["application_mode"] != "assist":
        from . import browser

        browser_busy = browser.login_in_progress()
    if worker["submitting"] or worker["current"] or browser_busy:
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
    if settings()["application_mode"] == "assist":
        from .links import open_external_url

        try:
            result = open_external_url(url)
        except (ValueError, OSError) as exc:
            raise HTTPException(
                400,
                "The job page could not be opened. Copy its public posting link into your browser.",
            ) from exc
    else:
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
def prepare_action(job_id: int):
    with store.lock:
        job = require_job(job_id)
        assist_mode = settings()["application_mode"] == "assist"
        if (
            (job.get("uncertain") and not assist_mode)
            or _manual_handoff_active(job)
            or (job.get("review_session") or {}).get("state") in ["opening", "opened"]
            or job["status"]
            in ["confirmed", "manually_verified", "applying", "submitting", "preparing", "skipped"]
        ):
            raise HTTPException(409, "This application is already complete, skipped, or busy.")
        if assist_mode:
            queued = store.update_job(
                job_id,
                preparation_requested=True,
                preparation_prior_status=job["status"],
                preparation_prior_note=job.get("note", ""),
            )
            return {"ok": True, "queued": True, "job": queued}
    if not application_lock.acquire(blocking=False):
        raise HTTPException(409, "Wait for the active application before preparing documents.")
    try:
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
    finally:
        application_lock.release()


@app.post("/api/resumeforge/profile/open")
def open_resumeforge_profile():
    try:
        resumeforge_bridge.open_editor(
            resumeforge_bridge.desktop_executable(), resumeforge_bridge.master_workspace()
        )
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(503, "ResumeForge editor could not open.") from exc
    return {"opened": True}


@app.post("/api/jobs/{job_id}/resumeforge/open")
def open_in_resumeforge(job_id: int):
    job = require_job(job_id)
    try:
        executable = resumeforge_bridge.desktop_executable()
        workspace = resumeforge_bridge.prepare_workspace(DATA, job)
        resumeforge_bridge.open_editor(executable, workspace)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            503, "ResumeForge could not open. Try launching it from Start."
        ) from exc
    return {"opened": True, "message": "Opened this opportunity in ResumeForge."}


@app.get("/api/jobs/{job_id}/resumeforge/status")
def resumeforge_status(job_id: int):
    job = require_job(job_id)
    try:
        workspace = resumeforge_bridge.workspace_path(DATA, job)
    except ValueError:
        return {"status": "no_description", "attached": False}
    try:
        resumeforge_bridge.validate_workspace(DATA, workspace)
    except ValueError:
        return {"status": "invalid", "attached": False}
    if not (workspace / "draft.json").is_file():
        if (job.get("resumeforge") or {}).get("status") == "setup_required":
            return {"status": "setup_required", "attached": False}
        return {"status": "not_opened", "attached": False}
    try:
        result = resumeforge_bridge.checked_run(workspace)
    except (OSError, ValueError):
        return {"status": "invalid", "attached": False}
    run_id = result.get("run_id")
    attached_path = (job.get("documents") or {}).get("resumeforge_pdf")
    attached = (
        run_id is not None
        and (job.get("resumeforge") or {}).get("run_id") == run_id
        and isinstance(attached_path, str)
        and resumeforge_bridge.checked_copy(attached_path, result.get("sha256", ""), DATA)
    )
    return {"status": result["status"], "attached": attached}


@app.post("/api/jobs/{job_id}/resumeforge/use")
@guard_job_mutation
def use_resumeforge_pdf(job_id: int):
    from resumeforge.desktop_support import export_checked

    job = require_job(job_id)
    try:
        workspace = resumeforge_bridge.workspace_path(DATA, job)
        resumeforge_bridge.validate_workspace(DATA, workspace)
        result = resumeforge_bridge.checked_run(workspace)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    if result["status"] != "ready":
        raise HTTPException(409, "Build and review the resume in ResumeForge first.")
    try:
        destination = resumeforge_bridge.resume_destination(DATA, job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    was_checked = resumeforge_bridge.checked_copy(str(destination), result["sha256"], DATA)
    try:
        export_checked(result["pdf"].parent, destination)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    documents = {"resumeforge_pdf": str(destination)}
    cover = destination.parent / "Alnajjar_CoverLetter.pdf"
    if cover.is_file() and cover.stat().st_size > 5 and cover.read_bytes()[:5] == b"%PDF-":
        documents["resumeforge_cover_pdf"] = str(cover)
    job = require_job(job_id)
    already_attached = (
        (job.get("resumeforge") or {}).get("run_id") == result["run_id"]
        and job.get("documents") == documents
        and was_checked
    )
    changes = {
        "status": "needs_review" if job["status"] == "needs_review" else "prepared",
        "documents": documents,
        "resumeforge": {
            "run_id": result["run_id"],
            "sha256": result["sha256"],
            "workspace": workspace.name,
            "attached_at": store.now(),
        },
    }
    if isinstance(job.get("application"), dict):
        changes["application"] = {**job["application"], "documents": documents}
    store.update_job(job_id, **changes)
    return {
        "attached": True,
        "already_attached": already_attached,
        "message": "ResumeForge PDF saved in JobPilot RF Docs.",
    }


def _cover_workspace(job_id):
    job = require_job(job_id)
    return resumeforge_bridge.cover_workspace(DATA, job)


cover_task_lock = threading.Lock()
cover_tasks = {}
cover_preview_lock = threading.Lock()


@app.get("/api/jobs/{job_id}/cover-letter")
def cover_letter_status(job_id: int, summary: bool = False):
    try:
        result = _cover_workspace(job_id).state()
        if summary:
            result.pop("draft", None)
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        result = {"can_generate": False, "exists": False, "ready": False, "message": str(exc)}
    with cover_task_lock:
        task = cover_tasks.get(job_id)
        if task:
            result["task"] = task.copy()
    return result


def _generate_cover_task(workspace, job_id, revision, options):
    def progress(message):
        with cover_task_lock:
            cover_tasks[job_id].update(message=message)

    try:
        workspace.generate(revision, progress=progress, **options)
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as exc:
        state = {"state": "failed", "message": str(exc)}
    except Exception:
        logging.exception("The explicit cover letter task could not finish")
        state = {"state": "failed", "message": "ResumeForge could not finish the cover letter."}
    else:
        state = {"state": "ready", "message": "Cover letter ready."}
    with cover_task_lock:
        cover_tasks[job_id] = state


@app.post("/api/jobs/{job_id}/cover-letter")
def change_cover_letter(job_id: int, body: dict):
    action = body.get("action")
    revision = body.get("revision")
    if action not in ("generate", "save") or type(revision) is not int or revision < 0:
        raise HTTPException(400, "Choose a cover letter action and reopen its current draft.")
    try:
        workspace = _cover_workspace(job_id)
        if action == "save":
            return workspace.save(body.get("text"), revision)
        options = {
            "confirmed": body.get("confirmed") is True,
            "instructions": str(body.get("instructions") or "")[:3000],
            "company_url": str(body.get("company_url") or "")[:1800].strip(),
        }
        workspace.check_generation(revision, options["confirmed"])
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(409, str(exc)) from exc
    with cover_task_lock:
        if any(task["state"] == "running" for task in cover_tasks.values()):
            raise HTTPException(409, "Another cover letter is still being drafted in JobPilot.")
        cover_tasks.pop(job_id, None)
        if len(cover_tasks) >= 24:
            del cover_tasks[next(iter(cover_tasks))]
        queued = {"state": "running", "message": "Preparing the cover letter…"}
        cover_tasks[job_id] = queued.copy()
    threading.Thread(
        target=_generate_cover_task,
        args=(workspace, job_id, revision, options),
        name="JobPilot cover letter",
        daemon=True,
    ).start()
    return JSONResponse({"task": queued}, status_code=202)


@app.get("/api/jobs/{job_id}/cover-letter/preview")
def cover_letter_preview(job_id: int):
    import pypdfium2

    try:
        workspace = _cover_workspace(job_id)
        pdf_path = _artifact_target(str(workspace.letter), document=True)
        if workspace.letter.is_symlink() or pdf_path.stat().st_size > 15 * 1024 * 1024:
            raise ValueError("The cover letter preview is unavailable.")
        # Job details can be open in multiple UI windows. PDFium renders
        # through one call at a time within this service.
        with cover_preview_lock, pypdfium2.PdfDocument(str(pdf_path)) as pdf:
            page = pdf[0]
            try:
                bitmap = page.render(scale=1.35)
                try:
                    stream = io.BytesIO()
                    bitmap.to_pil().save(stream, format="PNG")
                finally:
                    bitmap.close()
            finally:
                page.close()
        return Response(
            stream.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"}
        )
    except (OSError, ValueError, KeyError, pypdfium2.PdfiumError) as exc:
        raise HTTPException(409, "The cover letter preview is unavailable.") from exc


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
    if settings()["application_mode"] == "assist":
        raise HTTPException(
            409, "The combined app uses your regular browser for application review."
        )
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
    if settings()["application_mode"] == "assist":
        raise HTTPException(409, "The combined app uses your regular browser for sign-in.")
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
    with email_sync_lock:
        if email_task_running.is_set():
            raise HTTPException(
                409, "Wait for the inbox check to finish before changing the account."
            )
        return _save_email_configuration(body)


def _save_email_configuration(body: dict):
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
    store.set("_email_next_poll", 0)
    store.set(
        "email_sync",
        {
            "state": "not_connected",
            "message": "Gmail settings saved. Test the connection to continue.",
        },
    )
    return {"ok": True}


@app.get("/api/email/status")
def email_status():
    config = settings().get("email", {})
    defaults = {
        "state": "not_connected",
        "message": "Connect Gmail in Email settings to import job alerts.",
        "checked_at": None,
        "messages_available": 0,
        "messages_checked": 0,
        "messages_skipped": 0,
        "non_alerts": 0,
        "links_found": 0,
        "imported": 0,
        "existing": 0,
        "filtered": 0,
        "removed": 0,
        "truncated": False,
        "researched": 0,
        "awaiting_research": 0,
        "unverified": 0,
        "closed": 0,
    }
    return {
        **defaults,
        **store.get("email_sync", {}),
        "credential_saved": bool(config.get("credential_saved")),
        "enabled": bool(config.get("enabled")),
    }


def _save_email_result(result, imported=0, complete_task=False):
    fields = [
        "checked_at",
        "messages_available",
        "messages_checked",
        "messages_skipped",
        "non_alerts",
        "links_found",
        "truncated",
        "existing",
        "filtered",
        "removed",
        "researched",
        "awaiting_research",
        "unverified",
        "closed",
    ]
    summary = {key: result[key] for key in fields if key in result}
    result_state = result.get("state", "connected")
    summary.update(
        state=result_state,
        message=result.get("message")
        or (
            "Gmail connection verified."
            if result_state == "connected"
            else "Gmail could not finish this check. Reconnect the inbox and try again."
        ),
        imported=imported,
    )
    with email_sync_lock:
        if email_task_running.is_set() and not complete_task:
            return email_status()
        store.set("email_sync", summary)
        worker["email_status"] = summary["message"]
    return summary


EMAIL_SCAN_INTERVAL = 15 * 60
EMAIL_RESEARCH_BATCH = 6
EMAIL_RESEARCH_RETRIES = (5 * 60, 30 * 60)


def _email_pending(job):
    return (
        job.get("source") == "email"
        and job["status"] in {"queued", "needs_review", "review_required"}
        and (job.get("description_missing") or job.get("needs_description_review"))
        and not (job.get("documents") or job.get("applied") or job.get("uncertain"))
        and not job.get("attempts")
        and not _manual_handoff_active(job)
        and (job.get("review_session") or {}).get("state") not in {"opening", "opened"}
    )


def _email_due(job, now):
    research = job.get("alert_research") or {}
    return _email_pending(job) and (
        not research
        or (research.get("state") == "pending" and (research.get("retry_at") or 0) <= now)
    )


def _matching_employer_posting(alert, saved_jobs):
    def signature(job):
        return tuple(
            " ".join(str(job.get(key) or "").casefold().split())
            for key in ("title", "company", "location")
        )

    identity = signature(alert)
    if not all(identity):
        return None
    matches = [
        job
        for job in saved_jobs
        if job.get("source", "").casefold() in {"greenhouse", "lever", "ashby", "employer"}
        and signature(job) == identity
        and not (job.get("description_missing") or job.get("needs_description_review"))
        and len(str(job.get("description") or "")) >= 80
    ]
    return matches[0] if len(matches) == 1 else None


def _research_email_batch(job_id=None):
    from .posting_research import PostingClosed, research_posting

    deadline = time.monotonic() + 45
    saved_jobs = store.jobs()
    candidates = [
        job
        for job in saved_jobs
        if (
            _email_due(job, time.time())
            if job_id is None
            else job["id"] == job_id and _email_pending(job)
        )
    ]
    candidates.sort(key=lambda job: (-(job.get("fit") or 0), job["id"]))
    verified = 0
    for job in candidates[:EMAIL_RESEARCH_BATCH]:
        if stop_event.is_set() or time.monotonic() >= deadline:
            break
        previous = job.get("alert_research") or {}
        attempt = 1 if job_id is not None else int(previous.get("attempts") or 0) + 1
        state = "verified"
        duplicate = None
        try:
            details = research_posting(job)
        except PostingClosed:
            state = "closed"
        except Exception as exc:
            state = "pending" if attempt <= len(EMAIL_RESEARCH_RETRIES) else "unverified"
            if alternate := _matching_employer_posting(job, saved_jobs):
                # The saved employer role must still have a live public
                # posting. Do not use an old cached description as proof.
                try:
                    details = research_posting(alternate)
                    duplicate = alternate["id"]
                    state = "duplicate"
                except Exception:
                    pass
            if state != "duplicate" and attempt == 1:
                report_error(
                    "A full posting was unavailable for a saved inbox alert. JobPilot will retry.",
                    category="fetch",
                    job=job,
                    detail=type(exc).__name__,
                )
        with store.lock:
            current = store.get_job(job["id"])
            if not current or not _email_pending(current):
                continue
            research = {"state": state, "attempts": attempt, "checked_at": store.now()}
            if state in {"verified", "duplicate"}:
                verified += 1
                if duplicate:
                    research["duplicate_of"] = duplicate
                    details["source_url"] = current.get("source_url") or current["url"]
                enriched = classify_job(
                    {**current, **details, "alert_research": research},
                    store.get("profile"),
                    settings(),
                )
                # The stable alert row may already be bookmarked. Preserve its
                # ID and job identity while updating its public posting details.
                enriched.pop("url", None)
                enriched.setdefault("note", "")
                enriched.setdefault("review_reason", None)
                if duplicate:
                    enriched.update(
                        status="skipped", note="Already saved from the employer's job board."
                    )
                store.update_job(job["id"], **enriched)
            elif state == "closed":
                store.update_job(
                    job["id"],
                    alert_research=research,
                    status="skipped",
                    note="The employer's public posting has closed.",
                )
            else:
                if state == "pending":
                    research["retry_at"] = time.time() + EMAIL_RESEARCH_RETRIES[attempt - 1]
                store.update_job(
                    job["id"],
                    alert_research=research,
                    note="Full posting unavailable. JobPilot will retry."
                    if state == "pending"
                    else "Full posting unverified. Review the public link.",
                )
    return verified


def _stage_email_alerts(alerts):
    existing_jobs = store.jobs()
    existing = {job["id"] for job in existing_jobs}
    routes = {
        canonical_url(job[key])
        for job in existing_jobs
        for key in ("url", "source_url", "apply_url")
        if job.get(key)
    }
    counts = dict.fromkeys(("imported", "existing", "filtered", "removed"), 0)
    profile, conf = store.get("profile"), settings()
    for alert in alerts:
        # Location and job-summary hints are provisional. A confident title
        # can eliminate an obvious mismatch, but an inferred title cannot.
        classified = classify_job(
            {**alert, "source": "email", "description_missing": True, "location": ""},
            profile,
            conf,
        )
        classified["location"] = alert.get("location", "")
        if (
            alert.get("title") in (None, "", "Job from email alert")
            or alert.get("alert_title_source") == "subject"
        ) and classified.get("note") != "Company is excluded in preferences.":
            classified.update(status="needs_review", note="Waiting for the public posting.")
        if classified["status"] == "skipped":
            counts["filtered"] += 1
            if canonical_url(classified["url"]) in routes:
                store.add_job(classified)
            continue
        saved = store.add_job(classified)
        if saved is None:
            counts["removed"] += 1
        elif saved["id"] in existing:
            counts["existing"] += 1
        else:
            counts["imported"] += 1
            existing.add(saved["id"])
    return counts


def _email_work(mode, config, job_id=None):
    from . import collectors

    try:
        if mode == "checking":
            _save_email_result(collectors.check_email_connection(config), complete_task=True)
            return
        result = email_status()
        if mode == "syncing":
            account = [config.get(key) for key in ("host", "username", "mailbox", "lookback_days")]
            saved = store.get("_email_checkpoint", {})
            checkpoint = saved.get("cursor") if saved.get("account") == account else None
            result = collectors.sync_email({**config, "checkpoint": checkpoint})
            result.update(_stage_email_alerts(result["jobs"]))
            # Only advance after staging all jobs. A crash may repeat a
            # batch, but the store deduplicates URLs and respects removals.
            if result.get("checkpoint"):
                store.set("_email_checkpoint", {"account": account, "cursor": result["checkpoint"]})
            delay = (
                5 * 60
                if result.get("scan_interrupted")
                else 30
                if result.get("truncated") and result.get("checkpoint")
                else EMAIL_SCAN_INTERVAL
            )
            store.set("_email_next_poll", time.time() + delay)
        result["researched"] = (result.get("researched") or 0) + _research_email_batch(job_id)
        jobs = store.jobs()
        pending = [job for job in jobs if _email_pending(job)]
        unverified = sum(
            (job.get("alert_research") or {}).get("state") == "unverified" for job in pending
        )
        inbox_state = (
            result.get("inbox_state", "connected") if mode == "researching" else "connected"
        )
        result.update(
            state=inbox_state,
            awaiting_research=len(pending) - unverified,
            unverified=unverified,
            closed=sum((job.get("alert_research") or {}).get("state") == "closed" for job in jobs),
            message=result.get("inbox_message")
            if inbox_state != "connected"
            else (
                f"Found {result.get('links_found', 0)} job links: {result.get('imported', 0)} new, "
                f"{result.get('existing', 0)} already saved, "
                f"{result.get('filtered', 0)} outside preferences, "
                f"{result.get('removed', 0)} previously removed."
            ),
        )
        _save_email_result(result, result.get("imported", 0), complete_task=True)
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, collectors.EmailConnectionError)
            else "Gmail could not finish this check. Reconnect the inbox and try again."
        )
        report_error(message, category="email", detail=f"{type(exc).__name__}: {exc}")
        with email_sync_lock:
            store.set("_email_next_poll", time.time() + EMAIL_SCAN_INTERVAL)
            store.set(
                "email_sync",
                {**email_status(), "state": "error", "message": message, "checked_at": store.now()},
            )
            worker["email_status"] = message
    finally:
        with email_sync_lock:
            email_task_running.clear()


def email_monitor_loop():
    while not stop_event.wait(15):
        conf = settings().get("email", {})
        if (
            not (conf.get("enabled") and conf.get("credential_saved") and conf.get("username"))
            or email_task_running.is_set()
        ):
            continue
        if email_status()["state"] == "not_connected":
            continue
        now = time.time()
        if now >= store.get("_email_next_poll", 0):
            _start_email("syncing")
        elif any(_email_due(job, now) for job in store.jobs()):
            _start_email("researching")


def _start_email(mode, job_id=None):
    with email_sync_lock:
        config = settings().get("email", {})
        if job_id is None and not config.get("username"):
            raise HTTPException(
                400, "Save your Gmail address and a Google app password in Email settings first."
            )
        if email_task_running.is_set():
            if job_id is not None:
                raise HTTPException(409, "Wait for the active inbox or research task to finish.")
            return JSONResponse({"ok": True, "state": email_status()["state"]}, status_code=202)
        email_task_running.set()
        prior = email_status()
        if mode == "researching":
            # Keep the last inbox result while the work uses only saved links.
            prior["inbox_state"] = prior["state"]
            prior["inbox_message"] = prior["message"]
        store.set(
            "email_sync",
            {
                **prior,
                "state": mode,
                "message": {
                    "checking": "Checking the Gmail connection.",
                    "syncing": "Reading job alerts from Gmail.",
                    "researching": "Verifying public postings for saved alerts.",
                }[mode],
            },
        )
        threading.Thread(target=_email_work, args=(mode, dict(config), job_id), daemon=True).start()
    return JSONResponse({"ok": True, "state": mode}, status_code=202)


@app.post("/api/email/check")
def check_email(body: dict | None = None):
    return _start_email("checking")


@app.post("/api/email/sync")
def sync_email(body: dict | None = None):
    return _start_email("syncing")


@app.post("/api/jobs/{job_id}/email/research")
def research_email_job(job_id: int):
    if not _email_pending(require_job(job_id)):
        raise HTTPException(409, "This alert does not need public posting research.")
    return _start_email("researching", job_id=job_id)


def _artifact_target(path, *, document=False):
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        raise HTTPException(400, "Choose a generated document and try again.")
    target = Path(path).resolve()
    allowed = [
        DATA / "applications",
        DATA / "receipts",
        DATA / "evidence",
        Path.home() / "Downloads" / "JobPilot RF Docs",
    ]
    if not any(target.is_relative_to(x.resolve()) for x in allowed):
        raise HTTPException(403, "Only generated application files can be accessed.")
    if document and target.suffix.lower() != ".pdf":
        raise HTTPException(400, "Open supports PDF documents.")
    if not target.is_file():
        raise HTTPException(404, "This file is missing. Regenerate the documents and try again.")
    return target


@app.post("/api/artifact/open")
def open_artifact(body: dict):
    from .artifacts import open_document

    target = _artifact_target(body.get("path"), document=True)
    try:
        open_document(target)
    except OSError as exc:
        raise HTTPException(
            503, "Your document app could not open this file. Use Download to save it instead."
        ) from exc
    return {"ok": True, "opened": True, "name": target.name}


@app.get("/api/artifact")
def artifact(path: str):
    target = _artifact_target(path)
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
        "applied_at",
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
