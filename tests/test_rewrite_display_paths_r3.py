"""Round-3 display paths for acceptance criteria (1), (2) and (3) of fix/tailor-review.

Provider-free, through the helpers of tests/test_rewrite_display_paths.py: the
generation call, the renovation plan and the faithfulness review are stubbed at
``chat_completion``. Each test was written as a probe of a gap the round-3
re-measure reported, failed on 1e15a8e, and now pins the fix.

Round 4 moved extraction back to origin/main's and removed this file's extraction
probes; their résumés are cases of tests/fixtures/extraction_differential_cases.json,
which tests/test_extraction_matches_main.py runs against main.

Run from the repository root:
    python -m pytest tests/test_rewrite_display_paths_r3.py -q
"""
from __future__ import annotations

import json

import pytest

from tests.test_rewrite_display_paths import (
    ALL_PATHS,
    TWO,
    TWO_ANCHORS,
    _rewrite,
    offered,
    opportunity,  # noqa: F401  (pytest fixture)
    post_tailor,
    run,
)

# ------------------------------------------------------------------ criterion (1): the verdict list
# ai_review applied each verdict by its "index", so an incomplete or misnumbered list let a verdict
# written for one pair accept another. TWO's first pair is a lead_with rewrite with one link (L1),
# its second a verdict-free verb_first rewrite.


def _verdict(index, faithful, links):
    return {"index": index, "changes": "[ok]" if faithful else "drops the student's qualifier",
            "faithful": faithful, "links": [{"id": ident, "entailed": True} for ident in links],
            "problem": "" if faithful else "qualifier"}


MISBOUND_REVIEWS = {
    # The reviewer judged only pair 2 (faithful) and numbered its verdict 1: pair 1 was never judged.
    "pair 2 judged, numbered 1": [_verdict(1, True, ["L1"])],
    # Pair 1 rejected under number 2 and pair 2 accepted under number 1: read by index, pair 1 is accepted.
    "both judged, numbers swapped": [_verdict(2, False, []), _verdict(1, True, ["L1"])],
    # Pair 1 judged twice and pair 2 not at all.
    "pair 1 twice": [_verdict(1, True, ["L1"]), _verdict(1, True, ["L1"])],
}


@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/renovate"])
@pytest.mark.parametrize("name", list(MISBOUND_REVIEWS))
def test_a_verdict_list_not_tied_to_its_pairs_shows_no_rewrite(opportunity, monkeypatch, path, name):  # noqa: F811
    reply = json.dumps({"verdicts": MISBOUND_REVIEWS[name]})
    body, reviews = post_tailor(opportunity, monkeypatch, path, TWO, reply, anchors=TWO_ANCHORS)
    assert len(reviews) == 1 and len(reviews[0]["pairs"]) == 2
    assert offered(path, body) == [[], []], (name, offered(path, body))


@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/renovate"])
def test_a_complete_list_in_pair_order_still_shows_the_accepted_rewrite(opportunity, monkeypatch, path):  # noqa: F811
    reply = json.dumps({"verdicts": [_verdict(1, False, ["L1"]), _verdict(2, True, [])]})
    body, _ = post_tailor(opportunity, monkeypatch, path, TWO, reply, anchors=TWO_ANCHORS)
    assert [bool(texts) for texts in offered(path, body)] == [False, True]


# ------------------------------------------------------------------ criterion (2b): symbols are English
# 33fc0db's rules kept faithful rewrites of English lines holding a Greek letter, the micro sign or an
# accented Latin letter as wrong_language, before the review; main sends them to the review. Each line
# holds two English function words of three letters, which the default keep asks for (round 4).
SYMBOL_LINES = {
    "beta-amyloid": ("Research assistant in the Lee Lab, measuring β-amyloid levels in 40 mouse brains for a study.",
                     "Measured β-amyloid levels in 40 mouse brains for a study as a research assistant in the Lee Lab."),
    "micro-sign": ("Research assistant in the Lee Lab, imaging 5 \u00b5m sections of 40 mouse brains for a study.",
                   "Imaged 5 \u00b5m sections of 40 mouse brains for a study as a research assistant in the Lee Lab."),
    "alpha-symbol": ("Research assistant in the Lee Lab, measuring α and β waves in 40 EEG recordings.",
                     "Measured α and β waves in 40 EEG recordings as a research assistant in the Lee Lab."),
}


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(SYMBOL_LINES))
def test_a_line_with_a_greek_symbol_still_reaches_the_review(opportunity, monkeypatch, path, name):  # noqa: F811
    original, rewrite = SYMBOL_LINES[name]
    shown, seen = run(opportunity, monkeypatch, path, original, _rewrite(rewrite, [{"op": "verb_first"}]),
                      "We measure brain tissue in mouse models.")
    assert rewrite in seen and shown == [rewrite], (shown, seen)


# ------------------------------------------------------------------ criterion (3): pronouns
# tokens() drops first-person markers and personal_markers() counts them in any script, so an English
# line that already holds Chinese could have its "I" written as 我 or 本人: the rewrite passed the
# contract and the locks and was shown after an accepting review.
PRONOUN_LINE = "Responsible for writing Python scripts for 数据清洗; I also tested them."


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("marker", ["我", "本人"])
def test_an_english_lines_i_written_in_chinese_is_kept_before_the_review(opportunity, monkeypatch, path, marker):  # noqa: F811
    rewrite = f"Wrote Python scripts for 数据清洗; {marker} also tested them."
    shown, seen = run(opportunity, monkeypatch, path, PRONOUN_LINE, _rewrite(rewrite, [{"op": "verb_first"}]),
                      "We clean survey data with Python scripts.")
    assert (shown, seen) == ([], set())
