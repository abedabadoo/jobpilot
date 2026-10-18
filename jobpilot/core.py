import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
BUCKET_LABELS = [
    "Posted today",
    "Previous 24 hours",
    "Previous 3 days",
    "Previous 7 days",
    "Older than 7 days",
    "Date unknown",
]


def parse_date(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return d.replace(tzinfo=TZ) if d.tzinfo is None else d
    except (ValueError, TypeError, OverflowError):
        return None


def freshness(value, now=None):
    now = now or datetime.now(timezone.utc)
    date = parse_date(value)
    if date is None or date > now:
        return 5
    age = (now - date).total_seconds()
    if date.astimezone(TZ).date() == now.astimezone(TZ).date():
        return 0
    for index, seconds in [(1, 86400), (2, 259200), (3, 604800)]:
        if age <= seconds:
            return index
    return 4


def canonical_url(value):
    parts = urlsplit(str(value).strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.port and parts.port not in [80, 443]:
        host += f":{parts.port}"
    path = re.sub("/+", "/", parts.path).rstrip("/") or "/"
    tracking = {
        "trk",
        "trackingid",
        "ref",
        "refid",
        "source",
        "gh_src",
        "lever-source",
        "from",
        "vjk",
    }
    args = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query)
        if not k.lower().startswith("utm_") and k.lower() not in tracking
    )
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(args), ""))


def rank_key(job):
    date = parse_date(job.get("posted_at"))
    return (
        freshness(job.get("posted_at")),
        -float(job.get("fit", 0)),
        -(date.timestamp() if date else 0),
        job.get("id", 0),
    )


def _normal_title(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _documented_years(profile):
    """A dated career-span upper bound, not a claim of qualified experience."""
    intervals = []
    for entry in profile.get("experience", []):
        dates = []
        for key in ["start", "end"]:
            value = str(entry.get(key, "")).strip()
            date = None
            if key == "end" and value.lower() in ["present", "current"]:
                date = datetime.now(TZ)
            else:
                for fmt in ["%B %Y", "%b %Y", "%Y-%m", "%Y-%m-%d"]:
                    try:
                        date = datetime.strptime(value, fmt)
                        break
                    except ValueError:
                        pass
            if date is None:
                return None
            dates.append(date.year * 12 + date.month - 1)
        if dates[1] < dates[0]:
            return None
        # Inclusive end month gives a conservative upper bound for month-only dates.
        intervals.append((dates[0], dates[1] + 1))
    if not intervals:
        return None
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged) / 12


def _required_years(description):
    requirements = []
    pattern = r"\b(\d+(?:\.\d+)?)\s*(?:\+|[-–]\s*\d+)?\s*(?:years?|yrs?)\s+(?:of\s+)?[^.;\n]{0,100}?\bexperience\b"
    for match in re.finditer(pattern, str(description).lower()):
        prefix = re.split(
            r"[.;\n]", str(description).lower()[max(0, match.start() - 90) : match.start()]
        )[-1]
        if re.search(
            r"\b(preferred|desired|bonus|nice to have|optional)\b", prefix + match.group()
        ):
            continue
        if re.search(r"\b(?:our|the)\s+(?:company|business|team)\b", prefix):
            continue
        requirements.append(float(match.group(1)))
    return max(requirements) if requirements else None


def role_assessment(job, profile, settings):
    """Gate role intent and explain experience gaps without blocking stretches."""
    title = _normal_title(job.get("title"))
    targets = settings.get("target_roles", settings.get("search_titles", []))
    if isinstance(targets, str):
        targets = [targets]
    explicit = any(title == _normal_title(target) for target in targets if target)
    commercial = re.search(
        r"\b(sales|presales|pre sales|channels?|account executive|account manager|business development|customer success|marketing)\b",
        title,
    )
    if commercial and not explicit:
        return (
            "excluded",
            "Commercial sales or channel role is outside the configured security career targets.",
        )
    security = re.search(r"\b(security|cybersecurity|cyber|infosec|grc|compliance)\b", title)
    ordinary = security and re.search(r"\b(engineer|analyst|specialist|auditor)\b", title)
    if not ordinary and not explicit:
        return (
            "excluded",
            "Role is outside the configured security engineering, analysis and compliance targets.",
        )
    required = _required_years(job.get("description", ""))
    if required is not None:
        documented = _documented_years(profile)
        if documented is None:
            return (
                "eligible",
                "Experience comparison is unavailable because career dates are unknown or incomplete.",
            )
        if required > documented:
            return (
                "eligible",
                f"Experience stretch: the role requests {required:g}+ years; the dated career history spans at most approximately {documented:.1f} years.",
            )
    return "eligible", ""


