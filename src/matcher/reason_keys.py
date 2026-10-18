"""Machine-readable keys for the match reasons the ranker writes (M107).

The reasons stay English sentences: the local explanation, the AI prompt,
the search filter and the dedupe all read them, so a translation must not
touch them. Each served sentence is instead matched back to the template
that wrote it, and the response carries ``{"key", "params"}`` beside it
(index-aligned, None where no template matches) for an interface in
another language to render from its own table. The params are the
sentence's own substrings, so a quoted label, a name or a skill reaches
that table exactly as the English sentence has it.

Matching after the fact, rather than at each append site, leaves the
ranker's strings and its hot path untouched. A template whose wording
changes without its pattern here falls back to the English sentence, never
to a blank line; tests/test_reason_keys_m107.py keys every reason a varied set
of profiles produces, so that drift fails a test.
"""

from __future__ import annotations

import re

from backend.lib.opportunity_detail import SIMPLIFY_NO_SPONSORSHIP_LABEL

from .ranker import (
    _NOT_ON_PAGE,
    _OUR_LISTING_AND_READING,
    _OUR_READING,
    _SIMPLIFY_NO_SPONSORSHIP_GAP,
    _SIMPLIFY_NO_SPONSORSHIP_REASON,
    _summarize_research,
)

ReasonKey = dict  # {"key": str, "params": dict[str, str]}

# A line can echo profile text whole (one desired-field chip may be 60,000
# characters), and keying runs on every served card. The longest line the
# ranker writes from the corpus is about 330 characters (a research summary
# headline in "This lab focuses on …"), so this bound leaves six times
# that. A longer line is not keyed and shows in English, so no line costs
# the patterns below more than a bounded scan.
MAX_KEYED_REASON_CHARACTERS = 2_000

# Sentences with no variable part: sentence -> (key, fixed params).
_FIT_EXACT: dict[str, tuple[str, dict[str, str]]] = {
    "This faculty member's department aligns with your major": ("major_department_aligns", {}),
    "This faculty member's department is related to your major": ("major_department_related", {}),
    "Your major may fit this field": ("major_field_may_fit", {}),
    "Your major may be related to this field": ("major_field_may_relate", {}),
    f"Our listing says this is open to all majors{_NOT_ON_PAGE}": ("major_all_listing", {}),
    "Open to all majors": ("major_all", {}),
    f"Our listing says this is open to international students{_NOT_ON_PAGE}": ("intl_open_listing", {}),
    f"Open to international students{_OUR_READING}": ("intl_open_read", {}),
    "Open to international students": ("intl_open", {}),
    "Your experience can support a thoughtful faculty outreach": ("experience_faculty", {}),
    "Your experience level is competitive": ("experience_competitive", {}),
    "You're comfortable with direct outreach": ("outreach_comfortable", {}),
    "Low application effort — quick to apply": ("effort_low", {}),
    "Paid opportunity": ("paid", {}),
    "Includes stipend": ("stipend", {}),
    "Explicitly welcomes first-time researchers": ("first_time_welcome", {}),
    "At your university": ("at_your_university", {}),
    "Faculty profile from a major research university": ("brand_faculty_university", {}),
    "Major research university — strong resume builder": ("brand_university", {}),
    "Faculty profile from a recognized research institution": ("brand_faculty_institution", {}),
    "Prestigious institution — strong resume builder": ("brand_institution", {}),
    "Potential for publication or long-term involvement": ("publication_pathway", {}),
    "Summer research — in season; applications are typically active now": ("summer_in_season", {}),
}

_GAP_EXACT: dict[str, tuple[str, dict[str, str]]] = {
    "Add your class year to confirm year eligibility": ("year_missing", {}),
    "For undergraduates — not a graduate-level opening": ("year_undergrad_only", {}),
    f"Our listing suggests this is for undergraduates{_NOT_ON_PAGE}": ("year_listing_undergrad", {}),
    _SIMPLIFY_NO_SPONSORSHIP_GAP: ("intl_listing_no_sponsorship", {"label": SIMPLIFY_NO_SPONSORSHIP_LABEL}),
    f"Our listing says this requires US citizenship or permanent residency{_NOT_ON_PAGE}": ("citizenship_listing", {}),
    f"May require US citizenship or permanent residency{_OUR_READING}": ("citizenship_read", {}),
    f"May require US citizenship or permanent residency{_OUR_LISTING_AND_READING}": ("citizenship_listing_and_read", {}),
    _SIMPLIFY_NO_SPONSORSHIP_REASON: ("citizenship_no_sponsorship", {}),
    "Requires US citizenship or permanent residency": ("citizenship_required", {}),
    "International eligibility unclear — many internships qualify for CPT/OPT; confirm with the employer": (
        "intl_unclear_internship", {},
    ),
    "International eligibility is not stated — confirm when contacting the faculty member": (
        "intl_unstated_faculty", {},
    ),
    "International eligibility unclear — verify before applying": ("intl_unclear", {}),
    "Resume required — prepare one before applying": ("resume_required", {}),
    "Your experience signal is limited — ask what preparation would help": ("experience_limited_faculty", {}),
    "Limited prior experience — position may be competitive": ("experience_limited", {}),
    "High application effort — plan time for materials": ("effort_high", {}),
    "Research area looks different from your stated interests": ("topic_mismatch", {}),
    "Deadline has passed — verify if still accepting applications": ("deadline_passed", {}),
    "This program's start date has passed — check whether a new cycle is open": ("start_passed", {}),
    "Targets graduate / PhD students — a reach for undergraduates": ("grad_level_reach", {}),
    "Faculty availability and eligibility are not confirmed — verify when you contact them": (
        "faculty_unconfirmed", {},
    ),
}

