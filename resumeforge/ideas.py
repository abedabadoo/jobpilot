"""Fictional writing examples. This endpoint has no path to facts, plans or PDFs."""
from __future__ import annotations

import re
from typing import Annotated

from pydantic import Field

from .laptop import ask
from .models import Model, ModelSettings, Profile


class IdeaRequest(Model):
    profile: Profile
    role_id: str = Field(min_length=1, max_length=200)
    job_description: str = Field(default="", max_length=40000)
    keywords: list[Annotated[str, Field(max_length=150)]] = Field(default_factory=list, max_length=100)
    focus: str = Field(default="", max_length=3000)
    previous: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=60)
    settings: ModelSettings = Field(default_factory=ModelSettings)


class Idea(Model):
    text: str = Field(min_length=20, max_length=600)
    verify: list[Annotated[str, Field(min_length=2, max_length=180)]] = Field(min_length=1, max_length=4)


class IdeaBatch(Model):
    ideas: list[Idea] = Field(min_length=3, max_length=3)


# Starting points available with inference disabled. Each has an action, a
# measurable scope or result, and a different way to remember real experience.
_EXAMPLES = {
    "cloud": (
        r"\b(cloud|aws|terraform|kubernetes|prometheus|grafana|infrastructure|deployments?|pipelines?|devops|ci/cd)\b",
        (
            "Built a Terraform module for 6 AWS services and cut the time to provision a test environment from 2 hours to 25 minutes.",
            "Connected Prometheus alerts to a Grafana dashboard for 8 services so the on-call engineer could isolate a failing dependency in 10 minutes.",
            "Added rollback checks to a CI/CD pipeline and caught 7 incompatible configuration changes before they reached production.",
            "Consolidated 12 service runbooks into a single release checklist and rehearsed the recovery steps with 3 engineering teams.",
        )),
    "risk": (
        r"\b(risk|audit|controls?|compliance|grc|iso|evidence|regulatory|governance)\b",
        (
            "Mapped evidence owners to 24 access controls and cut the number of overdue review items from 9 to 3 in one quarter.",
            "Built a weekly reconciliation for 6 audit evidence sources and reduced manual preparation by 4 hours per review cycle.",
            "Ran a tabletop exercise with 3 service teams and turned 8 gaps in the incident plan into assigned remediation tasks.",
            "Compared 35 vendor questionnaires against a shared risk rubric and escalated 5 missing data-retention commitments for legal review.",
        )),
    "security": (
        r"\b(security|cybersecurity|vulnerabilit\w*|access|soc|iam|threat|alerting)\b",
        (
            "Wrote detection rules for 4 recurring account-abuse patterns and verified the alerts against 30 days of authentication logs.",
            "Triaged 48 vulnerability reports with application owners and brought the median time to assign a fix from 5 days to 2.",
            "Reviewed privileged access across 7 applications and worked with service owners to retire 14 unused administrator grants.",
            "Built a replay set of 32 redacted security events to test whether changes to an alert rule missed known incidents.",
        )),
    "software": (
        r"\b(software|engineer|api|python|testing|developer|application|backend|frontend|code)\b",
        (
            "Reworked a slow API query and reduced its median response time from 410 to 180 milliseconds in a production load test.",
            "Added 28 regression tests for checkout failures and caught 4 release-blocking defects before the next deployment.",
            "Built a self-service diagnostic that helped support staff resolve 15 recurring integration tickets without engineering assistance.",
            "Migrated 3 services to a common authentication library and replaced 11 duplicate implementations with one maintained package.",
        )),
    "analysis": (
        r"\b(data|sql|analytics|analyst|reconciliation|excel|inventory|logistics|reporting)\b",
        (
            "Reconciled 1,200 shipment records against carrier invoices and identified 18 duplicate charges for the finance team to review.",
            "Automated a weekly SQL report for 5 regional leads and reduced preparation time from 3 hours to 30 minutes.",
            "Compared 8 weeks of order exceptions and tested a routing change that reduced repeat handoffs from 16 per week to 7.",
            "Traced missing dashboard values to 2 upstream feeds and added freshness checks before the next reporting cycle.",
        )),
    "teamwork": (
        r"\b(teamwork|team|collaborat\w*|leadership|mentoring|mentor|training|onboarding)\b",
        (
            "Coordinated 4 teams during a pilot rollout and assigned an owner to each of the 11 handoff gaps found in the first week.",
            "Paired with 3 new hires to document recurring troubleshooting steps and shortened their first independent assignment by 2 days.",
            "Ran 6 feedback sessions with frontline staff and used their findings to revise 3 steps in the team’s intake process.",
            "Facilitated a review of 18 stalled requests and secured next steps from 5 partner teams before the next planning cycle.",
        )),
}
_GENERAL = (
    "Simplified a 9-step intake process and reduced the median handoff time from 4 days to 2 days during a one-month pilot.",
    "Reviewed 60 recurring requests, identified the 3 most common causes of rework, and wrote a checklist for handling each one.",
    "Coached 4 colleagues on a new review process and tracked 12 cases together before handing off responsibility.",
    "Compared 6 weeks of work records and identified a scheduling change that freed 3 hours per week for urgent requests.",
    "Piloted a shared tracker with 2 teams and replaced 5 separate status reports with one weekly update.",
    "Revised an escalation guide after reviewing 16 delayed cases and assigned a named owner to each of 4 decision points.",
    "Interviewed 8 frequent users and tested a revised intake form that cut incomplete submissions from 14 to 6 per week.",
    "Audited 42 completed requests against the service standard and documented 7 exceptions for the next planning cycle.",
    "Created a handover guide from 10 common questions and used it to train 3 people covering the weekend shift.",
    "Tracked the age of 24 open requests and helped resolve the 6 that had been waiting more than 2 weeks.",
    "Organized a trial with 5 colleagues and converted their feedback into 3 changes before the wider rollout.",
    "Compared 2 scheduling approaches across 4 shifts and presented the measured waiting times to the team lead.",
)


