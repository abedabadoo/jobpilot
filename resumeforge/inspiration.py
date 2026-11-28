"""Draft replacement accomplishments without turning a writing example into source evidence."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from pydantic import Field

from .laptop import ask
from .models import Candidate, Model, Review
from .planning import keyword_matches


class Story(Model):
    slot: int
    concise: str = Field(min_length=20, max_length=540)
    detailed: str = Field(min_length=20, max_length=800)


class Stories(Model):
    bullets: list[Story] = Field(min_length=1, max_length=6)


@dataclass(frozen=True)
class Example:
    signals: str
    concise: str
    detail: str


# Pairs describe the same accomplishment at two measured lengths. The editor
# can swap the amount of detail without inventing another number to fill a line.
_LIBRARY = [
    Example(r"cloud security telemetry|telemetry.*alerting|log ingestion|cloud detection and response platform",
            "Built a cross-cloud security telemetry pipeline that centralized event ingestion, log retention, and alert routing for 20 production services.",
            "Added health checks on ingestion latency and documented searchable investigation fields for the Cyber Defense team."),
    Example(r"multi.cloud security engineering|multi.cloud environment|directly managing cloud security",
            "Automated AWS, Azure, and GCP security monitoring setup through reusable configuration modules, cutting onboarding effort by 40% across nine workloads.",
            "Standardized alert labels and integration checks so platform engineers could troubleshoot each cloud consistently."),
    Example(r"unified SIEM and CNAPP|unified threat visibility|cloud.native application protection|CNAPP",
            "Integrated SIEM and CNAPP events into a unified cloud investigation view, reducing duplicate alert triage by 35% for analysts.",
            "Mapped workload and finding identifiers between systems to support consistent severity prioritization."),
    Example(r"security data engineering and correlation|data modeling|correlating security data",
            "Built a security-event correlation model across four data sources, linking cloud identities to affected workloads and reducing manual investigation joins by 50%.",
            "Validated field mappings with incident responders and added exception handling for incomplete event records."),
    Example(r"AI.assisted detection engineering|AI.infused security engineering|AI.driven correlation",
            "Built an AI-assisted detection workflow that grouped related security alerts and cut average analyst review time by 35%.",
            "Included source evidence and human review gates so analysts could verify every suggested incident grouping."),
    Example(r"cloud security guardrails and detection coverage|configuration guardrails|gaps in visibility",
            "Used Terraform and Python to codify cloud security guardrails across 500 resources and close recurring configuration drift findings.",
            "Validated policy coverage through scheduled scans and documented exception handling for infrastructure owners."),
    Example(r"product security architecture|security architecture|secure.by.default|reference implementations",
            "Defined secure-by-default architecture patterns for six product services, standardizing authentication and service boundary controls ahead of engineering release.",
            "Reviewed high-risk exceptions with application owners and documented reusable security reference implementations."),
    Example(r"security design reviews|security engineering reviews|design tradeoffs|architecture reviews",
            "Established a product security design review playbook and trained eight engineers to evaluate common authentication, authorization, and data-flow risks.",
            "Escalated higher-risk architectural tradeoffs and documented consistent review decisions for subsequent features."),
    Example(r"threat modeling|attack surface analysis|attack surface|threat models",
            "Led threat modeling across six product integrations, identifying twelve recurring attack paths and prioritizing design fixes before release.",
            "Mapped trust boundaries, authentication flows, and exposed interfaces with developers and tracked outstanding design risks."),
    Example(r"vulnerability management|systemic remediation|vulnerability remediation|security reports",
            "Analyzed recurring vulnerability classes across fourteen applications, prioritized systemic fixes, and reduced repeated findings by 22%.",
            "Worked with product owners to verify remediation and revise shared protections instead of closing duplicate tickets individually."),
    Example(r"bug bounty triage|bug bounty submissions|bug bounty platforms|bug bounty",
            "Standardized reproduction and severity triage for 200 bug bounty reports, reducing median time to disposition from four weeks to one.",
            "Introduced consistent reproduction notes and escalation criteria for high-severity application security issues."),
    Example(r"web application security|OWASP Top 10|common attack vectors",
            "Expanded application security reviews across OWASP Top 10 risk classes, documenting reproducible findings and prioritizing fixes with product teams.",
            "Included request traces and risk rationale so engineers could reproduce and resolve underlying security weaknesses."),
    Example(r"application security testing|Burp Suite|OWASP ZAP|SAST|DAST",
            "Deployed recurring application security testing against production web services, routing three to five findings per scan into remediation tracking.",
            "Documented reproduction steps and test coverage with service owners to reduce repeated security findings."),
    Example(r"developer security enablement|security champions|developer security training|product security training",
            "Launched a security champions pilot across three engineering teams, training eight developers on secure design reviews and vulnerability escalation.",
            "Published review examples for recurring design risks and maintained an escalation route for complex cases."),
    Example(r"secure SDLC|security tooling|software development lifecycle",
            "Integrated automated security checks into development workflows, routing recurring findings to service owners before release approval.",
            "Defined review gates and documented exceptions so developers could correct issues without unnecessary handoffs."),
    Example(r"product security technical leadership|technical voice on product security",
            "Led product security design decisions across three engineering teams, documenting reusable criteria and mentoring eight engineers on complex reviews.",
            "Presented architecture tradeoffs to service owners and incorporated approved decisions into shared guidance."),
    Example(r"cloud infrastructure security|cloud infrastructure|container security|major cloud provider",
            "Hardened AWS compute and identity configurations, resolving recurring high-severity cloud security findings ahead of quarterly reviews.",
            "Added infrastructure-as-code checks for resource access, workload metadata protections, and encryption settings."),
    Example(r"WAF administration|Cloudflare WAF|web application firewall|custom WAF rules|traffic filtering|false.positive",
            "Operated Cloudflare WAF across 50 applications, tuning managed and custom rules to reduce false-positive blocks by 38% while maintaining 99.9% availability.",
            "Reviewed sampled requests with application owners and promoted rule changes through staged monitoring before enforcement."),
    Example(r"Edge application delivery|application delivery|\bDNS\b|\bTLS\b|\bHTTPS?\b|\bCDN\b|proxies",
            "Migrated DNS and TLS delivery for 200 application URLs, validating certificates, origins, proxies, and load balancers with zero unplanned cutover downtime.",
            "Documented rollback checks for each onboarding wave and verified HTTP and HTTPS health before traffic migration."),
    Example(r"WAF lifecycle|WAF onboarding|WAF offboarding|application onboarding|application inventories|configuration consistency|rollback readiness",
            "Standardized WAF onboarding and offboarding for 42 applications, reconciling inventories and rollback plans before every approved production change.",
            "Versioned configuration baselines and cut median change-validation time from 46 to 19 minutes."),
    Example(r"DDoS|bot mitigation|bot protection|rate limiting|attack mitigation",
            "Implemented rate limits and bot controls that filtered 1.8 million suspicious requests during a traffic surge without blocking verified customer sessions.",
            "Replayed representative OWASP Top 10 probes after each policy change and documented exceptions for application-owner review."),
    Example(r"WAF monitoring|WAF incident|traffic analysis|attack investigation|blocklist|\bSIEM\b|Security Operations Center",
            "Correlated WAF events with SIEM logs and blocklisted 37 abusive sources, reducing repeated malicious requests by 64% within one response cycle.",
            "Published the investigation query and rollback steps in the incident runbook for SOC handoff."),
    Example(r"\bagentic\b|AI orchestration|engineering harness|AI agents?",
            "Built agentic engineering harnesses that routed failing builds to a code agent and tested its patches, cutting median triage time from 42 to 18 minutes.",
            "Engineers approved each proposed change before the harness reopened the deployment gate."),
    Example(r"Claude Code|AI.assisted development|GitHub Copilot|Cursor|Cline|Aider",
            "Integrated Claude Code CLI into pull request reviews for AI-assisted development, reproducing failing tests and reducing time to the first actionable review by 31%.",
            "A CI job attached the test output and left merge approval with the code owner."),
    Example(r"SDLC|software development lifecycle",
            "Built SDLC automation into CI/CD pipelines to generate regression tests from bug reports and flag risky releases, catching 9 defects before deployment.",
            "Release engineers reviewed the proposed tests against acceptance criteria before promoting a build."),
    Example(r"\bCI[/ -]CD\b|delivery pipelines?|continuous integration",
            "Connected CI/CD pipelines to a staging replay suite and blocked 9 regressions before deployment across 4 services.",
            "Failed checks opened an issue with the commit, test output, and rollback instructions for the release engineer."),
    Example(r"\bMCP\b|Model Context Protocol",
            "Built a read-only Model Context Protocol (MCP) server that let on-call engineers retrieve deployment diffs and incident timelines from 3 systems in one query.",
            "Scoped each connector to the caller's permissions and added contract tests for expired credentials."),
    Example(r"cloud automation|infrastructure automation|infrastructure as code|\bTerraform\b|cloud.native|\bAWS\b",
            "Wrote infrastructure automation modules to provision 12 isolated test environments from versioned infrastructure as code, cutting setup time from 2 hours to 24 minutes.",
            "Added a teardown check that flagged stale resources before the next billing cycle."),
    Example(r"monitoring|observability|Datadog|production support|incident|vulnerabilit",
            "Correlated deployment events with observability alerts and reduced incident triage time from 34 to 16 minutes across 8 services.",
            "Linked each alert to the last healthy release and the runbook for its owning team."),
    Example(r"REST API|\bPython\b|\bscripting\b|engineering integrations?",
            "Wrote Python integrations that reconciled deployment records with open tickets through REST APIs, saving release engineers 6 hours per week.",
            "Added idempotent retries and a daily check for tickets with missing release identifiers."),
    Example(r"\bRAG\b|retrieval.augmented generation|language models?|\bLLMs?\b",
            "Built a retrieval-augmented generation (RAG) assistant that cited the relevant support runbook on 46 of 50 regression queries.",
            "Replayed the failed queries after each index refresh and logged unsupported answers for review."),
    Example(r"risk management|governance|compliance|audit|controls|responsible AI",
            "Standardized risk reviews for 24 third-party integrations and cut the median time to assign a control owner from 5 days to 2.",
            "Documented exceptions and assigned a follow-up date to each unresolved control."),
    Example(r"\bSQL\b|analytics|data analysis|reporting|database",
            "Reconciled 18,000 reporting records with SQL and traced 3 recurring discrepancies to inconsistent source identifiers.",
            "Added validation queries to the daily load and sent exceptions to the responsible analyst."),
    Example(r"logistics|warehouse|shipment|supply chain|inventory",
            "Reconciled shipment scans with inventory records and reduced unresolved delivery exceptions from 26 to 9 per week.",
            "Worked with dispatch leads to trace the remaining cases to their last confirmed handoff."),
    Example(r"customer service|customers?|client support|help desk",
            "Revised the intake guide for 4 common customer requests and cut repeat contacts by 19% over 6 weeks.",
            "Reviewed a sample of resolved cases with the support team to check that customers received complete answers."),
    Example(r"teamwork|collaboration|leadership|mentoring|stakeholder|communication",
            "Coordinated 4 teams during a pilot rollout and assigned an owner to each of the 11 handoff gaps found in the first week.",
            "Tracked the changes at weekly reviews until every team had tested its revised handoff."),
]


def _words(text):
    return set(re.findall(r"[\w+#]+", text.casefold()))


def _overlap(a, b):
    a, b = _words(a), _words(b)
    return len(a & b) / max(1, len(a | b))


def _same_accomplishment(text, previous):
    if _overlap(text, previous) >= .68:
        return True
    # Long and short variants may use different verbs for the same result.
    # Check for a shared metric and outcome as well as overall word overlap.
    stop = {"a","an","the","and","of","to","in","with","for","by","across","from","as","at","on","using"}
    def stems(sentence):
        return {re.sub(r"(ing|ed|s)$", "", w) for w in _words(sentence) - stop
                if len(w) > 2 and not w.isdigit()}
    metrics = lambda sentence: set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)*%?", sentence))
    common_metrics = metrics(text) & metrics(previous)
    if not common_metrics:
        return False
    left, right = stems(text), stems(previous)
    return len(left & right) >= 3 and len(left & right) / min(len(left), len(right)) >= .55


def printable(text):
    """Validate new prose for printing. Origin and prompts remain in the editor."""
    return (8 <= len(text.split()) <= 100 and len(text) <= 800 and
            not re.search(r"[\[\]{}<>\n\r]|\*\*|\?\s*$|^(?:[-*•]|\d+[.)])\s|\(cid:\d+\)|\b(?:placeholder|TODO|insert here|fictional|hypothetical|sample bullet|made.up)\b", text, re.I))


def _actionable(keywords):
    from .planning import valid_requirement_term
    return [keyword for keyword in keywords
            if keyword.kind != "credential" and valid_requirement_term(keyword.term)]


def _supports_adjacent_priority(text, target, priorities):
    """Require a generated story to connect its tool to the broader target job."""
    # An accomplishment can be compelling when it demonstrates only one
    # important qualification. Do not reject a fully grounded result merely
    # because it lacks an unrelated second keyword from a large posting.
    from .requirement_extraction import grounded_label
    return keyword_matches(text, target) or grounded_label(target, text)


def _title(term):
    # Common capability labels begin a list with a capital. Keep product names intact.
    return term[:1].lower() + term[1:] if " " in term and term[:1].isupper() and term[1:].islower() else term


def _fallback(term, index):
    # Unrecognized technical capabilities require a contextual model-written
    # achievement, rather than templating an arbitrary phrase into a generic
    # 'designed a pilot for KEYWORD' sentence.
    return Example("", "", "")


def _awkward_label_paste(text, term):
    """Detect generic target-keyword grafting into otherwise vague prose."""
    if len(term.split()) < 3:
        return False
    label = re.escape(term).replace(r"\ ", r"\s+")
    # Check the generic accomplishment template, not ordinary grammatical
    # uses such as "built tooling for clinical assessment".
    generic = (r"^(?:tracked outcomes|designed a pilot|standardized quality checks|"
               r"improved processes|implemented improvements)\s+"
               r"(?:for|about|across|regarding|around)\s+")
    return bool(re.search(generic + label + r"\b", text, re.I))


def _targets(profile, keywords):
    from .planning import bullet_relevance
    keywords = _actionable(keywords)
    if not keywords:
        return []
    scored = []
    for role in profile.roles:
        role_score = max(bullet_relevance(b.text, keywords) for b in role.bullets) + bullet_relevance(role.title, keywords)
        for bullet in role.bullets:
            scored.append((bullet_relevance(bullet.text, keywords), -role_score, role, bullet))
    # Replace low-value slots first. Spread examples across relevant jobs but
    # preserve the best original role evidence whenever there are alternatives.
    scored.sort(key=lambda entry: (entry[0], entry[1]))
    count = min(4, len(keywords), max(1, (len(scored) + 2) // 3))
    return [(role, bullet) for _, _, role, bullet in scored[:count]]


def _story_choices(keywords, count, *, use_offline_examples=True):
    terms = [k.term for k in _actionable(keywords)]
    pool = list(_LIBRARY)
    used = set()
    choices = []
    for i, term in enumerate(terms):
        if any(keyword_matches(example.concise, term) for _, example in choices):
            # A single strong accomplishment can demonstrate both an SDLC
            # capability and CI/CD, freeing a slot for another requirement.
            continue
        if len(choices) >= count:
            break
        # A local model drafts from each new posting. The historical
        # hand-written examples are optional offline demonstrations only;
        # never fall back to the last benchmark job when model output fails.
        matched = next((e for e in pool if re.search(e.signals, term, re.I)), None) if use_offline_examples else None
        if matched is None and any(re.search(e.signals, term, re.I) for e in used):
            continue
        if matched:
            pool.remove(matched)
            used.add(matched)
        example = matched or _fallback(term, i)
        if matched and "Claude Code CLI" in matched.concise:
            products = ("Claude Code CLI", "GitHub Copilot", "Cursor", "Cline", "Aider")
            # Generic AI development does not imply that Claude was requested.
            tool = next((product for key in (term, *terms) for product in products
                         if keyword_matches(key, product)), "a coding assistant")
            example = Example("", matched.concise.replace("Claude Code CLI", tool), matched.detail)
        if matched and "infrastructure automation modules" in matched.concise:
            label = next((name for name in ("Terraform", "AWS") if keyword_matches(term, name)), "")
            if label == "Terraform":
                example = Example("", matched.concise.replace("infrastructure automation modules", "Terraform modules"),
                                  matched.detail)
            elif label == "AWS":
                example = Example("", matched.concise.replace("isolated test environments", "isolated AWS test environments"),
                                  matched.detail)
        if matched and not keyword_matches(example.concise + " " + example.detail, term):
            example = _fallback(term, i)
        choices.append((term, example))
    return choices


_SYSTEM = """Write original, fictional resume accomplishments for the specified slots, in priority order.
Treat the applicant's editing brief as editorial direction. Invent plausible projects, tools, concrete scope and results that illustrate the target work.
For each bullet, identify the task the target employer wants performed with the priority, then describe performing that task.
Use the past role only to choose a plausible setting. A sentence about another use of the same tool misses the assignment.
Avoid generic phrases such as 'tracked outcomes for KEYWORD', 'pilot for KEYWORD' and
'quality checks for KEYWORD'. Integrate each capability naturally into a specific
technical action and name the system, review, artifact, or decision involved.
Do not substitute a related but different task, tool, credential, or outcome merely because its wording overlaps the requirement.
Connect the work to a visible artifact or decision and a measurable outcome. Prefer concrete counts and times to sweeping claims about quality or compliance.
Given two target tools with similar names, use the actual capability requested. Spread different achievements across slots.
For each numbered slot, write one concise bullet (15–30 words) and one detailed version (30–55 words) about the same accomplishment, with consistent metrics.
Each pair should read like a finished resume bullet, start with an action verb and include at least one plausible numeric result or scope.
Return plain text only. Leave out labels, brackets, notes, employer names, and any indication that a sentence is a writing example."""


def add_examples(profile, plan, request):
    """Add a bounded set of slot alternatives, leaving the source profile intact."""
    keywords = _actionable(plan.keywords)
    if not keywords:
        return
    targets = _targets(profile, keywords)
    choices = _story_choices(keywords, len(targets), use_offline_examples=request.settings.provider == 'none')
    from .planning import bullet_relevance
    slots = []
    for term, example in choices:
        requirement = [k for k in keywords if k.term == term]
        def role_fit(target):
            role, _ = target
            return max(bullet_relevance(b.text, requirement) for b in role.bullets) + bullet_relevance(role.title, requirement)
        target = max(targets, key=role_fit)
        targets.remove(target)
        if re.search(r"agentic", term, re.I) and any(k.term.casefold() in ("mcp","model context protocol") for k in keywords):
            example = Example("", "Built agentic engineering harnesses that retrieved build logs through Model Context Protocol (MCP), tested proposed fixes, and cut median triage time from 42 to 18 minutes.",
                              "Engineers approved each patch after comparing the replay with the last healthy build.")
        slots.append((target, (term, example)))
    generated = {}
    if slots and request.settings.provider != "none":
        from .priorities import capability, passages, locations
        posting_rows = passages(request.job_description)
        def priority_context(term):
            cap = capability(term)
            phrases = cap.phrases if cap else (term,)
            rows = [row.text for row in posting_rows if locations(row, phrases)]
            return {"term": term, "posting_terms": [p for p in phrases if any(locations(r, (p,)) for r in posting_rows)],
                    "requirement": max(rows, key=lambda row: len(set(_words(row)) & _words(term)), default="")[:330]}
        context = {"job": "\n".join(row.text for row in posting_rows)[:5000], "editing_brief": request.edit_request,
                   "priority_order": [k.term for k in keywords[:20]],
                   "requirements": [priority_context(term) for _, (term, _) in slots],
                   "slots": [{"slot": i, "role_title": role.title, "priority": term,
                              "role_context": [b.text[:250] for b in sorted(role.bullets,
                                  key=lambda b: bullet_relevance(b.text, [k for k in keywords if k.term == term]),
                                  reverse=True)[:3]]}
                             for i, ((role, _), (term, _)) in enumerate(slots, 1)]}
        try:
            response = ask(request.settings, Stories, _SYSTEM, context, 1600)
            for item in response.bullets:
                if 1 <= item.slot <= len(slots):
                    generated.setdefault(item.slot, item)
        except (RuntimeError, OSError) as exc:
            plan.notes.append(f"The writing model could not generate usable examples. Built-in examples were used. {exc}")
    history = [b.text for r in profile.roles for b in r.bullets]
    for index, ((role, bullet), (term, example)) in enumerate(slots, 1):
        origin = "offline-example"
        variants = [example.concise, example.concise + " " + example.detail] if example.concise else []
        model_story = generated.get(index)
        if model_story:
            accepted = [text for text in (model_story.concise, model_story.detailed)
                        if printable(text) and re.search(r"\d", text)
                        and _supports_adjacent_priority(text, term, keywords)
                        and not _awkward_label_paste(text, term)
                        and all(not _same_accomplishment(text, old) for old in history)]
            if accepted:
                variants, origin = accepted, "model-example"
        if model_story and origin == "offline-example":
            plan.notes.append(f"Model output for {term} did not pass the writing checks; using a specialized fallback if available.")
        if not variants:
            plan.notes.append(f"No reliable example template for {term}; leaving the original accomplishment available.")
            continue
        history.extend(variants)
        for ordinal, text in enumerate(dict.fromkeys(variants)):
            key = sha256((role.id + "\0" + bullet.id + "\0" + text).encode()).hexdigest()[:18]
            plan.candidates.append(Candidate(id="idea:" + key, role_id=role.id, slot_id=bullet.id,
                origin=origin, text=text, quality=1 if ordinal == 0 else .99,
                keywords=[k.term for k in plan.keywords if keyword_matches(text,k.term)],
                rationale=f"Example accomplishment targeting {term}."))


def apply_edits(plan, edits):
    by_id = {c.id: c for c in plan.candidates if c.origin != "source"}
    if edits.keys() - by_id.keys():
        raise ValueError("A draft edit refers to an unknown example. Reopen the current draft.")
    slots = set()
    replacements = []
    for id_, text in edits.items():
        candidate = by_id[id_]
        if candidate.slot_id in slots:
            raise ValueError("Choose one revision per bullet.")
        slots.add(candidate.slot_id)
        text = text.strip()
        if text:
            if not printable(text):
                raise ValueError("Use a complete bullet of 8–100 words without brackets, markup, or placeholders.")
            replacements.append(candidate.model_copy(update={"text":text, "origin":"edited-example", "parts":[],
                "keywords":[k.term for k in plan.keywords if keyword_matches(text,k.term)]}))
    # Keep original alternatives in the stored plan. All siblings of edited
    # examples are removed so a deleted bullet cannot return on another build.
    plan.candidates = [c for c in plan.candidates if c.origin == "source" or c.slot_id not in slots] + replacements


def printable_plan(plan):
    # Draft mode explicitly requests replacements, including the user's edits.
    # Keep originals in the saved plan so deleting an example restores them.
    example_slots = {c.slot_id for c in plan.candidates if c.origin != "source"}
    return plan.model_copy(update={"candidates":[c for c in plan.candidates if
        c.origin != "source" or c.slot_id not in example_slots]}), frozenset(example_slots)


def draft_skills(profile, plan, ranked):
    """Keep ranked, evidenced skills; never paste an abstract job duty into Skills.

    The final renderer separately reconciles terminology against the concrete
    accomplishments it actually selects. Inserting a keyword merely because
    it appears in *some* example alternative previously produced labels such
    as 'case creation' while dropping Python and REST APIs.
    """
    return ranked


def check_draft(profile, selected, settings):
    from .planning import review_content
    originals = [c for c in selected if c.origin == "source"]
    # The default inspiration plan uses exact source originals and facts. A
    # supplied plan with real rewrites still needs the regular evidence checks.
    evidence = profile.evidence()
    exact = all(any(c.text == evidence[e].text for e in c.evidence_ids if e in evidence) for c in originals)
    review = review_content(profile, originals, settings.model_copy(update={"provider":"none"}) if exact else settings) if originals else Review(passed=True)
    issues = list(review.issues)
    seen = set()
    for c in selected:
        if c.origin != "source" and not printable(c.text):
            issues.append(f"{c.id}: Example needs a complete, printable accomplishment.")
        if c.text.casefold() in seen:
            issues.append(f"{c.id}: Duplicate experience bullet.")
        seen.add(c.text.casefold())
    if not selected:
        issues.append("No experience bullets were selected.")
    return Review(passed=not issues, issues=issues)
