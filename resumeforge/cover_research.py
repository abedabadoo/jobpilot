"""Bounded public-source research for a single, explicitly requested letter."""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from datetime import date
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

import certifi

_ARTICLE = {"Article", "NewsArticle", "BlogPosting", "PressRelease"}
_NEWS = re.compile(r"\b(newsroom|news|press releases?|announcements?|blog|insights)\b", re.I)
_BAD_LINK = re.compile(r"\b(sign in|sign up|subscribe|privacy|terms|careers|jobs|about us)\b", re.I)
_STOP = set("this that with from will have team role work their company skills experience years about using "
            "more other and the for are support based within including position professional solutions".split())


def _public_url(url, *, posting=False, directory=False):
    parts = urlsplit(url.strip())
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.port not in (None, 443) or len(url) > 1800):
        raise ValueError("Use a public HTTPS webpage.")
    keys = {"jk", "vjk", "gh_jid", "jobid", "job_id", "requisitionid"}
    params = [(k, v) for k, v in parse_qsl(parts.query)
              if posting and k.casefold() in keys and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v)]
    if directory and parts.hostname == "www.wikidata.org" and parts.path == "/w/api.php":
        params = [(k, v[:180]) for k, v in parse_qsl(parts.query)
                  if k in {"action", "search", "language", "format", "limit", "entity", "property"}]
    return parts._replace(query=urlencode(params), fragment="").geturl()


class _PublicConnection(http.client.HTTPSConnection):
    def connect(self):
        # Pin the checked public address for this connection. TLS still
        # validates the original hostname and sends the server-name indication.
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("The research address is outside the public internet.")
        last = None
        for item in addresses[:3]:
            try:
                raw = socket.create_connection((item[4][0], 443), timeout=self.timeout)
                with raw:
                    self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                return
            except OSError as exc:
                last = exc
        raise OSError("Could not reach the public source.") from last


def _read_page(url, deadline, *, posting=False, domain=None, directory=False):
    for _ in range(3):
        current = _public_url(url, posting=posting, directory=directory)
        parts = urlsplit(current)
        if domain and not _on_domain(parts.hostname, domain):
            raise ValueError("The article redirected away from the confirmed employer domain.")
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise TimeoutError("Company research reached its time limit.")
        origin = _PublicConnection(parts.hostname, timeout=min(4, budget),
                                   context=ssl.create_default_context(cafile=certifi.where()))
        try:
            # The request carries no browser cookies, credentials, referrer or applicant data.
            route = parts.path or "/"
            if parts.query:
                route += "?" + parts.query
            content_type = "application/json" if directory else "text/html"
            origin.request("GET", route, headers={"User-Agent": "ResumeForge/1.0 public research",
                                                   "Accept": content_type})
            with origin.getresponse() as reply:
                if reply.status in (301, 302, 303, 307, 308):
                    url = urljoin(current, reply.getheader("Location", ""))
                    continue
                if reply.status != 200 or content_type not in reply.getheader("Content-Type", "").lower():
                    raise ValueError("The public source did not return the expected content type.")
                body = bytearray()
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Company research reached its time limit.")
                    chunk = reply.read1(32 * 1024)
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError("The public source is too large.")
                decoded = body.decode("utf-8", errors="replace")
                return (json.loads(decoded) if directory else _parse(decoded)), current
        finally:
            origin.close()
    raise ValueError("The public source redirected too many times.")


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.links = []
        self.records = []
        self.text = []
        self._script = None
        self._link = None
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("content"):
            self.meta[attrs.get("property") or attrs.get("name") or ""] = attrs["content"]
        if tag == "script":
            self._script = [] if attrs.get("type") == "application/ld+json" else None
        if tag in {"script", "style"}:
            self._hidden += 1
        if tag == "a" and attrs.get("href"):
            self._link = (attrs["href"], [])

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._hidden = max(0, self._hidden - 1)
        if tag == "script" and self._script is not None:
            try:
                self.records.extend(_records(json.loads("".join(self._script))))
            except (ValueError, RecursionError):
                pass
            self._script = None
        if tag == "a" and self._link:
            url, label = self._link
            self.links.append((url, " ".join(label).strip()))
            self._link = None

    def handle_data(self, data):
        value = data.strip()
        if self._script is not None:
            self._script.append(data)
        if self._hidden or not value:
            return
        self.text.append(value)
        if self._link:
            self._link[1].append(value)


def _records(value):
    if isinstance(value, list):
        for item in value:
            yield from _records(item)
    elif isinstance(value, dict):
        if "@type" in value:
            yield value
        for item in value.values():
            if isinstance(item, (dict, list)):
                yield from _records(item)


def _parse(html):
    page = _Page()
    page.feed(html)
    page.close()
    return page


def _types(item):
    type_ = item.get("@type", [])
    return {str(v).rsplit("/", 1)[-1] for v in (type_ if isinstance(type_, list) else [type_])}


def _on_domain(host, domain):
    return bool(host and (host == domain or host.endswith("." + domain)))


def _words(text):
    return {w for w in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()) if w not in _STOP}


def _employer_domain(url, company):
    host = urlsplit(url).hostname or ""
    labels = host.split(".")
    pos = -3 if ".".join(labels[-2:]) in {"co.uk", "com.au", "co.jp", "co.in"} else -2
    if len(labels) < -pos:
        return ""
    name = re.sub(r"[^a-z0-9]", "", labels[pos])
    company_name = re.sub(r"[^a-z0-9]", "", company.casefold())
    if len(name) < 3 or not (company_name == name or company_name.startswith(name + "inc")
                               or company_name.startswith(name + "corp") or company_name.startswith(name + "group")):
        return ""
    return ".".join(labels[pos:])


