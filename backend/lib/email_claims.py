"""Bounded English checks for claims the cold-email schema cannot authorize.

These are pattern checks, not semantic entailment. In particular, a paper's
metadata is not proof that the sender read it, and a resume bullet is not proof
that a file was attached to an email. Skill levels come from student_evidence's
claimable levels; concrete project actions are deliberately not level claims.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

_CLAUSES = re.compile(
    r"[!?;\n]+|\.(?=\s|$)|\b(?:but|however|whereas)\b|"
    r"\b(?:and|which|that|while)(?=\s+(?:i\b|my\b|your\b|you\b|we\b|our\b|hope\b|want\b|plan\b|would\b|can\b))",
    re.IGNORECASE,
)
_DOCUMENT = r"(?:r[eé]sum[eé]|cv|curriculum\s+vitae|transcript|portfolio|cover\s+letter|documents?|files?)"
_ATTACHMENT = re.compile(
    r"\b(?:i(?:\s+have|['’]ve)?\s+(?:already\s+)?(?:attached|enclosed)|"
    r"i(?:\s+am|['’]m)\s+(?:also\s+)?(?:attaching|enclosing))\s+"
    rf"(?:(?:my|the|an?|updated)\s+){{0,2}}{_DOCUMENT}\b|"
    rf"\b(?:please\s+)?(?:find|see)\s+(?:(?:my|the)\s+)?(?:attached|enclosed)\s+(?:(?:my|the)\s+)?{_DOCUMENT}\b|"
    rf"\b(?:attached|enclosed)\s+(?:is|are)\s+(?:(?:my|the)\s+)?{_DOCUMENT}\b|"
    rf"\b(?:my\s+)?{_DOCUMENT}\s+(?:(?:is|are|has\s+been|have\s+been)\s+)?(?:attached|enclosed)\b|"
    rf"\bi(?:\s+have|['’]ve)?\s+included\s+(?:(?:my|the)\s+)?{_DOCUMENT}\s+(?:as\s+an?\s+attachment|with\s+this\s+email)\b|"
    rf"\b(?:my\s+)?{_DOCUMENT}\s+(?:is|are|has\s+been|have\s+been)\s+included\s+with\s+this\s+email\b",
    re.IGNORECASE,
)
_READING = re.compile(
    r"\b(?:i(?:\s+have|['’]ve)?\s+(?:(?:carefully|thoroughly|closely|recently|already)\s+)?"
    r"(?:(?:finished|completed)\s+reading|read|reviewed|studied)|"
    r"(?:after|having)\s+(?:(?:carefully|thoroughly|closely)\s+)?(?:read|reading|reviewed|reviewing|studied|studying))\s+"
    r"(?:through\s+)?(?:(?:all\s+of|the\s+full\s+text\s+of)\s+)?"
    r"(?:(?:your|the|this|a)\s+)?(?:(?:recent|latest|full|entire|published)\s+){0,2}"
    r"(?:papers?|articles?|publications?|manuscripts?|stud(?:y|ies)|work|research)\b",
    re.IGNORECASE,
)


def unsupported_action_claims(text: str) -> list[str]:
    """Reject positive attachment/completed-reading claims, never an offer.

    There is no attachment or reader-confirmation field in the request schema.
    Neither the draft, instruction, source metadata nor an uploaded resume can
    supply such a field. The checked reading objects are scholarly works, not
    ordinary descriptions or future plans to read them.
    """
    findings: set[str] = set()
    for clause in _CLAUSES.split(text):
        attached = _ATTACHMENT.search(clause)
        if attached and not re.search(r"\b(?:no|not|without)\s+(?:(?:a|any|my|the)\s+)?$", clause[:attached.start()], re.I):
            findings.add("unsupported attachment claim")
        read = _READING.search(clause)
        if read:
            prefix = clause[:read.start()].lower()
            # "If/when I read ..." and "I will write after reading ..." do
            # not assert that reading has already happened.
            if re.search(r"\b(?:if|when|once|unless)\s*$", prefix):
                continue
            if re.search(r"\bi\s+(?:will|would|can|could|plan\s+to|hope\s+to)\b", prefix):
                continue
            if re.match(r"after\b", read.group(), re.I) and re.search(r"\bi\s+(?:will|plan\s+to)\b", clause[read.end():], re.I):
                continue
            findings.add("unsupported completed-reading claim")
    return sorted(findings)


# Lower tiers are included as boundaries: in "expert in Python and basic
# knowledge of Rust", the second skill must not inherit the first adjective.
_LEVEL_WORDS = (
    r"strong\s+proficiency|advanced\s+(?:skills?|knowledge)|working\s+knowledge|"
    r"(?:hands-on|working|practical|extensive|some)\s+experience|"
    r"(?:foundational|basic|introductory)\s+(?:exposure|knowledge|skills?|coursework|courses?)|"
    r"expertise|expert|mastery|proficiency|proficient|experienced|experience|"
    r"skilled|adept|fluent|comfortable|familiar|beginner|learning|background"
)
_LEVEL_HEAD = re.compile(
    rf"\b(?P<subject>i(?:\s+am|['’]m|\s+have|['’]ve)|my)\s+"
    rf"(?:(?:an?|very|quite|highly|well|deeply)\s+)*(?P<level>{_LEVEL_WORDS})\b|"
    rf"(?:,|\band)\s+(?:with\s+)?(?:(?:have|am)\s+)?(?P<neg>not\s+|no\s+)?(?:an?\s+)?(?P<next>{_LEVEL_WORDS})\b",
    re.IGNORECASE,
)
_RANK = {"beginner": 0, "experienced": 1, "expert": 2}


def _claim_rank(label: str) -> int:
    label = label.lower()
    if re.search(r"\b(?:expert|expertise|mastery|advanced)\b|strong\s+proficiency", label):
        return 2
    if re.search(r"\b(?:foundational|basic|introductory|familiar|beginner|learning)\b", label):
        return 0
    return 1


def _skill_pattern(name: str) -> str:
    return rf"(?<![\w+#]){re.escape(name)}(?![\w+#])"


def skill_level_violations(text: str, levels: Mapping[str, str]) -> list[str]:
    """Detect explicit first-person level inflation without grading projects.

    Known beginner skills cannot become experience/proficiency, and known
    experienced skills cannot become expertise. A concrete action such as
    "I built a Python parser" is left to the existing student-evidence gate.
    This intentionally does not infer skill aliases or certify arbitrary prose.
    """
    known = [(name, _RANK.get(level, 0), re.compile(_skill_pattern(name), re.I))
             for name, level in levels.items() if name.strip()]
    findings: set[str] = set()
    for clause in _CLAUSES.split(text):
        heads = list(_LEVEL_HEAD.finditer(clause))
        student_context = False
        for index, head in enumerate(heads):
            if head.group("subject"):
                student_context = True
            if not student_context or head.group("neg"):
                continue
            label = head.group("level") or head.group("next")
            if label.lower() == "experience" and re.search(r"\bexample\s+of\s+$", clause[:head.start()], re.I):
                continue
            rank = _claim_rank(label)
            end = heads[index + 1].start() if index + 1 < len(heads) else len(clause)
            claim = clause[head.end():end]
            # A negated object is not claimed: "my experience is not in X".
            if re.match(r"\s+(?:(?:is|lies)\s+)?(?:not|never|no)\b", claim, re.I):
                continue
            mentioned = []
            for name, level, pattern in known:
                for skill in pattern.finditer(claim):
                    if not re.search(r"\b(?:no|not|without)\s+(?:any\s+)?$", claim[:skill.start()], re.I):
                        mentioned.append((name, level))
                        break
            for name, level in mentioned:
                if rank > level:
                    findings.add(f"unsupported skill level: {name}")
            if rank == 2 and not mentioned:
                findings.add("unsupported expertise level")

        # Common inversions do not put the skill after a level word.
        for name, level, _pattern in known:
            skill = _skill_pattern(name)
            patterns = (
                (rf"\bi(?:\s+am|['’]m)\s+(?:an?\s+)?(?P<level>expert|experienced|proficient|skilled)\s+{skill}", None),
                (rf"\bi(?:\s+have|['’]ve)\s+(?:(?P<level>advanced|expert|hands-on|working|practical|extensive)\s+)?{skill}\s+(?P<kind>experience|expertise|proficiency|skills?)\b", 1),
                (rf"\bmy\s+{skill}\s+(?:skills?|knowledge)\s+(?:is|are)\s+(?P<level>advanced|expert|proficient)\b", None),
            )
            for pattern, default in patterns:
                match = re.search(pattern, clause, re.I)
                if match and _claim_rank(match.groupdict().get("level") or match.groupdict().get("kind") or ("experience" if default else "expert")) > level:
                    findings.add(f"unsupported skill level: {name}")
    return sorted(findings)
