"""Measurable edit constraints; leave unrecognized semantic claims to review.

These checks are conservative. They do not prove general textual entailment.
An explicitly requested, identifiable shorter/longer bullet must survive page
fitting, and its actual length must move in the requested direction.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
import math
import re

_N = r"\d[\d,]*(?:\.\d+)?"
# Concrete measurement pairs rather than arbitrary numbers in the same passage.
_PAIR = re.compile(rf"\bfrom\s+({_N})\s*(%|(?:[a-z][a-z-]*\s+){{0,2}})\s*to\s+({_N})\s*(%|[a-z][a-z-]*)?",re.I)
_BY = re.compile(rf"\bby\s+({_N})\s*(percentage\s+points?|percent(?:age)?|%|[a-z][a-z-]*)?",re.I)
_MOTION=re.compile(r"\b(?:reduc\w*|lower\w*|decreas\w*|cut|slash\w*|drop\w*|shrank|shrink\w*|fell|improv\w*|rais\w*|increas\w*|grew|grow\w*|boost\w*|rose)\b",re.I)
def _num(s):return Decimal(s.replace(',',''))
def _unit(s):
    u=(s or '').lower().strip().split(' ')[0]
    if u in ('in','during','over','after','before','from','for','by','and','on','at','across','to',''):return ''
    if u in ('%','percent','percentage'):return '%'
    return u.rstrip('s')

# An inclusive deadline and a strictly earlier deadline describe different results.
_NUMBER_WORDS = {word: str(n) for n, word in enumerate(
    ("zero","one","two","three","four","five","six","seven","eight","nine","ten","eleven","twelve"))}
_AMOUNT = r"(?:\d+(?:\.\d+)?|" + "|".join(_NUMBER_WORDS) + r")"
_MEASURE = rf"({_AMOUNT})\s*(%|percent\b|seconds?|minutes?|hours?|days?|weeks?|months?|years?|tickets?|incidents?|releases?)"
_INCLUSIVE = re.compile(rf"(?:<=|≤|\bat most\s+|\bno more than\s+|\bwithin\s+)\s*{_MEASURE}|{_MEASURE}\s+(?:or less|or fewer|or earlier)", re.I)
_STRICT = re.compile(rf"(?:<(?![=])|\bunder\s+|\bless than\s+|\bfewer than\s+)\s*{_MEASURE}", re.I)

def _bounds(pattern, text):
    result = set()
    for match in pattern.finditer(text.casefold()):
        number, unit = (x for x in match.groups() if x is not None)
        result.add((_NUMBER_WORDS.get(number, number), "%" if unit == "percent" else unit.rstrip("s")))
    return result

def comparative_issue(sources,claim):
    """Recognize endpoint-as-change and reversed ranges; no automatic new KPIs."""
    if any(claim==s for s in sources):return None
    source = " ".join(sources)
    if (_bounds(_STRICT, claim) - _bounds(_STRICT, source)) & _bounds(_INCLUSIVE, source):
        return "The proposed strict upper bound excludes a value allowed by the cited result."
    pairs=[];explicit=[]
    for s in sources:
        for seg in re.split(r'[;!?]|\.(?=\s|$)',s):
            if not _MOTION.search(seg):continue
            for ma in _PAIR.finditer(seg):
                a,u,b,v=ma.groups();ua,ub=_unit(u),_unit(v)
                if ua and ub and ua!=ub:continue
                pairs.append((_num(a),_num(b),ua or ub))
            explicit.extend((_num(m[1]),_unit(m[2])) for m in _BY.finditer(seg))
    if not pairs:return None
    for seg in re.split(r'[;!?]|\.(?=\s|$)',claim):
        if not _MOTION.search(seg):continue
        for ma in _PAIR.finditer(seg):
            a,u,b,v=ma.groups();a,b=_num(a),_num(b);unit=_unit(u) or _unit(v)
            compatible=[(x,y) for x,y,t in pairs if not t or not unit or unit==t]
            if (b,a) in compatible and (a,b) not in compatible and a!=b:
                return 'The proposed starting and ending values reverse the cited measurement.'
        for ma in _BY.finditer(seg):
            d=_num(ma[1]);raw=(ma[2] or '').lower();unit=_unit(raw)
            if (d,unit) in explicit:continue
            relevant=[(x,y,t) for x,y,t in pairs if (not unit or not t or unit==t or unit=='%')]
            # A known endpoint is not evidence of an equal absolute/relative
            # change. If multiple ranges might justify this amount, abstain.
            if not relevant or not any(d in (x,y) for x,y,_ in relevant):continue
            def delta(x,y):
                if unit=='%' and 'point' not in raw:
                    return abs(y-x)*100/abs(x) if x else None
                return abs(y-x)
            if all(delta(x,y)!=d for x,y,_ in relevant):
                return 'An ending or starting value has been represented as the amount of change; the cited range does not support that difference.'
    return None

_FORMAT=re.compile(r"\b(?:fonts?|typefaces?|margins?|line spacing|leading|character spacing|letter spacing|bold(?:ing)?|italic(?:s|ize)?|underlin\w*|page size)\b",re.I)
_FORMAT_ACTION=re.compile(r"\b(?:chang\w*|increas\w*|decreas\w*|reduc\w*|enlarg\w*|shrink\w*|widen\w*|narrow\w*|switch\w*|adjust\w*|set|use|apply|make|ignore|override)\b",re.I)
_PRESERVE=re.compile(r"\b(?:unchanged|as is|preserve|retain|maintain|keep|without changing|don['’]t change|do not change|never change)\b",re.I)
_NEGATIVE=re.compile(r"\b(?:exclude|remove|omit|drop|delete|do not include|do not list|do not mention|don['’]t include|don['’]t list|don['’]t mention)\b",re.I)
_POSITIVE=re.compile(r"\b(?:include|add|retain|keep|list|show|mention|highlight)\b",re.I)
def unsupported_brief(profile,brief):
    # Split distinct commands so a preservation instruction about titles cannot
    # give permission to change a different field's typography.
    for clause in re.split(r"[.;!?]|\bbut\b|\band\s+(?=(?:set|use|change|increase|decrease|ignore|adjust|apply|make)\b)",brief,flags=re.I):
        if not(_FORMAT.search(clause) and _FORMAT_ACTION.search(clause)):continue
        if _PRESERVE.search(clause) and not re.search(r'\b(?:ignore|override)\b',clause,re.I):continue
        return 'This brief requests a typography or page-layout change that the fixed template cannot perform.'
    commands=re.split(r"[,.;!?]|\b(?:and|but|then)\s+(?=(?:add|include|retain|keep|list|show|mention|exclude|remove|omit|drop|delete|do not|don[’\x27]t)\b)",brief,flags=re.I)
    seen={}
    for clause in commands:
        neg=_NEGATIVE.search(clause); pos=_POSITIVE.search(clause)
        if not neg and not pos:continue
        acts=0 if neg else 1;act=neg or pos
        field='skills' if re.search(r'\b(?:skill|skills|tools|technologies)\s*(?:row|list|section)?\b',clause,re.I) else 'experience' if re.search(r'\b(?:experience|bullets?)\b',clause,re.I) else 'unspecified'
        for r in profile.roles:
            if r.company and r.company.casefold() in clause.casefold():field='role:'+r.id
        obj=re.split(r"\b(?:in|from|under|into|to|on|as|within)\b",clause[act.end():],maxsplit=1,flags=re.I)[0]
        for val in profile.skills:
            if not re.search(r'(?<![\w+#])'+re.escape(val)+r'(?![\w+#])',obj,re.I):continue
            key=(val.casefold(),field)
            if key in seen and seen[key]!=acts:return f'The brief both includes and excludes {val} in the same section.'
            seen[key]=acts
    return None

_WORD=re.compile(r"[\w+#]+",re.UNICODE)
def word_count(text):return len(_WORD.findall(text))

_STOP=set("a an the this that these those my me our all every one only just about describing describe referenced mentioning name named under in for from on into of to by with while and or but at as remain remains stay stays same original target named include retain keep preserve preserved preserving unchanged job jobs title titles dates date more less fewer shorter longer short brief concise shorten shortenention rewrite reword expand lengthen trim condense elaborat make bullet bullets point points item experience role employer without".split())
def _stem(s):
    for end in ('ations','ation','encies','ing','ed','ies','es','s'):
        if s.endswith(end) and len(s)-len(end)>=4:
            return s[:-len(end)]
    return s
def _tokens(s):return {_stem(t) for t in _WORD.findall(s.casefold()) if t not in _STOP and not t.isdigit() and len(t)>=3}
@dataclass(frozen=True)
class LengthSpec:
    slot:str
    before_words:int
    direction:str
    max_words:int|None=None
    def allows(self,text):
        n=word_count(text)
        return (n<self.before_words if self.direction=='shorter' else n>self.before_words) and (self.max_words is None or n<=self.max_words)

def length_spec(profile,brief):
    lower=brief.casefold()
    if not re.search(r'\b(?:bullet|point)\b',lower):return None,None
    short=bool(re.search(r'\b(?:shorten|trim|condense|compress|shorter|more concise|less wordy)\b',lower))
    long=bool(re.search(r'\b(?:lengthen|expand|elaborate|longer|more detailed)\b',lower))
    if not(short or long):return None,None
    if short and long:return None,'The brief asks for both shorter and longer wording; clarify the intended bullet and direction.'
    if re.search(r"\b(?:do not|don['’]t|never|avoid)\s+(?:shorten|trim|condense|compress|lengthen|expand|elaborate)",lower):return None,None
    rows=[b for r in profile.roles for b in r.bullets]
    by_id=[b for b in rows if re.search(r'(?<!\w)'+re.escape(b.id)+r'(?!\w)',brief,re.I)]
    by_text=[b for b in rows if len(b.text)>12 and b.text.casefold() in lower]
    if len(by_id or by_text)==1:target=(by_id or by_text)[0]
    elif len(rows)==1:target=rows[0]
    else:
        rmatch=[r for r in profile.roles if r.company.casefold() in lower]
        if len(rmatch)==1:rows=rmatch[0].bullets
        ordinal=re.search(r'\b(first|second|third|last)\s+(?:bullet|point)\b',lower)
        if ordinal and (len(rmatch)==1 or len(profile.roles)==1):
            idx={'first':0,'second':1,'third':2,'last':-1}[ordinal[1]]
            if idx>=len(rows):return None,'The requested ordinal bullet does not exist.'
            target=rows[idx]
        else:
            q=_tokens(brief);docs=[_tokens(b.text) for b in rows];n=len(rows)
            freq={t:sum(t in doc for doc in docs) for t in q}
            scores=sorted(((sum(1+math.log((n+1)/(1+freq[t])) for t in q&doc),i) for i,doc in enumerate(docs)),reverse=True)
            highest=scores[0][0];second=scores[1][0] if len(scores)>1 else 0
            if not highest or highest<1.33*second or not any(freq[t]==1 for t in q&docs[scores[0][1]]):
                return None,'The requested bullet could not be identified unambiguously. Name its employer and quote its source text or ID.'
            target=rows[scores[0][1]]
    limit=re.search(r'\b(at most|no more than|within|under|fewer than|less than)\s+(\d+)\s+words?\b',lower)
    max_words=(int(limit[2])-int(limit[1] in ('under','fewer than','less than'))) if limit else None
    return LengthSpec(target.id,word_count(target.text),'shorter' if short else 'longer',max_words),None

def selected_length_issue(spec,selected):
    if not spec:return None
    c=next((c for c in selected if c.slot_id==spec.slot),None)
    if not c:return f'The target {spec.slot} was omitted instead of being rewritten.'
    if not spec.allows(c.text):return f'Requested {spec.direction} wording for {spec.slot}: original {spec.before_words} words, selected {word_count(c.text)} words. A matching rewrite is required.'
    return None
