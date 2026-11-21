"""Hold specific new method/purpose links that word overlap cannot establish."""
import re

# We deliberately hold ambiguous paraphrases for review; this is not a test
# of all entailments or a source of factual approvals.
_TOOL_PURPOSE = re.compile(r"\b(?:using|with|in|through|via)\s+([A-Za-z][A-Za-z0-9.+#-]*)\s+(?:in order )?to\s+([A-Za-z][a-z-]+)\b", re.I)
_COMPLETION = re.compile(r"\b(?:to complete|completing|completed)\s+(?:the |a |an |all )?([^.;,]{2,75}?)\s+(scope|rollout|migration|deployment|transition|implementation)\b", re.I)


def issues(source_texts, candidate_text, tool_names):
    source = ' '.join(source_texts).casefold()
    warnings = []
    names = {n.casefold() for n in tool_names}
    for tool, action in _TOOL_PURPOSE.findall(candidate_text):
        if tool.casefold() not in names:
            continue
        # A neighboring tool name and an unrelated second action in the same
        # source sentence do not establish that the tool performed that action.
        if not re.search(r'\b'+re.escape(tool)+r'\s+(?:in order )?to\s+'+re.escape(action)+r'\b', source,re.I):
            warnings.append(f"New purpose attributed to {tool}: the evidence does not explicitly link it to '{action}'.")
    for qualifier, event in _COMPLETION.findall(candidate_text):
        if not re.search(r'\bcomplet(?:e|ed|ing|ion of)\s+(?:the |a |an |all )?'+re.escape(qualifier)+'\\s+'+re.escape(event)+r'\b',source,re.I):
            warnings.append(f"The wording introduces completion of a {event} that the source does not explicitly establish.")
    return warnings
