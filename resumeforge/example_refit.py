"""Refine unlocked example bullets using measurements from the rendered page."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import re

from .inspiration import Stories, printable
from .laptop import ask
from .planning import keyword_matches


def refit_examples(request, plan, selection, report, review):
    groups = defaultdict(list)
    for candidate in plan.candidates:
        groups[candidate.slot_id].append(candidate)
    # Edit the actual printable accomplishment slots. Previously, source-only
    # resumes had no editable slots, so a sparse page was left underfilled even
    # with the model available. Keep user-edited variants inviolate.
    chosen = {c.slot_id: c for c in selection.selected}
    editable = [
        variants for slot, variants in groups.items()
        if slot in chosen
        and all(c.origin != "edited-example" for c in variants)
        and not any(c.needs_confirmation for c in variants)
    ]
    if not editable:
        return False
    from .planning import bullet_relevance
    editable.sort(key=lambda variants: (
        -bullet_relevance(chosen[variants[0].slot_id].text, plan.keywords),
        -len(chosen[variants[0].slot_id].text.split())))
    # Keep the local model's task small enough to produce complete, testable
    # short/long pairs rather than truncating a large JSON response.
    editable = editable[:6]
    roles = {r.id: r.title for r in request.profile.roles}
    rows = []
    for i, variants in enumerate(editable, 1):
        bullet = chosen.get(variants[0].slot_id, variants[0])
        rows.append({"slot": i, "job_title": roles[bullet.role_id], "current_bullet": bullet.text,
                     "focus": bullet.keywords, "alternative_word_counts": [len(c.text.split()) for c in variants]})

    payload = {"slots": rows, "priorities": [k.term for k in plan.keywords],
               "job_requirements": request.job_description[:3500],
               "editing_brief": request.edit_request, "feedback": review.issues,
               "page_feasible": selection.feasible, "unused_points": report["bottom_gap_pt"],
               "needed_lines": max(0, round(max(0, report.get("ink_bottom_gap_pt", report["bottom_gap_pt"]) -
                           report.get("target_bottom_gap_pt", report["template"]["leading"])) / report["template"]["leading"])),
               "line_height_points": report["template"]["leading"]}
    prompt = ("Refine the ACTUAL selected resume bullets to fill exactly one page with meaningful content. "
              "The PDF font, margins, line spacing and typography are LOCKED. A positive unused_points "
              "means more relevant experience must be described; negative means shorten existing prose. "
              "Prefer describing systems, attack paths, investigation steps, decisions, validation, "
              "or consequences actually represented by the current work and target requirements. "
              "For each numbered slot, produce a shorter and a longer COMPLETE professional bullet "
              "about that slot's SAME accomplishment. Source-only bullets must preserve the original "
              "actions, products, scope, metrics and outcomes. Do not transfer achievements between roles, "
              "invent numeric results, duplicate facts or pad with generic adjectives. Do not repeat existing "
              "bullets elsewhere on the page. The longer alternatives should collectively contribute "
              "about needed_lines extra wrapped text lines, but don't artificially elongate every bullet. "
              "Keep all existing numbers exactly; use natural prose without placeholders or labels.")
    added = []
    # A small local model can occasionally produce a superficially valid
    # response that fails the semantic/metric constraints. Try once more with
    # explicit feedback rather than immediately abandoning the page-fill
    # target after the first unusable response.
    for attempt in range(2):
        try:
            variants = ask(request.settings, Stories, prompt, payload, 1600)
        except (RuntimeError, OSError) as exc:
            plan.notes.append(f"Could not refine example wording: {exc}")
            return False
        for story in variants.bullets:
            if not 1 <= story.slot <= len(editable):
                continue
            alternatives = editable[story.slot - 1]
            base = chosen.get(alternatives[0].slot_id, alternatives[0])
            metrics = set(re.findall(r"\d+(?:[.,]\d+)*%?", base.text))
            seen = {c.text.casefold() for c in plan.candidates + added}
            for text in (story.concise, story.detailed):
                new_metrics = set(re.findall(r"\d+(?:[.,]\d+)*%?", text))
                if (not printable(text) or text.casefold() in seen or
                        new_metrics != metrics or
                        (base.keywords and not any(keyword_matches(text, term) for term in base.keywords))):
                    continue
                digest = hashlib.sha256((base.slot_id + "\0" + text).encode()).hexdigest()[:18]
                added.append(base.model_copy(update={
                    "id": "idea:" + digest, "text": text, "origin": "model-example",
                    "rationale": "Measured full-page content refinement based on the selected accomplishment.",
                    "evidence_ids": [], "parts": [],
                    "keywords": [k.term for k in plan.keywords if keyword_matches(text, k.term)]}))
                seen.add(text.casefold())
        if added:
            break
        payload["retry_note"] = ("Your previous suggestion could not be used: it either omitted "
                                 "existing numbers, added new numbers, did not describe the "
                                 "same accomplishment, or duplicated existing wording. "
                                 "Return shorter and longer complete versions without changing "
                                 "the original metrics.")

    plan.candidates.extend(added)
    return bool(added)
