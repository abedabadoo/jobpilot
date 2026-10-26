"""Extract role terminology without treating an incomplete profile as a ceiling."""

import json
import re
from functools import lru_cache

from bs4 import BeautifulSoup


def _catalog(source):
    return [
        tuple(part.strip() for part in line.split("|"))
        for line in source.splitlines()
        if line.strip()
    ]


TOOLS = _catalog("""
AWS|Amazon Web Services
Azure|Microsoft Azure
Google Cloud|Google Cloud Platform|GCP
Terraform
CloudFormation|AWS CloudFormation
Kubernetes|K8s
Docker
Ansible
Pulumi
Helm
Jenkins
GitHub Actions
GitLab CI|GitLab CI/CD
GitHub
GitLab
Git
Linux|Unix/Linux|Linux/Unix
Windows Server
PowerShell
Python
JavaScript
TypeScript
Java
Go|Golang
Rust
C++
C#
.NET|ASP.NET
Bash
SQL
KQL
SPL
R programming|R language
PostgreSQL|Postgres
MySQL
SQL Server|Microsoft SQL Server
MongoDB
Redis
Snowflake
Databricks
BigQuery
Redshift
dbt
Apache Spark|PySpark
Airflow|Apache Airflow
Kafka|Apache Kafka
Pandas
NumPy
TensorFlow
PyTorch
scikit-learn
OpenAI|OpenAI SDK
Azure OpenAI
Amazon Bedrock|AWS Bedrock
Vertex AI
Google Gemini|Gemini
Claude
ChatGPT
LangChain
LangGraph
LlamaIndex
AutoGen
CrewAI
Semantic Kernel
Hugging Face|HuggingFace
Transformers
MLflow
LangSmith
Langfuse
Arize Phoenix
Pinecone
Weaviate
Chroma|ChromaDB
FAISS
Milvus
Azure AI Foundry
Splunk
Microsoft Sentinel|Azure Sentinel
Datadog
Elastic|Elasticsearch|ELK
Sumo Logic
Chronicle|Google SecOps
IBM QRadar|QRadar
CrowdStrike|CrowdStrike Falcon
SentinelOne
Microsoft Defender|Defender for Endpoint
Wiz
Prisma Cloud
Orca Security
Lacework
Tenable|Nessus
Qualys
Rapid7|InsightVM
Snyk
Semgrep
SonarQube
Checkmarx
Veracode
Burp Suite
OWASP ZAP|Zed Attack Proxy
Nmap
Wireshark
Metasploit
Trivy
Aqua Security
Sysdig
Okta
Microsoft Entra ID|Entra ID|Azure Active Directory|Azure AD
Active Directory|Microsoft Active Directory
SailPoint
CyberArk
BeyondTrust
Ping Identity
JumpCloud
Duo Security
Jamf
Kandji
Intune|Microsoft Intune
OneTrust
Drata
Vanta
ServiceNow
Archer|RSA Archer
AuditBoard
Hyperproof
Secureframe
Jira
Confluence
Slack
Microsoft Teams
Google Workspace
Microsoft 365|Office 365|M365
Salesforce
HubSpot
Marketo
Pardot
Mailchimp
Google Analytics|GA4
Google Tag Manager
Google Ads
Meta Ads
Adobe Analytics
Adobe Experience Manager|AEM
Excel|Microsoft Excel
Power BI
Tableau
Looker
Alteryx
Figma
Sketch
Adobe Photoshop|Photoshop
Adobe Illustrator|Illustrator
Adobe InDesign|InDesign
Canva
Miro
Notion
Airtable
Asana
Monday.com
Workday
SAP
Oracle
NetSuite
QuickBooks
Xero
ADP
Greenhouse
Lever
Ashby
AutoCAD
SolidWorks
Revit
MATLAB
Simulink
ArcGIS
QGIS
SPSS
SAS
Epic
Cerner
Zendesk
Intercom
Gainsight
Amplitude
Mixpanel
Segment
Optimizely
LaunchDarkly
Postman
Selenium
Playwright
Cypress
JUnit
pytest
React
Angular
Vue
Node.js|NodeJS
Next.js
FastAPI
Django
Flask
Spring Boot
Ruby on Rails
Nginx
Apache HTTP Server
Vault|HashiCorp Vault
AWS IAM
EC2|Amazon EC2
S3|Amazon S3
KMS|AWS KMS
RDS|Amazon RDS
CloudTrail|AWS CloudTrail
GuardDuty|Amazon GuardDuty
Security Hub|AWS Security Hub
""")

