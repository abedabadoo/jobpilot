"""Combine posting structure with a local model's reading of the actual requirements."""
from __future__ import annotations

from typing import Literal
import re
from pydantic import Field
from .laptop import ask
from .models import Keyword, Model
from .planning import (_canonical, _evidence_for, analyze_job, credential_requirement,
                       keyword_matches, valid_requirement_term)
from .priorities import capability, literal_pattern, normalize, passages, score
from .requirement_extraction import grounded_label, word_stems, without_experience_duration


class Requirement(Model):
    capability: str = Field(min_length=2, max_length=100)
    quote: str = Field(min_length=8, max_length=310)
    kind: Literal["capability", "credential", "strength"] = "capability"


class Reading(Model):
    requirements: list[Requirement] = Field(max_length=8)


_SYSTEM = """Analyze ONLY the supplied hiring requirements. Rank up to seven distinct
job capabilities, prioritizing the specialty, hands-on responsibilities, and required
skills. Group alternative tools and languages into one OR requirement, not several
mandatory missing skills. Keep preferred qualifications lower than core duties.
Classify degrees, licenses and certifications separately from performable capabilities.
Ignore compensation, benefits, privacy disclosures, tracking codes, and recruiting
boilerplate. Never reuse requirements from a previous job or infer them from the
candidate resume. Reject fragments such as 'with application' and 'are multiplied'.
For every requirement supply an exact supporting quotation from the given posting.
Quote actual requirements; do not invent or paraphrase the quoted text.
In experience requirements ignore the years-of-experience NUMBER for skill ranking:
identify the discipline(s) named AFTER the duration. For example, "5+ years
experience in accounting, payroll, and reporting" means those domains, NOT
"5+ years" as a capability. Keep labels concise (3-8 complete words), never
unfinished clauses or fragments; group alternative paths with OR."""


def _concise_capability(term):
    """Replace tenure wrappers and clipped model phrases with usable labels."""
    term = without_experience_duration(term.strip(" ,.;:-"))
    if len(term.split()) > 10:
        for separator in (
            r"\s+to\s+(?:improve|reduce|support|accelerate|ensure|detect|enable)\b",
            r"[,;]\s+", r"\s+(?:including|such as)\b",
        ):
            match = re.search(separator, term, re.I)
            if match and len(term[:match.start()].split()) >= 3:
                term = term[:match.start()]
                break
    if len(term.split()) > 10:
        term = " ".join(term.split()[:10])
    return re.sub(r"\s+(?:and|or|to|for|with|including|of)$", "", term,
                                 flags=re.I).strip(" ,.;:-")


def _capability_key(term):
    canonical = _canonical(term)
    group = capability(canonical)
    return normalize(group.label if group else canonical)


def _distinct_requirements(rows):
    """Consolidate near-identical capability labels while retaining evidence.

    A job can describe the same work as a broad responsibility, a required
    qualification, and a tooling example. Those should not become three
    separate priorities. Compare *semantic content words* after ranking;
    keep distinct platform competencies and never discard stronger source
    evidence or an explicitly required capability for a weaker mention.
    """
    def content(term):
        text = term.casefold().replace("vb scripts", "vbscript")
        words = word_stems(text)
        normalized = set()
        for word in words:
            if word in {"service", "platform", "system", "tool", "experience",
                        "skill", "knowledge", "including", "other"}:
                continue
            if word.startswith(("automat", "automa")):
                word = "automat"
            elif word.startswith("administ"):
                word = "administ"
            elif word.startswith("manag"):
                word = "manag"
            elif word.startswith("configur"):
                word = "configur"
            normalized.add(word)
        return normalized

    kept = []
    for row in rows:
        target = content(row["term"])
        duplicate = False
        for previous in kept:
            if row["kind"] != previous["kind"]:
                continue
            earlier = content(previous["term"])
            if not target or not earlier:
                continue
            shared = target & earlier
            # Require meaningful multiword overlap. "Network security" and
            # "endpoint security" should never collapse into one skill.
            if (len(shared) < 3 or
                    len(shared) / min(len(target), len(earlier)) < .8):
                continue
            if row["required"] and not previous["required"]:
                continue
            if row["evidence"] == "exact" and previous["evidence"] != "exact":
                continue
            if row["rationale"].startswith("User requested priority."):
                continue
            duplicate = True
            break
        if not duplicate:
            kept.append(row)
    return kept


