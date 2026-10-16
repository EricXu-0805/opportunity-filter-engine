"""What the student may be said to have, as distinct from what we inferred.

``src/evidence.py`` is the provenance authority for the TARGET side: what a
source stated, how sure we are, and what may therefore be printed about a lab.
This is its counterpart for the STUDENT side, and it exists because the two
generators that speak in the student's voice — the cold email and the tailored
résumé — were each reading a skill's level directly and reaching opposite
conclusions from the same data.

The rule it enforces is narrow and one-directional: a level the student did not
choose cannot authorise a claim about them. It says nothing about whether a
skill may be SCORED — a weaker signal inside a ranking is not a claim made to a
person, and the ranker deliberately keeps reading the stored level.

Why this was needed. A skill the student TYPES starts at ``beginner``
(SkillTags.tsx). Every skill a regex found in their uploaded PDF was stamped
``experienced``, as was every language the GitHub import read off a repo — so a
substring match outranked the student's own statement about themselves, and
arrived at a professor as "I have hands-on experience with X". The résumé
extractor is a bare presence test over a fixed list, so "Relevant coursework:
Introduction to Python" and "hoping to learn PyTorch" both qualified.

The same holds for courses and interests (checklist M13). A course is
completed, in progress, planned or of unknown status, and only the first may be
said to be done; every course stored before statuses existed is unknown, and
is mentioned only neutrally until the student marks it (owner decision
2026-10-16). An interest is never experience. The cold email gate reads both
rules from here (bounded patterns, not semantic verification); Tailor, Renovate
and Ask-AI read each course's status, and the ranker which courses count as
taken.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from functools import lru_cache

DEFAULT_LEVEL = "beginner"

# The one level that provenance-less data can still be trusted at.
#
# Nothing in this tree writes "expert" except SkillTags.cycleLevel — the badge
# the student clicks — while BOTH import sites stamped exactly "experienced".
# So a stored "expert" is provably two clicks, and a stored "experienced" is
# byte-identical between one click and the bug. The ambiguous value fails
# closed; the provable one does not.
#
# The cost of failing closed is real: a student who did click once to
# "experienced" is quietly held back too. It is paid back in the form, which
# marks every unconfirmed skill and restores it in one click — nobody is muted
# without being told, and no migration has to guess at data that cannot be
# disambiguated.
_PROVABLY_CHOSEN_LEGACY_LEVEL = "expert"


def _field(raw: object, name: str) -> object:
    if isinstance(raw, dict):
        return raw.get(name)
    return getattr(raw, name, None)


def skill_level_is_the_students_own(raw: object) -> bool:
    """Whether the student stands behind this skill's LEVEL, not just its name.

    A bare string carries no level at all, so it defaults to ``beginner`` and
    there is nothing to overstate — it reads as theirs.
    """
    if isinstance(raw, str):
        return True
    if _field(raw, "confirmed") is True:
        return True
    if _field(raw, "source") is not None:
        return False
    return str(_field(raw, "level") or "") == _PROVABLY_CHOSEN_LEGACY_LEVEL


def claimable_skill_level(raw: object) -> str:
    """The level this skill may be spoken at, which is not always the one stored.

    An unconfirmed import reads as ``beginner``, so every generator says
    "foundational exposure to X" rather than "experience with X". The skill is
    still named — it IS on their résumé, and the overstatement was the verb.
    """
    if isinstance(raw, str):
        return DEFAULT_LEVEL
    level = _field(raw, "level") or DEFAULT_LEVEL
    return str(level) if skill_level_is_the_students_own(raw) else DEFAULT_LEVEL


def skill_name(raw: object) -> str:
    if isinstance(raw, str):
        return raw
    name = _field(raw, "name")
    return str(name) if name else str(raw)


def claimable_skill_levels(raw_skills: list) -> dict[str, str]:
    """``{name: level}`` for every generator that speaks in the student's voice."""
    return {
        skill_name(s): claimable_skill_level(s)
        for s in (raw_skills or [])
        if skill_name(s)
    }


# ---------------------------------------------------------------------------
# Courses (checklist M13).
#
# Every course used to be one bare string that each consumer read as taken: the
# email template wrote "Relevant coursework includes BIOE 498" for a course the
# student only planned, and "I have completed BIOE 498" passed every gate. A
# course now carries one of four statuses, and the status decides the words.

