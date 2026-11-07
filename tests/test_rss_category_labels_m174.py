"""M174: the OUR blog feed's own categories are its labels, not tags we inferred.

uiuc_our_rss keeps each post's feed categories as its keywords ("URAP",
"FGSRP", "Unsorted"). The enricher replaces a bare "Unsorted" with its keyword
bank's topics where the bank finds any, and stamps them; five rows on the
2026-11-07 corpus kept their categories. The rule every surface shares counted
those as ours: the detail facts called them topics read off the text, the card
flagged them inferred, and a chip one matched ended "— based on topics we
inferred". They are the source's own words. They name no research area
either, so the detail facts list none, and no line calls them the program's
work or the email's "your work on".
"""
from __future__ import annotations

import copy

import pytest

from backend.lib.opportunity_detail import build_detail_fields, keywords_basis
from backend.lib.public_opportunity_detail import project_public_detail
from backend.routes.opportunities import _redact
from src.evidence import keywords_are_source_labels, stamp_inferred
from src.matcher.config import MATCHER_VERSION
from src.matcher.ranker import _OUR_TOPICS, _summarize_research, rank_opportunity, score_upside
from src.recommender.cold_email import _stated_keywords


def _rss(keywords, *, stamp=None, source="uiuc_our_rss"):
    row = {
        "id": "rss-our-m174", "source": source, "source_type": "rss", "opportunity_type": "research",
        "title": "RESEARCH OPPORTUNITY: Summer Lab Assistant",
        "organization": "University of Illinois at Urbana-Champaign", "keywords": list(keywords),
        "description_raw": "A lab is looking for undergraduate assistants this summer.",
        "eligibility": {}, "application": {}, "metadata": {"is_active": True},
    }
    if stamp:
        stamp_inferred(row["metadata"], "keywords", stamp)
    return row


def _profile(*chips):
    return {"research_interests_text": ", ".join(chips), "desired_fields": list(chips),
            "seeking_type": ["research"]}


@pytest.mark.parametrize(("labels", "chip"), [
    (["URAP"], "urap"),
    (["Neuroscience", "Unsorted"], "neuroscience"),
    # The label inside the chip: no word of the row names "cognitive neuroscience".
    (["Neuroscience"], "cognitive neuroscience"),
], ids=["program label", "topic label", "label inside the chip"])
def test_a_chip_a_category_matches_is_not_called_inferred(labels, chip):
    _, fit, _ = score_upside(_profile(chip), _rss(labels), precomputed_sim=0.0)
    assert f"Matches your interests: {chip}" in fit
    assert not any(_OUR_TOPICS in line for line in fit)


def test_bank_topics_the_enricher_stamped_stay_ours():
    _, fit, _ = score_upside(_profile("neuroscience"), _rss(["neuroscience"], stamp="rule:enricher"),
                             precomputed_sim=0.0)
    assert f"Matches your interests: neuroscience{_OUR_TOPICS}" in fit


@pytest.mark.parametrize("labels", [["Neuroscience"], ["Unsorted"], ["URAP", "Unsorted"]])
def test_no_line_calls_a_category_their_work(labels):
    row = _rss(labels)
    fit = rank_opportunity(_profile("neuroscience"), row, precomputed_sim=0.5).reasons_fit
    named = [line for line in fit if any(label.lower() in line.lower() for label in labels)
             and not line.startswith("Matches your interests")]
    assert named == []
    assert _summarize_research(row) == ""


@pytest.mark.parametrize("labels", [["URAP"], ["Neuroscience", "Unsorted"]])
def test_a_row_with_a_lab_gets_no_focus_area_from_its_labels(labels):
    """As before the labels were the source's: the similarity names no focus
    area, and no topics we inferred, of a row whose keywords are its labels."""
    row = {**_rss(labels), "lab_or_program": "Neural Imaging Lab"}
    fit = rank_opportunity(_profile("neuroscience imaging"), row, precomputed_sim=0.5).reasons_fit
    assert [line for line in fit if "align" in line or "work on" in line] == []


def test_a_feed_row_with_no_labels_keeps_the_focus_area_any_listing_gets():
    # The line then rests on the post's own text, as on any listing (M171).
    row = {**_rss([]), "lab_or_program": "Neural Imaging Lab"}
    fit = rank_opportunity(_profile("neuroscience imaging"), row, precomputed_sim=0.5).reasons_fit
    assert "Your research interests align with Neural Imaging Lab's focus area" in fit


def _facts(row):
    payload = _redact(copy.deepcopy(row))
    return payload, build_detail_fields(payload, row)["fields"]["research_content"]


def test_the_detail_facts_and_the_card_flag_show_them_as_the_sources():
    row = _rss(["URAP", "Unsorted"])
    payload, research = _facts(row)
    assert keywords_basis(row) is None
    assert "keywords_attribution" not in payload
    assert "research_areas" not in research["explicit"] and "research_areas" not in research["inferred"]


def test_stamped_bank_topics_keep_the_inferred_facts():
    row = _rss(["neuroscience"], stamp="rule:enricher")
    payload, research = _facts(row)
    assert keywords_basis(row) == "text_scan"
    assert payload["keywords_attribution"] == "inferred"
    assert research["inferred"]["research_areas"] == {"value": ["neuroscience"], "basis": "text_scan"}


def test_the_email_does_not_call_them_their_work():
    assert _stated_keywords(project_public_detail(_rss(["Neuroscience"]))) == []


@pytest.mark.parametrize(("row", "labels"), [
    (_rss(["URAP"]), True),
    (_rss(["neuroscience"], stamp="rule:enricher"), False),
    (_rss(["URAP"], source="uiuc_sro"), False),
    (_rss(["URAP"], source="nsf_reu"), False),
], ids=["rss", "stamped rss", "sro", "nsf"])
def test_whose_keywords_are_source_labels(row, labels):
    assert keywords_are_source_labels(row) is labels


def test_the_matcher_version_moved_for_the_line():
    assert int(MATCHER_VERSION.split(".")[0]) >= 37
