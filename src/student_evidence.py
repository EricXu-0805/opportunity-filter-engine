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

import hashlib
import re
import threading
import unicodedata
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from functools import lru_cache
from itertools import accumulate

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


def skill_may_be_named(raw: object) -> bool:
    """Whether a writer in the student's voice may name this skill at all.

    A GitHub skill imported before M12 carries no evidence: that import mapped
    the topics machine-learning and deep-learning to PyTorch and data-science
    to pandas, so it may name a library no repo states. Since M12 each GitHub
    skill keeps the repo field that named it (``evidence`` as the profile
    stores it, ``evidenced`` as the browser sends it). Until the student
    confirms one without it, it is still scored but never named. A
    re-import that names it again attaches its evidence.
    """
    if isinstance(raw, str) or _field(raw, "source") != "github" or _field(raw, "confirmed") is True:
        return True
    evidence = _field(raw, "evidence")
    return _field(raw, "evidenced") is True or (isinstance(evidence, str) and bool(evidence.strip()))


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


def nameable_skills(raw_skills: list) -> list:
    """The skills a writer in the student's voice may name, as given."""
    return [s for s in (raw_skills or []) if skill_may_be_named(s)]


def claimable_skill_levels(raw_skills: list) -> dict[str, str]:
    """``{name: level}`` for every generator that speaks in the student's voice."""
    return {
        skill_name(s): claimable_skill_level(s)
        for s in nameable_skills(raw_skills)
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


# A course code a name opens with: "CS 173" alone, or "CS 173 Discrete Structures".
# At most one space, so it is a code _LISTED_CODE also reads inside the titled
# name: hiding the bare code must never hide a code the claim check cannot see.
_OPENING_CODE = re.compile(r"[A-Za-z]{2,4} ?[0-9]{3,4}(?![^\W_])")


def _opening_code(name: str) -> tuple[str, bool] | None:
    """The course key of the code ``name`` opens with, and whether that code is all it names."""
    m = _OPENING_CODE.match(name)
    return None if m is None else (course_key(m.group()), course_key(name) == course_key(m.group()))


def course_entries(profile: object) -> list[dict]:
    """Every course the profile lists, each with exactly one status.

    ``courses`` entries come first, the first of one name winning. A legacy
    ``coursework`` string becomes an ``unknown`` entry unless ``courses`` names
    the same course: an old client's list never outranks the status the
    student chose, and is never read as completed. Legacy strings are kept as
    written and in order, so a profile without ``courses`` lists what it did.

    The résumé parser stored "CS 173" beside "CS 173 Discrete Structures" for
    one listed course (checklist M130). A résumé course the student has not
    marked that is only a code is not listed beside a résumé course that opens
    with that code: the titled course keeps the code and the title the course
    claim check reads, and a code the student marked or added stays.
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
    codes = [_opening_code(entry["name"]) if entry["source"] == "resume" else None for entry in entries]
    titled = {code[0] for code in codes if code and not code[1]}
    return [entry for entry, code in zip(entries, codes, strict=True)
            if not (code and code[1] and code[0] in titled and entry["status"] == "unknown")]


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


# Only courses the student listed are checked; text naming a course code or
# title the student never listed is not a course claim. A listed course is
# recognised by its code, or by its title written with the same capitalisation
# as in the list: lower-case, "machine learning" is the topic. Beside a course
# noun a title is the course in any case ("coursework in machine learning",
# "machine learning courses"); right after "a" or "an" it is the course only
# before a course noun ("a Machine Learning project" is a project). A title
# with its code in parentheses ("Machine Learning (CS 446)") is the course its
# code names, and an unlisted code is read only to find where a list of courses
# ends.
_CODE_TEXT = r"[A-Z]{2,6}[ \-]?\d{2,4}[A-Z]?"
_CODE = re.compile(rf"(?<![A-Za-z0-9]){_CODE_TEXT}(?![A-Za-z0-9])")
_LISTED_CODE = re.compile(_CODE.pattern, re.I)
_TITLE_WORD = r"(?:[A-Z][\w'’&-]*|of|to|for|the|in|and|with|&)"
_TITLE_CODE = re.compile(rf"[A-Z][\w'’&-]*(?:\s+{_TITLE_WORD}){{0,7}}\s*\(\s*(?P<code>{_CODE_TEXT})\s*\)")
_YEARLIKE = re.compile(r"(?:19[5-9]\d|20[0-4]\d)$")

# A listed name is read piece by piece through a trie built once per check, so
# finding the courses at a word costs the length of the name found there, not
# the number of courses listed. A piece is a run of ASCII letters (with the
# four other letters case-insensitive matching reads as ASCII ones), a run of
# digits, or one other letter. Pieces compare as re.IGNORECASE compares them;
# between words a name needs a separator, except where letters meet digits
# ("CS225" is "CS 225"), and its end may not run on into an ASCII letter or
# digit (nor, read in any case, into one of those four).
_PIECE = re.compile(r"([A-Za-zİıſK]+|[0-9]+|[^\W_])([\W_]*)")
_LATIN = re.compile(r"[A-Za-z0-9İıſK]")
_ASCII_ALNUM = re.compile(r"[A-Za-z0-9]")
_LATIN_FOLD = str.maketrans({"İ": "i", "ı": "i", "ſ": "s", "K": "k"})
_CASED_CUT = re.compile("[İıſK]")
# How a piece follows the one before it: in the same word, after a separator,
# or either way (a word starting with a digit after one ending in a letter).
_JOINED, _APART, _EITHER = 0, 1, 2


def _fold(piece: str) -> str:
    if piece.isascii():
        return piece.lower()
    if _LATIN.match(piece):
        return piece.translate(_LATIN_FOLD).lower()
    return "\0" + piece.casefold()


@lru_cache(maxsize=4096)
def _name_steps(name: str) -> tuple[tuple[tuple[int, str], ...], str] | None:
    """A name as the trie reads it: each piece with how it follows the last, and its letters."""
    steps: list[tuple[int, str]] = []
    letters: list[str] = []
    words = re.findall(r"[^\W_]+", name)
    for before, word in zip([""] + words, words, strict=False):
        joint = _EITHER if not before or before[-1].isdigit() != word[0].isdigit() else _APART
        for piece in _PIECE.finditer(word):
            steps.append((joint, _fold(piece.group(1))))
            letters.append(piece.group(1))
            joint = _JOINED
    return (tuple(steps), "".join(letters)) if steps else None


class _Name:
    """The listed names read alike in any case: the first of them, the first that is a code, and each as written."""

    __slots__ = ("order", "entry", "code", "written")

    def __init__(self, order: int, entry: Mapping):
        self.order, self.entry = order, entry
        self.code: tuple[int, Mapping] | None = None
        self.written: dict[str, tuple[int, Mapping]] = {}


class _OverBudget(Exception):
    """A text's check needs more trie steps than any real draft and course list do."""


class _Budget:
    """The trie steps one text's check may still take."""

    __slots__ = ("left",)

    def __init__(self, steps: int):
        self.left = steps

    def spend(self, steps: int) -> None:
        self.left -= steps
        if self.left < 0:
            raise _OverBudget


def _course_aliases(entries: Iterable[Mapping]) -> dict:
    """The trie of every listed course's names, longest name first in ``order``."""
    aliases: list[tuple[int, str, bool, Mapping]] = []
    for entry in entries:
        name = str(entry.get("name") or "")
        rest = _LISTED_CODE.sub(" ", name)
        title = rest if re.search(r"[^\W\d_]", rest) else ""
        # Its codes in any case; its name and title only as written, unless
        # the name is only a code.
        forms = {name: not title, **dict.fromkeys((m.group() for m in _LISTED_CODE.finditer(name)), True)}
        if title:
            forms.setdefault(title, False)
        aliases.extend((len(alias.strip()), alias, any_case, entry) for alias, any_case in forms.items())
    trie: dict = {}
    names: dict[tuple, _Name] = {}
    for order, (_length, alias, any_case, entry) in enumerate(sorted(aliases, key=lambda item: -item[0])):
        if (read := _name_steps(alias)) is None:
            continue
        steps, letters = read
        if (known := names.get(steps)) is None:
            known = names[steps] = _Name(order, entry)
            node = trie
            for step in steps:
                node = node.setdefault(step, {})
            node[None] = known
        if any_case:
            known.code = known.code or (order, entry)
        else:
            known.written.setdefault(letters, (order, entry))
    return trie


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
    listed, key = _listed(entries)
    reader = _Reader(text, _trie_for(key, listed), _Budget(_text_steps(text)))
    try:
        spans = {(head.end() + start, head.end() + end)
                 for head in _LISTING.finditer(text)
                 for _name, entry, start, end in _courses_named(reader, head.end(), bare=False)
                 if entry is not None}
    except _OverBudget:
        # Unmasked, the competence check reads every course name as words,
        # which can only refuse more.
        return text
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
    r"(?:\b(?:not(?!\s+only\b)|never|no|without)\b|n['’]t|没有|没|未|尚未)\s*(?:\w+\s+){0,2}$", re.I)
