"""Read a private local ResumeForge source profile into JobPilot's candidate format.

The public sample profile remains fictional. No applicant content is committed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)


def _dates(value):
    text = str(value or "")
    matches = re.findall(rf"\b{_MONTH}\s+\d{{4}}\b", text, re.I)
    if len(matches) > 1:
        end = matches[1]
    elif re.search(r"\b(?:present|current)\b", text, re.I):
        end = "Present"
    else:
        end = ""
    return (matches[0] if matches else ""), end


def read_local_profile(master_dir: Path) -> dict | None:
    """Map a saved ResumeForge master draft without writing its contents to the repo."""
    path = Path(master_dir) / "draft.json"
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if not 2 <= path.stat().st_size <= 10 * 1024 * 1024:
            return None
        draft = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None

    source = draft.get("profile") if isinstance(draft, dict) else None
    if not isinstance(source, dict):
        return None
    name = str(source.get("name") or "").strip()
    if not name or name.casefold() in {"morgan example", "jordan morgan"}:
        return None
    if any(not isinstance(source.get(key, []), list) for key in ("roles", "skills", "education")):
        return None

    contact = str(source.get("contact") or "")
    segments = [part.strip() for part in contact.split("|") if part.strip()]
    email = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", contact)
    phone = next(
        (
            part
            for part in segments
            if sum(char.isdigit() for char in part) >= 10 and "@" not in part and "http" not in part
        ),
        "",
    )
    if not email or not phone:
        return None
    location = next(
        (
            part
            for part in segments
            if "," in part and "@" not in part and sum(c.isdigit() for c in part) < 5
        ),
        "",
    )
    linkedin = next((part for part in segments if "linkedin.com/" in part.lower()), "")
    if linkedin and not linkedin.startswith(("https://", "http://")):
        linkedin = "https://" + linkedin

    experience = []
    confirmed_facts = source.get("facts") if isinstance(source.get("facts"), list) else []
    for role in source.get("roles", []):
        if not isinstance(role, dict) or not role.get("company") or not role.get("title"):
            continue
        if not isinstance(role.get("bullets", []), list):
            return None
        facts = []
        for bullet in role.get("bullets", []):
            if isinstance(bullet, dict) and bullet.get("id") and bullet.get("text"):
                facts.append({"id": "rf:" + str(bullet["id"]), "text": str(bullet["text"])})
        for item in confirmed_facts:
            if (
                isinstance(item, dict)
                and item.get("role_id") == role.get("id")
                and item.get("confirmed", True)
                and item.get("id")
                and item.get("text")
            ):
                facts.append({"id": "rf:" + str(item["id"]), "text": str(item["text"])})
        if not facts:
            continue
        start, end = _dates(role.get("dates"))
        experience.append(
            {
                "company": str(role["company"]),
                "title": str(role["title"]),
                "start": start,
                "end": end,
                "location": str(role.get("location") or location),
                "facts": facts,
            }
        )
    if not experience:
        return None

    education = []
    for item in source.get("education", []):
        if not isinstance(item, dict) or not item.get("institution") or not item.get("degree"):
            continue
        start, end = _dates(item.get("dates"))
        education.append(
            {
                "institution": str(item["institution"]),
                "degree": str(item["degree"]),
                "start": start,
                "end": end,
            }
        )

    raw_certs = source.get("certifications") or ""
    if isinstance(raw_certs, list):
        certs = [str(value).strip() for value in raw_certs]
    else:
        certs = re.split(r"\s*[,;|]\s*", str(raw_certs))
    names = name.split(maxsplit=1)
    return {
        "sample_profile": False,
        "name": name,
        "first_name": names[0],
        "last_name": names[1] if len(names) > 1 else "",
        "email": email.group(),
        "phone": phone,
        "location": location,
        "linkedin": linkedin,
        "experience": experience,
        "skills": [
            value.strip()
            for value in source.get("skills", [])
            if isinstance(value, str) and value.strip()
        ],
        "certifications": [value.strip() for value in certs if value.strip()],
        "education": education,
    }


def adopt_local_profile(store, master_dir: Path, score_job, settings: dict) -> bool:
    """Replace only the sample profile and rescore unfinalized saved jobs."""
    current = store.get("profile", {})
    if not isinstance(current, dict) or current.get("sample_profile") is not True:
        return False
    candidate = read_local_profile(master_dir)
    if candidate is None:
        return False

    # Commit the profile LAST: interrupted rescoring can then retry safely.
    threshold = settings.get("min_fit", 40)
    for job in store.jobs():
        if job.get("status") in {
            "confirmed",
            "manually_verified",
            "preparing",
            "applying",
            "submitting",
        }:
            continue
        if job.get("applied") or job.get("documents"):
            continue
        fit = score_job(job, candidate, settings)
        changes = {"fit": fit}
        if (
            job.get("status") == "skipped"
            and job.get("note") == "Fit is below the configured search threshold."
            and fit >= threshold
        ):
            changes.update(status="queued", note="")
        store.update_job(job["id"], **changes)
    store.set("fit_scoring_signature", "")
    store.set("profile", candidate)
    store.event("JobPilot initialized its candidate profile from saved local ResumeForge data.")
    return True
