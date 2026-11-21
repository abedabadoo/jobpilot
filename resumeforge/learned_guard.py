"""Small learned warning model for changed bullet/evidence pairs.

No inference API, network, or third-party ML runtime. A low score never approves
a claim. The returned score is a classifier score, not a calibrated probability
of truth. See training/README.md for data provenance and measured error rates.
"""
from __future__ import annotations
from functools import lru_cache
import json
import math
from pathlib import Path
import re


# Features describe semantic moves between the *same* job's cited evidence
# and a proposed sentence, rather than memorizing employers or isolated words.
CUES = {
    "ownership": r"\b(?:led|owned|directed|headed|architected|solely|independently|spearheaded|oversaw|managed the entire)\b",
    "support": r"\b(?:helped|supported|assisted|contributed|partnered|alongside|participated|collaborated|aided|coordinated with|worked with)\b",
    "proposal": r"\b(?:planned|proposed|suggested|recommended|assessed|considered|evaluated|explored|prototyped|drafted|researched|trialed|piloted|tested|simulated|estimated|forecast|projected)\b",
    "shipped": r"\b(?:deployed|launched|rolled out|implemented|delivered|installed|shipped|released|migrated|introduced|put into operation)\b",
    "limited": r"\b(?:sandbox|staging|pilot|test environment|prototype|proof of concept|proof-of-concept|lab|trial|sample|demonstration)\b",
    "scale": r"\b(?:production|enterprise.wide|company.wide|global|all teams|all regions|entire organization|organization.wide|at scale|fleet.wide)\b",
    "outcome": r"\b(?:saved|boosted|improved|increased|cut|halved|reduced|lowered|accelerated|eliminated|prevented|doubled|achieved|avoided)\b",
    "observe": r"\b(?:tracked|documented|observed|measured|reported|reviewed|compiled|monitored|recorded|logged|audited)\b",
    "negative": r"\b(?:not|never|without|unable to|declined|excluded|didn.t|wasn.t)\b",
    "approx": r"\b(?:around|about|roughly|estimated|approximately|nearly|up to|at most|at least|more than|fewer than|over)\b|~",
    "certified": r"\b(?:certified|licensed|accredited)\b",
    "training": r"\b(?:course|studied|coursework|class|workshop|training|exam preparation)\b",
    "universal": r"\b(?:all|every|always|zero|entire|completely|eliminated|100\s*%)\b",
}
RX = {k:re.compile(v,re.I) for k,v in CUES.items()}
_WORDS = re.compile(r"[A-Za-z][A-Za-z'/-]*")
_STOP = frozenset("a about an and as at by for from in into its of on or our than that the their then to using via was were with work worked".split())
_NUMBER = re.compile(r"(?<!\w)\d+(?:[,.]\d+)*(?:\s*%)?")
_UNIT = re.compile(r"(?<!\w)(\d+(?:[,.]\d+)*)\s*(%|percent\b|hours?\b|minutes?\b|seconds?\b|days?\b|weeks?\b|years?\b|months?\b|users?\b|customers?\b|incidents?\b|systems?\b|servers?\b|projects?\b|hosts?\b)",re.I)


def _tokens(s):
    return {w.lower() for w in _WORDS.findall(s) if w.lower() not in _STOP}


def _units(s):
    return {(n,u.lower().rstrip('s').replace('percent','%')) for n,u in _UNIT.findall(s)}


def features(sources: list[str], candidate: str) -> dict[str, float]:
    src = ' '.join(sources)
    sh = {k:bool(rx.search(src)) for k,rx in RX.items()}
    ch = {k:bool(rx.search(candidate)) for k,rx in RX.items()}
    new = lambda k: ch[k] and not sh[k]
    lost = lambda k: sh[k] and not ch[k]
    s, c = _tokens(src), _tokens(candidate)
    ns,nc={x.replace(' ','') for x in _NUMBER.findall(src)},{x.replace(' ','') for x in _NUMBER.findall(candidate)}
    su,cu=_units(src),_units(candidate)
    def signed_unit_swap():
        return any(n == m and u != v for n,u in su for m,v in cu if (m,v) not in su)
    return {k:float(v) for k,v in {
        'new_ownership':new('ownership'), 'support_to_owner':sh['support'] and new('ownership') and not ch['support'],
        'proposal_to_delivery':sh['proposal'] and new('shipped') and not ch['proposal'],
        'trial_to_production':sh['limited'] and new('scale') and not ch['limited'],
        'new_scale':new('scale'), 'new_outcome':new('outcome'),
        'observation_to_outcome':sh['observe'] and new('outcome'),
        'qualification_removed_with_metric':lost('approx') and bool(nc),
        'new_number':bool(nc-ns), 'unit_swapped':signed_unit_swap(),
        'negation_removed':lost('negative'), 'training_to_certification':sh['training'] and new('certified'),
        'new_universal':new('universal'),
        'low_lexical_overlap':(len(s&c)/max(1,len(c)))<.35,
        'high_lexical_overlap':(len(s&c)/max(1,len(c)))>.8,
    }.items()}


@lru_cache(maxsize=1)
def _weights():
    return json.loads((Path(__file__).with_name('data')/'risk-guard.json').read_text(encoding='utf8'))


def assess(sources: list[str], candidate: str, *, weights=None) -> dict:
    model = _weights() if weights is None else weights
    f=features(sources,candidate)
    z=model['bias']+sum(f.get(k,0)*w for k,w in model['weights'].items())
    risk=1/(1+math.exp(-max(-50,min(50,z))))
    flagged=risk >= model['threshold']
    drivers=sorted(((k,w*f.get(k,0)) for k,w in model['weights'].items() if w*f.get(k,0)>0),key=lambda v:-v[1])
    return {'flagged':flagged,'score':round(risk,5),'signals':[k for k,_ in drivers[:3]],'model_id':model['model_id']}