def score_job(job, profile, settings):
    title = str(job.get("title", "")).lower()
    text = (title + " " + str(job.get("description", ""))).lower()
    roles = settings.get("target_roles", settings.get("search_titles", []))
    relevant = any(
        word in title
        for word in ["security", "cyber", "infosec", "grc", "compliance", "soc analyst"]
    )
    title_score = 45 if any(str(r).lower() in title for r in roles) else (30 if relevant else 0)
    skills = profile.get("skills", [])
    matches = sum(str(s).lower() in text for s in skills)
    skill_score = min(40, matches * 5)
    seniority = 5 if re.search(r"\b(principal|director|vice president|staff)\b", title) else 15
    return min(100, title_score + skill_score + (seniority if relevant else 0))


_US_STATES = dict(
    zip(
        "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split(),
        "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia".split(
            "|"
        ),
    )
)


def _states_in_location(value):
    # Abbreviations must be complete comma/semicolon-separated location tokens;
    # words such as "in" and "or" are not state abbreviations.
    tokens = {part.strip().upper() for part in re.split(r"[,;()]", value)}
    return {
        code
        for code, name in _US_STATES.items()
        if code in tokens or re.search(r"\b" + re.escape(name) + r"\b", value, re.I)
    }


def eligibility(job, settings):
    """Apply known geographic preferences without guessing remote eligibility."""
    location = str(job.get("location", "")).lower()
    city = str(settings.get("location", "Cincinnati, OH")).split(",")[0].strip().lower()
    if city and city in location:
        return "eligible", ""
    remote = bool(job.get("is_remote")) or "remote" in location
    if remote and settings.get("remote"):
        configured_states = _states_in_location(str(settings.get("location", "Cincinnati, OH")))
        if "OH" in configured_states:
            state, name = "OH", "Ohio"
            if re.search(
                r"\b(?:except|excluding|not available in|not eligible in)\s+(?:"
                + re.escape(name)
                + "|"
                + state
                + r")\b",
                location,
                re.I,
            ):
                return "excluded", f"The listed remote location excludes {name}."
            remote_parts = [
                part.strip()
                for part in str(job.get("location", "")).split(";")
                if "remote" in part.lower()
            ]
            state_sets = [_states_in_location(part) for part in remote_parts]
            # A generic "Remote - USA" entry keeps nationwide eligibility.
            # Only a list of named remote states establishes this restriction.
            if (
                state_sets
                and all(state_sets)
                and all(
                    re.search(r"\b(?:us|usa|united states)\b", part, re.I) for part in remote_parts
                )
            ):
                allowed = set().union(*state_sets)
                if state not in allowed:
                    return "excluded", f"The listed remote hiring states do not include {name}."
        if re.search(r"\b(us|usa|united states|u\.?s\.?a?\.?|north america)\b", location):
            return "eligible", ""
        return (
            "review",
            "Remote location eligibility is not established for USA; verify the employer requirements.",
        )
    if not location:
        return "review", "Job location is unknown; verify eligibility before applying."
    return "excluded", "Location does not match the configured city or remote USA preference."


def facts_map(profile):
    return {
        f["id"]: f["text"]
        for e in profile.get("experience", [])
        for f in e.get("facts", [])
        if f.get("id") and f.get("text")
    }


def validate_selection(value, profile):
    allowed = facts_map(profile)
    selected = value.get("fact_ids", []) if isinstance(value, dict) else []
    return list(dict.fromkeys(x for x in selected if isinstance(x, str) and x in allowed))


def select_facts(job, profile):
    terms = set(
        re.findall(
            r"[a-z0-9]+",
            (str(job.get("description", "")) + " " + str(job.get("title", ""))).lower(),
        )
    )
    chosen = []
    for entry in profile.get("experience", []):
        ranked = sorted(
            entry.get("facts", []),
            key=lambda f: -len(terms & set(re.findall(r"[a-z0-9]+", f["text"].lower()))),
        )
        chosen.extend(f["id"] for f in ranked[:5])
    return chosen