_NOT_YET = re.compile(
    r"\b(?:will|would|plan(?:ning)?\s+to|hope\s+to|intend\s+to|expect\s+to|going\s+to|unless|until|if)\b"
    r"|['’]ll\b|['’]d\s+have\b|\bonce(?=\s+(?:i|we)\b)|将|计划|打算|准备",
    re.I,
)
_FUTURE = re.compile(
    r"\b(?:next|upcoming|coming)\s+(?:semester|term|quarter|year|fall|spring|summer|winter)\b"
    r"|\bin\s+the\s+(?:fall|spring|summer|winter|future)\b|下学期|明年|将来",
    re.I,
)
# A future time phrase that opens a clause, or stands right after its courses.
_FUTURE_AT = re.compile(
    rf"[\s,]*(?:(?:for|in|during)\s+(?:the\s+)?)?(?:(?:this|starting|beginning|from)\s+)?(?:{_FUTURE.pattern})", re.I)
# Where the verb phrase before a claim's verb can start: after a comma or a
# conjunction, at the word before its subject ("if" in "if I took").
_STOP = re.compile(r"[,;:()，、：]|\b(?:and|or|but|so|that|which|who)\b", re.I)
_SUBJECT = re.compile(r"\b(?:i|we)\b|我们?", re.I)
# A verb with someone else as its subject: "students who have completed".
_OTHER_SUBJECT = re.compile(
    r"\b(?:you|they|he|she|students|applicants|candidates|undergraduates|those|anyone|others)"
    r"(?:\s+(?:who|that))?\s+(?:\w+\s+)?$", re.I)
