"""Recognize job capabilities and rank them using the posting's own structure."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import html
import re


@dataclass(frozen=True)
class Capability:
    label: str
    phrases: tuple[str, ...]
    related: tuple[str, ...] = ()
    title_cues: tuple[str, ...] = ()


# Alternate expressions in a posting form one priority. Neighbors help identify
# transferable experience but do not establish an exact match to that priority.
CAPABILITIES = (
    # Cloud defense engineering: platforms, telemetry, and unified visibility.
    Capability("Cloud security telemetry and alerting infrastructure", (
        "cloud security telemetry", "security telemetry", "telemetry, logging, and alerting",
        "telemetry, monitoring, and alerting infrastructure", "cloud security logging",
        "logging and alerting", "alerting infrastructure", "log ingestion",
        "log storage", "log retention", "log retrieval",
        "cloud detection and response platform", "cloud security monitoring infrastructure"),
        ("alert ingestion", "SLO alerts", "Datadog", "logging", "log analysis",
         "monitoring", "runbooks", "SIEM", "cloud logging")),
    Capability("Multi-cloud security engineering", (
        "multi-cloud experience", "multi-cloud environment", "multi-cloud environments",
        "multiple cloud environments", "multi-cloud security", "multi-cloud",
        "cloud and security engineering", "cloud engineering", "cloud defensive operations",
        "directly managing cloud security infrastructure"),
        ("AWS", "Amazon Web Services", "Azure", "Microsoft Azure", "GCP",
         "Google Cloud Platform", "Infrastructure as Code", "Terraform", "Docker")),
    Capability("Unified SIEM and CNAPP threat visibility", (
        "unified threat visibility", "unified view", "unified data platforms",
        "cloud-native application protection", "cloud native application protection",
        "CNAPP", "SIEM platforms", "detection & SIEM", "detection and SIEM",
        "log-analytics platforms", "security log analytics", "cloud-native alerts"),
        ("SIEM", "Splunk", "Datadog", "incident response", "alert ingestion",
         "Microsoft Azure", "AWS", "Google Cloud Platform")),
    Capability("Security data engineering and correlation", (
        "correlating data across systems", "data modeling", "data correlation",
        "correlating security data", "AI-driven correlation", "security data",
        "data modeling or correlating", "correlation across data sources",
        "log ingestion, storage, retention, and retrieval"),
        ("SQL", "Python", "Datadog", "log ingestion", "alert ingestion", "SIEM",
         "automated reporting", "data pipelines")),
    Capability("AI-assisted detection engineering", (
        "AI-infused security engineering", "AI-driven correlation",
        "AI-assisted engineering", "AI-driven security", "applied AI",
        "AI tools for building", "AI for detection", "AI into how we build",
        "AI can change how we build"),
        ("LLM-powered", "AI-assisted development", "AI code-review",
         "AI assistant", "Python", "automation")),
    Capability("Cloud security guardrails and detection coverage", (
        "configuration guardrails", "guardrails and improvements",
        "cloud security guardrails", "gaps in visibility", "gaps in coverage",
        "visibility or coverage", "close gaps in visibility", "security guardrails",
        "cloud-native guardrails"),
        ("Infrastructure as Code", "AWS", "Azure", "Google Cloud Platform",
         "Terraform", "security controls", "Datadog")),

    # Product security is its own discipline, not a synonym for perimeter WAF
    # operations. Each family captures job responsibilities and transferable
    # evidence, while related terms are not treated as exact experience.
    Capability("Product security architecture", (
        "product security architecture", "security architecture for", "define security architecture",
        "security architecture", "secure-by-default", "reference implementations",
        "security patterns", "product security", "application security architecture"),
        ("AWS", "Google Cloud", "Microsoft Azure", "Infrastructure as Code", "security design reviews",
         "threat modeling", "web application security")),
    Capability("Security design reviews", (
        "security engineering reviews", "security design reviews", "security design review",
        "security reviews for", "high-risk product features", "design tradeoffs",
        "security design tradeoffs", "architecture reviews"),
        ("code review", "AI code-review", "OWASP ZAP", "risk reviews", "secure SDLC")),
    Capability("Threat modeling and attack surface analysis", (
        "threat modeling and attack surface analysis", "threat modeling", "threat modelling",
        "attack surface analysis", "attack surface", "threat models", "trust boundaries"),
        ("OWASP ZAP", "Vulnerability Analysis", "security reviews", "risk assessments")),
    Capability("Vulnerability management and remediation", (
        "vulnerability management", "vulnerability remediation", "systemic classes of vulnerability",
        "remediation of systemic", "vulnerability triage", "vulnerability prioritization",
        "internal security reports", "security reports"),
        ("bug bounty", "vulnerability scanning", "remediation tracking", "OWASP ZAP",
         "Vulnerability Analysis", "security findings")),
    Capability("Bug bounty triage", (
        "bug bounty triage", "bug bounty submissions", "bug bounty platforms",
        "bug bounty program", "bug bounty", "bug bounty reports"),
        ("vulnerability triage", "vulnerability scanning", "remediation tracking",
         "Vulnerability Analysis")),
    Capability("Web application security", (
        "web application security", "web application security principles",
        "common attack vectors", "OWASP Top 10", "web attacks",
        "product/application security", "application security"),
        ("OWASP ZAP", "Burp Suite", "DAST", "SAST", "vulnerability scanning", "REST APIs")),
    Capability("Application security testing", (
        "application testing tools", "application security testing",
        "web application testing", "Burp Suite", "OWASP ZAP", "browser developer tools",
        "SAST tools", "SAST", "DAST", "Semgrep", "Snyk", "Cycode"),
        ("OWASP ZAP", "vulnerability scanning", "code review", "security testing")),
    Capability("Security champions and developer enablement", (
        "security champions program", "security champions", "developer security training",
        "product security training", "developer enablement", "developer training",
        "mentor other engineers", "security training programs"),
        ("playbook", "trained", "mentored", "engineering documentation", "code-review tools")),
    Capability("Secure SDLC and security tooling", (
        "secure SDLC", "secure software development lifecycle", "secure development",
        "SDLC best practices", "security services and tooling",
        "security tooling consumed by product teams", "developer security tooling"),
        ("GitHub Actions", "CI/CD", "OWASP ZAP", "code review", "automation", "Git")),
    Capability("Product security technical leadership", (
        "lead security engineering reviews", "engineering leadership",
        "authoritative technical voice", "technical voice on product security",
        "mentor other engineers", "mentoring engineers", "design tradeoffs"),
        ("leadership", "stakeholder coordination", "security review playbook", "training")),
    Capability("Cloud infrastructure security", (
        "cloud infrastructure security", "cloud infrastructure", "cloud security",
        "container technologies", "container security", "major cloud provider",
        "one major cloud provider"),
        ("AWS", "Google Cloud Platform", "GCP", "Microsoft Azure", "Docker",
         "Terraform", "Infrastructure as Code", "IaC", "Linux/Unix")),
    Capability("Programming languages", (
        "modern programming language", "programming language", "at least one modern programming language"),
        ("Python", "Ruby", "Java", "Kotlin", "TypeScript", "JavaScript")),
    Capability("Security on-call", ("security on-call", "on-call rotation", "security on-call rotation"),
        ("incident response", "runbooks", "on-call", "SLO alerts")),
    Capability("WAF administration", ("WAF administration", "WAF operations", "WAF management",
        "web application firewall administration", "web application firewall operations",
        "web application firewall", "web application firewalls", "Cloudflare WAF", "WAF",
        "WAF policies", "WAF policy", "custom WAF rules", "custom rules", "traffic filtering",
        "false-positive tuning", "false positive tuning", "rule tuning"),
        ("Role-based Access Control", "RBAC", "OWASP ZAP", "TCP/IP", "AWS", "Microsoft Azure",
         "Linux", "Unix", "REST APIs", "Vulnerability Analysis"), ("WAF", "web application firewall")),
    Capability("Edge application delivery", ("edge application delivery", "application delivery",
        "DNS", "domain name system", "HTTP", "HTTPS", "TLS", "SSL", "web protocols",
        "reverse proxies", "reverse proxy", "proxies", "proxy", "CDN", "content delivery network",
        "certificate provisioning", "origin health checks", "origin health", "load balancers",
        "load balancing"),
        ("TCP/IP", "REST APIs", "AWS", "Microsoft Azure", "Google Cloud Platform", "Linux", "Unix")),
    Capability("WAF lifecycle and change management", ("WAF lifecycle and change management",
        "WAF lifecycle", "WAF onboarding", "WAF offboarding", "application onboarding",
        "application offboarding", "onboarding applications", "offboarding applications",
        "application inventories", "application inventory", "configuration consistency",
        "rollback readiness", "WAF change management", "maintenance windows", "signature updates",
        "rule signature updates", "rule lifecycle"),
        ("Infrastructure as Code", "IaC", "Terraform", "AWS", "Microsoft Azure", "ServiceNow",
         "Role-based Access Control", "RBAC", "Linux", "Unix")),
    Capability("DDoS and bot mitigation", ("DDoS and bot mitigation", "DDoS mitigation",
        "distributed denial of service", "bot protection", "bot management", "rate limiting",
        "attack mitigation", "volumetric attacks"),
        ("OWASP ZAP", "Vulnerability Analysis", "Datadog", "Splunk", "SIEM", "TCP/IP", "AWS",
         "Microsoft Azure", "Linux", "Unix")),
    Capability("WAF monitoring and incident response", ("WAF monitoring and incident response",
        "WAF monitoring", "WAF incident response", "WAF incidents", "WAF traffic analysis",
        "WAF traffic investigation", "WAF IP blocklisting", "WAF blocklist",
        "WAF telemetry", "WAF events", "WAF logs"),
        ("incident response", "logs", "runbooks", "on-call", "SLO alerts", "Datadog", "Splunk",
         "OWASP ZAP", "TCP/IP", "Linux", "Unix")),
    Capability("Agentic engineering harnesses", ("agentic engineering harnesses", "agentic engineering harness",
        "agentic workflows", "agentic workflow", "AI orchestration frameworks", "AI orchestration",
        "AI agents", "agent-based architectures", "software development harnesses"),
        ("LLM-powered", "LLM assistant", "LLM", "language models", "AI-assisted development")),
    Capability("AI-assisted development", ("AI-assisted development", "AI-assisted coding", "AI-enabled development", "AI-assisted development tools",
        "AI coding assistants", "AI pair programming"), ("AI code-review", "AI code review", "LLM-powered", "Claude",
        "Claude Code", "GitHub Copilot", "Cursor", "Cline", "Aider"), ("Claude",)),
    Capability("Claude Code CLI", ("Claude Code CLI", "Claude Code"), ("Claude", "AI code-review", "AI-assisted coding"),
        ("Claude",)),
    Capability("CI/CD", ("CI/CD", "continuous integration and continuous delivery", "continuous integration and deployment",
        "continuous delivery", "continuous integration"), ("GitHub Actions", "GitLab CI", "GitLab", "Jenkins", "Azure Pipelines")),
    Capability("Infrastructure as Code", ("infrastructure as code", "IaC", "infrastructure automation",
        "cloud automation", "environment provisioning", "cloud-native solutions", "cloud-native infrastructure"),
        ("infrastructure as code", "IaC", "AWS", "Amazon Web Services", "Google Cloud", "GCP", "Microsoft Azure", "Docker", "Terraform",
         "CloudFormation", "Ansible", "Linux", "Unix", "Kubernetes")),
    Capability("SDLC automation", ("SDLC automation", "automate software development lifecycle",
        "software development lifecycle automation", "software development lifecycle processes", "automate the software development lifecycle",
        "automated software delivery", "AI-driven SDLC"), ("CI/CD", "GitHub Actions", "AI code-review", "deployment automation")),
    Capability("Programming and scripting", ("programming, scripting", "programming and infrastructure as code", "programming experience", "scripting", "programming skills",
        "scripting skills"), ("Python", "Bash", "PowerShell", "Linux", "Unix", "Go language", "JavaScript")),
    Capability("Platform integrations", ("integrating development platforms", "integrate engineering platforms",
        "platform integrations", "engineering integrations", "API integrations"),
        ("REST APIs", "REST API", "GraphQL", "webhooks", "OAuth", "Python", "Git", "GitHub Actions", "Datadog", "Jira", "ServiceNow")),
    Capability("observability", ("observability",), ("monitoring", "Datadog", "SLO alerts", "runbooks",
        "Prometheus", "Grafana", "Splunk", "OpenTelemetry", "alert ingestion")),
    Capability("incident response", ("incident response", "incident management"), ("runbooks", "on-call", "Datadog", "SLO alerts", "observability",
        "alert ingestion", "incident triage")),
    Capability("risk management", ("risk management",), ("risk reviews", "risk assessments", "risk register",
        "vendor risk", "risk assessment", "risk review")),
    Capability("MCP", ("MCP", "Model Context Protocol")),
    Capability("RAG", ("RAG", "retrieval-augmented generation")),
    Capability("human-in-the-loop controls", ("human-in-the-loop controls", "human in the loop controls")),
    Capability("AI governance", ("AI governance", "Responsible AI", "model risk management")),
    Capability("data engineering", ("data engineering", "data pipelines"), ("Airflow", "Spark", "SQL", "PostgreSQL")),
    Capability("financial forecasting", ("financial forecasting", "financial forecasts"), ("financial modeling", "Excel")),
    Capability("demand forecasting", ("demand forecasting", "demand forecasts"), ("inventory planning", "forecast modeling")),
)
def normalize(text):
    return re.sub(r"[\s‐‑–—-]+", " ", text.casefold()).strip()


_BY_NAME = {normalize(term): cap for cap in CAPABILITIES for term in (cap.label, *cap.phrases)}


def capability(term):
    return _BY_NAME.get(normalize(term))


@lru_cache(maxsize=2048)
def literal_pattern(term):
    pieces = re.split(r"[\s‐‑–—-]+", term.strip())
    return re.compile(r"(?<![\w+#])" + r"[\s/‐‑–—-]+".join(map(re.escape, pieces)) + r"(?![\w+#])", re.I)


def related(text, term):
    cap = capability(term)
    return bool(cap and any(literal_pattern(neighbor).search(text) for neighbor in (*cap.related, *cap.phrases)))


@dataclass(frozen=True)
class Passage:
    text: str
    section: str
    title: bool


_HEADINGS = {
    "preferred": r"(?:preferred|desirable|desired(?:\s+skills?\s*/\s*certifications?)?|additional|bonus|nice[- ]to[- ]have|good[- ]to[- ]have)(?: qualifications?| requirements?| skills?| experience|s)?",
    "required": r"(?:required|minimum|essential|basic)(?: qualifications?| requirements?| skills?(?:\s*(?:&|and|/)\s*qualifications?)?| experience)?|requirements?|what you(?:'|’)ll need|what you bring|you should have|must[- ]have(?: technical/functional skills)?|qualifications",
    "duties": r"(?:key |primary |core |essential )?(?:responsibilities|duties)|what you(?:'|’)ll do|where you(?:'|’)ll make an impact|about (?:the|this) (?:role|job|position)|the role|your impact",
    "ignore": r"salary(?: range)?|compensation(?: and benefits)?|benefits|equal (?:employment )?opportunity(?: employer)?|commitment to equal opportunity|global data privacy notice|data privacy notice|privacy notice|privacy policy|about (?:us|the company)|how to apply|how we work|why this role is special|the team|who we are|our (?:company|organization)|physical demands|work environment|legal notices?|(?:california|washington|colorado|illinois|new york city) pay range|#?li-[a-z0-9-]+",
}
_EXAMPLES = re.compile(r"\b(?:such as|e\.g\.|tools? (?:like|including)|one of|any of|such tools as)\b", re.I)
_PREFERRED = re.compile(r"\b(?:preferred|desirable|nice[- ]to[- ]have|good[- ]to[- ]have|bonus|a plus)\b", re.I)
_REQUIRED = re.compile(r"\b(?:must|required|essential|mandatory|minimum)\b", re.I)


def passages(job):
    rows = []
    section = "intro"
    content = html.unescape(job).replace("\\", "").replace("**", "")
    for line in content.splitlines():
        line = re.sub(r"^[\s•#*-]+", "", line).strip()
        if not line:
            continue
        if line.casefold().strip(": ") in ("job description", "job title", "position"):
            continue
        # Employer-specific About headings are company information, not
        # qualifications. "About the role" remains a duties heading.
        if re.fullmatch(r"about\s+(?!the\s+(?:job|role|position)\b|this\s+(?:job|role|position)\b)(?:[\w&.'-]+\s*){1,4}", line.rstrip(" :–—-"), re.I):
            section = "ignore"
            continue
        # Standalone recruiting markers are not required skills.
        if re.fullmatch(r"(?:#?LI[-_][A-Z0-9_-]+|IND[A-Z0-9]{3,}|REQ[-_#]?\d{4,})", line, re.I):
            continue
        for name, expression in _HEADINGS.items():
            header = re.match(rf"^(?:{expression})(?:\s*[:–—-]\s*|\s*$)", line, re.I)
            if header:
                section = name
                line = line[header.end():].strip()
                break
        if not line or section == "ignore":
            continue
        title = not rows and section == "intro" and len(line.split()) <= 18 and (
            bool(re.search(r"\b(?:engineer|developer|analyst|designer|manager|coordinator|devops|architect|nurse|specialist|director|accountant|technician|scientist|officer|lead)\b", line, re.I))
            and not bool(re.match(r"(we|the ideal|you|our|must|seeking)\b", line, re.I)))
        for sent in re.split(r"[;]|(?<!\be\.g)(?<=[.!?])\s+", line):
            if sent.strip():
                rows.append(Passage(sent.strip().rstrip("."), section, title))
    return rows


def locations(row, terms):
    positions = []
    for term in terms:
        for match in literal_pattern(term).finditer(row.text):
            # "Without the SOC or on-call rotation" describes excluded work,
            # not a competency the employer wants applicants to demonstrate.
            prefix = row.text[max(0, match.start() - 45):match.start()]
            if re.search(r"\b(?:without|no|not requiring|rather than|instead of)\s+(?:(?:a|an|the)\s+)?(?:[\w-]+\s+){0,3}$", prefix, re.I):
                continue
            positions.append(match.start())
    return positions


def score(rows, phrases, cues=()):
    found = []
    for row in rows:
        indexes = locations(row, phrases)
        if not indexes:
            continue
        example = _EXAMPLES.search(row.text)
        is_example = bool(example and min(indexes) >= example.end())
        # In "tools such as A, B, or similar, and has experience building X",
        # X is a separate requirement rather than an alternative to A or B.
        if is_example and re.search(r"(?:\.\s+|\b(?:and|who) (?:has|have|can|will|builds?|designs?)\b|\bor (?:equivalent|similar)\b)", row.text[example.end():min(indexes)], re.I):
            is_example = False
        is_preferred = row.section == "preferred" or bool(_PREFERRED.search(row.text))
        is_required = (row.section == "required" or bool(_REQUIRED.search(row.text))) and not is_preferred
        points = 3 if is_example else 5 if is_preferred else 17 if is_required else 10 if row.section == "duties" else 8
        found.append((points, row.section, is_required and not is_example, row.title, is_example, is_preferred))
    if not found:
        return None
    title_hit = any(item[3] for item in found) or any(row.title and locations(row, cues) for row in rows)
    sections = len({item[1] for item in found if not item[4]})
    points = max(i[0] for i in found) + min(len(found) - 1, 3) * 1.4 + max(0, sections - 1) * 2 + (8 if title_hit else 0)
    required = any(i[2] for i in found)
    if title_hit:
        reason = "Specialty named in the job title."
    elif required:
        reason = "Required qualification" + (" also present in the role description." if sections > 1 else ".")
    elif all(i[4] for i in found):
        reason = "One of several example tools accepted by the posting."
    elif all(i[5] for i in found):
        reason = "Preferred qualification."
    elif sections > 1:
        reason = "Repeated across the role description and its responsibilities."
    else:
        reason = "Named in the role description."
    weight = 5 if required or title_hit or points >= 17 else 4 if points >= 10 else 3 if points >= 7 else 2
    return points, weight, required, reason


_DUTY_VERBS = r"build|design|manage|maintain|coordinate|perform|conduct|implement|oversee|prepare|administer|develop|lead|monitor|review|assess|support|apply|configure|integrate|ensure|operate"
_QUALIFIER = re.compile(r"^(?:(?:demonstrated|hands.on|strong|proven|working|practical|prior) +)*(?:(?:experience|proficiency|expertise|knowledge|skills?) (?:with|in|of) |skilled in )", re.I)
_FRAGMENT_EDGE = re.compile(
    r"^(?:and|or|with|for|to|of|in|on|at|by|from|as|into|across|using|including|such as)\b|"
    r"\b(?:and|or|with|for|to|of|in|on|at|by|from|as|into|across|using|including|such)$", re.I)


def valid_observed_phrase(phrase):
    """Reject clipped prepositional fragments while retaining complete noun phrases."""
    phrase = phrase.strip(" ,.;:()")
    return bool(phrase and not _FRAGMENT_EDGE.search(phrase)
                and normalize(phrase) not in {
                    "not", "tools", "tool", "analyzing", "clouds", "gcs",
                    "modern software", "working relationships",
                    "modern engineering depth", "cross system thinking",
                    "curiosity", "ownership", "att", "ck", "az",
                })


def _listed_requirements(row):
    if row.section not in {"required", "preferred", "duties"}:
        return []
    # A short nominal list is often the whole qualifications section in a
    # posting for a nontechnical occupation. Keep multiword terms together.
    text = _QUALIFIER.sub("", row.text)
    if len(text.split()) > 16 or re.match(
            rf"(?:{_DUTY_VERBS}|experience|ensure|configure|integrate|develop|promote|automate|designing|strong|ability|knowledge|you|the|we|our)\b",
            text, re.I):
        return []
    parts = re.split(r"\s*,\s*|\s+and\s+|\s+or\s+", text)
    result = []
    for part in parts:
        phrase = re.sub(r"^(?:and|or)\s+", "", _QUALIFIER.sub("", part.strip()), flags=re.I)
        phrase = re.sub(r"\s+(?:is |are )?(?:preferred|required|a plus)$", "", phrase, flags=re.I)
        if not valid_observed_phrase(phrase):
            continue
        if not 1 <= len(phrase.split()) <= 4 or not 3 <= len(phrase) <= 65:
            continue
        if re.search(r"\b(?:with|we|you|will|to|that|who|have|has|such|similar|equivalent|skills?|experience|solutions|platforms|systems|ability|ability to|working|degree|required|preferred|strong|proficiency|knowledge|years?|benefits|other|understanding|practices|functions|methodologies|technologies|qualifications)\b", phrase, re.I):
            continue
        if re.match(rf"(?:{_DUTY_VERBS}|designing|building|implementing|the|a|an)\b", phrase, re.I):
            continue
        if re.fullmatch(r"[A-Za-z][\w +/#&.-]*", phrase):
            result.append(phrase)
    return result

def observed_phrases(rows):
    """Find novel named tools, not arbitrary fragments of responsibility prose.

    Generic duties are already extracted independently by
    requirement_extraction.extract(). The old object-after-verb heuristic
    turned "manage multiple concurrent projects" into dozens of unrelated
    fragments, while its sentence-initial capitals produced "Five", "Create",
    "Secure", etc. Here we retain bounded nominal qualifications and unusual
    product acronyms, with a general filter for grammar and boilerplate.
    """
    seen = {}
    for row in rows:
        if row.title or row.section not in {"duties", "required", "preferred"}:
            continue
        tokens = _listed_requirements(row)
        # Novel mixed-case software names and all-caps domain acronyms may be
        # present outside a short list. Discard ordinary initial capitals.
        if len(row.text.split()) <= 22:
            tokens.extend(re.findall(
                r"(?<![\w])(?:[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+|[A-Z]{3,}[0-9]{0,5})(?![\w])",
                row.text))
        for term in tokens:
            term = term.strip(" .,:;")
            if term.isupper() and len(term.split()) == 1:
                # Fragments from ATT&CK and AZ-500 are not independent skills.
                occurrences = list(re.finditer(
                    r"(?<![\w])" + re.escape(term) + r"(?![\w])", row.text))
                if occurrences and all(
                    (m.start() > 0 and row.text[m.start()-1] in "&+-") or
                    (m.end() < len(row.text) and row.text[m.end()] in "&+-") or
                    bool(re.match(r"\s+[A-Z]{2,}&[A-Z]{2,}\b", row.text[m.end():]))
                    for m in occurrences):
                    continue
            if not valid_observed_phrase(term):
                continue
            norm = normalize(term)
            if norm in {
                "ai", "cli", "usd", "eeo", "applicants", "gdpr", "ccpa",
                "salary", "pay range", "eq", "li va1", "psi", "it",
                "other duties", "special projects", "qualifications",
                "skills", "experience", "responsibilities", "certifications",
                "management", "leadership", "supervisors", "alternatively",
                "reliable attendance", "flexibility", "scheduling",
            }:
                continue
            # A normal unqualified word such as "Five" or "Create" cannot
            # stand alone as a technology/skill. Keep invented or compound
            # professional nouns when a source list actually contains them.
            if len(term.split()) == 1 and not re.fullmatch(
                    r"(?:[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+|[A-Z]{3,}[0-9]{0,5})", term):
                # Short stand-alone preferred/required items can legitimately
                # name an unfamiliar brand ("Preferred: Epic", "Salesforce").
                # A lone capital at the START of a full sentence must not
                # become a qualification ("Five years", "Create runbooks").
                if not (row.section in {"preferred", "required"} and
                        row.text.strip(" .,:;") == term and
                        term[:1].isupper() and len(term) >= 4):
                    continue
            seen.setdefault(norm, term)

    return list(seen.values())
