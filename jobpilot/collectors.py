"""Bounded job discovery, public employer listings and read-only email alerts.

No credentials are accepted in URLs, and every fetch/redirect is checked before
connecting. Email receipt dates are never treated as job posting dates.
"""

from __future__ import annotations

import email
import imaplib
import ipaddress
import json
import logging
import math
import re
import socket
import threading
from datetime import datetime, timedelta, timezone
from email import policy
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import keyring
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
_errors: list[dict] = []
_search_warnings: list[dict] = []
_errors_lock = threading.Lock()
_CREDENTIAL_SERVICE = "JobPilot/IMAP"
_MAX_BODY = 4 * 1024 * 1024


def _validate_host(host: str) -> None:
    host = str(host).lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Only public internet hosts are supported")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            ]
        except socket.gaierror as exc:
            raise ValueError("Host could not be resolved") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Private, loopback and reserved network destinations are blocked")


def validate_public_url(url: str, *, allow_fixture: bool = False) -> str:
    if not isinstance(url, str) or len(url) > 4096 or any(c in url for c in "\r\n\\"):
        raise ValueError("Invalid job URL")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise ValueError("Invalid job URL") from exc
    if (
        parts.scheme not in ("https", "http")
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ValueError("Job URLs must be public HTTP(S) addresses without credentials")
    if allow_fixture and parts.hostname in ("127.0.0.1", "localhost", "::1"):
        return url.strip()
    if port and port not in (80, 443):
        raise ValueError("Only public web ports are supported")
    _validate_host(parts.hostname)
    return url.strip()


def _get_public(url: str) -> tuple[str, str]:
    """Read bounded pages (4 MiB; known ATS APIs 32 MiB), checking redirects."""
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(5):
            url = validate_public_url(url)
            cap = (
                32 * 1024 * 1024
                if urlsplit(url).hostname
                in ("boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com")
                else _MAX_BODY
            )
            with session.get(
                url,
                allow_redirects=False,
                timeout=(6, 20),
                stream=True,
                headers={
                    "User-Agent": "JobPilot/1.0 job discovery",
                    "Accept": "application/json,text/html",
                },
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    target = response.headers.get("Location")
                    if not target:
                        raise ValueError("Redirect without a destination")
                    url = urljoin(url, target)
                    continue
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > cap:
                        raise ValueError("Job page exceeds the download limit")
                    chunks.append(chunk)
                return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace"), url
    raise ValueError("Too many job-page redirects")


def _text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value)
    return (
        BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        if "<" in text
        else text.strip()
    )


def _date(value):
    if value is None or str(value).lower() in ("nat", "nan", "none", ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(
                value / 1000 if value > 1e11 else value, timezone.utc
            ).isoformat()
        except (OverflowError, ValueError, OSError):
            return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _canonical_link(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path
    if host.endswith("linkedin.com"):
        found = re.search(r"/jobs/view/(\d+)", path)
        if found:
            return f"https://www.linkedin.com/jobs/view/{found[1]}/"
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in ("trackingid", "refid", "trk", "source", "gh_src", "lever-source")
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def _job(source, url, title="", company="", location="", description="", posted_at=None, **extra):
    return {
        "source": source,
        "url": _canonical_link(url),
        "title": _text(title),
        "company": _text(company),
        "location": _text(location),
        "description": _text(description)[:120000],
        "posted_at": _date(posted_at),
        **extra,
    }


def _jsonld_postings(value):
    if isinstance(value, list):
        for item in value:
            yield from _jsonld_postings(item)
    elif isinstance(value, dict):
        kind = value.get("@type", [])
        kinds = kind if isinstance(kind, list) else [kind]
        if any(str(item).split("/")[-1] == "JobPosting" for item in kinds):
            yield value
        for item in value.values():
            if isinstance(item, (dict, list)):
                yield from _jsonld_postings(item)


def fetch_job(url: str) -> dict:
    validate_public_url(url)
    content, final_url = _get_public(url)
    soup = BeautifulSoup(content, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            postings = list(_jsonld_postings(json.loads(script.get_text())))
        except (ValueError, TypeError):
            continue
        if not postings:
            continue
        posting = postings[0]
        org = posting.get("hiringOrganization") or {}
        company = org.get("name", "") if isinstance(org, dict) else str(org)
        locations = posting.get("jobLocation") or []
        locations = locations if isinstance(locations, list) else [locations]
        labels = []
        for location in locations:
            address = location.get("address", {}) if isinstance(location, dict) else {}
            if isinstance(address, dict):
                labels.append(
                    ", ".join(
                        str(address[key])
                        for key in ("addressLocality", "addressRegion", "addressCountry")
                        if address.get(key)
                    )
                )
            elif address:
                labels.append(str(address))
        if posting.get("jobLocationType") == "TELECOMMUTE":
            labels.insert(0, "Remote")
        return _job(
            "employer",
            final_url,
            posting.get("title", ""),
            company,
            "; ".join(labels),
            posting.get("description", ""),
            posting.get("datePosted"),
            requisition_id=_text(posting.get("identifier", {}).get("value", ""))
            if isinstance(posting.get("identifier"), dict)
            else "",
        )
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    heading = soup.find("h1") or soup.find("title")
    description = soup.find("main") or soup.find("article") or soup.body or soup
    return _job(
        "employer",
        final_url,
        heading.get_text(" ", strip=True) if heading else "",
        description=description.get_text(" ", strip=True),
        needs_description_review=True,
    )


def _alert_job_link(url: str) -> bool:
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in ("https", "http")
            or parts.username
            or parts.password
            or not parts.hostname
        ):
            return False
        host = parts.hostname.lower()
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
                return False
        if any(
            word in url.lower()
            for word in ("unsubscribe", "preferences", "signin", "login", "tracking/pixel")
        ):
            return False
        if host == "linkedin.com" or host.endswith(".linkedin.com"):
            return bool(re.search(r"/jobs/view/\d+", parts.path))
        if host == "indeed.com" or host.endswith(".indeed.com"):
            return bool(parse_qs(parts.query).get("jk"))
        if host.endswith((".lever.co", ".ashbyhq.com", ".greenhouse.io")):
            return len(parts.path.strip("/").split("/")) >= 2
        return bool(re.search(r"/(?:jobs?|careers?|positions?)/[^/?]+", parts.path, re.I))
    except ValueError:
        return False


def import_eml(text: str | bytes) -> list[dict]:
    if len(text) > _MAX_BODY:
        raise ValueError("Email exceeds the import limit")
    message = email.message_from_bytes(
        text if isinstance(text, bytes) else text.encode(), policy=policy.default
    )
    candidates, description_parts = [], []
    for part in message.walk():
        if part.get_content_disposition() == "attachment" or part.get_content_type() not in (
            "text/plain",
            "text/html",
        ):
            continue
        try:
            body = part.get_content()
        except (LookupError, UnicodeError):
            continue
        if part.get_content_type() == "text/html":
            soup = BeautifulSoup(body, "html.parser")
            for anchor in soup.find_all("a", href=True):
                candidates.append((anchor["href"], anchor.get_text(" ", strip=True)))
            body = soup.get_text(" ", strip=True)
        description_parts.append(str(body))
        candidates.extend(
            (match.rstrip(".,);]>"), "") for match in re.findall(r'https?://[^\s<>"\']+', str(body))
        )
    jobs, seen = [], set()
    for url, title in candidates:
        if not _alert_job_link(url):
            continue
        url = _canonical_link(url)
        if url in seen:
            continue
        seen.add(url)
        jobs.append(
            _job(
                "email",
                url,
                title or "Job from email alert",
                description="\n".join(description_parts)[:20000],
                alert_received_at=str(message.get("Date", "")),
                alert_subject=str(message.get("Subject", "")),
            )
        )
    return jobs


def _credential_account(config: dict) -> str:
    return f"{config.get('username', '')}@{config.get('host', '')}"


def configure_email(config: dict) -> dict:
    host = str(config.get("host", "imap.gmail.com")).strip().lower()
    username = str(config.get("username") or config.get("email") or "").strip()
    if not username or any(c in username for c in "\r\n") or len(username) > 320:
        raise ValueError("A valid email account is required")
    _validate_host(host)
    if int(config.get("port", 993)) != 993:
        raise ValueError("Encrypted IMAP on port 993 is required")
    safe = {
        "host": host,
        "port": 993,
        "username": username,
        "enabled": bool(config.get("enabled", False)),
        "mailbox": str(config.get("mailbox", "INBOX"))[:128],
        "limit": max(1, min(int(config.get("limit", 30)), 100)),
    }
    password = config.get("password")
    if password:
        keyring.set_password(_CREDENTIAL_SERVICE, _credential_account(safe), str(password))
        safe["credential_saved"] = True
    else:
        safe["credential_saved"] = bool(
            keyring.get_password(_CREDENTIAL_SERVICE, _credential_account(safe))
        )
    return safe


def _imap_jobs(config: dict) -> list[dict]:
    _validate_host(config["host"])
    password = keyring.get_password(_CREDENTIAL_SERVICE, _credential_account(config))
    if not password:
        raise ValueError("IMAP password is missing from Windows credential storage")
    jobs = []
    with imaplib.IMAP4_SSL(config["host"], 993, timeout=20) as inbox:
        inbox.login(config["username"], password)
        status, _ = inbox.select(config.get("mailbox", "INBOX"), readonly=True)
        if status != "OK":
            raise ValueError("IMAP mailbox could not be opened")
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%d-%b-%Y")
        status, result = inbox.uid("search", None, "SINCE", since)
        if status != "OK":
            raise ValueError("IMAP alert search failed")
        identifiers = (result[0] or b"").split()[-max(1, min(int(config.get("limit", 30)), 100)) :]
        for identifier in identifiers:
            status, parts = inbox.uid("fetch", identifier, "(BODY.PEEK[])")
            if status != "OK":
                continue
            for part in parts:
                if (
                    isinstance(part, tuple)
                    and isinstance(part[1], bytes)
                    and len(part[1]) <= _MAX_BODY
                ):
                    jobs.extend(import_eml(part[1]))
    return jobs


def _jobspy_search(**kwargs):
    from jobspy import scrape_jobs

    class WarningRecorder(logging.Handler):
        def emit(self, record):
            with _errors_lock:
                _search_warnings.append(
                    {
                        "source": record.name.partition(":")[2].lower(),
                        "note": record.getMessage()[:300],
                    }
                )

    handler = WarningRecorder(level=logging.WARNING)
    loggers = [
        logging.getLogger(name)
        for name in logging.root.manager.loggerDict
        if name.startswith("JobSpy:")
    ]
    for logger in loggers:
        logger.addHandler(handler)
    try:
        frame = scrape_jobs(**kwargs)
    finally:
        for logger in loggers:
            logger.removeHandler(handler)
    return frame.to_dict("records")


def _board_jobs(source: str, board: str) -> list[dict]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", board):
        raise ValueError("ATS board must be a company board slug")
    endpoints = {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
        "lever": f"https://api.lever.co/v0/postings/{board}?mode=json",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{board}",
    }
    if source not in endpoints:
        raise ValueError("Unsupported public ATS source")
    content, _ = _get_public(endpoints[source])
    data = json.loads(content)
    rows = data if isinstance(data, list) else data.get("jobs", [])
    jobs = []
    for row in rows[:500]:
        if source == "greenhouse":
            job = _job(
                source,
                row.get("absolute_url", ""),
                row.get("title", ""),
                board,
                (row.get("location") or {}).get("name", ""),
                row.get("content", ""),
                row.get("first_published") or row.get("published_at"),
                requisition_id=str(row.get("id", "")),
            )
        elif source == "lever":
            job = _job(
                source,
                row.get("hostedUrl", ""),
                row.get("text", ""),
                board,
                (row.get("categories") or {}).get("location", ""),
                row.get("descriptionPlain") or row.get("description", ""),
                row.get("createdAt"),
                requisition_id=str(row.get("id", "")),
            )
        else:
            if row.get("isListed") is False:
                continue
            job = _job(
                source,
                row.get("jobUrl", ""),
                row.get("title", ""),
                board,
                row.get("location", ""),
                row.get("descriptionPlain") or row.get("descriptionHtml", ""),
                row.get("publishedAt"),
                requisition_id=str(row.get("id", "")),
            )
        direct = _text(row.get("applyUrl"))
        if direct:
            try:
                job["apply_url"] = _canonical_link(validate_public_url(direct))
            except ValueError:
                pass
        if job["url"] and job["title"]:
            jobs.append(job)
    return jobs


def get_last_errors() -> list[dict]:
    with _errors_lock:
        return [dict(error) for error in _errors]


def discover(settings: dict, profile: dict) -> list[dict]:
    jobs, errors = [], []
    with _errors_lock:
        _search_warnings.clear()
    sources = settings.get("sources", ["linkedin", "indeed"])
    if isinstance(sources, str):
        sources = [sources] if sources != "both" else ["linkedin", "indeed"]
    titles = settings.get("search_titles") or settings.get("target_roles") or ["Security Engineer"]
    locations = settings.get("locations") or [settings.get("location", "Cincinnati, OH")]
    if settings.get("remote") and "Remote" not in locations:
        locations = [*locations, "Remote"]
    limit = max(1, min(int(settings.get("results_per_source", 20)), 100))
    for source in sources:
        if source not in (
            "linkedin",
            "indeed",
            "glassdoor",
            "zip_recruiter",
            "bayt",
            "naukri",
            "bdjobs",
            "hellowork",
        ):
            continue
        source_found = 0
        for title in list(titles)[:8]:
            for location in list(locations)[:4]:
                if source_found >= limit:
                    break
                try:
                    rows = _jobspy_search(
                        site_name=[source],
                        search_term=title,
                        location=location,
                        results_wanted=limit - source_found,
                        hours_old=max(1, min(int(settings.get("hours_old", 168)), 8760)),
                        fetch_description=True,
                        country_indeed="USA",
                        verbose=1,
                    )
                    for row in rows[: limit - source_found]:
                        source_url = _text(row.get("job_url"))
                        direct_url = _text(row.get("job_url_direct"))
                        if direct_url:
                            try:
                                direct_url = validate_public_url(direct_url)
                            except ValueError:
                                direct_url = ""
                        url = direct_url or source_url
                        if not url:
                            continue
                        description = _text(row.get("description"))
                        if not description:
                            errors.append(
                                {
                                    "source": source,
                                    "note": "Description unavailable; review required: " + url,
                                }
                            )
                        jobs.append(
                            _job(
                                source,
                                url,
                                row.get("title"),
                                row.get("company"),
                                row.get("location"),
                                row.get("description"),
                                row.get("date_posted"),
                                source_url=_canonical_link(source_url) if source_url else None,
                                apply_url=_canonical_link(direct_url) if direct_url else None,
                                description_missing=not bool(description),
                                requisition_id=_text(row.get("id")),
                                salary_min=row.get("min_amount")
                                if isinstance(row.get("min_amount"), (int, float))
                                and not math.isnan(row.get("min_amount"))
                                else None,
                            )
                        )
                        source_found += 1
                except Exception as exc:
                    errors.append(
                        {"source": source, "note": f"{type(exc).__name__}: {str(exc)[:240]}"}
                    )
                    break
    for board in list(settings.get("ats_boards", []))[:30]:
        try:
            jobs.extend(_board_jobs(str(board["source"]).lower(), str(board["board"])))
        except Exception as exc:
            errors.append(
                {
                    "source": str(board.get("source", "ats")),
                    "note": f"{type(exc).__name__}: {str(exc)[:240]}",
                }
            )
    email_config = settings.get("email") or {}
    if email_config.get("enabled"):
        try:
            jobs.extend(_imap_jobs(email_config))
        except Exception as exc:
            errors.append({"source": "email", "note": f"{type(exc).__name__}: {str(exc)[:240]}"})
    unique = {}
    for job in jobs:
        if job["url"] not in unique:
            unique[job["url"]] = job
    with _errors_lock:
        _errors[:] = errors + list(_search_warnings)
    return list(unique.values())