_STOP_END = re.compile(rf"(?:{_STOP.pattern})$", re.I)
# What an end-anchored verb-phrase pattern can match: a few words and spaces.
_FEW_WORDS = re.compile(r"\s*[\w'’]*(?:\s+[\w'’]*){0,4}\s*")
_WORDISH = re.compile(r"\w")
_SEP = re.compile(r"(?:[\s,;/&()\[\]\-–—'’\"“”《》「」、，]|和|与|及|以及|了|过|的)+")
_FILLER = re.compile(
    r"(?:the|my|a|an|both|two|three|four|several|relevant|related|introductory|intro|advanced|"
    r"upper[- ]level|graduate|undergraduate|core|required|foundational|following|and|or|plus|"
    r"as\s+well\s+as|also)\b",
    re.I,
)
_COURSE_NOUN = re.compile(r"(?:coursework|courses?|class(?:es)?|modules?)\b", re.I)
_INTRO = re.compile(r"(?:in|on|including|includes?|such\s+as|like|namely|are|is)\b|:", re.I)
# A title after a code ends on a capitalised word: "CS 446 in the fall" has none.
_TITLE_TAIL = re.compile(r"(?:(?:\s+(?:of|to|for|the|in|with|&))*\s+[A-Z][a-z][\w'’-]*)+")
_WORD = re.compile(r"[^\W_]+")
_NOUN_AHEAD = re.compile(r"(?:[^\W_]+[\s-]+){1,4}(?=(?:coursework|courses?|class(?:es)?)\b)", re.I)
# The course nouns a title may stand beside, and "a" or "an" right before it.
_TITLE_NOUN = re.compile(r"(?:coursework|courses?|class(?:es)?)\b", re.I)
_NOUN_NEXT = re.compile(rf"\s+{_TITLE_NOUN.pattern}", re.I)
# How the next listed title joins a list: "Machine Learning and (a) Computer
# Vision course", "Machine Learning, Computer Vision, or Robotics classes".
_LIST_JOIN = re.compile(r"(?:\s*,)?\s+(?:and|or)\s+(?:an?\s+)?|\s*,\s*(?:an?\s+)?", re.I)
# After a course noun and a comma, "and" or "but" starts a new clause: a title
# after it is not one the noun introduces.
_NEW_CLAUSE = re.compile(r"(?:and|but)\b", re.I)
_HEAD_NOUN = re.compile(rf"{_TITLE_NOUN.pattern}$", re.I)
_ARTICLE = re.compile(r"\ban?\s+$", re.I)


