"""The stable, model-independent document contract. All text is plain text."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(Model):
    id: str
    text: str = Field(min_length=1, max_length=4000)
    role_id: str | None = None
    confirmed: bool = True


class Bullet(Model):
    id: str
    text: str = Field(min_length=1, max_length=2000)


class Role(Model):
    id: str
    company: str
    title: str
    dates: str
    location: str = ""
    bullets: list[Bullet] = Field(min_length=1, max_length=30)


class Education(Model):
    institution: str
    dates: str = ""
    degree: str
    detail: str = ""


class Profile(Model):
    name: str = Field(min_length=1)
    contact: str
    roles: list[Role] = Field(min_length=1, max_length=12)
    skills: list[str] = Field(default_factory=list)
    certifications: str = ""
    interests: str = ""
    education: list[Education] = Field(default_factory=list)
    facts: list[Evidence] = Field(default_factory=list)
    source: str = ""
    source_sha256: str = ""

    @model_validator(mode="after")
    def unique_ids(self):
        roles = [r.id for r in self.roles]
        ids = [b.id for r in self.roles for b in r.bullets] + [f.id for f in self.facts]
        if len(roles) != len(set(roles)) or len(ids) != len(set(ids)):
            raise ValueError("Role and evidence IDs must be unique")
        if any(f.role_id and f.role_id not in roles for f in self.facts):
            raise ValueError("Evidence refers to an unknown role")
        return self

    def evidence(self) -> dict[str, Evidence]:
        result = {b.id: Evidence(id=b.id, text=b.text, role_id=r.id)
                  for r in self.roles for b in r.bullets}
        result.update({f.id: f for f in self.facts})
        return result


class Keyword(Model):
    term: str = Field(min_length=1, max_length=100)
    weight: int = Field(default=3, ge=1, le=5)
    # Credentials are legitimate eligibility requirements, but they are not
    # work capabilities.  Keeping them typed prevents degree text from being
    # sent to the accomplishment writer or printed in the Skills row.
    kind: Literal["tool", "skill", "strength", "domain", "credential"] = "skill"
    required: bool = False
    rationale: str = ""


class Candidate(Model):
    origin: Literal["source", "model-example", "offline-example", "edited-example"] = "source"
    parts: list[str] = Field(default_factory=list,max_length=2)
    id: str
    role_id: str
    slot_id: str
    text: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    rationale: str = ""
    quality: float = Field(default=0.8, ge=0, le=1)
    needs_confirmation: bool = False

    @model_validator(mode="after")
    def parts_are_text(self):
        if self.parts and (len(self.parts)!=2 or self.text!=" ".join(self.parts)
                or any(len(p.split())<5 for p in self.parts)):
            raise ValueError("A split alternative must contain two complete statements matching its text")
        return self


class Proposal(Model):
    id: str
    role_id: str
    text: str
    reason: str
    keywords: list[str] = Field(default_factory=list)


class Plan(Model):
    # Optional evidence-backed professional summary generated only when it
    # contributes useful content to a sparse, job-targeted one-page resume.
    summary: str = Field(default="", max_length=220)
    skill_order: list[str] = Field(default_factory=list, max_length=120)
    keywords: list[Keyword] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    proposed_claims: list[Proposal] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ModelSettings(Model):
    draft_mode: Literal["inspiration", "grounded"] = "inspiration"
    wording_policy: Literal["rewrite", "verified"] = "rewrite"
    strategy: Literal["full", "laptop"] = "full"
    provider: Literal["none", "ollama", "openai-compatible"] = "none"
    base_url: str = "http://127.0.0.1:11434"
    model: str = ""
    api_key_env: str = "RESUMEFORGE_API_KEY"
    timeout_seconds: int = Field(default=180, ge=10, le=900)
    max_rounds: int = Field(default=5, ge=1, le=5)


class Template(Model):
    id: str = "abu-letter-v1"
    page_width: float = 612
    page_height: float = 792
    margin_left: float = 40
    margin_right: float = 40
    margin_top: float = 40
    margin_bottom: float = 40
    body_size: float = 12
    leading: float = 13.2
    name_size: float = 32
    heading_size: float = 14
    heading_leading: float = 16
    section_gap: float = 10
    role_gap: float = 7
    bullet_gap: float = 2
    bullet_indent: float = 13
    bottom_tolerance: float = 13.2
    min_bullets_per_role: int = 2


class RunRequest(Model):
    profile: Profile
    edit_request: str = Field(default="", max_length=3000)
    job_description: str = Field(default="", max_length=40000)
    keywords: list[str] = Field(default_factory=list, max_length=100)
    settings: ModelSettings = Field(default_factory=ModelSettings)
    plan: Plan | None = None
    confirmed_claim_ids: list[str] = Field(default_factory=list)
    reviewed_priorities: list[str] | None = Field(default=None, max_length=100)
    draft_edits: dict[str, str] = Field(default_factory=dict, max_length=100)


class Review(Model):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