def _company_link(page, url, company):
    for record in page.records:
        if "JobPosting" in _types(record):
            org = record.get("hiringOrganization")
            if isinstance(org, dict):
                candidate = org.get("sameAs") or org.get("url")
                if isinstance(candidate, str) and _employer_domain(candidate, company):
                    return candidate
    return next((candidate for href, _ in page.links
                 if _employer_domain(candidate := urljoin(url, href), company)), "")


def _directory_website(company, deadline):
    """Use the public company name alone to discover a uniquely named official website."""
    host = "www.wikidata.org"

    def lookup(**query):
        url = f"https://{host}/w/api.php?" + urlencode({"format": "json", **query})
        return _read_page(url, deadline, domain=host, directory=True)[0]

    def normalized(name):
        return re.sub(r"[^a-z0-9]", "", name.casefold())

    try:
        search = lookup(action="wbsearchentities", search=company, language="en", limit=6)
        exact = {item["id"] for item in search.get("search", [])
                 if re.fullmatch(r"Q[1-9][0-9]{0,12}", item.get("id", ""))
                 and normalized(company) in {normalized(name) for name in
                                             [item.get("label", ""), *item.get("aliases", [])]}
                 and not re.search(r"\b(library|software package|disambiguation|brand of clothing)\b",
                                   item.get("description", ""), re.I)}
        if len(exact) != 1:
            return ""
        record = lookup(action="wbgetclaims", entity=exact.pop(), property="P856")
        urls = [_public_url(statement["mainsnak"]["datavalue"]["value"])
                for statement in record.get("claims", {}).get("P856", [])
                if statement.get("rank") != "deprecated"]
        sites = {urlsplit(url).hostname.removeprefix("www.") for url in urls}
        return urls[0] if len(sites) == 1 else ""
    except (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException):
        return ""


def _source(page, url, focus, today):
    for item in page.records:
        if _types(item) & _ARTICLE:
            title = str(item.get("headline") or page.meta.get("og:title") or "").strip()
            excerpt = str(item.get("description") or page.meta.get("og:description") or "").strip()
            article = str(item.get("articleBody") or "")
            if article:
                excerpt = (excerpt + " " + " ".join(article.split())[:700]).strip()
            published = str(item.get("datePublished") or page.meta.get("article:published_time") or "")
            break
    else:
        if page.meta.get("og:type") != "article":
            return None
        title = page.meta.get("og:title", "").strip()
        excerpt = page.meta.get("og:description", "").strip()
        published = page.meta.get("article:published_time", "")
    if len(excerpt) < 40 or not title:
        return None
    shared = _words(title + " " + excerpt) & focus
    if len(shared) < 2:
        return None
    try:
        published_on = date.fromisoformat(published[:10])
        age = (today - published_on).days
        published = published_on.isoformat() if age >= 0 else ""
    except ValueError:
        age, published = 1000, ""
    return (len(shared) + (3 if 0 <= age <= 180 else 0),
            {"url": url, "title": title[:200], "published": published, "excerpt": excerpt[:950]})


def research(company, description, posting_url="", company_url=""):
    deadline = time.monotonic() + 18
    hiring_manager = None
    homepage = company_url
    if posting_url:
        try:
            page, url = _read_page(posting_url, deadline, posting=True)
            # Use only an explicit recruiting label on the supplied job posting.
            names = {match.group(1) for line in page.text for match in re.finditer(
                r"^(?:Hiring [Mm]anager|Recruiter):\s*([A-Z][a-z'’-]+(?: [A-Z][a-z'’-]+){1,3})\s*$", line)}
            if len(names) == 1:
                hiring_manager = {"name": names.pop(), "url": url}
            if not homepage:
                homepage = _company_link(page, url, company)
                if not homepage and _employer_domain(url, company):
                    homepage = urljoin(url, "/")
        except (OSError, ValueError, http.client.HTTPException):
            pass
    if not homepage and time.monotonic() < deadline:
        homepage = _directory_website(company, deadline)
    results = []
    try:
        if homepage:
            candidate = _public_url(homepage)
            domain = _employer_domain(candidate, company) or urlsplit(candidate).hostname.removeprefix("www.")
            queue, seen = [candidate], set()
            focus = _words(description[:18000])
            for depth in range(6):
                if not queue or time.monotonic() >= deadline:
                    break
                link = queue.pop(0)
                if link in seen:
                    continue
                seen.add(link)
                try:
                    page, url = _read_page(link, deadline, domain=domain)
                except (OSError, ValueError, http.client.HTTPException):
                    continue
                if item := _source(page, url, focus, date.today()):
                    results.append(item)
                elif depth < 3:
                    links = []
                    for href, label in page.links:
                        join = urljoin(url, href)
                        if _on_domain(urlsplit(join).hostname, domain) and not _BAD_LINK.search(label):
                            relevance = len(_words(label) & focus)
                            newsroom = depth == 0 and bool(_NEWS.search(label))
                            if newsroom or relevance >= 2:
                                links.append((relevance + (2 if newsroom else 0), join))
                    queue = list(dict.fromkeys(link for _, link in sorted(links, reverse=True)[:8])) + queue
    except (OSError, ValueError, http.client.HTTPException):
        pass
    sources = [source for _, source in sorted(results, key=lambda item: item[0], reverse=True)[:2]]
    return {"sources": sources, "hiring_manager": hiring_manager,
            "message": ("Company sources verified for this posting." if sources
                        else "No relevant company source could be verified. The draft uses the job posting."),
            "company_url": company_url}