_UNREAD = object()


class _Reader:
    """One text's course reads, shared by every claim in it.

    Each piece of the text, the listed names that start at each place, and
    each object from where it stands in a given reading state are read once: a
    claim whose object runs into one already read takes the courses read from
    there, so a text full of claims costs about what one claim reading to its
    end does.
    """

    def __init__(self, text: str, trie: dict, budget: _Budget | None = None):
        self.text, self.trie, self.budget = text, trie, budget
        self.pieces: dict[int, tuple | None] = {}
        self.names_at: dict[int, list[tuple[_Name, int, bool]]] = {}
        self.letters: tuple[str, list[int]] | None = None
        self.nouns: dict[int, bool] = {}
        self.list_nouns: dict[int, bool] = {}
        self.objects: dict[tuple, tuple[list, int]] = {}
        self._marks: dict[str, tuple[list[int], list[int]]] = {}

    def marks(self, pattern: re.Pattern) -> tuple[list[int], list[int]]:
        """Where ``pattern`` matches in the text: the starts and the ends, in order."""
        if (known := self._marks.get(pattern.pattern)) is None:
            spans = [m.span() for m in pattern.finditer(self.text)]
            known = self._marks[pattern.pattern] = ([start for start, _ in spans], [end for _, end in spans])
        return known

    def within(self, pattern: re.Pattern, start: int, end: int) -> bool:
        """Whether ``pattern`` matches in ``text[start:end]`` read alone (no match of it spans a word's start)."""
        starts, ends = self.marks(pattern)
        first = bisect_left(starts, start)
        if (start and _WORDISH.match(self.text, start - 1) and _WORDISH.match(self.text, start)) or (
                first < len(starts) and starts[first] < end < ends[first]):
            return pattern.search(self.text[start:end]) is not None
        return first < len(starts) and ends[first] <= end

    def _piece(self, at: int) -> tuple | None:
        known = self.pieces.get(at, _UNREAD)
        if known is _UNREAD:
            m = _PIECE.match(self.text, at)
            known = self.pieces[at] = None if m is None else (
                _fold(m.group(1)), m.end(1), m.end(), not m.group(1).isascii() and _LATIN.match(m.group(1)) is not None)
        return known

    def _names(self, at: int) -> list[tuple[_Name, int, bool]]:
        """The listed names whose text starts at ``at``, each with where it ends and whether only as written.

        A name that runs on into one of the four letters only case-insensitive
        matching reads as ASCII is the name only as the list writes it, even
        where that letter continues the name's last run of letters.
        """
        if (known := self.names_at.get(at)) is not None:
            return known
        found: list[tuple[_Name, int, bool]] = []
        nodes, joints, start = [self.trie], (_EITHER,), at
        while nodes and (piece := self._piece(at)) is not None:
            folded, end, after, mixed = piece
            if self.budget is not None:
                self.budget.spend(len(nodes) * len(joints))
            for cut in (_CASED_CUT.finditer(self.text, at + 1, end) if mixed else ()):
                if self.budget is not None:
                    # Each cut copies and folds the word up to it.
                    self.budget.spend(len(nodes) * len(joints) + cut.start() - at)
                head = _fold(self.text[at:cut.start()])
                found.extend((name, cut.start(), True) for node in nodes for joint in joints
                             if (name := node.get((joint, head), {}).get(None)) is not None)
            at = after
            nodes = [child for node in nodes for joint in joints if (child := node.get((joint, folded))) is not None]
            if names := [name for node in nodes if (name := node.get(None)) is not None]:
                cased = _LATIN.match(self.text, end) is not None
                if not cased or not _ASCII_ALNUM.match(self.text, end):
                    found.extend((name, end, cased) for name in names)
            joints = (_JOINED, _EITHER) if at == end else (_APART, _EITHER)
        self.names_at[start] = found
        return found

    def _letters(self, start: int, end: int) -> str:
        """The letters (word characters but "_") of ``text[start:end]``, from one join of the text's letters."""
        starts, ends = self.marks(_WORD)
        if self.letters is None:
            self.letters = ("".join(self.text[run:stop] for run, stop in zip(starts, ends, strict=True)),
                            list(accumulate((stop - run for run, stop in zip(starts, ends, strict=True)), initial=0)))
        letters, before = self.letters

        def count(at: int) -> int:
            run = bisect_right(starts, at) - 1
            return 0 if run < 0 else before[run] + min(at, ends[run]) - starts[run]

        return letters[count(start):count(end)]

    def _written(self, name: _Name, start: int, end: int) -> tuple[int, Mapping] | None:
        """The first listed name of ``name``'s group written exactly as ``text[start:end]``, if any."""
        return name.written.get(self._letters(start, end)) if name.written else None

    def noun_next(self, at: int) -> bool:
        if (known := self.nouns.get(at)) is None:
            known = self.nouns[at] = _NOUN_NEXT.match(self.text, at) is not None
        return known

    def noun_after(self, at: int) -> bool:
        """Whether a course noun follows a listed name ending at ``at``, right after it or at the end of its list.

        The list is listed names joined by and, or, commas and "a"/"an"
        ("a Machine Learning and a Computer Vision course"); the longest name
        at each place is followed. A walk stops where a place already walked
        is known, so each place is walked once.
        """
        walked: list[int] = []
        result = False
        while True:
            if (known := self.list_nouns.get(at)) is not None:
                result = known
                break
            walked.append(at)
            if self.noun_next(at):
                result = True
                break
            join = _LIST_JOIN.match(self.text, at)
            ends = [end for _, end, cased in self._names(join.end()) if not cased] if join else []
            if not ends:
                break
            at = max(ends)
        for place in walked:
            self.list_nouns[place] = result
        return result

    def listed(self, at: int, *, whole: bool = False) -> Mapping | None:
        """The listed course written at ``at`` as the list writes it (a code in any case), first in list order."""
        best: tuple[int, Mapping] | None = None
        for name, end, cased in self._names(at):
            if not whole or end == len(self.text):
                written = self._written(name, at, end)
                for pick in ((written,) if cased else (name.code, written)):
                    if pick is not None and (best is None or pick[0] < best[0]):
                        best = pick
        return best[1] if best else None

    def course_at(self, span: str, pos: int, origin: int, *, noun_before: bool, article: bool
                  ) -> tuple[Mapping, int] | None:
        """The listed course read at ``pos`` of ``span`` (``origin`` in the text), and where it ends in the span.

        The first name in list order that counts there: a code in any case;
        a title as the list capitalises it, or in any case when a course noun
        stands right before it or follows it (right after it or at the end of
        the list it belongs to); right after "a" or "an" only when a course
        noun follows it.
        """
        if pos and _LATIN.match(span, pos - 1):
            return None
        start = origin + pos
        best: tuple[int, Mapping, int] | None = None
        for name, end, cased in self._names(start):
            if cased or (best is not None and name.order > best[0]):
                continue
            if (name.code is not None and name.code[0] == name.order) or self.noun_after(end) or (
                    not article and noun_before):
                pick: tuple[int, Mapping] | None = (name.order, name.entry)
            else:
                pick = name.code
                if not article and (hit := self._written(name, start, end)) is not None and (
                        pick is None or hit[0] < pick[0]):
                    pick = hit
            if pick is not None and (best is None or pick[0] < best[0]):
                best = (pick[0], pick[1], end - origin)
        return (best[1], best[2]) if best else None


