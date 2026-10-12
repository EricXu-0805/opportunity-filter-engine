"""The ranker's per-record static build (M74).

A cross-school ranking scores 130,000+ records, more than the static cache
holds, so it rebuilds every record's static: 13-15 s of a 23 s first page.
Two steps of the build did their work the slow way: the professor's name was
cut out of the interest-bonus text with a pattern compiled for each record,
and fourteen mentor and pathway patterns walked every position of every
description. These tests hold the fast paths to the answers of the
expressions they replace.
"""

import os
import random
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matcher import ranker


def _regex_cut(text, name):
    return re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)


@pytest.mark.parametrize(("text", "name"), [
    ("Smith Lab", "Smith"),
    ("SMITH lab of smith and sMiTh", "smith"),
    ("Prof. J. Smith (PI) group", "J. Smith (PI)"),
    ("a+b A+B a+b", "A+B"),
    ("aaaaa", "aa"),
    ("O'Neil Lab of O'NEIL", "o'neil"),
    ("short", "a much longer name"),
    ("no match here", "Zed"),
    ("", "Smith"),
    ("Smith", " "),
    ("tab\tand\nnewline SMITH", "smith"),
    # Case folds re knows outside ASCII: the Kelvin sign matches k, the long
    # s matches s, the dotted capital I matches i. Either side non-ASCII
    # takes re's own path.
    ("Kelvin lab", "kelvin"),
    ("Kelvin lab", "Kelvin"),
    ("Strauſ lab", "STRAUS"),
    ("İstanbul group", "istanbul"),
    ("José Núñez Lab", "JOSÉ NÚÑEZ"),
])
def test_the_name_is_cut_where_the_case_insensitive_pattern_cuts_it(text, name):
    assert ranker._cut_name(text, name) == _regex_cut(text, name)


def test_the_name_cut_matches_the_pattern_on_random_text():
    rng = random.Random(74)
    ascii_letters = "aAbBkKsSiI .-()+*?'\\"
    folding = ascii_letters + "KſİıéÉ"
    for case in range(6000):
        alphabet = ascii_letters if case % 2 else folding
        name = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 3)))
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 14)))
        assert ranker._cut_name(text, name) == _regex_cut(text, name), (text, name)


def test_the_name_cut_fails_where_the_pattern_fails():
    with pytest.raises(TypeError):
        _regex_cut(None, "Smith")
    with pytest.raises(TypeError):
        ranker._cut_name(None, "Smith")


def _record(description: str | None, **overrides) -> dict:
    return {
        "id": "static-1",
        "title": "Undergraduate Research Assistant",
        "organization": "Example University",
        "department": "Chemistry",
        "lab_or_program": "Smith Lab",
        "pi_name": "Jane Smith",
        "source_type": "listing",
        "opportunity_type": "research",
        "keywords": ["catalysis", "Smith chemistry", "machine learning"],
        "description_raw": description,
        "eligibility": {"skills_required": ["Python"]},
        **overrides,
    }


def _scan_with_every_pattern(record: dict) -> tuple[int, int]:
    desc = (record.get("description_raw") or record.get("description_clean") or "").lower()
    stem_scan = ranker._ML_TOPIC_RE.sub(" ", desc)
    mentor = sum(1 for k in ranker._MENTOR_KEYWORDS if ranker._UPSIDE_STEM_RES[k].search(stem_scan))
    pathway = sum(1 for k in ranker._PATHWAY_KEYWORDS if ranker._UPSIDE_STEM_RES[k].search(stem_scan))
    return mentor, pathway


@pytest.mark.parametrize("description", [
    None,
    "",
    "We use machine learning and deep-learning methods.",
    "Students learn to use machine learning; we teach and mentor.",
    "Machine   Learning to LEARN: guided supervision, onboarding.",
    "Organic synthesis and newspaper archives.",
    "Co-authored publications, conference papers and a senior thesis.",
    "_mentor and xteach and 9paper are inside words.",
    "émentor is inside a word; —mentor and (paper) are not.",
    "Return in the summer to continue the work; returning students welcome.",
    "self-supervised learning, meta learning, federated-learning, training.",
    "mentor mentor mentor training learn guided supervision teach onboard",
    "publication paper co-author return continue conference thesis",
])
def test_the_mentor_and_pathway_scores_are_what_every_pattern_finds(description):
    record = _record(description)
    mentor, pathway = _scan_with_every_pattern(record)
    static = ranker._build_opp_static(record)
    assert static.mentor_score == 35.0 + min(55.0, mentor * 20.0)
    assert static.pathway_score == 40.0 + min(55.0, pathway * 18.0)
    assert static.pathway_reason == (pathway >= 2)


def test_the_interest_text_is_cut_as_before():
    record = _record("A lab.", title="Smith group: SMITH-lab research", keywords=["smith", "catalysis"])
    static = ranker._build_opp_static(record)
    parts = [_regex_cut(part, "Jane Smith") for part in (record["title"], "smith catalysis", "Smith Lab")]
    expected = re.sub(r"[^a-z0-9]+", " ", " ".join(parts).lower()).strip()
    assert static.signal_text == f" {expected} "

    named = _record("A lab.", pi_name="Smith", title="Smith group: SMITH-lab research")
    parts = [_regex_cut(part, "Smith") for part in (named["title"], " ".join(named["keywords"]), "Smith Lab")]
    expected = re.sub(r"[^a-z0-9]+", " ", " ".join(parts).lower()).strip()
    assert ranker._build_opp_static(named).signal_text == f" {expected} "


def test_a_static_build_compiles_no_pattern_for_an_ascii_name(monkeypatch):
    name_patterns: list[str] = []
    real_sub = re.sub

    def recording_sub(pattern, *args, **kwargs):
        if pattern == re.escape("Jane Smith"):
            name_patterns.append(pattern)
        return real_sub(pattern, *args, **kwargs)

    monkeypatch.setattr(ranker.re, "sub", recording_sub)
    ranker._build_opp_static(_record("Students learn and publish."))
    assert name_patterns == [], "a ranking would compile a pattern for every record"