SKILLS = _catalog("""
Cloud security
Application security|AppSec
Product security
Security engineering
Security operations
Incident response|Incident-response
Threat detection
Threat hunting
Threat modeling|Threat modelling
Vulnerability management
Vulnerability assessment|Vulnerability analysis
Penetration testing|Pentesting|Pen testing
Security monitoring
Detection engineering
Digital forensics
Malware analysis
Network security
Endpoint security
Container security
Data security
Identity governance
IAM|Identity and access management|Identity & access management
SSO|Single sign-on|Single sign on
MFA|Multi-factor authentication|Multifactor authentication
RBAC|Role-based access control
Least privilege|Least-privilege
Zero Trust|Zero-trust
SAML
OIDC|OpenID Connect
OAuth
SCIM
SIEM|Security information and event management
SOAR|Security orchestration automation and response
EDR|Endpoint detection and response
DLP|Data loss prevention
PAM|Privileged access management
GRC|Governance risk and compliance|Governance, risk, and compliance
Risk assessment|Risk assessments
Risk management
Third-party risk|Third party risk|Vendor risk
Vendor security reviews|Vendor security assessments
Security questionnaires
Audit readiness
Audit evidence|Evidence collection|Evidence operations
Control testing
Internal audit|Internal audits
Security policies
Policy development
Compliance automation
SOC 2|SOC2|SOC 2 Type II|SOC 2 Type 2
ISO 27001|ISO/IEC 27001|ISO27001
NIST CSF|NIST Cybersecurity Framework
NIST 800-53|NIST SP 800-53
NIST 800-171|NIST SP 800-171
PCI DSS|PCI-DSS
HIPAA
HITRUST
FedRAMP
SOX|Sarbanes-Oxley
GDPR
CCPA
CMMC
CIS Controls|CIS Benchmarks
MITRE ATT&CK|MITRE ATTACK
Secure SDLC|Secure software development lifecycle
DevSecOps
DevOps
CI/CD|Continuous integration|Continuous delivery
Infrastructure as code|IaC
Security automation
Automation
API security
REST APIs|REST API|RESTful APIs
Encryption
Key management
Secrets management
Access reviews|User-access reviews
Patch management
Configuration management
Disaster recovery
Business continuity
Change management
Technical documentation
Project management
Program management
Product management
Agile
Scrum
Kanban
Stakeholder management
Cross-functional collaboration|Cross functional collaboration
Process improvement
Strategic planning
Data analysis|Data analytics
Statistical analysis
Data visualization|Data visualisation
Data modeling|Data modelling
Data engineering
ETL|Extract transform load
Data governance
Machine learning
Natural language processing|NLP
Generative AI|GenAI
Large language models|LLM|LLMs
Artificial intelligence|AI
Agentic AI
AI agents|Autonomous agents
AI security|Artificial intelligence security
AI governance
Responsible AI
LLM security
MCP|Model Context Protocol
RAG|Retrieval-augmented generation|Retrieval augmented generation
Prompt engineering
Prompt injection
Model evaluation
Model monitoring
AI red teaming
Adversarial machine learning
Vector search
Embeddings
Agent orchestration
Solution architecture|Solutions architecture
Cloud architecture
Technical leadership
Client delivery
Consulting
Financial analysis
Financial reporting
Forecasting
Budgeting
Accounting
Accounts payable
Accounts receivable
Revenue recognition
FP&A|Financial planning and analysis
Sales operations
Sales enablement
Customer success
Account management
Business development
Lead generation
Demand generation
Marketing automation
Campaign management
Content strategy
Content marketing
Copywriting
SEO|Search engine optimization
SEM|Search engine marketing
A/B testing|AB testing
Conversion optimization|Conversion rate optimization
CRM|Customer relationship management
Market research
Brand strategy
UX research|User research
Usability testing
Interaction design
Design systems
Prototyping
Quality assurance|QA testing
Test automation
Regression testing
Performance testing
Procurement
Supply chain management
Inventory management
Logistics
Continuous improvement
Lean manufacturing
Six Sigma
Recruiting|Recruitment
Talent acquisition
Employee relations
Performance management
Payroll
Benefits administration
Clinical research
Patient care
Case management
Medical coding
""")