def _courses_named(reader: _Reader, origin: int, *, bare: bool, noun: bool = False
                   ) -> list[tuple[str, Mapping | None, int, int]]:
    """The courses the object at ``origin`` of the reader's text names, each with where it stands from ``origin``.

    "the courses CS 225 and CS 446", "Data Structures (CS 225) and Machine
    Learning (CS 446)". ``noun``: a course noun ends the text before the span.
    A course noun stands right before each title of the list it introduces
    ("coursework in machine learning and data structures") until a word that
    names no course.
    """
    span = reader.text[origin:]
    found: list[tuple[str, Mapping | None, int, int]] = []
    # From its fourth character on, what an object reads depends only on where
    # it stands and the reading state, so every claim shares it.
    visited: list[tuple[tuple, int]] = []
    pos, free, started, noun_before = 0, 0, False, noun
    while True:
        if pos > 2:
            state = (origin + pos, free, started, noun_before, bool(found), bare)
            if (known := reader.objects.get(state)) is not None:
                read, first = known
                found += [(name, entry, start - origin, end - origin) for name, entry, start, end in read[first:]]
                break
            visited.append((state, len(found)))
        sep = _SEP.match(span, pos)
        start, pos = pos, (sep.end() if sep else pos)
        if pos >= len(span):
            break
        article = _ARTICLE.search(span, max(0, start - 2), pos) is not None
        entry, end = reader.course_at(span, pos, origin, noun_before=noun_before, article=article) or (None, None)
        name = entry["name"] if entry is not None else ""
        if end is None and (match := _CODE.match(span, pos) or _TITLE_CODE.match(span, pos)) is not None:
            name = match.groupdict().get("code") or match.group()
            entry = _Reader(name, reader.trie, reader.budget).listed(0, whole=True)
            name, end = (entry["name"] if entry is not None else name), match.end()
        if end is not None:
            tail = _TITLE_TAIL.match(span, end)
            end = tail.end() if tail else end
            if entry is not None or not _YEARLIKE.search(name):
                found.append((name, entry, pos, end))
            pos, started = end, True
            continue
        if (filler := _FILLER.match(span, pos)) is not None:
            pos, started = filler.end(), True
            continue
        if (noun := _COURSE_NOUN.match(span, pos)) is not None:
            # "coursework in machine learning (CS 446)" names the course a few
            # words on; "a course project in CS 446" names a project.
            nxt = _SEP.match(span, noun.end())
            rest = nxt.end() if nxt else noun.end()
            if not (nxt and re.search(r"[,:(]", nxt.group())) and not _INTRO.match(span, rest) \
                    and not _CODE.match(span, rest) and reader.listed(origin + rest) is None:
                break
            pos, free, started = noun.end(), 6, True
            # "several courses, and machine learning became ...": a new clause,
            # so a title after it counts only as written or by its code.
            noun_before = _TITLE_NOUN.fullmatch(noun.group()) is not None and not (
                nxt and "," in nxt.group() and _NEW_CLAUSE.match(span, rest))
            continue
        if (intro := _INTRO.match(span, pos)) is not None and (started or not bare):
            pos, started = intro.end(), True
            continue
        if free == 0 and not found and (ahead := _NOUN_AHEAD.match(span, pos)) is not None:
            pos = ahead.end()
            continue
        if free > 0 and (word := _WORD.match(span, pos)) is not None:
            pos, free, noun_before = word.end(), free - 1, False
            continue
        break
    if visited:
        read = [(name, entry, start + origin, end + origin) for name, entry, start, end in found]
        for state, first in visited:
            reader.objects[state] = (read, first)
    return found