def _tokens(text):
    return set(re.findall(r"[a-z]+", text.casefold()))


def _distinct(text, prior):
    words = _tokens(text)
    return all(len(words & other) / max(1, len(words | other)) < .74 for other in prior)


def _templates(request, role):
    signals = [(request.focus, 8), (" ".join(request.keywords), 6),
               (request.job_description, 3), (role.title, 3)]
    groups = []
    for pattern, examples in _EXAMPLES.values():
        score = sum(weight * min(3, len(set(re.findall(pattern, value, re.I))))
                    for value, weight in signals)
        if score:
            groups.append((score, examples))
    for _, examples in sorted(groups, key=lambda group: -group[0]):
        yield from examples
    yield from _GENERAL


_SYSTEM = """Write three fictional sample resume bullets to jog the applicant's memory.
Use the role, topic and target job as inspiration. Make up realistic actions,
tools and concrete numeric examples. Each bullet must use at least one digit
and illustrate a different kind of accomplishment. Use plain past-tense prose.
Skip placeholders, headings, employer names and bullet marks. For each, give
one or two short prompts in 'verify' to help replace the invented details.
Avoid repeating the supplied previous ideas. Each entire bullet is hypothetical."""


def brainstorm(request: IdeaRequest) -> dict:
    role = next((role for role in request.profile.roles if role.id == request.role_id), None)
    if role is None:
        raise ValueError("Choose a role from the current profile.")
    previous = request.previous[-8:]
    seen = [_tokens(text) for text in previous]
    ideas = []
    if request.settings.provider != "none":
        context = {
            "role_title": role.title[:160],
            "sample_role_work": [b.text[:260] for b in role.bullets[:3]],
            "target_job": request.job_description[:2600],
            "target_keywords": [term[:90] for term in request.keywords[:18]],
            "topic": request.focus[:600],
            "previous_ideas": [text[:220] for text in previous],
        }
        try:
            generated = ask(request.settings, IdeaBatch, _SYSTEM, context, 650)
        except (RuntimeError, OSError):
            generated = None
        for idea in generated.ideas if generated else []:
            if re.search(r"\d", idea.text) and _distinct(idea.text, seen):
                ideas.append(idea)
                seen.append(_tokens(idea.text))

    model_count = len(ideas)
    for example in _templates(request, role):
        if len(ideas) == 3:
            break
        if _distinct(example, seen):
            quantities = re.findall(r"\b\d[\d,]*(?:\.\d+)?%?", example)
            ideas.append(Idea(text=example, verify=[
                "Which actions did you personally perform, and which tools or steps did you use?",
                f"Replace the sample figures ({', '.join(quantities)}) with your recorded numbers, or remove them.",
            ]))
            seen.append(_tokens(example))
    mode = "model" if model_count == 3 else "mixed" if model_count else "templates"
    return {"role_id": role.id, "mode": mode, "fictional": True,
            "ideas": [idea.model_dump() for idea in ideas]}