def analyze_posting(profile, job, keywords, settings):
    rows = analyze_job(profile, job, keywords)
    if settings.provider == "none" or not settings.model.strip() or not job.strip():
        return rows
    # Exclude non-hiring sections before sending context to the model. Sending
    # the raw tail of a long job advert previously amplified salary/privacy text.
    cleaned = "\n".join(row.text for row in passages(job))
    excerpt = cleaned[:12000]
    try:
        reading = ask(settings, Reading, _SYSTEM,
                      {"posting": excerpt}, 850)
    except (RuntimeError, OSError):
        return rows

    by_label = {}
    by_alias = {}
    for row in rows:
        primary = by_label.setdefault(_capability_key(row["term"]), row)
        for alias in row["terms"]:
            by_alias.setdefault(_capability_key(alias), primary)
    quoted_source = " ".join(excerpt.casefold().split())
    records = [(e.id, e.text) for e in profile.evidence().values() if e.confirmed and e.role_id]
    education = [" ".join(x for x in (item.degree, item.detail) if x) for item in profile.education]
    if profile.certifications:
        education.append(profile.certifications)
    by_model = {}
    for finding in reading.requirements:
        label = _concise_capability(finding.capability)
        if not valid_requirement_term(label):
            continue
        quote = " ".join(finding.quote.split())
        # Passage parsing normalizes terminal punctuation, but the model may
        # legitimately quote the original sentence including its final period.
        if quote.casefold().rstrip(" .") not in quoted_source:
            continue
        name = _capability_key(label)
        row = by_label.get(name) or by_alias.get(name)
        if row is not None and finding.kind == "credential" and row.get("kind") != "credential":
            target = Keyword(term=row["term"], weight=row["weight"], required=row["required"],
                             rationale=row["rationale"], kind="credential")
            row = {**_evidence_for(target, records, profile.skills, education, roles=profile.roles),
                   "terms": row.get("terms", [target.term])}
            by_label[_capability_key(row["term"])] = row
        source_passage = next((source for source in passages(job)
                               if quote.casefold().rstrip(" .") in source.text.casefold()), None)
        if source_passage is None:
            continue
        # A new, unrecognized capability may be a useful paraphrase of a
        # specific task. Validate it against the quoted source instead of
        # requiring every word to appear verbatim in the job posting.
        lexical = row and any(keyword_matches(quote, term)
                              for term in [row["term"], *row["terms"]])
        semantic = grounded_label(label, quote)
        if not lexical and not semantic:
            continue
        if row is None:
            # Overlapping generic words ("monitoring", "response") do not
            # license adding an unmentioned security product or specialty.
            # Known catalog aliases have already resolved to an existing row.
            named = re.findall(r"(?<![\w])(?:[A-Z]{2,}[A-Z0-9+#]*)(?![\w])", label)
            if any(not keyword_matches(quote, tech) for tech in named):
                continue
            if not valid_requirement_term(label):
                continue
            rank = score([source_passage], [source_passage.text])
            if not rank:
                continue
            _, weight, required, rationale = rank
            kind = "credential" if (finding.kind == "credential" or credential_requirement(label)) \
                   else "strength" if finding.kind == "strength" else "skill"
            target = Keyword(term=label, weight=weight, required=required,
                             rationale=rationale, kind=kind)
            row = {**_evidence_for(target, records, profile.skills, education, roles=profile.roles), "terms": [target.term]}
        # A model's natural-language capability description is rarely worded
        # exactly like a source-resume bullet. Borrow ONLY partial, already
        # established evidence for concrete requirements named in the same
        # posting quote; never relabel partial experience as an exact match.
        if row["evidence"] == "missing" and row["kind"] != "credential":
            anchors = [
                existing for existing in rows
                if existing["kind"] != "credential" and existing["evidence"] != "missing"
                and len(existing["term"]) >= 4
                and (keyword_matches(quote, existing["term"])
                     or keyword_matches(label, existing["term"]))
            ]
            if anchors:
                anchors.sort(key=lambda existing: (
                    existing["evidence"] == "exact",
                    existing["required"], existing["weight"]), reverse=True)
                best = anchors[0]
                row["evidence"] = "related"
                row["evidence_ids"] = best["evidence_ids"]
                row["related_skills"] = list(dict.fromkeys(
                    best["exact_skills"] + best["related_skills"]))
        key = _capability_key(row["term"])
        by_label.setdefault(key, row)
        if key not in by_model:
            row["posting_quote"] = quote
            by_model[key] = len(by_model)
    if not by_model:
        return rows
    explicit = {_capability_key(t) for t in keywords}
    structural = {}
    for index, row in enumerate(rows):
        structural.setdefault(_capability_key(row["term"]), index)

    def priority(row):
        key = _capability_key(row["term"])
        position = structural.get(key, len(rows))
        if row.get("kind") == "credential":
            return -1, -(by_model.get(key, position) + position / 100)
        if key in explicit or row["rationale"] == "User requested priority.":
            return 2, -position
        # Ranked, source-quoted model results take precedence within their
        # importance tier. Unselected catalog matches cannot outrank an
        # explicitly ranked requirement merely because the catalog contains
        # more synonyms or repeated product names.
        optional = row.get("rationale", "").startswith(("Preferred qualification", "One of several example"))
        # The model reads the entire posting without catalogue suggestions.
        # A core responsibility it ranks highly must beat an unselected
        # mandatory keyword merely because that keyword has many aliases.
        if key in by_model:
            # Explicit mandatory work selected by the reader outranks duties;
            # selected duties still outrank unselected catalog matches.
            return (1 if optional else 4 if row["required"] else 3), 1, -by_model[key]
        return (1 if optional else 2 if row["required"] or row["weight"] >= 4 else 1), 0, -position

    return _distinct_requirements(sorted(by_label.values(), key=priority, reverse=True))
