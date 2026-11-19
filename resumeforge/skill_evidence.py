"""Conservative eligibility for promoting a technical term into Skills.

A positive result is a lexical ownership screen, not proof of expertise. Call
only after recognizing the term and a work verb. Do not use to infer job titles,
production deployment, individual ownership of a team outcome, or metrics.
"""
import re

_ACTOR=r"(?:vendors?|providers?|partners?|customers?|clients?|contractors?|consultants?|colleagues?|supervisors?|managers?|leads?|engineers?|administrators?|admins?|teams?|groups?|departments?|organizations?|maintainers?|owners?|staff|agency|agencies)"
_VERB=r"(?:used?|uses|using|operat\w*|own(?:s|ed)?|configur\w*|deploy\w*|built|build\w*|runs?|ran|maintain\w*|host\w*|install\w*|implement\w*|integrat\w*|manag\w*|support\w*|select\w*|adopt\w*|develop\w*|design\w*|test\w*|administ\w*|creat\w*|automate\w*|monitor\w*|migrat\w*|enforc\w*|validat\w*|remediat\w*|perform\w*|provision\w*|harden\w*|execut\w*|troublesho\w*|wrot\w*|analy[sz]\w*|reconcil\w*|inspect\w*|train\w*|teach\w*|assess\w*|prepar\w*|calculat\w*|schedul\w*|deliver\w*|evaluat\w*|standardiz\w*|enhanc\w*|upgrad\w*|refactor\w*)"
_THIRD=re.compile(r"\b(?:"+_ACTOR+r"|they|he|she)\b(?:\s+(?:that|who|had|have|has|was|were|is|are|solely|primarily|previously|also|already|now|actively|independently|successfully))*\s+"+_VERB+r"\b",re.I)
_SPECULATIVE=re.compile(r"\b(?:never|not|without|would|could|might|planned|planning|proposed|suggested|recommended|anticipated|intended|hoped|potential|prospective|hypothetical|considered|required to learn|evaluated whether|discussed whether|explored whether|proposal to|request to|opportunity to)\b|n['’]t\b",re.I)
_SOFT=re.compile(r"^\s*(?:(?:I|we)\s+)?(?:documented|transcribed|described|reported|recorded|observed|shadowed|recommended|attended|coordinated|communicated|watched)\b",re.I)
_POSSESSIVE=re.compile(r"\b(?:(?:[\w-]+['’]s|[\w-]+s['’]|their|its|"+_ACTOR+r"[- ](?:owned|operated|managed|hosted))\s+)(?:[\w-]+\s+){0,2}$",re.I)
_DIRECT=re.compile(r"^\s*(?:(?:I|we)\s+)?"+_VERB+r"\b",re.I)
_DIRECT_AFTER=re.compile(r"\b(?:I|we)\s+"+_VERB+r"\b",re.I)

def personally_attributed(clause: str,term: str,aliases=()) -> bool:
    """Require at least one plausible personal-use mention; decline ambiguity.

    Optional aliases should be the existing planner's recognized spellings, so
    alias resolution does not depend on a second technology dictionary.
    """
    terms=[v.strip() for v in (term,*aliases) if v.strip()]
    if not terms:return False
    pattern=r"(?<![\w+#])(?:"+"|".join(re.escape(v) for v in sorted(set(terms),key=len,reverse=True))+r")(?![\w+#])"
    marker=re.compile(pattern,re.I)
    # Keep the named actor's verb and object together. Another subject's later
    # 'I wrote the minutes' must never license the earlier vendor's tool.
    segments=re.split(r"[;\n]|(?<=[.!?])\s+|\b(?:while|whereas|but|although|however)\b|(?:,\s*|\band\s+)(?=(?:I|we|they|he|she)\s+)",clause,flags=re.I)
    for segment in segments:
        for match in marker.finditer(segment):
            prefix=segment[:match.start()]
            if _SPECULATIVE.search(segment) or _SOFT.search(segment):continue
            if _THIRD.search(prefix) or re.search(r"\b"+_ACTOR+r"\s+(?:to\s+)?(?:use|deploy|operate|manage|configure|implement)\b",prefix,re.I):continue
            if _POSSESSIVE.search(prefix):continue
            # e.g. 'The Terraform instance was operated by the vendor.'
            if re.search(r"\b(?:operated|managed|configured|deployed|hosted|owned)\s+(?:solely\s+)?by\s+(?:[\w-]+\s+){0,3}"+_ACTOR+r"\b",segment[match.end():],re.I):continue
            # Elliptical resume action ('Configured ...') or explicit applicant
            # subject. A noun-led third-party statement has neither.
            if _DIRECT.search(segment) or _DIRECT_AFTER.search(segment):return True
    return False
