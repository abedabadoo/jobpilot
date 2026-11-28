"""Rank confirmed wording without giving the model control over printable text."""
from .models import Plan, Profile


def rank_verified_plan(profile, baseline, job, keywords, settings, brief):
    if job.strip() or keywords or brief.strip():
        from .laptop import rank_sources
        evidence, ordered, _, skills = rank_sources(profile, job, keywords, settings, brief)
        weights = {}
        for rank, (_, i) in enumerate(sorted(ordered, reverse=True)):
            weights.setdefault(evidence[i-1].id, 1 / (rank+1))
        for candidate in baseline.candidates:
            candidate.quality = .65 + .35 * weights.get(candidate.evidence_ids[0], 0)
        baseline.skill_order = list(dict.fromkeys(skills))
    baseline.notes.append("Only exact source wording and explicitly confirmed experience can be printed.")
    return baseline


def verified_material(profile: Profile, plan: Plan, skills: list[str]):
    # Recheck after confirmations and on supplied/saved plans; never trust an
    # 'original:' ID or an evidence citation as proof that wording is unchanged.
    trusted = {(r.id,b.id):(b.id,b.text) for r in profile.roles for b in r.bullets}
    trusted.update({(f.role_id,"fact:"+f.id):(f.id,f.text) for f in profile.facts if f.confirmed and f.role_id})
    def exact(c):
        source = trusted.get((c.role_id,c.slot_id))
        return (source is not None and not c.needs_confirmation and not c.parts and
                source[0] in c.evidence_ids and c.text == source[1])
    return (plan.model_copy(update={"candidates":[c for c in plan.candidates if exact(c)]}),
            [s for s in skills if s in profile.skills])
