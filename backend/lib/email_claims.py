"""Bounded English checks for claims the cold-email schema cannot authorize.

These are pattern checks, not semantic entailment. In particular, a paper's
metadata is not proof that the sender read it, and a resume bullet is not proof
that a file was attached to an email. Skill levels come from student_evidence's
claimable levels; concrete project actions are deliberately not level claims.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping

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
# "Went through" counts only for "your" or "this" paper or work: "I went
# through a study abroad program" or "the research process" reads nothing.
_READING = re.compile(
    r"\b(?:i(?:\s+have|['’]ve)?\s+(?:(?:carefully|thoroughly|closely|recently|already|also)\s+)?"
    r"(?:(?:finished|completed)\s+reading|read|reviewed|studied)|"
    r"(?:after|having)\s+(?:(?:carefully|thoroughly|closely)\s+)?(?:read|reading|reviewed|reviewing|studied|studying))\s+"
    r"(?:through\s+)?(?:(?:all\s+of|the\s+full\s+text\s+of|the\s+abstracts?\s+of)\s+)?"
    r"(?:(?:your|the|this|a)\s+)?(?:(?:recent|latest|full|entire|whole|published)\s+){0,2}"
    r"(?:papers?|articles?|publications?|manuscripts?|stud(?:y|ies)|work|research)\b|"
    r"\b(?:i(?:\s+have|['’]ve)?\s+(?:(?:carefully|thoroughly|closely|recently|already|also)\s+)?(?:went|gone)|"
    r"(?:after|having)\s+(?:(?:carefully|thoroughly|closely)\s+)?(?:going|gone))\s+through\s+"
    r"(?:(?:the\s+full\s+text|the\s+abstracts?)\s+of\s+)?(?:your|this)\s+(?:(?:recent|latest|full|entire|whole|published)\s+){0,2}"
    r"(?:papers?|articles?|publications?|manuscripts?|work)\b",
    re.IGNORECASE,
)
# M129: a claim about the one paper ("your/the/this [whole|entire|full] paper",
# its full text or its abstract) that claims no more than the confirmed
# sentence repeats the student's attestation; reading an abstract is below
# reading the paper. Other papers, "recent" ones and a body of work never are.
_ONE_PAPER = re.compile(
    r"\s(?:the\s+(?:full\s+text|abstract)\s+of\s+)?(?:your|the|this)\s+(?:(?:whole|entire|full)\s+)?"
    r"(?:paper|article|manuscript|publication|study)$",
    re.IGNORECASE,
)


def _reading_rank(claim: str) -> int:
    return 1 if re.search(r"\babstracts?\s+of\b", claim, re.I) else 2


def unsupported_action_claims(text: str, *, confirmed_reading_sentence: str | None = None) -> list[str]:
    """Reject positive attachment/completed-reading claims, never an offer.

    Attachment claims remain unsupported. A server-rendered, target-validated
    reading sentence may be supplied separately; only its exact single occurrence
    is exempt from the reading check, never from attachment checks, and only
    then may a claim about that one paper repeat its level or a lower one. The
    checked reading objects are scholarly works, not ordinary descriptions or
    future plans to read them.
    """
    findings: set[str] = set()
    reading_text, ceiling = text, 0
    if confirmed_reading_sentence and text.count(confirmed_reading_sentence) == 1:
        reading_text = text.replace(confirmed_reading_sentence, "", 1)
        # The fixed prefix states the level; the quoted title never does.
        confirmed = _READING.match(confirmed_reading_sentence)
        if confirmed and _ONE_PAPER.search(confirmed.group()):
            ceiling = _reading_rank(confirmed.group())
    for clause in _CLAUSES.split(text):
        attached = _ATTACHMENT.search(clause)
        if attached and not re.search(r"\b(?:no|not|without)\s+(?:(?:a|any|my|the)\s+)?$", clause[:attached.start()], re.I):
            findings.add("unsupported attachment claim")
    for clause in _CLAUSES.split(reading_text):
        for read in _READING.finditer(clause):
            prefix = clause[:read.start()].lower()
            # "If/when I read ..." and "I will write after reading ..." do
            # not assert that reading has already happened.
            if re.search(r"\b(?:if|when|once|unless)\s*$", prefix):
                break
            if re.search(r"\bi\s+(?:will|would|can|could|plan\s+to|hope\s+to)\b", prefix):
                break
            if re.match(r"after\b", read.group(), re.I) and re.search(r"\bi\s+(?:will|plan\s+to)\b", clause[read.end():], re.I):
                break
            if _ONE_PAPER.search(read.group()) and _reading_rank(read.group()) <= ceiling:
                continue
            findings.add("unsupported completed-reading claim")
            break
    return sorted(findings)


# M33 (owner decision 2026-10-12): a paper is named only when the student chose
# it. The reply check is one rule: a reply may not quote the full title of an
# unchosen verified paper unless the student supplied that title for this
# request. A stated reaction to a paper is left to the prompt. Titles compare
# after NFKC, casefolding, one quotation-mark and dash style and single spaces;
# a title's words are its tokens with at least one letter or digit.
_COMPARABLE = str.maketrans({**dict.fromkeys("“”„‟", '"'), **dict.fromkeys("‘’‛", "'"),
                             **dict.fromkeys("‐‑‒–—―", "-")})


def _comparable(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).translate(_COMPARABLE).casefold())


def _title_core(title: str) -> str:
    return _comparable(title).strip(" \"'.,;:!?")


def unchosen_paper_claims(text: str, titles: Iterable[str], *, student_text: str = "",
                          chosen_title: str | None = None) -> list[str]:
    """Reject a reply that quotes the full title of a paper the student did not choose.

    ``titles`` are the professor's verified paper titles. A title counts only
    inside quotation marks (straight or curly, single or double; a closing
    punctuation mark may sit inside them). A title under three words, the
    chosen paper's title, a title found inside an occurrence of the chosen
    title (which may itself quote another title), and a title that also appears
    anywhere in ``student_text`` (what the student supplied for this request)
    never count. An unquoted, partial or paraphrased title is not detected.
    """
    norm, supplied = _comparable(text), _comparable(student_text)
    chosen = _title_core(chosen_title or "")
    inside_chosen = [match.span() for match in re.finditer(rf"(?<!\w){re.escape(chosen)}(?!\w)", norm)] if chosen else []
    for title in titles:
        core = _title_core(str(title))
        if sum(any(char.isalnum() for char in word) for word in core.split()) < 3 or core == chosen:
            continue
        for quoted in re.finditer(rf"(?<!\w)[\"'] ?({re.escape(core)})[.,;:!?]? ?[\"'](?!\w)", norm):
            if any(start <= quoted.start(1) and quoted.end(1) <= end for start, end in inside_chosen):
                continue
            if not re.search(rf"(?<!\w){re.escape(core)}(?!\w)", supplied):
                return ["names a paper the student did not choose"]
    return []


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