def _ends_on(pattern: re.Pattern, text: str, at: int) -> bool:
    """Whether ``pattern``, anchored at its end, matches ``text[:at]``, read near ``at`` unless all words lead there."""
    near = max(0, at - 200)
    if pattern.search(text, near, at):
        return True
    return near > 0 and _FEW_WORDS.fullmatch(text, near, at) is not None and pattern.search(text, 0, at) is not None


def _claims_nothing(reader: _Reader, head: re.Match) -> bool:
    """Whether a completion or enrolment verb claims nothing for the student, judged on its own verb phrase.

    A negation right before the verb ("have not taken"), someone else as its
    subject ("students who have completed"), or a conditional, modal or future
    word from the word before its subject to its verb ("if I took", "I would
    have completed"). The same word elsewhere in the sentence ("I would love to
    join and have completed CS 446") exempts nothing. Each is read near the
    verb or from where the clause marks it, never by re-reading the clause.
    """
    text, verb, end = reader.text, head.start(), head.end()
    if _ends_on(_NEGATED, text, verb):
        return True
    # The phrase starts after the last stop before the verb.
    _starts, ends = reader.marks(_STOP)
    stop = bisect_left(ends, verb)
    start = verb if _STOP_END.search(text, max(0, verb - 8), verb) else ends[stop - 1] if stop else 0
    starts, _ends = reader.marks(_SUBJECT)
    subject = bisect_left(starts, end) - 1
    if subject >= 0 and starts[subject] >= start:
        # From the word before the subject, if only non-word characters
        # ("_" is none) stand between them.
        subject = starts[subject]
        words, word_ends = reader.marks(_WORD)
        word = bisect_left(words, subject) - 1
        last = min(word_ends[word], subject) if word >= 0 else start
        start = max(words[word], start) if last > start and text.find("_", last, subject) < 0 else subject
    elif _ends_on(_OTHER_SUBJECT, text, verb):
        return True
    return reader.within(_NOT_YET, start, end) or reader.within(_FUTURE, start, end)


