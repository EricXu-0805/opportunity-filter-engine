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
"""

from __future__ import annotations

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
