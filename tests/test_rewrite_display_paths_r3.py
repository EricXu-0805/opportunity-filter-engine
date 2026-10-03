"""Round-3 display paths for acceptance criteria (1) and (3) of fix/tailor-review.

Provider-free, through the helpers of tests/test_rewrite_display_paths.py: the
generation call, the renovation plan and the faithfulness review are stubbed at
``chat_completion``. Each test was written as a probe of a gap the round-3
re-measure reported, failed on 1e15a8e, and now pins the fix.

Run from the repository root:
    python -m pytest tests/test_rewrite_display_paths_r3.py -q
"""
from __future__ import annotations

import json

import pytest

from tests.test_rewrite_display_paths import (
    TWO,
    TWO_ANCHORS,
    offered,
    opportunity,  # noqa: F401  (pytest fixture)
    post_tailor,
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
