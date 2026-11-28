"""End-to-end tailoring: propose, measure, refine, review, export."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import re
import hashlib
from typing import Callable

from .models import Candidate, Evidence, Plan, Profile, RunRequest, Template
from .layout import Typesetter, clean
from .planning import build_plan, keyword_matches, selected_skills, review_content


def merge_plans(old: Plan, new: Plan) -> Plan:
    # Preserve alternatives across iterations, while allowing a model to revise a
    # named alternative. Each slot remains an either/or choice in the optimizer.
    candidates = {c.id: c for c in old.candidates}
    candidates.update({c.id: c for c in new.candidates})
    claims = {p.id: p for p in old.proposed_claims}
    claims.update({p.id: p for p in new.proposed_claims})
    return Plan(summary=new.summary or old.summary,
                skill_order=new.skill_order or old.skill_order,keywords=new.keywords or old.keywords, candidates=list(candidates.values()),
                proposed_claims=list(claims.values()), notes=list(dict.fromkeys(old.notes+new.notes)))


def validate_plan(profile, plan, *, inspiration=False):
    evidence = profile.evidence()
    roles = {r.id for r in profile.roles}
    slots = {b.id: r.id for r in profile.roles for b in r.bullets}
    slots.update({"fact:"+f.id: f.role_id for f in profile.facts})
    ids = set()
    for c in plan.candidates:
        if c.id in ids:
            raise ValueError("Duplicate candidate ID: " + c.id)
        ids.add(c.id)
        if c.role_id not in roles or slots.get(c.slot_id) != c.role_id:
            raise ValueError("Candidate role/slot does not match the profile: " + c.id)
        if c.origin != "source":
            if not inspiration or c.evidence_ids or c.parts or not c.id.startswith("idea:"):
                raise ValueError("An inspiration bullet must be a draft example without evidence citations.")
            continue
        if not c.evidence_ids or any(i not in evidence or evidence[i].role_id != c.role_id for i in c.evidence_ids):
            raise ValueError("Candidate must cite evidence from the same job: " + c.id)
        if any(not evidence[i].confirmed for i in c.evidence_ids):
            c.needs_confirmation = True
    if len(plan.candidates) > 700:
        raise ValueError("Too many candidates; use at most 700 alternatives")


def run(request: RunRequest, directory: Path, progress: Callable[[str], None] | None = None) -> dict:
    from .planning import CALLS
    token=CALLS.set([])
    try:
        return _run(request,directory,progress)
    finally:
        CALLS.reset(token)


def _fit_reconciled_skills(typesetter, profile, plan, initial_skills, required_slots,
                           request, *, verified=False):
    """Allocate Skills and experience together without requiring manual page fit.

    Start with source-backed skills, measure the actual printable bullets,
    then reconcile technical skills demonstrated by *selected* achievements.
    If fitting changes the printed examples, repeat before accepting the
    final skills. A source skill is always eligible; a generated example alone
    cannot make a new skill eligible unless that example was actually chosen.
    """
    from .planning import selected_skills

    def fit_bounded(candidates):
        fitted = typesetter.fit(profile, plan, candidates, required_slots)
        if not fitted.feasible:
            for count in range(len(candidates) - 1, -1, -1):
                trimmed = candidates[:count]
                alternative = typesetter.fit(profile, plan, trimmed, required_slots)
                if alternative.feasible:
                    return alternative, trimmed
        return fitted, candidates

    chosen, skills = fit_bounded(initial_skills)
    previously = set()
    for _ in range(5):
        ranked = selected_skills(
            profile, plan, request.settings, request.edit_request,
            job_description=request.job_description, selected=chosen.selected)
        if verified:
            ranked = [skill for skill in ranked if skill in profile.skills]
        if ranked == skills:
            break
        signature = (tuple(c.id for c in chosen.selected), tuple(skills))
        if signature in previously:
            break
        previously.add(signature)
        chosen, skills = fit_bounded(ranked)

    # One final provenance check: if layout changed which fictional example
    # prints, remove any promoted term not supported by the current selection.
    eligible = selected_skills(
        profile, plan, request.settings, request.edit_request,
        job_description=request.job_description, selected=chosen.selected)
    if verified:
        eligible = [skill for skill in eligible if skill in profile.skills]
    from .skills import _identity
    permitted = {_identity(skill) for skill in eligible}
    if any(_identity(skill) not in permitted for skill in skills):
        reduced = [skill for skill in skills if _identity(skill) in permitted]
        chosen, skills = fit_bounded(reduced)
    # Search discrete, evidence-backed Skills allocations after the bullet
    # selector stabilizes. A different number of relevant skills changes the
    # measured number of wrapped lines; no font, tracking, spacing, or margins
    # are altered. This also helps when one otherwise strong set leaves a
    # large empty band at the bottom of the page.
    if request.job_description.strip() and chosen.feasible:
        from .skills import choices, _identity
        supported = choices(profile, plan.keywords, request.job_description,
                            selected=chosen.selected, model_order=plan.skill_order)
        if verified:
            original_ids = {_identity(x) for x in profile.skills}
            supported = [c for c in supported if _identity(c.label) in original_ids]
        if supported:
            # Do not fill page space with low-value unrelated skills simply
            # because a technology appears somewhere in the original resume.
            cutoff = max(12.0, supported[0].score * .19)
            best = (chosen, skills)
            def fill_value(pair):
                fit, labels = pair
                if not fit.feasible:
                    return (-1, float("-inf"))
                remaining = max(0, fit.bottom_gap - typesetter.t.bottom_tolerance)
                # First minimize unfilled points; use role evidence and stronger
                # skill scores to break ties, not visual spacing tricks.
                usefulness = sum(c.score for c in supported
                                 if _identity(c.label) in {_identity(s) for s in labels})
                return (-remaining, usefulness)
            base_count = len(skills)
            counts = set(range(max(0, base_count - 4),
                               min(18, len(supported), base_count + 5) + 1))
            counts.add(base_count)
            for count in sorted(counts):
                options = [c.label for c in supported[:count]
                           if c.score >= cutoff or count <= 7]
                if len(options) == len(skills) and options == skills:
                    continue
                alternative = typesetter.fit(profile, plan, options, required_slots)
                if (alternative.feasible
                        and len(alternative.selected) >= len(best[0].selected)
                        and fill_value((alternative, options)) > fill_value(best)):
                    best = (alternative, options)
            chosen, skills = best
            eligible = selected_skills(
                profile, plan, request.settings, request.edit_request,
                job_description=request.job_description, selected=chosen.selected)
            permitted = {_identity(s) for s in eligible}
            # Extended labels must be independently sourced. Allow additional
            # highly scored original skills without bypassing provenance.
            permitted.update(_identity(c.label) for c in supported if c.source == "source")
            if any(_identity(s) not in permitted for s in skills):
                skills = [s for s in skills if _identity(s) in permitted]
                chosen, skills = fit_bounded(skills)
    # A short professional summary is a real, evidence-backed content
    # section. Try it only when the page has substantially more than a line
    # of white space, other bullet/skill variants are insufficient, and its
    # measured height stays inside the locked one-page template.
    if (chosen.feasible and not plan.summary
            and chosen.bottom_gap > typesetter.t.bottom_tolerance + 23
            and request.job_description.strip()
            and request.settings.provider != "none" and not verified):
        from .page_content import sourced_summary
        sentence = sourced_summary(profile, plan, chosen.selected)
        if sentence:
            trial_plan = plan.model_copy(update={"summary": sentence})
            trial = typesetter.fit(profile, trial_plan, skills, required_slots)
            if (trial.feasible and len(trial.selected) >= len(chosen.selected)
                    and 0 <= trial.bottom_gap < chosen.bottom_gap - 2):
                plan.summary = sentence
                chosen = trial
    return chosen, skills


def _run(request: RunRequest, directory: Path, progress: Callable[[str], None] | None = None) -> dict:
    progress = progress or (lambda _: None)
    directory.mkdir(parents=True, exist_ok=True)
    # CLI callers can reuse a run directory. Retire a prior managed export
    # before inference, so a timeout cannot leave an obsolete 'ready' file.
    prior = directory/'resume.pdf'
    if prior.exists():
        try:
            old = json.loads((directory/'result.json').read_text())
            owned = old['report']['pdf_sha256'] == hashlib.sha256(prior.read_bytes()).hexdigest()
        except (OSError,ValueError,KeyError,TypeError):
            owned = False
        if not owned:
            raise FileExistsError('Output contains an unrecognized resume.pdf. Choose a new run directory.')
        prior.replace(directory/'previous-checked.pdf')
        (directory/'result.json').replace(directory/'previous-result.json')
    profile = request.profile.model_copy(deep=True)
    # Normalize artifacts from uploaded PDF/DOCX content once, BEFORE
    # generating source-backed alternatives and before semantic validation.
    # Renderer, reviewer and exported document must agree on the same text.
    for role in profile.roles:
        for bullet in role.bullets:
            bullet.text = clean(bullet.text)
    for fact in profile.facts:
        fact.text = clean(fact.text)
    profile.skills = [clean(skill) for skill in profile.skills if clean(skill)]
    profile.certifications = clean(profile.certifications)
    profile.interests = clean(profile.interests)
    progress("Ranking keywords and preparing content alternatives")
    edit_options = {"edit_request":request.edit_request} if request.edit_request else {}
    if request.reviewed_priorities is not None:
        edit_options["reviewed_priorities"] = request.reviewed_priorities
    inspiration = (request.settings.draft_mode == "inspiration" and request.settings.wording_policy != "verified"
                   and bool(request.job_description.strip() or request.keywords or request.reviewed_priorities
                            or (request.plan and any(c.origin != "source" for c in request.plan.candidates))))
    if request.draft_edits and (not inspiration or request.plan is None):
        raise ValueError("Draft edits require an inspiration plan.")
    if request.plan is not None:
        plan = request.plan.model_copy(deep=True)
        if not inspiration:
            plan.candidates = [c for c in plan.candidates if c.origin == "source"]
    elif inspiration:
        from .inspiration import add_examples
        # Gather and rank actual source material first. The writing model receives
        # a different task here: invent an accomplishment for each targeted slot.
        if request.reviewed_priorities is None and request.settings.provider != "none" and request.job_description.strip():
            from .job_analysis import analyze_posting
            rows = analyze_posting(profile, request.job_description, request.keywords, request.settings)
            explicit = {term.strip().casefold() for term in request.keywords if term.strip()}
            actionable = [row for row in rows if row.get("kind") != "credential"
                          or row["term"].casefold() in explicit]
            edit_options["reviewed_priorities"] = [row["term"] for row in
                                                     actionable[:max(7, len(request.keywords))]]
        baseline_settings = request.settings.model_copy(update={"provider": "none"})
        plan = build_plan(profile, request.job_description, request.keywords, baseline_settings, **edit_options)
        plan.proposed_claims = []
        plan.notes = [n for n in plan.notes if not n.startswith(("AI is disabled", "Original bullets"))]
        progress("Writing new accomplishments for the highest-priority capabilities")
        add_examples(profile, plan, request)
    else:
        plan = build_plan(profile, request.job_description, request.keywords, request.settings, **edit_options)
    # Older saved plans may include raw imported text. Normalize the plan's
    # candidates as well, so source matching and PDF verification agree.
    for candidate in plan.candidates:
        if candidate.parts:
            candidate.parts = [clean(part) for part in candidate.parts]
            candidate.text = " ".join(candidate.parts)
        else:
            candidate.text = clean(candidate.text)
    if request.draft_edits:
        from .inspiration import apply_edits
        apply_edits(plan, request.draft_edits)
    # A proposed accomplishment only becomes usable after explicit user confirmation.
    confirmations = set(request.confirmed_claim_ids)
    known = {p.id for p in plan.proposed_claims}
    if len(known) != len(plan.proposed_claims):
        raise ValueError("Proposed claim IDs must be unique")
    if not confirmations <= known:
        raise ValueError("Confirmation refers to an unknown proposed claim")
    roles = {r.id for r in profile.roles}
    for claim in plan.proposed_claims:
        if claim.id not in confirmations:
            continue
        if claim.role_id not in roles:
            raise ValueError("Proposed claim refers to an unknown role")
        if (claim.text.rstrip().endswith("?") or len(claim.text.split()) < 5
            or re.search(r"\b(have you|did you|please confirm|insert|placeholder|TODO)\b|\[[^\]]+\]", claim.text, re.I)):
            raise ValueError("Replace the proposed question or placeholder with an actual accomplishment before confirming it")
        fact_id = "confirmed:" + claim.id
        if fact_id in {b.id for r in profile.roles for b in r.bullets}:
            raise ValueError("Confirmed claim ID conflicts with an existing source bullet")
        profile.facts = [f for f in profile.facts if f.id != fact_id]
        profile.facts.append(Evidence(id=fact_id, text=claim.text, role_id=claim.role_id, confirmed=True))
        plan.candidates = [c for c in plan.candidates if c.id != fact_id]
        plan.candidates.append(Candidate(id=fact_id, role_id=claim.role_id, slot_id="fact:"+fact_id,
                              text=claim.text, evidence_ids=[fact_id], keywords=claim.keywords,
                              rationale="Experience explicitly confirmed by the user", quality=.9))
    profile = Profile.model_validate(profile.model_dump())
    typesetter = Typesetter(Template())
    iterations = []
    best = None
    rejected = set()
    verified = request.settings.wording_policy == "verified"
    rounds = request.settings.max_rounds if request.settings.provider != "none" and not verified else 1
    for index in range(rounds):
        plan.candidates = [c for c in plan.candidates if c.id not in rejected]
        validate_plan(profile, plan, inspiration=inspiration)
        skills = selected_skills(
            profile, plan, request.settings, request.edit_request,
            job_description=request.job_description)
        progress(f"Measuring bullet alternatives and rendering page (pass {index+1}/{rounds})")
        from .edit_constraints import length_spec,unsupported_brief
        length,ambiguous=length_spec(profile,request.edit_request)
        blocked=unsupported_brief(profile,request.edit_request) or ambiguous
        fit_plan=plan
        required_slots=frozenset()
        if inspiration:
            from .inspiration import printable_plan, draft_skills
            fit_plan, required_slots = printable_plan(plan)
            skills = draft_skills(profile, fit_plan, skills)
        if length and not blocked:
            options=[c for c in fit_plan.candidates if c.slot_id!=length.slot or length.allows(c.text)]
            if any(c.slot_id==length.slot and not c.needs_confirmation for c in options):
                fit_plan=fit_plan.model_copy(update={'candidates':options})
                required_slots=required_slots | {length.slot}
            else:
                blocked=f'No admissible {length.direction} version of {length.slot} is available. Generate a grounded alternative.'
        if verified:
            from .wording import verified_material
            fit_plan,skills = verified_material(profile,fit_plan,skills)
        selection, skills = _fit_reconciled_skills(
            typesetter, profile, fit_plan, skills, required_slots, request,
            verified=verified)
        if fit_plan.summary and not plan.summary:
            plan.summary = fit_plan.summary
        pdf_path = directory / f"pass-{index+1}.pdf"
        report = typesetter.render(selection, pdf_path)
        progress(f"Checking text, evidence and page geometry (pass {index+1}/{rounds})")
        if blocked:
            from .models import Review
            review=Review(passed=False,issues=[blocked])
        elif inspiration:
            from .inspiration import check_draft
            review = check_draft(profile, selection.selected, request.settings)
        else:
            review = review_content(profile, selection.selected, request.settings)
        if review.passed and request.edit_request:
            from .laptop import check_request
            review = check_request(request,selection.selected,skills, inspiration=True) if inspiration else check_request(request,selection.selected,skills)
        report["edit_request"] = request.edit_request
        report["strategy"] = request.settings.strategy
        report["wording_policy"] = request.settings.wording_policy
        report["draft_mode"] = "inspiration" if inspiration else "grounded"
        report["priorities"] = [k.term for k in plan.keywords]
        report["inspiration_bullets"] = [c.model_dump(include={"id","role_id","slot_id","text","keywords","origin"})
                                          for c in selection.selected if c.origin != "source"]
        report["quality_review"] = review.model_dump()
        report["warnings"] = list(dict.fromkeys(plan.notes + selection.warnings))
        report["warnings"] += ["Unconfirmed proposed claims are excluded from this PDF."] if any(p.id not in confirmations for p in plan.proposed_claims) else []
        report["model_used"] = request.settings.model if request.settings.provider != "none" else None
        report["semantic_review"] = "model-assisted" if request.settings.provider != "none" else "source-preserving checks"
        if inspiration:
            report["semantic_review"] = "Source evidence checked separately from example wording"
        report["skills"] = skills
        report["professional_summary"] = fit_plan.summary
        report["confirmed_claim_ids"] = sorted(confirmations)
        from .planning import keyword_coverage
        report["keyword_coverage"] = keyword_coverage(plan.keywords, selection.selected, skills)
        changes = []
        for role in profile.roles:
            for bullet in role.bullets:
                chosen = next((c for c in selection.selected if c.slot_id == bullet.id), None)
                if not chosen or chosen.text != bullet.text:
                    changes.append({"role_id":role.id,"before":bullet.text,"after":chosen.text if chosen else "",
                                    "reason":chosen.rationale if chosen else "Lower-ranked content omitted to fit the fixed page"})
        for c in selection.selected:
            if c.slot_id.startswith("fact:"):
                changes.append({"role_id":c.role_id,"before":"","after":c.text,"reason":c.rationale})
        report["changes"] = changes
        iterations.append({"pass":index+1,"bottom_gap_pt":report["bottom_gap_pt"],
                           "geometry_passed":report["geometry_passed"],
                           "full_page_passed":report["full_page_passed"],
                           "quality_passed":review.passed,
                           "selected_ids":[c.id for c in selection.selected]})
        # Select the best completed pass; a failed later attempt cannot silently
        # replace an earlier fit. No failed pass is advertised as export-ready.
        score = (report["geometry_passed"] and review.passed,
                 report["full_page_passed"], report["bounds_passed"], review.passed,
                 -abs(report["bottom_gap_pt"]))
        if best is None or score > best[0]:
            best = (score, pdf_path, report, selection, plan.model_copy(deep=True))
        # A safe one-page PDF is already exportable; additional model passes
        # may improve its visual fill but must never revoke that success.
        if report["geometry_passed"] and review.passed and report["full_page_passed"]:
            break
        if unsupported_brief(profile,request.edit_request) or ambiguous:
            break # Unchanged fixed template or ambiguous instructions cannot be repaired by padding.
        if index + 1 < rounds:
            if inspiration:
                from .example_refit import refit_examples
                progress("Refining example wording using the measured page fit")
                if not refit_examples(request, plan, selection, report, review):
                    break
                continue
            rejected.update(c.id for c in selection.selected if not c.id.startswith('original:') and any(issue.startswith(c.id+':') for issue in review.issues))
            feedback = json.dumps({"layout": {k:report[k] for k in ("bottom_gap_pt","ink_bottom_gap_pt","target_bottom_gap_pt","issues")},
                                   "quality": review.model_dump(), "selected": [c.model_dump() for c in selection.selected],
                                   "instruction":"Provide coherent shorter and longer alternatives using more details from the cited evidence. Keep fonts and margins fixed. Do not invent facts to fill space."})
            progress("Requesting revised wording for the measured remaining space")
            plan = merge_plans(plan, build_plan(profile, request.job_description, request.keywords, request.settings, feedback=feedback, **edit_options))
    _, pdf_path, report, selection, final_plan = best
    report["iterations"] = iterations
    report["unattended_submission_qualified"] = False
    from .planning import CALLS
    report["inference_calls"]=list(CALLS.get() or [])
    # A targeted, model-powered run must finish the visual page-fill brief,
    # not silently export a four-line white band as if it were intentional.
    # Keep a safe one-page draft viewable for diagnosis when no suitable
    # grounded content combination can be found. Untargeted/source-only runs
    # remain exportable because no model is available to create refinements.
    full_required = bool(request.job_description.strip()) and (
        request.settings.provider != "none" and not verified)
    report["full_page_required"] = full_required
    if report["geometry_passed"] and report["quality_review"]["passed"]:
        status = "ready" if (not full_required or report["full_page_passed"]) else "needs_content"
        if status == "needs_content":
            report["warnings"].append(
                "Automatic content refinement exhausted its measured alternatives without "
                "meeting the fixed one-page fill target. The preview is not a finished export.")
    else:
        status = "needs_content" if not report["geometry_passed"] else "needs_review"
    shutil.copyfile(pdf_path, directory/"preview.pdf")
    if status == "ready":
        shutil.copyfile(pdf_path, directory/"resume.pdf")
    else:
        (directory/"resume.pdf").unlink(missing_ok=True)
    result = {"status":status,"profile":profile.model_dump(),"plan":final_plan.model_dump(),"report":report}
    (directory/"result.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    (directory/"selected.json").write_text(json.dumps([c.model_dump() for c in selection.selected],indent=2),encoding="utf-8")
    progress("Ready to export" if status == "ready" else "Revision needed before export")
    return result