def _course_findings(text: str, trie: dict, budget: _Budget | None = None) -> set[tuple[frozenset, str]]:
    """Each unsupported claim as the statuses its kind of claim allows and the course it names."""
    findings: set[tuple[frozenset, str]] = set()
    for clause in _CLAUSE.split(text or ""):
        if not clause.strip():
            continue
        reader = _Reader(clause, trie, budget)
        opens_future = _FUTURE_AT.match(clause) is not None
        for allowed, head_re in _HEADS:
            heads = [(m, False) for m in head_re.finditer(clause)]
            if head_re is _DONE_HEAD:
                starts, ends = [m.start() for m, _ in heads], [m.end() for m, _ in heads]
                heads += [(m, True) for m in _BARE_DONE.finditer(clause)
                          if not (at := bisect_right(starts, m.start())) or ends[at - 1] <= m.start()]
            for head, bare in heads:
                if _claims_nothing(reader, head):
                    continue
                named = _courses_named(reader, head.end(), bare=bare,
                                       noun=_HEAD_NOUN.search(head.group()) is not None)
                # A time phrase makes only an enrolment claim future ("I am
                # taking CS 446 next semester"); "I took CS 446 in the fall" is past.
                if head_re is not _DONE_HEAD and (
                        opens_future or (named and _FUTURE_AT.match(clause, head.end() + named[-1][3]))):
                    continue
                for name, entry, _start, _end in named:
                    if entry is not None and entry["status"] not in allowed:
                        findings.add((allowed, name))
    return findings


