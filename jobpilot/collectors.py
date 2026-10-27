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
_email_result: dict = {}
_email_lock = threading.Lock()


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
        if host.endswith(".greenhouse.io"):
            return host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and bool(
                re.search(r"^/[^/]+/(?:jobs/)?\d+/?$", parts.path)
            )
        if host.endswith((".lever.co", ".ashbyhq.com")):
            return len(parts.path.strip("/").split("/")) >= 2
        return bool(re.search(r"/(?:jobs?|careers?|positions?)/[^/?]+", parts.path, re.I))
    except ValueError:
        return False


def _alert_destination(url: str) -> str:
    for _ in range(3):
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host in {
            "www.google.com",
            "google.com",
            "www.linkedin.com",
            "linkedin.com",
        } or host.endswith(".safelinks.protection.outlook.com"):
            query = parse_qs(parts.query)
            nested = next((query[key][0] for key in ("url", "q", "target") if query.get(key)), "")
            if nested.startswith(("https://", "http://")):
                url = nested
                continue
        break
    return (
        _canonical_link(url)
        if _alert_job_link(url) or re.search(r"/comm/jobs/view/\d+", url)
        else url
    )


def _alert_has_title(title: str) -> bool:
    return bool(title.strip()) and title.strip().casefold() not in {
        "view job",
        "view jobs",
        "apply",
        "apply now",
        "see job",
        "learn more",
    }


def _alert_title_company(title: str, subject: str, url: str) -> tuple[str, str]:
    title = re.sub(r"\s+", " ", title).strip()
    if not _alert_has_title(title):
        title = (
            subject
            if re.search(
                r"\b(?:at|engineer|analyst|manager|specialist|developer|consultant)\b",
                subject,
                re.I,
            )
            else "Job from email alert"
        )
    match = re.match(r"(.+?)\s+(?:at|@)\s+(.+)", title, re.I)
    if match:
        return match[1].strip(), match[2].strip()
    parts = urlsplit(url)
    host = parts.hostname or ""
    company = ""
    if host.endswith((".lever.co", ".ashbyhq.com", ".greenhouse.io")):
        company = parts.path.strip("/").split("/")[0].replace("-", " ").title()
    return title, company


