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
# "Went through" counts only for "your [whole|entire|full]" paper, article,
# publication or manuscript: "a study abroad program", "this work experience"
# and "your papers' reference list" are not reading the paper.
_READING = re.compile(
    r"\b(?:i(?:\s+have|['’]ve)?\s+(?:(?:carefully|thoroughly|closely|recently|already|also)\s+)?"
    r"(?:(?:finished|completed)\s+reading|read|reviewed|studied)|"
    r"(?:after|having)\s+(?:(?:carefully|thoroughly|closely)\s+)?(?:read|reading|reviewed|reviewing|studied|studying))\s+"
    r"(?:through\s+)?(?:(?:all\s+of|the\s+full\s+text\s+of|the\s+abstracts?\s+of)\s+)?"
    r"(?:(?:your|the|this|a)\s+)?(?:(?:recent|latest|full|entire|whole|published)\s+){0,2}"
    r"(?:papers?|articles?|publications?|manuscripts?|stud(?:y|ies)|work|research)\b|"
    r"\b(?:i(?:\s+have|['’]ve)?\s+(?:(?:carefully|thoroughly|closely|recently|already|also)\s+)?(?:went|gone)|"
    r"(?:after|having)\s+(?:(?:carefully|thoroughly|closely)\s+)?(?:going|gone))\s+through\s+"
    r"(?:(?:the\s+full\s+text|the\s+abstracts?)\s+of\s+)?your\s+(?:(?:whole|entire|full)\s+)?"
    r"(?:paper|article|publication|manuscript)\b",
    re.IGNORECASE,
)


def unsupported_action_claims(text: str, *, confirmed_reading_sentence: str | None = None) -> list[str]:
    """Reject positive attachment/completed-reading claims, never an offer.

    Attachment claims remain unsupported. A server-rendered, target-validated
    reading sentence may be supplied separately; only its exact single occurrence
    is exempt from the reading check, never from attachment checks. The checked reading objects are scholarly works, not
    ordinary descriptions or future plans to read them.
    """
    findings: set[str] = set()
    reading_text = text
    if confirmed_reading_sentence and text.count(confirmed_reading_sentence) == 1:
        reading_text = text.replace(confirmed_reading_sentence, "", 1)
    for clause in _CLAUSES.split(text):
        attached = _ATTACHMENT.search(clause)
        if attached and not re.search(r"\b(?:no|not|without)\s+(?:(?:a|any|my|the)\s+)?$", clause[:attached.start()], re.I):
            findings.add("unsupported attachment claim")
    for clause in _CLAUSES.split(reading_text):
        # Every claim in the clause: skipping a first, conditional one must not
        # skip a later one ("Once I went through your paper, I read your ...").
        for read in _READING.finditer(clause):
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
            break
    return sorted(findings)


# M30: a faculty contact profile is not a posting, so a draft to one may ask
# whether an opening exists but may not refer to a specific opening as existing
# ("your open position", "the RA position in your lab", "the position you
# posted", "your job posting") or say the student is applying for a position.
_ROLE = r"(?:positions?|openings?|vacanc(?:y|ies)|roles?|jobs?|assistantships?)"
# Up to three modifiers ("undergraduate research assistant"), never a
# preposition or clause word that would carry the match into another phrase.
_MODIFIERS = r"(?:(?!(?:of|in|on|at|for|with|about|and|or|to|that|which|is|are|you|your)\b)[a-z][\w'’-]*\s+){0,3}"
_LAB = r"(?:your|the)\s+(?:research\s+)?(?:lab|laboratory|group|team)\b"
_OPENING_CLAIM = re.compile(
    rf"\b(?:your|the|this)\s+(?:(?:lab|group|team)['’]s\s+)?(?:(?:recently|newly|currently|still)\s+)?"
    rf"(?:open|posted|advertised|listed|announced|available|vacant)\s+{_MODIFIERS}{_ROLE}\b|"
    rf"\b(?:your|the|this)\s+{_MODIFIERS}{_ROLE}\s+(?:(?:that|which)\s+)?(?:you|{_LAB})\s+"
    r"(?:(?:have|has|had|recently|just)\s+)*(?:posted|advertised|listed|announced|opened)\b|"
    rf"\b(?:the|this)\s+{_MODIFIERS}(?:positions?|openings?|vacanc(?:y|ies))\s+(?:(?:available|open)\s+)?"
    rf"(?:in|at|with|on)\s+{_LAB}|"
    r"\b(?:your|the|this|a|an)\s+(?:(?:recent|lab['’]s|group['’]s)\s+)?"
    r"(?:job|position|opening|vacancy|hiring|recruitment|recruiting|ra|research\s+assistant)\s+"
    r"(?:posting|post|advertisement|advert|ad|announcement|listing)s?\b|"
    r"\byour\s+(?:(?:lab|group|team)['’]s\s+)?(?:(?:open|current|new|recent)\s+)?(?:research\s+)?(?:opening|vacancy)\b"
    r"(?!\s+(?:remarks?|talk|lecture|keynote|statement|paragraph|of)\b)|"
    r"\b(?:i(?:\s+am|['’]m)\s+(?:(?:writing|reaching\s+out|contacting\s+you|emailing\s+you)\s+to\s+apply|applying|"
    r"interested\s+in\s+applying)|i\s+(?:would\s+like|wish|want)\s+to\s+apply|i\s+hereby\s+apply|my\s+application)\s+"
    rf"(?:for|to)\s+(?:(?:the|your|this)\s+{_MODIFIERS}{_ROLE}\b|an?\s+{_MODIFIERS}{_ROLE}\s+(?:in|at|with|on)\s+{_LAB})",
    re.IGNORECASE,
)
_QUESTION = re.compile(
    r"^\W*(?:(?:and|so|also|then|finally|lastly)\b\W*)?(?:do|does|did|is|are|was|were|could|would|can|will|may|might|"
    r"should|have|has|how|what|when|where|which|who|why|i\s+wonder|i\s+was\s+wondering)\b",
    re.IGNORECASE,
)
_OPENING_CLAUSES = re.compile(r"[;:—]|,\s*(?:and|so)\b|\b(?:but|however|whereas|although|though)\b", re.IGNORECASE)


def unsupported_opening_claims(text: str) -> list[str]:
    """Reject a stated opening or application in a draft to a target with no posting.

    A question ("Do you have any openings?") and a clause under if, whether,
    unless or a negation ("whether you are taking students", "I did not see a
    posting") assert nothing and pass. The caller decides the target has no
    posted opening; this is a bounded English check, not semantic entailment.
    """
    for sentence in re.finditer(r"[^.!?\n]+[.!?]*", text):
        if sentence.group().rstrip().endswith("?") and _QUESTION.match(sentence.group()):
            continue
        for clause in _OPENING_CLAUSES.split(sentence.group()):
            for claim in _OPENING_CLAIM.finditer(clause):
                if not re.search(r"\b(?:if|whether|unless|no|not|never|without)\b|n['’]t\b", clause[:claim.start()], re.I):
                    return ["unsupported opening claim"]
    return []


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
