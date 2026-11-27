"""Bounded job discovery, public employer listings and read-only email alerts.

No credentials are accepted in URLs, and every fetch/redirect is checked before
connecting. Email receipt dates are never treated as job posting dates.
"""

from __future__ import annotations

import email
import html
import imaplib
import ipaddress
import json
import logging
import math
import re
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email import policy
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import certifi
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
GREENHOUSE_BATCH_SIZE = 1000


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
    deadline = time.monotonic() + 30
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(5):
            url = validate_public_url(url)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Public posting lookup timed out")
            cap = (
                32 * 1024 * 1024
                if urlsplit(url).hostname
                in ("boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com")
                else _MAX_BODY
            )
            with session.get(
                url,
                allow_redirects=False,
                timeout=(min(6, remaining), min(20, remaining)),
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
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Public posting lookup timed out")
                    size += len(chunk)
                    if size > cap:
                        raise ValueError("Job page exceeds the download limit")
                    chunks.append(chunk)
                return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace"), url
    raise ValueError("Too many job-page redirects")


def _text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = html.unescape(html.unescape(str(value)))
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


def _description(value) -> str:
    source = html.unescape(str(value or ""))
    if not re.search(r"<[a-z][^>]*>", source, re.I):
        return source.strip()
    soup = BeautifulSoup(source, "html.parser")
    for tag in soup(["script", "style", "img"]):
        tag.decompose()
    for block in soup(["p", "li", "br", "h1", "h2", "h3", "h4", "div"]):
        block.append("\n")
    return "\n".join(
        cleaned for line in soup.get_text().splitlines() if (cleaned := " ".join(line.split()))
    )


def _canonical_link(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
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
        "description": _description(description)[:120000],
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
    postings = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            postings.extend(_jsonld_postings(json.loads(script.get_text())))
        except (ValueError, TypeError):
            continue
    if len(postings) > 1:
        postings = [
            item
            for item in postings
            if isinstance(item.get("url"), str)
            and _canonical_link(urljoin(final_url, item["url"])) == _canonical_link(final_url)
        ]
    if len(postings) == 1:
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
        remote = "TELECOMMUTE" in (posting.get("jobLocationType") or [])
        if remote:
            labels.insert(0, "Remote")
            regions = posting.get("applicantLocationRequirements") or []
            if isinstance(regions, dict):
                regions = [regions]
            labels.extend(
                str(region["name"])
                for region in regions
                if isinstance(region, dict) and region.get("name")
            )
        return _job(
            "employer",
            final_url,
            posting.get("title", ""),
            company,
            "; ".join(labels),
            posting.get("description", ""),
            posting.get("datePosted"),
            is_remote=remote,
            valid_through=_date(posting.get("validThrough")),
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
            return any(parse_qs(parts.query).get(key) for key in ("jk", "vjk"))
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
    if not _alert_job_link(url):
        return url
    # Do not send recipient IDs or tracking parameters from an email to a
    # public careers site. Keep only the parameters that identify the job.
    parts = urlsplit(_canonical_link(url))
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if key.casefold() in {"jk", "vjk", "gh_jid", "jobid", "job_id", "requisitionid"}
        and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value)
    ]
    host = parts.hostname or ""
    if host == "indeed.com" or host.endswith(".indeed.com"):
        ids = {key.casefold(): value for key, value in query}
        if key := ids.get("jk") or ids.get("vjk"):
            return urlunsplit(("https", "www.indeed.com", "/viewjob", urlencode({"jk": key}), ""))
    return urlunsplit(parts._replace(query=urlencode(query), fragment=""))


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
        title_source = "card" if _alert_has_title(title) else "subject"
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
                alert_title_source=title_source,
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
    mailbox = str(config.get("mailbox") or "INBOX").strip()
    if not 1 <= len(mailbox) <= 128 or any(ord(c) < 32 for c in mailbox):
        raise ValueError("Choose a valid IMAP folder name")
    safe = {
        "host": host,
        "port": 993,
        "username": username,
        "enabled": bool(config.get("enabled", False)),
        "mailbox": mailbox,
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


def _looks_like_job_alert(raw_headers: bytes) -> bool:
    headers = email.message_from_bytes(raw_headers, policy=policy.default)
    subject = str(headers.get("Subject", ""))
    return bool(
        re.search(
            r"\bjob (?:alerts?|recommendations?|digest)\b|\b(?:new|recommended|matching|similar) jobs?\b"
            r"|\bjobs (?:for you|matching|you may like)\b"
            r"|\b(?:engineer|analyst|developer|security|devops) jobs? (?:in|near|at)\b"
            r"|\b(?:engineer|analyst|developer|specialist|manager|officer|architect|"
            r"coordinator|technician|administrator|director|scientist|consultant)\b.{0,90}\bat\b",
            subject,
            re.I,
        )
    )


def _imap_bytes(parts):
    return next(
        (part[1] for part in parts if isinstance(part, tuple) and isinstance(part[1], bytes)),
        None,
    )


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
    jobs, checked, skipped, non_alerts = {}, 0, 0, 0
    checkpoint = None
    interrupted = False
    try:
        with imaplib.IMAP4_SSL(
            host, 993, ssl_context=ssl.create_default_context(cafile=certifi.where()), timeout=20
        ) as inbox:
            try:
                inbox.login(config["username"], password)
            except imaplib.IMAP4.error as exc:
                raise EmailConnectionError(
                    "Gmail did not accept this connection. Save a Google app password, rather than your normal account password, and try again."
                ) from exc
            mailbox = config.get("mailbox", "INBOX")
            # IMAP folder names containing spaces are quoted strings.
            folder = (
                mailbox
                if mailbox.upper() == "INBOX"
                else ('"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"')
            )
            status, _ = inbox.select(folder, readonly=True)
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
            identifiers = sorted({int(uid) for uid in (result[0] or b"").split() if uid.isdigit()})
            # A UID is meaningful only within this mailbox's UIDVALIDITY.
            response = inbox.response("UIDVALIDITY")[1] if hasattr(inbox, "response") else []
            validity = next((int(item) for item in response or [] if item and item.isdigit()), None)
            previous = config.get("checkpoint") or {}
            last_uid = previous.get("uid", 0) if validity == previous.get("validity") else 0
            identifiers = [uid for uid in identifiers if not validity or uid > last_uid]
            available = len(identifiers)
            limit = max(1, min(int(config.get("limit", 100)), 500))
            deadline = time.monotonic() + 60
            for uid in identifiers[:limit] if fetch_messages else []:
                if time.monotonic() >= deadline:
                    break
                if mailbox.upper() == "INBOX":
                    status, parts = inbox.uid(
                        "fetch", str(uid), "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])"
                    )
                    headers = _imap_bytes(parts)
                    if status != "OK" or headers is None:
                        interrupted = True
                        break
                    if not _looks_like_job_alert(headers):
                        checked += 1
                        non_alerts += 1
                        checkpoint = {"validity": validity, "uid": uid} if validity else None
                        continue
                status, parts = inbox.uid("fetch", str(uid), f"(BODY.PEEK[]<0.{_MAX_BODY + 1}>)")
                body = _imap_bytes(parts)
                if status != "OK" or body is None:
                    interrupted = True
                    break
                checked += 1
                checkpoint = {"validity": validity, "uid": uid} if validity else None
                if len(body) > _MAX_BODY:
                    skipped += 1
                    continue
                try:
                    for job in import_eml(body):
                        # Keep the alert identity and card metadata, not the
                        # contents of a digest or unrelated application email.
                        job["description"] = " · ".join(
                            job[key] for key in ("title", "company", "location") if job.get(key)
                        )
                        jobs[job["url"]] = job
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
        "non_alerts": non_alerts,
        "checkpoint": checkpoint,
        "scan_interrupted": interrupted,
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
    summary = {key: value for key, value in result.items() if key not in {"jobs", "checkpoint"}}
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
                row.get("company_name") or board,
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


def greenhouse_boards() -> list[str]:
    """Bundled public board directory; all postings still come from Greenhouse."""
    path = Path(__file__).with_name("greenhouse_boards.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _greenhouse_slug(url: str) -> str | None:
    parts = urlsplit(str(url or ""))
    if (parts.hostname or "").lower() not in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
        return None
    slug = parts.path.strip("/").split("/")[0]
    return slug.lower() if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", slug) else None


def _greenhouse_catalog_board(board: str, profile: dict, settings: dict) -> tuple[list[dict], bool]:
    from .core import parse_date, role_assessment

    base = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    try:
        body, _ = _get_public(base)
        rows = json.loads(body).get("jobs", [])
    except Exception:
        return [], False
    jobs = []
    for row in rows:
        if row.get("internal_job_id") is None or not row.get("id"):
            continue
        if role_assessment(row, profile, settings)[0] == "excluded":
            continue
        published = parse_date(row.get("first_published"))
        if published and datetime.now(timezone.utc) - published > timedelta(days=90):
            continue
        try:
            detail, _ = _get_public(f"{base}/{row['id']}")
            item = json.loads(detail)
            job = _job(
                "greenhouse",
                item.get("absolute_url") or row.get("absolute_url", ""),
                item.get("title") or row.get("title", ""),
                item.get("company_name") or row.get("company_name") or board,
                (item.get("location") or row.get("location") or {}).get("name", ""),
                item.get("content", ""),
                item.get("first_published") or row.get("first_published"),
                requisition_id=str(row["id"]),
            )
            if job["url"] and job["title"]:
                jobs.append(job)
        except Exception:
            continue
    return jobs, True


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
    sources = settings.get("sources", ["indeed"])
    if isinstance(sources, str):
        sources = [sources] if sources != "both" else ["linkedin", "indeed"]
    titles = settings.get("search_titles") or settings.get("target_roles") or ["Security Engineer"]
    locations = settings.get("locations") or [settings.get("location", "Cincinnati, OH")]
    if isinstance(titles, str):
        titles = [titles]
    if isinstance(locations, str):
        locations = [locations]
    all_titles = list(dict.fromkeys(titles))
    try:
        title_cursor = int(settings.get("_search_title_cursor", 0)) % len(all_titles)
    except (TypeError, ValueError, ZeroDivisionError):
        title_cursor = 0
    titles = [
        all_titles[(title_cursor + index) % len(all_titles)]
        for index in range(min(8, len(all_titles)))
    ]
    next_title_cursor = (title_cursor + len(titles)) % len(all_titles) if all_titles else 0
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

    greenhouse_next_cursor = None
    greenhouse_total_boards = 0
    if settings.get("greenhouse_discovery"):
        boards = list(
            dict.fromkeys(
                [
                    *greenhouse_boards(),
                    *(
                        slug
                        for slug in settings.get("_greenhouse_learned_boards", [])
                        if isinstance(slug, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", slug)
                    ),
                ]
            )
        )
        greenhouse_total_boards = len(boards)
        if boards:
            state = summary("greenhouse")
            try:
                cursor = int(settings.get("_greenhouse_cursor", 0)) % len(boards)
            except (TypeError, ValueError):
                cursor = 0
            count = min(GREENHOUSE_BATCH_SIZE, len(boards))
            batch = [boards[(cursor + index) % len(boards)] for index in range(count)]
            state["queries_planned"] += count
            state["catalog_boards_checked"] = count
            state["catalog_total_boards"] = len(boards)
            failed = 0
            with ThreadPoolExecutor(max_workers=8) as pool:
                for found, ok in pool.map(
                    lambda board: _greenhouse_catalog_board(board, profile, settings), batch
                ):
                    state["queries_attempted"] += 1
                    if not ok:
                        failed += 1
                    for job in found:
                        add_job(job, state)
            greenhouse_next_cursor = (cursor + count) % len(boards)
            state["catalog_boards_failed"] = failed
            state["message"] = (
                f"Checked {count} of {len(boards)} Greenhouse employer boards this pass"
                + (f"; {failed} could not be read." if failed else ".")
            )
            if failed >= max(10, count // 10) and state["status"] == "ok":
                state.update(
                    status="partial",
                    message=f"Checked {count - failed} of {count} Greenhouse boards; several boards could not be read.",
                )

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
    with _errors_lock:
        _errors[:] = [
            dict(state, note=state.get("note") or state["message"])
            for state in summaries.values()
            if state["status"] in ("error", "blocked")
        ]
        _search_result.clear()
        _search_result.update(
            sources=list(summaries.values()),
            completed_at=datetime.now(timezone.utc).isoformat(),
            greenhouse_next_cursor=greenhouse_next_cursor,
            greenhouse_total_boards=greenhouse_total_boards,
            search_title_next_cursor=next_title_cursor,
            greenhouse_learned_boards=sorted(
                {
                    slug
                    for job in jobs
                    for key in ("url", "source_url", "apply_url")
                    if (slug := _greenhouse_slug(job.get(key)))
                }
            ),
        )
    return jobs