# The skill line's label, served as a code: the label is ours, not a name.
_SKILL_LEVELS = {
    "Strong tech stack fit": "strong",
    "Tech stack overlap": "overlap",
    "Partial skill match": "partial",
}
_SKILL_LEVEL = "(?P<level>" + "|".join(map(re.escape, _SKILL_LEVELS)) + ")"
_NOT_ON_PAGE_RE = re.escape(_NOT_ON_PAGE)

# Sentences with a variable part, tried in order; the first full match wins.
# DOTALL: a parameter can hold a newline, and a `.` that stops at one makes a
# line fall through to later patterns that backtrack over the whole line.
_FIT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (key, re.compile(pattern, re.DOTALL)) for key, pattern in (
        ("year_may_fit", r"Your class year \((?P<year>.+)\) may fit this program"),
        ("year_accepts", r"Accepts (?P<year>.+) students"),
        ("major_may_fit", r"Your major \((?P<major>.*)\) may fit this program"),
        ("major_may_relate", r"Your major \((?P<major>.*)\) may be related to this program"),
        ("major_direct", r"Your major \((?P<major>.*)\) is a direct match"),
        ("major_close", r"Your major \((?P<major>.*)\) is closely related to requirements"),
        ("skills_fit_required", _SKILL_LEVEL + r": (?P<skills>.+) — (?P<matched>\d+)/(?P<required>\d+) required"),
        ("skills_fit", _SKILL_LEVEL + r": (?P<skills>.+)"),
        ("skills_mentioned", r"Skills mentioned in the description: (?P<skills>.+)"),
        ("skills_preferred", r"Preferred skill overlap: (?P<skills>.+)"),
        ("type_match", r"Matches your interest in (?P<type>.*)"),
        ("interests_match", r"Matches your interests: (?P<terms>.+)"),
        ("interest_their_work", r"Your interest in (?P<interest>.+?) closely matches their work on (?P<work>.+)"),
        ("interest_lab_work", r"Your interest in (?P<interest>.+?) closely matches (?P<lab>.+)'s work on (?P<work>.+)"),
        ("they_also_work", r"They also work on (?P<work>.+)"),
        ("interests_lab_focus", r"Your research interests align with (?P<lab>.+)'s focus area"),
        ("deadline_soon", r"Deadline in (?P<days>\d+) days — apply soon"),
        ("lab_focus", r"This lab focuses on (?P<summary>.+)"),
        ("lab_also_works", r"(?P<lab>.+?) also works on (?P<work>.+)"),
    )
)

_GAP_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (key, re.compile(pattern, re.DOTALL)) for key, pattern in (
        ("year_targets", r"Typically targets (?P<years>.+)"),
        ("year_listing_targets", r"Our listing suggests (?P<years>.+) students" + _NOT_ON_PAGE_RE),
        ("major_listing", r"Our listing suggests (?P<majors>.+) majors" + _NOT_ON_PAGE_RE),
        ("major_prefers", r"Prefers (?P<majors>.+)"),
        ("skills_missing", r"Missing skills: (?P<skills>.+)"),
        ("type_mismatch", r"This is a (?P<type>.*) — not your primary target type"),
    )
)


def _keyed(key: str, params: dict[str, str]) -> ReasonKey:
    return {"key": key, "params": dict(params)}


def reason_key(reason: str, kind: str, *, research_summary: str = "") -> ReasonKey | None:
    """The template key and params of one fit (``kind="fit"``) or gap
    (``kind="gap"``) sentence, or None when no template wrote it or the
    sentence is longer than ``MAX_KEYED_REASON_CHARACTERS``."""
    if not isinstance(reason, str) or not reason or len(reason) > MAX_KEYED_REASON_CHARACTERS:
        return None
    exact, patterns = (_FIT_EXACT, _FIT_PATTERNS) if kind == "fit" else (_GAP_EXACT, _GAP_PATTERNS)
    found = exact.get(reason)
    if found is not None:
        return _keyed(*found)
    # The research-summary headline is the record's own names and topics,
    # with no words of ours to translate; keyed so it is not mistaken for
    # an unknown template.
    if kind == "fit" and research_summary and reason == research_summary:
        return _keyed("research_summary", {"text": reason})
    for key, pattern in patterns:
        match = pattern.fullmatch(reason)
        if match is not None:
            params = match.groupdict()
            if "level" in params:
                params["level"] = _SKILL_LEVELS[params["level"]]
            return _keyed(key, params)
    return None


def reason_keys(
    reasons: list[str],
    kind: str,
    *,
    record: dict | None = None,
    model_reason: str | None = None,
) -> list[ReasonKey | None]:
    """``reason_key`` for each sentence, index-aligned with ``reasons``.

    ``record`` is the opportunity the reasons are about (its research
    summary is one fit line). ``model_reason`` is a sentence a model wrote
    into the list; it keeps a None key whatever it happens to look like,
    since model output is never rendered from our table.
    """
    summary = _summarize_research(record) if kind == "fit" and record else ""
    return [
        None if model_reason and reason == model_reason
        else reason_key(reason, kind, research_summary=summary)
        for reason in reasons
    ]
