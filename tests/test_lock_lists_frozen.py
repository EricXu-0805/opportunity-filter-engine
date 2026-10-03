"""The lock lists and the review prompt are frozen (docs/resume_writing_quality_contract.md, "Frozen lists").

Every family the claim locks (target_resume_ai_grounding.py) and the contract's checks
(evidence_map.py) read is pinned here with its number of entries. In a pattern an entry
is an alternative of a "|" or a listed character of a "[...]" class, exceptions and
lookarounds included; in a word list it is a word; in a table it is an item, plus the
entries of the patterns the item holds (a family a table holds by name counts once, as
itself). Adding a word, an exception or a whole family fails here.

A shape a reviewer finds goes to the review's calibration set and to the PR's limits,
not into a list. A family changes only to remove a measured faithful refusal or a CPU
path; its count here changes in the same commit, with the measurement in the message.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import re

import pytest

from backend.lib import evidence_map as em
from backend.lib import target_resume_ai_grounding as grounding

try:
    from re import _parser
except ImportError:  # Python before 3.11
    import sre_parse as _parser

FROZEN = {
    grounding: {
        "_TEAM_CONTEXT": 48, "NEGATION": 33, "TEAM": 12, "PUBLICATION": 21, "PERSONAL": 9, "ACTIONS": 60,
        "STAGES": 11, "ACTION_GERUNDS": 11, "_GERUND_POSITION": 30, "_GERUND_AND": 2, "INTENT": 64, "PLANNED": 41,
        "UNFINISHED": 25, "FUTURE_ZH": 11, "UNDERWAY_ZH": 105, "UNFINISHED_ZH": 121, "_REGULAR_VERBS": 249,
        "_DOUBLING_VERBS": 47, "_L_VERBS": 10, "_IRREGULAR_VERBS": 127, "_DOUBLED_IRREGULAR": 8, "_PAST_AS_BASE": 4,
        "RESUME_VERB_FORMS": 4410, "_WORD": 0, "_STATED_ACTIONS": 52, "HELP": 12, "RELEVANCE_PADDING": 37,
        "APPENDED_RELEVANCE": 45, "QUALITY": 44, "SETTING": 71, "_CJK": 0, "DENIAL": 49, "_TEAM_OWNER": 6,
        "_OBJECT_END": 31, "_SETTING_LEAD": 13, "LEADERSHIP": 3, "CO_CREDIT": 60, "_SHARED_CREDIT": 64,
        "_TEAM_RELATIVE": 10, "_CJK_RUN": 0, "_LATIN_WORD": 0, "_SENTENCE_BREAK": 10, "_CLAUSE_BREAK": 21,
        "_CLAUSE_LEAD": 18, "_PERSONAL_SUBJECT": 12, "_OTHER_SUBJECT": 65, "_TEAM_SUBJECT": 25, "_ZH_VERBS": 78,
        "_BASE_VERB_CUE": 10, "_STUDENT_AGENT": 15, "_BY": 0, "_TEAM_WITH": 47, "_STATUS_CLASSES": 50,
        "_QUALIFIERS": 156, "_NEXT_TOKEN": 5, "_CO_ACTIONS": 2, "_NOUN_END": 34, "_NOT_HEAD": 20, "_ZH_LEAD": 22,
        "_ZH_TAIL": 8, "_STATUS_WORDS": 50, "_CJK_RUN_AT": 0, "_CJK_RUN_END": 0, "_DURATION": 3, "_COUNT_ZHI": 0,
        "_UNDERWAY_ACTION": 82, "_IN_PRESS": 2, "_SURFACE_VERBS": 31, "_SURFACE_ACTOR": 5,
    },
    em: {
        "_FUNCTION_EN": 56, "_FUNCTION_ZH": 34, "_TOKEN": 11, "_PERSONAL_MARKER": 10, "_WEAK_OPENER": 14,
        "_PERSONAL_PART": 8, "_FIRST_CLAUSE": 10, "_OTHER_PERSON": 175, "_SPAN": 200, "_SOLO": 10, "_LIMIT": 5,
        "_STATUS_WORD": 23, "_UN_DONE": 7, "_TEAM_ZH_EXTRA": 25, "_TEAM_EN_EXTRA": 34, "_TEAM_OTHERS": 34,
        "_PARTICIPATION_EN": 9, "_PARTICIPATION_ZH": 3, "_ACTION_WORDS": 54, "_SETTING_NOUN": 28,
        "_RELEVANCE_WORD": 20, "_REVISION_WORD": 4, "_SPAN_WORD": 17, "_LOCK_WORD": 23, "_TEAM_HEADER": 17,
        "_GLUED_MARKER": 2, "_SHARED_OR_HELP": 6, "_NUMBER": 2,
    },
}
# evidence_map's own patterns and tables that no lock reads: the anchor cuts and term
# edges, the row protocol, and the review's answer parsing.
NOT_LOCKS = {
    grounding: set(),
    em: {"SUBSTANTIVE_OPS", "OPS", "KEEP_REASONS", "ROW_KEYS", "_FACULTY_HEAD", "_AREAS_LEAD", "_FACULTY_TAIL",
         "_SENTENCE_END", "_LIST_ITEM", "_CLAUSE", "_URL_OR_EMAIL", "_BOILERPLATE", "_CJK", "_STOPWORDS",
         "_WORD_CHARACTER", "_BROKEN_RULE_TAG"},
}
# A pattern fragment the claim locks read outside any compiled pattern (supported_surface_forms),
# and a family they import from main's attribution parser.
FRAGMENTS = {grounding: {"_SURFACE_ACTOR"}, em: set()}
IMPORTED = {grounding: {"_TEAM_CONTEXT"}, em: set()}
# The review prompt the 170-pair calibration ran on (85 traps and 85 faithful pairs, 3 samples
# each: 0/255 trap accepts, 17/255 faithful rejects); 6,704 characters.
CALIBRATED_REVIEW_PROMPT_SHA256 = "0936f8972e15eafa8a3f337114c71946ffb3f0e0b53c35912477be923fcd0548"

_WORD_LIST = re.compile(r"\s*[a-z]+(?:[-\s]+[a-z]+)*\s*")


def _alternatives(pattern) -> int:
    total = 0
    for op, value in pattern:
        if op is _parser.BRANCH:
            total += len(value[1]) + sum(_alternatives(branch) for branch in value[1])
        elif op is _parser.IN:
            if value[0][0] is not _parser.NEGATE and all(kind is _parser.LITERAL for kind, _ in value):
                total += len(value)
        else:
            for part in value if isinstance(value, tuple | list) else (value,):
                if isinstance(part, _parser.SubPattern):
                    total += _alternatives(part)
                elif isinstance(part, tuple | list):
                    total += sum(_alternatives(sub) for sub in part if isinstance(sub, _parser.SubPattern))
    return total


def _own_names(module) -> list[str]:
    names = []
    for node in ast.parse(inspect.getsource(module)).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        names += [target.id for target in targets if isinstance(target, ast.Name)]
    return names


def _families(module) -> dict[str, object]:
    found = {}
    for name in [*_own_names(module), *IMPORTED[module]]:
        value = getattr(module, name)
        if (isinstance(value, re.Pattern | dict | set | frozenset | tuple | list) or name in FRAGMENTS[module]
                or isinstance(value, str) and _WORD_LIST.fullmatch(value)):
            found[name] = value
    return {name: value for name, value in found.items() if name not in NOT_LOCKS[module]}


NAMED = {id(value) for module in FROZEN for value in _families(module).values() if isinstance(value, re.Pattern)}


def entries(value) -> int:
    if isinstance(value, re.Pattern):
        return _alternatives(_parser.parse(value.pattern, value.flags))
    if isinstance(value, str):
        return len(value.split()) if _WORD_LIST.fullmatch(value) else _alternatives(_parser.parse(value))
    items = list(value.values()) if isinstance(value, dict) else list(value)
    return len(items) + sum(entries(item) for item in items
                            if id(item) not in NAMED and not (isinstance(item, str) and _WORD_LIST.fullmatch(item)))


@pytest.mark.parametrize(("module", "name"), [(module, name) for module, pins in FROZEN.items() for name in pins],
                         ids=lambda value: value if isinstance(value, str) else value.__name__.rsplit(".", 1)[-1])
def test_each_lock_family_keeps_its_entry_count(module, name):
    count, pinned = entries(getattr(module, name)), FROZEN[module][name]
    assert count == pinned, (
        f"{module.__name__}.{name} has {count} entries, pinned at {pinned}. The lock lists are frozen: change a "
        "family only to remove a measured faithful refusal or a CPU path, and update this count in the same commit "
        "(docs/resume_writing_quality_contract.md, 'Frozen lists').")


@pytest.mark.parametrize("module", list(FROZEN), ids=lambda module: module.__name__.rsplit(".", 1)[-1])
def test_no_lock_family_is_added_or_dropped(module):
    found = set(_families(module))
    assert found == set(FROZEN[module]), (
        f"new: {sorted(found - set(FROZEN[module]))}, gone: {sorted(set(FROZEN[module]) - found)}. A new list is a "
        "new rule; a list no lock reads belongs in NOT_LOCKS.")


def test_the_review_prompt_is_the_calibrated_one():
    digest = hashlib.sha256(em.REVIEW_SYSTEM_PROMPT.encode()).hexdigest()
    assert digest == CALIBRATED_REVIEW_PROMPT_SHA256, (
        "The review prompt changes only together with a new run of the 170-pair calibration, whose result goes "
        "into the commit message (docs/resume_writing_quality_contract.md, 'Frozen lists').")
