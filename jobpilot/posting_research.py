"""Read the exact public posting behind an inbox alert."""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

from . import collectors


class PostingClosed(ValueError):
    """An official listing is no longer open."""


def _ats_detail(url, company):
    parts = urlsplit(url)
    host = parts.hostname
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        match = re.fullmatch(r"/([\w-]{1,100})/(?:jobs/)?(\d{1,20})/?", parts.path, re.ASCII)
        api_host, route = "boards-api.greenhouse.io", "/v1/boards/{}/jobs/{}?pay_transparency=true"
    elif host in {"jobs.lever.co", "jobs.eu.lever.co"}:
        match = re.fullmatch(
            r"/([\w-]{1,100})/([0-9a-f-]{36})(?:/apply)?/?", parts.path, re.IGNORECASE | re.ASCII
        )
        api_host = "api.eu.lever.co" if host == "jobs.eu.lever.co" else "api.lever.co"
        route = "/v0/postings/{}/{}?mode=json"
    else:
        return None
    if not match:
        return None
    board, identity = match.groups()
    endpoint = f"https://{api_host}" + route.format(board, identity)
    try:
        body, final = collectors._get_public(endpoint)
    except requests.HTTPError as exc:
        response = exc.response
        if (
            response is not None
            and response.status_code in (404, 410)
            and (urlsplit(response.url).hostname == api_host)
        ):
            raise PostingClosed("The employer's job board no longer lists this posting.") from exc
        raise
    if urlsplit(final).hostname != api_host:
        return None
    record = json.loads(body)
    if not isinstance(record, dict) or str(record.get("id")) != identity:
        return None
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        return collectors._job(
            "greenhouse",
            url,
            record.get("title"),
            record.get("company_name") or company,
            (record.get("location") or {}).get("name"),
            record.get("content"),
            record.get("first_published"),
            requisition_id=str(record.get("requisition_id") or identity),
        )
    location = (record.get("categories") or {}).get("location") or ""
    remote = record.get("workplaceType") == "remote"
    sections = [
        f"{section.get('text', '')}\n{collectors._description(section.get('content'))}"
        for section in record.get("lists", [])
        if isinstance(section, dict)
    ]
    description = "\n\n".join(
        filter(
            None,
            [
                record.get("descriptionPlain")
                or collectors._description(record.get("description")),
                *sections,
                record.get("additionalPlain"),
            ],
        )
    )
    return collectors._job(
        "lever",
        url,
        record.get("text"),
        company,
        "; ".join(filter(None, ["Remote" if remote else "", location])),
        description,
        record.get("createdAt"),
        requisition_id=identity,
        is_remote=remote,
    )


def research_posting(alert):
    """Return researched fields and their source, or explain why they are unavailable."""
    original = alert["url"]
    url = collectors._alert_destination(original)
    if not collectors._alert_job_link(url):
        raise ValueError("The alert has no direct public posting link.")
    primary = None
    try:
        primary = _ats_detail(url, alert.get("company", ""))
    except (requests.RequestException, ValueError) as exc:
        if isinstance(exc, PostingClosed):
            raise
        # Some employers disable their public API. Try the posting page.
    details = (
        primary if primary and len(primary["description"]) >= 80 else collectors.fetch_job(url)
    )
    if details.get("posting_closed"):
        raise PostingClosed("The public posting is no longer accepting applications.")
    if details.get("needs_description_review") or len(str(details.get("description") or "")) < 80:
        raise ValueError("The public link did not provide a full job posting.")
    expiry = details.get("valid_through")
    if expiry:
        try:
            deadline = datetime.fromisoformat(expiry)
        except (TypeError, ValueError):
            deadline = None
        if deadline:
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if deadline < datetime.now(timezone.utc):
                raise PostingClosed("The public posting has passed its published closing date.")
    company = details.get("company") or alert.get("company")
    if not company or not details.get("title"):
        raise ValueError("The public posting did not identify the role and employer.")
    final_url = collectors._alert_destination(details.get("url") or url)
    if not collectors._alert_job_link(final_url):
        # The published destination may be a custom route. Use the safe,
        # canonical alert link for navigation and retain the sourced details.
        final_url = url
    return {
        **details,
        "company": company,
        "url": url,
        "apply_url": final_url,
        "source_url": original if original != url else "",
        "source": "email",
        "description_missing": False,
        "posting_source": primary["source"] if details is primary else "job posting",
    }