def _alert_anchor_metadata(anchor, url: str) -> tuple[str, str, str, str]:
    """Read one alert card, stopping before a digest's other job cards."""
    card = anchor.find_parent(["article", "tr", "li"]) or anchor.parent or anchor
    company, location = "", ""
    for parent in [anchor, *anchor.parents]:
        if parent.name not in {"a", "article", "tr", "li", "td", "tbody", "table", "div"}:
            continue
        links = set()
        for link in parent.find_all("a", href=True):
            try:
                destination = _alert_destination(link["href"])
                if _alert_job_link(destination):
                    links.add(_canonical_link(destination))
            except ValueError:
                continue
        if links - {url}:
            break
        metadata = next(
            (
                match
                for text in parent.find_all("p")
                if (
                    match := re.match(
                        r"^(.+?)\s+[\u00b7\u2022]\s+(.+)$", text.get_text(" ", strip=True)
                    )
                )
            ),
            None,
        )
        if metadata:
            card = parent
            company, location = metadata[1].strip(), metadata[2].strip()
            break
    labels = []
    for link in [anchor, *card.find_all("a", href=True)]:
        try:
            if _canonical_link(_alert_destination(link.get("href", ""))) != url:
                continue
        except ValueError:
            continue
        label = link.get_text(" ", strip=True)
        if _alert_has_title(label) and not link.find("a"):
            labels.append(label)
    title = min(labels, key=len) if labels else anchor.get_text(" ", strip=True)
    return title, company, location, card.get_text(" ", strip=True)[:12000]


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
                try:
                    url = _alert_destination(anchor["href"])
                    if _alert_job_link(url):
                        title, company, location, context = _alert_anchor_metadata(anchor, url)
                        candidates.append((url, title, company, location, context))
                except ValueError:
                    continue
            body = soup.get_text(" ", strip=True)
        description_parts.append(str(body))
        candidates.extend(
            (match.rstrip(".,);]>\u201c\u201d"), "", "", "", "")
            for match in re.findall(r'https?://[^\s<>"\']+', str(body))
        )
    selected = {}
    for url, title, company, location, context in candidates:
        try:
            url = _alert_destination(url)
        except ValueError:
            continue
        if not _alert_job_link(url):
            continue
        url = _canonical_link(url)
        rank = (_alert_has_title(title), bool(company), bool(location), -len(title))
        if url not in selected or rank > selected[url][0]:
            selected[url] = (rank, title, company, location, context)
    jobs = []
    for url, (_, title, company, location, context) in selected.items():
        title, inferred_company = _alert_title_company(title, str(message.get("Subject", "")), url)
        jobs.append(
            _job(
                "email",
                url,
                title,
                company=company or inferred_company,
                location=location,
                description=context or "\n".join(description_parts)[:20000],
                description_missing=True,
                alert_metadata_version=1,
                alert_received_at=str(message.get("Date", "")),
                alert_subject=str(message.get("Subject", "")),
                alert_from=str(message.get("From", "")),
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
        "limit": max(1, min(int(config.get("limit", 100)), 500)),
        "lookback_days": max(1, min(int(config.get("lookback_days", 14)), 90)),
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


class EmailConnectionError(ValueError):
    """An inbox failure with a message suitable for the dashboard."""


def _read_email(config: dict, *, fetch_messages: bool) -> dict:
    host = config.get("host", "imap.gmail.com")
    try:
        _validate_host(host)
        password = keyring.get_password(_CREDENTIAL_SERVICE, _credential_account(config))
    except Exception as exc:
        raise EmailConnectionError(
            "JobPilot could not open your saved inbox connection. Reconnect Gmail in Email settings."
        ) from exc
    if not password:
        raise EmailConnectionError(
            "Add your Gmail address and a Google app password in Email settings, then test the connection."
        )
    jobs, checked, skipped, available = {}, 0, 0, 0
    try:
        with imaplib.IMAP4_SSL(host, 993, timeout=20) as inbox:
            try:
                inbox.login(config["username"], password)
            except imaplib.IMAP4.error as exc:
                raise EmailConnectionError(
                    "Gmail did not accept this connection. Save a Google app password, rather than your normal account password, and try again."
                ) from exc
            status, _ = inbox.select(config.get("mailbox", "INBOX"), readonly=True)
            if status != "OK":
                raise EmailConnectionError(
                    "JobPilot connected to your email account but could not open the selected folder. Choose INBOX in Email settings."
                )
            days = max(1, min(int(config.get("lookback_days", 14)), 90))
            since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
            status, result = inbox.uid("search", None, "SINCE", since)
            if status != "OK":
                raise EmailConnectionError(
                    "JobPilot connected to Gmail but could not list recent messages. Try Sync now again."
                )
            identifiers = (result[0] or b"").split()
            available = len(identifiers)
            limit = max(1, min(int(config.get("limit", 100)), 500))
            for identifier in identifiers[-limit:] if fetch_messages else []:
                status, parts = inbox.uid("fetch", identifier, "(BODY.PEEK[])")
                checked += 1
                if status != "OK":
                    skipped += 1
                    continue
                bodies = [
                    part[1]
                    for part in parts
                    if isinstance(part, tuple) and isinstance(part[1], bytes)
                ]
                if not bodies or any(len(body) > _MAX_BODY for body in bodies):
                    skipped += 1
                    continue
                for body in bodies:
                    try:
                        for job in import_eml(body):
                            jobs.setdefault(job["url"], job)
                    except (ValueError, TypeError, UnicodeError):
                        skipped += 1
    except EmailConnectionError:
        raise
    except Exception as exc:
        raise EmailConnectionError(
            "JobPilot could not reach your inbox. Check your internet connection, then try Sync now again."
        ) from exc
    return {
        "ok": True,
        "state": "connected",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "messages_available": available,
        "messages_checked": checked,
        "messages_skipped": skipped,
        "links_found": len(jobs),
        "truncated": fetch_messages and checked < available,
        "jobs": list(jobs.values()),
    }


def check_email_connection(config: dict) -> dict:
    return _email_scan(config, fetch_messages=False)


def sync_email(config: dict) -> dict:
    return _email_scan(config, fetch_messages=True)


def _email_scan(config: dict, *, fetch_messages: bool) -> dict:
    try:
        result = _read_email(config, fetch_messages=fetch_messages)
    except EmailConnectionError as exc:
        with _email_lock:
            _email_result.update(state="error", message=str(exc))
        raise
    summary = {key: value for key, value in result.items() if key != "jobs"}
    summary["message"] = (
        f"Checked {result['messages_checked']} recent messages and found {result['links_found']} job links."
        if fetch_messages
        else "Inbox connection verified. Use Sync now to import job alerts."
    )
    with _email_lock:
        _email_result.clear()
        _email_result.update(summary)
    return result


def get_last_email_result() -> dict:
    with _email_lock:
        return dict(_email_result)


def _imap_jobs(config: dict) -> list[dict]:
    return sync_email(config)["jobs"]


# A denied source is paused across scheduled scans; no proxy or challenge bypass.
_source_cooldowns: dict[str, float] = {}
_search_result: dict = {}


def _search_clock():
    import time

    return time.monotonic()


def _jobspy_search(**kwargs):
    from jobspy import scrape_jobs

    class WarningRecorder(logging.Handler):
        def emit(self, record):
            warning = {
                "source": record.name.partition(":")[2].lower(),
                "note": record.getMessage()[:300],
                "level": record.levelname.lower(),
            }
            with _errors_lock:
                if warning not in _search_warnings:
                    _search_warnings.append(warning)

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
    # Recent JobSpy versions also expose failures as dataframe metadata.
    for kind in ("errors", "warnings"):
        for source, notes in getattr(frame, "attrs", {}).get(kind, {}).items():
            for note in notes if isinstance(notes, list) else [notes]:
                warning = {
                    "source": str(source).lower(),
                    "note": str(note)[:300],
                    "level": "error" if kind == "errors" else "warning",
                }
                with _errors_lock:
                    if warning not in _search_warnings:
                        _search_warnings.append(warning)
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
    for row in rows:
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


def get_last_search_result() -> dict:
    """Coverage from the last bounded scan, separate from application decisions."""
    with _errors_lock:
        return json.loads(json.dumps(_search_result))


def discover(settings: dict, profile: dict) -> list[dict]:
    jobs, summaries, seen = [], {}, set()
    with _errors_lock:
        _search_warnings.clear()
    sources = settings.get("sources", ["linkedin", "indeed"])
    if isinstance(sources, str):
        sources = [sources] if sources != "both" else ["linkedin", "indeed"]
    titles = settings.get("search_titles") or settings.get("target_roles") or ["Security Engineer"]
    locations = settings.get("locations") or [settings.get("location", "Cincinnati, OH")]
    if isinstance(titles, str):
        titles = [titles]
    if isinstance(locations, str):
        locations = [locations]
    titles = list(dict.fromkeys(titles))[:8]
    locations = list(dict.fromkeys(locations))[:4]
    if settings.get("remote") and not any(str(value).casefold() == "remote" for value in locations):
        locations = [*locations[:3], "Remote"]
    # The quota applies to each role/location query, so the first role cannot
    # consume every later role's or remote search's allowance.
    limit = max(1, min(int(settings.get("results_per_source", 20)), 100))
    hours_old = max(1, min(int(settings.get("hours_old", 168)), 8760))

    def summary(source):
        return summaries.setdefault(
            source,
            {
                "source": source,
                "status": "ok",
                "checked": 0,
                "queries_attempted": 0,
                "queries_planned": 0,
                "descriptions_missing": 0,
                "message": "Search completed.",
            },
        )

    def add_job(job, state):
        if not job.get("url") or not job.get("title") or job["url"] in seen:
            return False
        seen.add(job["url"])
        jobs.append(job)
        state["checked"] += 1
        if not job.get("description"):
            state["descriptions_missing"] += 1
        return True

    for source in dict.fromkeys(sources):
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
        state = summary(source)
        state["queries_planned"] = len(titles) * len(locations)
        remaining = _source_cooldowns.get(source, 0) - _search_clock()
        if remaining > 0:
            state.update(
                status="blocked",
                retry_after_seconds=math.ceil(remaining),
                message="Source access is paused after a rate limit or access denial. Try again after the cooldown.",
            )
            continue
        stop_source = False
        for title in titles:
            for location in locations:
                remote = str(location).casefold() == "remote"
                try:
                    state["queries_attempted"] += 1
                    rows = _jobspy_search(
                        site_name=[source],
                        search_term=title,
                        location="USA"
                        if remote and source in ("indeed", "glassdoor")
                        else location,
                        is_remote=remote and source in ("indeed", "glassdoor"),
                        results_wanted=limit,
                        hours_old=hours_old,
                        # LinkedIn's public cards are useful without a burst of
                        # per-job detail requests, which have repeatedly hit 429.
                        fetch_description=source != "linkedin",
                        country_indeed="USA",
                        verbose=1,
                    )
                    query_found = 0
                    for row in rows:
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
                        job = _job(
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
                            is_remote=_text(row.get("is_remote")).casefold() in ("true", "1"),
                            requisition_id=_text(row.get("id")),
                            salary_min=row.get("min_amount")
                            if isinstance(row.get("min_amount"), (int, float))
                            and not math.isnan(row.get("min_amount"))
                            else None,
                        )
                        if add_job(job, state):
                            query_found += 1
                        if query_found >= limit:
                            break
                    with _errors_lock:
                        notices = [
                            dict(item) for item in _search_warnings if item["source"] == source
                        ]
                    warnings = [item["note"] for item in notices]
                    if warnings:
                        state.update(
                            status="partial",
                            message="Some source results or details could not be read.",
                            note=warnings[-1],
                        )
                        if not rows and any(item.get("level") == "error" for item in notices):
                            state.update(
                                status="error", message="The source search could not finish."
                            )
                            stop_source = True
                    if any(
                        re.search(r"\b(?:429|403)\b|captcha|access denied", note, re.I)
                        for note in warnings
                    ):
                        _source_cooldowns[source] = _search_clock() + 900
                        state.update(
                            status="blocked",
                            retry_after_seconds=900,
                            message="The source rate limited or denied access. Available listings were kept; further requests are paused for 15 minutes.",
                        )
                        stop_source = True
                except Exception as exc:
                    state.update(
                        status="error",
                        message="The source search could not finish.",
                        note=f"{type(exc).__name__}: {str(exc)[:240]}",
                    )
                    response = getattr(exc, "response", None)
                    if getattr(response, "status_code", None) in (403, 429):
                        retry = (getattr(response, "headers", {}) or {}).get("Retry-After", "900")
                        try:
                            delay = max(900, int(retry))
                        except (TypeError, ValueError):
                            from email.utils import parsedate_to_datetime

                            try:
                                retry_at = parsedate_to_datetime(str(retry))
                                delay = max(
                                    900,
                                    math.ceil(
                                        (retry_at - datetime.now(timezone.utc)).total_seconds()
                                    ),
                                )
                            except (TypeError, ValueError, OverflowError):
                                delay = 900
                        _source_cooldowns[source] = _search_clock() + delay
                        state.update(status="blocked", retry_after_seconds=delay)
                    stop_source = True
                if stop_source:
                    break
            if stop_source:
                break
        if state["descriptions_missing"] and state["status"] == "ok":
            state.update(
                status="partial",
                message="Listings found; some descriptions require review on the job page.",
            )
        if source == "linkedin":
            state["details_mode"] = "listing_cards"
    for board in list(settings.get("ats_boards", []))[:30]:
        source = str(board.get("source", "ats")).lower()
        state = summary(source)
        state["queries_planned"] += 1
        state["queries_attempted"] += 1
        try:
            for job in _board_jobs(source, str(board["board"])):
                add_job(job, state)
        except Exception as exc:
            state.update(
                status="error",
                message="An employer board could not be read.",
                note=f"{type(exc).__name__}: {str(exc)[:240]}",
            )
    email_config = settings.get("email") or {}
    if email_config.get("enabled"):
        state = summary("email")
        try:
            for job in _imap_jobs(email_config):
                add_job(job, state)
        except Exception as exc:
            state.update(
                status="error",
                message="Email job alerts could not be read.",
                note=f"{type(exc).__name__}: {str(exc)[:240]}",
            )
    with _errors_lock:
        _errors[:] = [
            dict(state, note=state.get("note") or state["message"])
            for state in summaries.values()
            if state["status"] in ("error", "blocked")
        ]
        _search_result.clear()
        _search_result.update(
            sources=list(summaries.values()), completed_at=datetime.now(timezone.utc).isoformat()
        )
    return jobs