COURSE_STATUSES = ("completed", "in_progress", "planned", "unknown")
COURSE_SOURCES = ("resume", "manual")

# How a course of each status may be stated in the student's voice. Unknown is
# every course stored before statuses existed: named, never said to be done.
COURSE_STATEMENTS = {
    "completed": "I have completed {courses}.",
    "in_progress": "I am currently taking {courses}.",
    "planned": "I plan to take {courses}.",
    "unknown": "My coursework includes {courses}.",
}

# The same rule, as a model is told it once for each status's courses.
COURSE_STATUS_LABELS = {
    "completed": "completed (may be stated as completed or taken)",
    "in_progress": "in progress (state only as currently taking; never as completed)",
    "planned": "planned (state only as planning to take; never as taken, in progress or experience)",
    "unknown": ("status not given: the student has not said whether they took these (mention only neutrally, "
                "as 'my coursework includes'; never as taken, in progress or not taken)"),
}

# Statuses whose course may support a claim of the student's competence. A
# planned course is not knowledge yet, and an unknown one may only be named.
COMPETENCE_COURSE_STATUSES = frozenset({"completed", "in_progress"})


def course_key(name: object) -> str:
    """One identity for a course however it is spaced or cased: "CS 225" is "cs225"."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(name)).casefold() if ch.isalnum())


def _course_status(raw: object) -> str:
    status = _field(raw, "status")
    return status if isinstance(status, str) and status in COURSE_STATUSES else "unknown"


def course_entries(profile: object) -> list[dict]:
    """Every course the profile lists, each with exactly one status.

    ``courses`` entries come first, the first of one name winning. A legacy
    ``coursework`` string becomes an ``unknown`` entry unless ``courses`` names
    the same course: an old client's list never outranks the status the
    student chose, and is never read as completed. Legacy strings are kept as
    written and in order, so a profile without ``courses`` lists what it did.
    """
    entries: list[dict] = []
    seen: set[str] = set()
    for raw in _field(profile, "courses") or []:
        name = str(_field(raw, "name") or "").strip()
        key = course_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        source = _field(raw, "source")
        entry = {"name": name, "status": _course_status(raw),
                 "source": source if source in COURSE_SOURCES else "resume"}
        evidence = _field(raw, "evidence")
        if isinstance(evidence, str) and evidence.strip():
            entry["evidence"] = evidence.strip()
        entries.append(entry)
    for raw in _field(profile, "coursework") or []:
        name = str(raw).strip()
        key = course_key(name)
        if key and key not in seen:
            entries.append({"name": name, "status": "unknown", "source": "resume"})
    return entries


def courses_counted_as_taken(profile: object) -> list[str]:
    """Course names the ranker may score as taken: every course but a planned one.

    In-progress and unknown courses count as every named course did before
    statuses existed (an entry with no letter or digit, such as "-", is no
    course and no longer counts); a planned course is not preparation the
    student has.
    """
    return [entry["name"] for entry in course_entries(profile) if entry["status"] != "planned"]


def _joined(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def course_sentences(entries: Iterable[Mapping], *, limit: int = 3) -> str:
    """At most ``limit`` courses, each stated only as its status allows."""
    chosen = list(entries)
    order = ("completed", "in_progress", "unknown", "planned")
    chosen = sorted(chosen, key=lambda entry: order.index(entry["status"]))[:limit]
    return " ".join(
        COURSE_STATEMENTS[status].format(courses=_joined(names))
        for status in order
        if (names := [entry["name"] for entry in chosen if entry["status"] == status])
    )


def course_brief(entries: Iterable[Mapping]) -> dict[str, list[str]]:
    """The courses grouped by status, each status's rule stated once, for a model's student brief."""
    entries = list(entries)
    return {COURSE_STATUS_LABELS[status]: names for status in COURSE_STATUSES
            if (names := [entry["name"] for entry in entries if entry["status"] == status])}


def course_context_line(entries: Iterable[Mapping]) -> str:
    """``CS 225 (completed), CS 446 (planned)``: each course beside its status."""
    return ", ".join(f"{entry['name']} ({entry['status'].replace('_', ' ')})" for entry in entries)


# A course is identified by its code or its listed title: where the text names
# a listed course (its whole name, a catalog code inside it, or its title — the
# name without its code), any catalog code at all ("CS 446"), or a title with
# its code in parentheses ("Machine Learning (CS 446)"), which is the course its
# code names. An unlisted course has no status, so nothing may be claimed done
# about it.
_CODE_TEXT = r"[A-Z]{2,6}[ \-]?\d{2,4}[A-Z]?"
_CODE = re.compile(rf"(?<![A-Za-z0-9]){_CODE_TEXT}(?![A-Za-z0-9])")
_TITLE_WORD = r"(?:[A-Z][\w'’&-]*|of|to|for|the|in|and|with|&)"
_TITLE_CODE = re.compile(rf"[A-Z][\w'’&-]*(?:\s+{_TITLE_WORD}){{0,7}}\s*\(\s*(?P<code>{_CODE_TEXT})\s*\)")
_YEARLIKE = re.compile(r"(?:19[5-9]\d|20[0-4]\d)$")


@lru_cache(maxsize=4096)
def _alias_pattern(name: str) -> re.Pattern | None:
    words = re.findall(r"[^\W_]+", name)
    if not words:
        return None
    pattern = re.escape(words[0])
    for before, word in zip(words, words[1:], strict=False):
        joint = r"[\W_]+" if before[-1].isdigit() == word[0].isdigit() else r"[\W_]*"
        pattern += joint + re.escape(word)
    return re.compile(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", re.I)


def _course_aliases(entries: Iterable[Mapping]) -> list[tuple[re.Pattern, Mapping]]:
    aliases: list[tuple[int, re.Pattern, Mapping]] = []
    for entry in entries:
        name = str(entry.get("name") or "")
        title = _CODE.sub(" ", name) if re.search(r"[^\W\d_]", _CODE.sub(" ", name)) else ""
        for alias in dict.fromkeys([name, *(m.group() for m in _CODE.finditer(name)), title]):
            pattern = _alias_pattern(alias)
            if pattern is not None:
                aliases.append((len(alias.strip()), pattern, entry))
    return [(pattern, entry) for _, pattern, entry in sorted(aliases, key=lambda item: -item[0])]


# "My coursework includes X": the neutral listing every course may take.
_LISTING = re.compile(r"\bmy\s+(?:\w+\s+)?(?:coursework|courses)\s+(?:includes?|spans?)\b", re.I)


def mask_course_names(text: str, entries: Iterable[Mapping]) -> str:
    """``text`` with each listed course a coursework listing names blanked.

    "My coursework includes Machine Learning" names the student's course
    without claiming anything about it, whatever its status, so the competence
    check never reads those names. Anywhere else a course's name is ordinary
    words: only a completed or in-progress course is in the student's
    competence corpus, so only its name may stand for its topic, and "I have
    experience with machine learning" is refused for a planned or unmarked
    "Machine Learning" course.
    """
    aliases = _course_aliases(entries)
    spans = {(head.end() + start, head.end() + end)
             for head in _LISTING.finditer(text)
             for _name, entry, start, end in _courses_named(text[head.end():], aliases, bare=False)
             if entry is not None}
    kept, pos = [], 0
    for start, end in sorted(spans):
        if end > pos:
            kept.append(text[pos:max(start, pos)] + " ")
            pos = end
    return "".join(kept) + text[pos:]


_CLAUSE = re.compile(
    r"[.!?;\n。！？；]+(?=\s|$|[^\x00-\x7f])|\b(?:but|however|whereas|although|though)\b|"
    r"\b(?:and|which|while)(?=\s+(?:i\b|my\b|we\b|our\b))",
    re.I,
)
_ADVERBS = r"(?:(?:already|successfully|recently|also|previously|just|both|currently|presently|now)\s+)*"
# Completion: "I (have) completed / took / have taken / passed", "after
# completing", "completed coursework", "courses I have taken", and a résumé
# line opening on the verb. Current enrolment: "I am (currently) taking /
# enrolled in", "current courses". "While taking" says only that the course
# was taken at some point, finished or not. Bounded English and Chinese
# patterns, not semantic entailment.
_DONE_HEAD = re.compile(
    rf"\b(?:i|we)\s+(?:have\s+|['’]ve\s+|had\s+|['’]d\s+)?{_ADVERBS}(?:completed|finished|passed|took|taken)\b"
    rf"|\b(?:have|has|['’]ve|had)\s+{_ADVERBS}(?:completed|finished|passed|taken)\b"
    r"|\b(?:after|having|upon|since)\s+(?:successfully\s+)?(?:completing|finishing|taking|passing|completed|finished|taken|passed)\b"
    r"|\b(?:completed|finished|past|previous|prior)\s+(?:coursework|courses?|class(?:es)?)\b"
    r"|\b(?:coursework|courses?|class(?:es)?)\s+(?:that\s+|which\s+)?i\s*(?:have\s+|['’]ve\s+)?(?:already\s+)?"
    r"(?:completed|finished|passed|took|taken)\b"
    r"|^\s*(?:completed|finished|took|passed)\b"
    r"|(?:已经|已)?(?:修读过|修过|学过|上过|修完了?|学完了?|上完了?|已修|已完成|完成了)",
    re.I,
)
# A bare verb, mid-clause and with no subject, is judged only against an object
# that starts with the course: "the project was completed in CS 446" is not.
_BARE_DONE = re.compile(r"\b(?:completed|finished|took|taken|passed)\b", re.I)
_NOW_HEAD = re.compile(
    rf"\b(?:i\s+am|i['’]m|am|we\s+are|we['’]re)\s+{_ADVERBS}(?:taking|enrolled\s+in|registered\s+for)\b"
    r"|\b(?:currently|presently|now)\s+(?:taking|enrolled\s+in|registered\s+for)\b"
    r"|\b(?:current|ongoing)\s+(?:coursework|courses?|class(?:es)?)\b"
    r"|\b(?:coursework|courses?|class(?:es)?)\s+(?:that\s+|which\s+)?i\s*(?:am|['’]m)\s+(?:currently\s+)?taking\b"
    r"|^\s*(?:currently\s+)?(?:taking|enrolled\s+in)\b"
    r"|正在(?:修读|修|上|学习|学)|(?:目前|本学期|这学期)(?:在|正在)?(?:修读|修|上|学习|学)",
    re.I,
)
_WHILE_TAKING = re.compile(r"\bwhile\s+(?:also\s+)?taking\b", re.I)
# Each claim shape and the statuses whose course it may name.
_HEADS = ((frozenset({"completed"}), _DONE_HEAD), (frozenset({"in_progress"}), _NOW_HEAD),
          (frozenset({"completed", "in_progress"}), _WHILE_TAKING))
_NEGATED = re.compile(
    r"(?:\b(?:not(?!\s+only\b)|never|no|yet|without)\b|n['’]t|没有|没|未|尚未)\s*(?:\w+\s+){0,2}$", re.I)
_NOT_YET = re.compile(
    r"\b(?:will|would|plan(?:ning)?\s+to|hope\s+to|intend\s+to|expect\s+to|going\s+to|unless|until|if)\b"
    r"|\bonce(?=\s+(?:i|we)\b)|将|计划|打算|准备",
    re.I,
)
_FUTURE = re.compile(
    r"\b(?:next|upcoming|coming)\s+(?:semester|term|quarter|year|fall|spring|summer|winter)\b"
    r"|\bin\s+the\s+(?:fall|spring|summer|winter|future)\b|下学期|明年|将来",
    re.I,
)
# A future time phrase that opens a clause, or stands right after its courses.
_FUTURE_AT = re.compile(rf"[\s,]*(?:(?:this|starting|beginning|from)\s+)?(?:{_FUTURE.pattern})", re.I)
# Where the verb phrase before a claim's verb can start: after a comma or a
# conjunction, at the word before its subject ("if" in "if I took").
_STOP = re.compile(r"[,;:()，、：]|\b(?:and|or|but|so|that|which|who)\b", re.I)
_SUBJECT = re.compile(r"\b(?:i|we)\b|我们?", re.I)
# A verb with someone else as its subject: "students who have completed".
_OTHER_SUBJECT = re.compile(
    r"\b(?:you|they|he|she|students|applicants|candidates|undergraduates|those|anyone|others)"
    r"(?:\s+(?:who|that))?\s+(?:\w+\s+)?$", re.I)
_SEP = re.compile(r"(?:[\s,;/&()\[\]\-–—'’\"“”《》「」、，]|和|与|及|以及|了|过|的)+")
_FILLER = re.compile(
    r"(?:the|my|a|an|both|two|three|four|several|relevant|related|introductory|intro|advanced|"
    r"upper[- ]level|graduate|undergraduate|core|required|foundational|following|and|or|plus|"
    r"as\s+well\s+as|also)\b",
    re.I,
)
_COURSE_NOUN = re.compile(r"(?:coursework|courses?|class(?:es)?|modules?)\b", re.I)
_INTRO = re.compile(r"(?:in|on|including|includes?|such\s+as|like|namely|are|is)\b|:", re.I)
_TITLE_TAIL = re.compile(r"(?:\s+(?:[A-Z][a-z][\w'’-]*|of|to|for|the|in|with|&))+")
_WORD = re.compile(r"[^\W_]+")
_NOUN_AHEAD = re.compile(r"(?:[^\W_]+[\s-]+){1,4}(?=(?:coursework|courses?|class(?:es)?)\b)", re.I)


def _courses_named(span: str, aliases: list[tuple[re.Pattern, Mapping]], *,
                   bare: bool) -> list[tuple[str, Mapping | None, int, int]]:
    """The courses an object span names, read from its start, each with where it stands in the span.

    "the courses CS 225 and CS 446", "Data Structures (CS 225) and Machine
    Learning (CS 446)".
    """
    found: list[tuple[str, Mapping | None, int, int]] = []
    pos, free, started = 0, 0, False
    while True:
        sep = _SEP.match(span, pos)
        pos = sep.end() if sep else pos
        if pos >= len(span):
            return found
        match, entry = next(((m, entry) for pattern, entry in aliases if (m := pattern.match(span, pos))),
                            (None, None))
        name = entry["name"] if entry is not None else ""
        if match is None and (match := _CODE.match(span, pos) or _TITLE_CODE.match(span, pos)) is not None:
            name = match.groupdict().get("code") or match.group()
            entry = next((candidate for pattern, candidate in aliases if pattern.fullmatch(name)), None)
            name = entry["name"] if entry is not None else name
        if match is not None:
            tail = _TITLE_TAIL.match(span, match.end())
            end = tail.end() if tail else match.end()
            if entry is not None or not _YEARLIKE.search(name):
                found.append((name, entry, match.start(), end))
            pos, started = end, True
            continue
        if (filler := _FILLER.match(span, pos)) is not None:
            pos, started = filler.end(), True
            continue
        if (noun := _COURSE_NOUN.match(span, pos)) is not None:
            # "coursework in machine learning (CS 446)" names the course a few
            # words on; "a course project in CS 446" names a project.
            after = span[noun.end():]
            nxt = _SEP.match(after)
            rest = after[nxt.end():] if nxt else after
            if not (nxt and re.search(r"[,:(]", nxt.group())) and not _INTRO.match(rest) and not _CODE.match(rest) \
                    and not any(pattern.match(rest) for pattern, _ in aliases):
                return found
            pos, free, started = noun.end(), 6, True
            continue
        if (intro := _INTRO.match(span, pos)) is not None and (started or not bare):
            pos, started = intro.end(), True
            continue
        if free == 0 and not found and (ahead := _NOUN_AHEAD.match(span, pos)) is not None:
            pos = ahead.end()
            continue
        if free > 0 and (word := _WORD.match(span, pos)) is not None:
            pos, free = word.end(), free - 1
            continue
        return found


def _claims_nothing(prefix: str, head: str) -> bool:
    """Whether a completion or enrolment verb claims nothing for the student, judged on its own verb phrase.

    A negation right before the verb ("have not taken"), someone else as its
    subject ("students who have completed"), or a conditional, modal or future
    word from the word before its subject to its verb ("if I took", "I would
    have completed"). The same word elsewhere in the sentence ("I would love to
    join and have completed CS 446") exempts nothing.
    """
    if _NEGATED.search(prefix):
        return True
    stops = list(_STOP.finditer(prefix))
    phrase = (prefix[stops[-1].end():] if stops else prefix) + head
    subjects = list(_SUBJECT.finditer(phrase))
    if subjects:
        before = re.search(r"[^\W_]+\W*$", phrase[:subjects[-1].start()])
        phrase = phrase[before.start() if before else subjects[-1].start():]
    elif _OTHER_SUBJECT.search(prefix):
        return True
    return bool(_NOT_YET.search(phrase) or _FUTURE.search(phrase))


def _course_findings(text: str, aliases: list[tuple[re.Pattern, Mapping]]) -> set[str]:
    findings: set[str] = set()
    for clause in _CLAUSE.split(text or ""):
        if not clause.strip():
            continue
        opens_future = _FUTURE_AT.match(clause) is not None
        for allowed, head_re in _HEADS:
            heads = [(m, False) for m in head_re.finditer(clause)]
            if head_re is _DONE_HEAD:
                covered = [m.span() for m, _ in heads]
                heads += [(m, True) for m in _BARE_DONE.finditer(clause)
                          if not any(start <= m.start() < end for start, end in covered)]
            for head, bare in heads:
                if _claims_nothing(clause[:head.start()], head.group()):
                    continue
                named = _courses_named(clause[head.end():], aliases, bare=bare)
                # A time phrase makes only an enrolment claim future ("I am
                # taking CS 446 next semester"); "I took CS 446 in the fall" is past.
                if head_re is not _DONE_HEAD and (
                        opens_future or (named and _FUTURE_AT.match(clause, head.end() + named[-1][3]))):
                    continue
                for name, entry, _start, _end in named:
                    if entry is None or entry["status"] not in allowed:
                        findings.add(f"unsupported course status: {name}")
    return findings


def course_claim_violations(text: str, entries: Iterable[Mapping], *, student_lines: Iterable[str] = ()) -> list[str]:
    """Courses the text claims done, or claims to be taking, when their status does not allow it.

    Only a ``completed`` course may be stated as completed or taken, only an
    ``in_progress`` course as currently taken, and "while taking" either. A
    planned course may be named as a plan and an unknown one only neutrally
    ("my coursework includes"). A course the student did not list has no
    status at all. A claim is exempt only when its own verb phrase is negated,
    conditional or future, or has someone else as its subject; a future time
    phrase that opens the clause or follows the courses makes only an
    enrolment claim future ("I am taking CS 446 next semester"), never a
    completion ("I took CS 446 in the fall"). ``student_lines`` are the student's own
    confirmed experience: a line of it that states a course, repeated verbatim
    ("Completed CS 225 project: built a parser"), is their statement, not one
    to check.
    """
    aliases = _course_aliases(list(entries))
    text = text or ""
    for line in student_lines:
        line = str(line).strip().rstrip(".!?。！？").strip()
        if line and _course_findings(line, aliases):
            text = text.replace(line, " ")
    return sorted(_course_findings(text, aliases))


# ---------------------------------------------------------------------------
# Interests (checklist M13): an interest is never experience. Where a sentence
# states the student's experience or competence — a first-person claim in an
# email, any line of a résumé — no interest phrase may appear in it unless the
# student's own facts state that phrase too.

def _phrase(text: str) -> str:
    return re.sub(r"[\W_]+", " ", str(text).lower()).strip()


def interest_phrases(interests: str) -> list[str]:
    """The phrases of the student's free-text interests, each normalised."""
    return [phrase for phrase in (_phrase(part) for part in re.split(r"[,;\n，；、]", interests or ""))
            if len(phrase) > 3]


def _contains(haystack: str, phrase: str) -> bool:
    if phrase.isascii():
        return f" {phrase} " in f" {haystack} "
    return phrase in haystack


def interest_experience_violations(claim: str, interests: str, student_facts: str) -> list[str]:
    """Interest phrases a statement of the student's experience uses that their own facts do not state.

    The caller decides that ``claim`` states experience (an email's
    first-person competence clause; any résumé line). ``student_facts`` are
    the student's own words that may support it — never their interests, and
    never a course they have only planned.
    """
    said, facts = _phrase(claim), _phrase(student_facts)
    return sorted({phrase for phrase in interest_phrases(interests)
                   if _contains(said, phrase) and not _contains(facts, phrase)})
