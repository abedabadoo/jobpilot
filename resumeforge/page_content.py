"""A measured, source-backed professional-summary option for sparse pages.

This is content allocation, not typography manipulation. The summary can only
describe competencies witnessed in actually selected accomplishments and the
current posting. It is omitted whenever it would repeat one concept twice or
make the page exceed the fixed physical boundaries.
"""
from __future__ import annotations

from .planning import keyword_matches, capability_overlap
from .models import Profile, Plan, Candidate


def sourced_summary(profile: Profile, plan: Plan, selected: list[Candidate]) -> str:
    if not profile.roles or not selected:
        return ""
    evidence = " ".join(c.text for c in selected)
    categories = []
    for keyword in plan.keywords:
        if keyword.kind in ("credential", "strength"):
            continue
        term = keyword.term.strip(" .,;:-")
        # An OR requirement lists acceptable alternatives, not expertise the
        # applicant has in *every* branch (e.g., red team OR SOC). Never
        # reproduce the entire list as a claimed professional specialty.
        if " or " in term.casefold() or "," in term:
            continue
        if not 2 <= len(term.split()) <= 6 or len(term) > 44:
            continue
        if not (keyword_matches(evidence, term)
                or capability_overlap(evidence, term) >= .36):
            continue
        normalized = term.casefold()
        if any(normalized == prev.casefold() or
               keyword_matches(normalized, prev) or
               keyword_matches(prev, normalized) for prev in categories):
            continue
        categories.append(term)
        if len(categories) >= 3:
            break
    if len(categories) < 2:
        return ""
    title = profile.roles[0].title.strip()
    if not title or len(title) > 40:
        return ""
    for first, second in ((categories[0], categories[1]),
                          (categories[0], categories[2] if len(categories) > 2 else categories[1])):
        def natural(term):
            return term if any(c.isupper() for c in term[1:]) else term[:1].lower() + term[1:]
        sentence = f"{title} with experience in {natural(first)} and {natural(second)}."
        if len(sentence) <= 117:
            return sentence
    return ""