_CERTIFICATES = {
    "CISSP",
    "CISM",
    "CISA",
    "CRISC",
    "CEH",
    "OSCP",
    "GSEC",
    "GCIH",
    "GCIA",
    "PHD",
    "MBA",
}
_IGNORED_ACRONYMS = {
    "US",
    "USA",
    "EEO",
    "EOE",
    "PTO",
    "USD",
    "BA",
    "BS",
    "MA",
    "MS",
    "HR",
} | _CERTIFICATES


def _plain(value):
    soup = BeautifulSoup(str(value or ""), "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


@lru_cache(maxsize=2048)
def _pattern(term):
    return re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(term).replace(r"\ ", r"\s+") + r"(?![A-Za-z0-9])", re.I
    )


def _matches(entry, text):
    return sum(len(_pattern(alias).findall(text)) for alias in entry)


def extract_keywords(job, profile=None):
    """Return job terms, recorded matches, and additional terms to review.

    Suggested terms remain available for an editable draft. They are not a
    statement that the applicant lacks those skills or holds a certification.
    """
    job = job if isinstance(job, dict) else {}
    title = _plain(job.get("title"))
    source = str(job.get("description") or "")
    footer = re.search(
        r"(?:^|\n)\s*\*{0,2}(?:equal employment|equal opportunity|reasonable accommodations?|requesting accommodations?|privacy notice|pay transparency|recruiting and hiring statement)\b",
        source,
        re.I,
    )
    if footer:
        source = source[: footer.start()]
    if not re.search(r"recruit|talent acquisition", title, re.I):
        source = re.sub(
            r"[^.!?\n]*(?:recruiting process|recruiting and hiring|recruiter|recruitment process)[^.!?\n]*[.!?]?[\n]?",
            " ",
            source,
            flags=re.I,
        )
    description = _plain(source)
    text = title + " " + description
    recorded = json.dumps(profile or {}, ensure_ascii=False)
    found = {}
    for category, entries in (("tools", TOOLS), ("skills", SKILLS)):
        for entry in entries:
            count = _matches(entry, text)
            if count:
                found[entry[0].casefold()] = {
                    "term": entry[0],
                    "category": category,
                    "score": 8 * _matches(entry, title) + count,
                    "matched": bool(_matches(entry, recorded)),
                }
    if isinstance(profile, dict):
        for term in profile.get("skills", []):
            if (
                not isinstance(term, str)
                or not 2 <= len(term) <= 70
                or not _pattern(term).search(text)
            ):
                continue
            key = term.casefold()
            if key not in found and not any(
                _matches(entry, term) and entry[0].casefold() in found for entry in TOOLS + SKILLS
            ):
                found[key] = {"term": term, "category": "skills", "score": 3, "matched": True}
    required = re.finditer(
        r"(?:experience (?:with|in)|proficien(?:cy|t) (?:with|in)|knowledge of|tools?\s*:)\s*([^.;\n]{1,180})",
        description,
        re.I,
    )
    for context in required:
        for token in re.findall(r"\b[A-Z][A-Za-z0-9+#.-]{1,40}\b", context.group(1)):
            if token.upper() in _IGNORED_ACRONYMS or token.casefold() in found:
                continue
            if not (re.search(r"[a-z][A-Z]", token) or (token.isupper() and 2 <= len(token) <= 8)):
                continue
            if any(_matches(entry, token) for entry in TOOLS + SKILLS):
                continue
            found[token.casefold()] = {
                "term": token,
                "category": "tools",
                "score": 2,
                "matched": bool(_pattern(token).search(recorded)),
            }
    ranked = sorted(found.values(), key=lambda item: (-item["score"], item["term"].casefold()))
    ranked = ranked[:24]
    return {
        "terms": [item["term"] for item in ranked],
        "tools": [item["term"] for item in ranked if item["category"] == "tools"],
        "skills": [item["term"] for item in ranked if item["category"] == "skills"],
        "matched": [item["term"] for item in ranked if item["matched"]],
        "suggested": [item["term"] for item in ranked if not item["matched"]],
    }


def canonical_term(value):
    value = str(value).strip()
    for entry in TOOLS + SKILLS:
        if any(value.casefold() == alias.casefold() for alias in entry):
            return entry[0]
    return value