def course_claim_violations(text: str, entries: Iterable[Mapping], *, student_lines: Iterable[str] = (),
                            student_draft: str = "") -> list[str]:
    """Courses the text claims done, or claims to be taking, when their status does not allow it.

    Only a ``completed`` course may be stated as completed or taken, only an
    ``in_progress`` course as currently taken, and "while taking" either. A
    planned course may be named as a plan and an unknown one only neutrally
    ("my coursework includes"). Only listed courses are checked, each read by
    its code or by its title as the list capitalises it (in any case beside a
    course noun; right after "a" or "an" only before one); text naming a course
    the student never listed is no course claim. A claim is exempt only when
    its own verb phrase is negated, conditional or future, or has someone else
    as its subject; a future time phrase that opens the clause or follows the
    courses makes only an enrolment claim future ("I am taking CS 446 next
    semester"), never a completion ("I took CS 446 in the fall").
    ``student_lines`` are the student's own confirmed experience: a line of it
    that states a course, repeated verbatim ("Completed CS 225 project: built a
    parser"), is their statement, not one to check. ``student_draft`` is the student's own draft that ``text`` edits:
    a claim it already makes (the same kind of claim about the same course) is
    theirs, so only a claim new to ``text`` is a finding.
    """
    listed, key = _listed(entries)
    text = text or ""
    for line in student_lines:
        line = str(line).strip().rstrip(".!?。！？").strip()
        if line and (stated := _findings_of(line, key, listed)):
            # An unreadable line states nothing anyone checked: cutting it out
            # would let the rest of the text through unread.
            if _UNCHECKED in stated:
                return [COURSE_CHECK_TOO_COSTLY]
            text = text.replace(line, " ")
    found, theirs = _findings_of(text, key, listed), _findings_of(student_draft or "", key, listed)
    # A text too costly to read is refused, never subtracted away: an unread
    # student draft cannot vouch for an unread one.
    if _UNCHECKED in found or _UNCHECKED in theirs:
        return [COURSE_CHECK_TOO_COSTLY]
    return sorted({f"unsupported course status: {name}" for _allowed, name in found - theirs})


# A draft and course list a student writes take at most about two trie steps
# per character of the text (a 5,000-character list of course codes against
# 512 codes: 2,376 steps; one Chinese sentence naming 60 titles that share
# 计算机…: 1.84 per character); names built to match each other at every word
# (nested inside each other, or one word split every way) take hundreds per
# character. A text whose check would take more than this is refused (the
# draft falls back to the template, or to the neutral inquiry when the
# unreadable text is the student's own draft or a line of their experience),
# so one text costs at most about 15 ms per thousand characters whatever the
# input within the request limits.
def _text_steps(text: str) -> int:
    return 1_000 + 5 * len(text)


_UNCHECKED = (frozenset(), "")
COURSE_CHECK_TOO_COSTLY = "unsupported course status: (too costly to check against the listed courses)"


# One request checks the same course list, the student's own draft and lines
# several times (each draft, its repair, the fallback, the final gate), so the
# trie and each text's findings are kept by content for the next call. Keys are
# digests: a course list can be a megabyte.
_TRIES: OrderedDict[str, dict] = OrderedDict()
_FINDINGS: OrderedDict[tuple[str, str], frozenset] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _digest(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", "surrogatepass"), digest_size=16).hexdigest()


def _listed(entries: Iterable[Mapping]) -> tuple[list[dict], str]:
    """The course list as the checks read it (each name and status) and the digest it is cached under."""
    listed = [{"name": str(entry.get("name") or ""), "status": entry.get("status")} for entry in entries]
    return listed, _digest(repr([(entry["name"], entry["status"]) for entry in listed]))


def _trie_for(key: str, listed: list[dict]) -> dict:
    with _CACHE_LOCK:
        if (trie := _TRIES.get(key)) is not None:
            _TRIES.move_to_end(key)
            return trie
    trie = _course_aliases(listed)
    with _CACHE_LOCK:
        _TRIES[key] = trie
        while len(_TRIES) > 2:
            _TRIES.popitem(last=False)
    return trie


def _findings_of(text: str, key: str, listed: list[dict]) -> frozenset:
    """``_course_findings`` of ``text`` against the course list ``key`` names, from the cache when it holds them.

    A text that needs more than ``_text_steps(text)`` trie steps gives ``{_UNCHECKED}``.
    """
    slot = (key, _digest(text))
    with _CACHE_LOCK:
        if (known := _FINDINGS.get(slot)) is not None:
            _FINDINGS.move_to_end(slot)
            return known
    try:
        found = frozenset(_course_findings(text, _trie_for(key, listed), _Budget(_text_steps(text))))
    except _OverBudget:
        found = frozenset({_UNCHECKED})
    with _CACHE_LOCK:
        _FINDINGS[slot] = found
        while len(_FINDINGS) > 64:
            _FINDINGS.popitem(last=False)
    return found


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
