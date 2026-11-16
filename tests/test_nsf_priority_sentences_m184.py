"""M184: the sentence naming NSF's priorities is no topic of the site.

NSF award abstracts state which of the agency's priority areas an award is
aligned with: "The training students will receive is aligned with NSF
priorities in Artificial Intelligence and Biotechnology." The collector's
keyword bank and major map read it like any other sentence, so a microbiology
site was tagged "artificial intelligence" and given CS and ECE as majors, and
ranked second for a student whose one interest was AI. On the 2026-11-16
corpus 60 of 758 NSF rows had such a sentence; on 22 it was the only place a
tagged topic stood (artificial intelligence 18, quantum 4, semiconductor 1),
and 12 rows' majors came from it (CS 10, ECE 9, Materials Science 1).

The rule: when the collector picks topic tags and majors, it does not read an
abstract sentence that names NSF (or the National Science Foundation) together
with the word "priority" or "priorities". The description keeps the sentence.

The enricher fills an NSF row the collector left without a tag from its own
keyword patterns, over the same abstract: it wrote "artificial intelligence"
back on 3 of the 5 rows the rule leaves without one, and had written it on a
sixth row from "NSF priorities in Biotechnology and AI". On an NSF row it
leaves out the same sentences.
"""
from __future__ import annotations

import pytest

from src.collectors.nsf_reu import normalize_award
from src.normalizers.enricher import enrich_opportunity

SITE = (
    "This REU Site award to Example State University supports the training of 10 students "
    "for 10 weeks. Students study how bacteria colonize a host and how the host responds."
)
MERIT = (
    "This award reflects NSF's statutory mission and has been deemed worthy of support through "
    "evaluation using the Foundation's intellectual merit and broader impacts review criteria."
)
TEMPLATE = "The training students will receive is aligned with NSF priorities in Artificial Intelligence and Biotechnology."


def _award(*sentences, title="REU Site: Microbes at the Host Interface"):
    return normalize_award({
        "id": "9900184", "title": title, "abstractText": " ".join(sentences),
        "fundProgramName": "RSCH EXPER FOR UNDERGRAD SITES", "awardeeName": "Example State University",
        "awardeeCity": "Springfield", "awardeeStateCode": "IL", "startDate": "06/01/2027", "expDate": "05/31/2030",
    })


def _majors(row):
    return row["eligibility"]["majors"]


@pytest.mark.parametrize(("sentence", "tag"), [
    (TEMPLATE, "artificial intelligence"),
    ("The training students will receive is aligned with the NSF priority in Quantum Information Science.", "quantum"),
    ("This project advances NSF’s priorities in Biotechnology and Artificial Intelligence.", "artificial intelligence"),
    ("This project advances NSF's priorities in Artificial Intelligence and Biotechnology.", "artificial intelligence"),
    ("The project advances current National Science Foundation priorities in Artificial Intelligence.",
     "artificial intelligence"),
    ("Research projects are aligned with NSF's Priority Areas of Advanced Manufacturing and Semiconductors.",
     "semiconductor"),
], ids=["template", "the NSF priority in", "curly apostrophe", "advances", "agency spelled out", "priority areas"])
def test_a_topic_named_only_as_an_nsf_priority_is_no_tag(sentence, tag):
    assert tag not in _award(SITE, sentence, MERIT)["keywords"]


def test_an_nsf_priority_gives_no_major():
    row = _award(SITE, TEMPLATE, MERIT)
    assert _majors(row) == ["STEM"]
    assert row["metadata"]["inferred_fields"]["eligibility.majors"] == "rule:keyword_bank"


def test_the_majors_the_site_states_stay_without_the_priority_ones():
    row = _award(SITE, "Projects span microbiology and cell biology.", TEMPLATE, MERIT)
    assert _majors(row) == ["Biology"]


@pytest.mark.parametrize("elsewhere", [
    "Students train artificial intelligence models that classify colony images.",
    "ARTIFICIAL INTELLIGENCE methods are used to segment the images.",
], ids=["a sentence of the site", "another case"])
def test_a_topic_the_abstract_states_elsewhere_is_still_tagged(elsewhere):
    row = _award(SITE, elsewhere, TEMPLATE, MERIT)
    assert row["keywords"] == ["artificial intelligence"]
    assert _majors(row) == ["CS", "ECE"]


def test_a_topic_in_the_title_is_still_tagged():
    row = _award(SITE, TEMPLATE, MERIT, title="REU Site: Artificial Intelligence for Microbiology")
    assert row["keywords"] == ["artificial intelligence"]
    assert {"CS", "ECE"} <= set(_majors(row))


@pytest.mark.parametrize("sentence", [
    # No NSF in it: national priorities, and a verb.
    "This site aligns with national priorities in artificial intelligence and workforce development.",
    "The program prioritizes artificial intelligence projects led by first-year students.",
    # NSF without the word: the sentence is the site's.
    "Students join an NSF-funded artificial intelligence institute for the summer.",
    "The NSF-funded institute prioritizes artificial intelligence projects.",
], ids=["national priorities", "prioritizes", "NSF without priorities", "NSF and prioritizes"])
def test_other_sentences_are_read_as_before(sentence):
    row = _award(SITE, sentence, MERIT)
    assert row["keywords"] == ["artificial intelligence"]
    assert _majors(row) == ["CS", "ECE"]


def test_the_sentences_around_it_are_read_as_before():
    """A paragraph break after it, and a topic in the sentence on each side."""
    abstract = (
        f"{SITE} Students use machine learning to count colonies. {TEMPLATE}\r\n\r\n"
        f"The site also teaches remote sensing of soil microbes. {MERIT}"
    )
    row = _award(abstract)
    assert row["keywords"] == ["machine learning", "remote sensing"]
    assert _majors(row) == ["CS", "ECE", "STAT"]


def test_an_abstract_without_the_sentence_is_tagged_as_before():
    abstract = (
        "Students work on robotics and computer vision.\r\n\r\nProjects use machine learning, "
        "and some study polymer chemistry! Is ecology included? Yes: marine biology and climate."
    )
    row = _award(abstract)
    assert row["keywords"] == [
        "machine learning", "computer vision", "robotics", "ecology", "climate", "chemistry",
        "marine biology", "polymer",
    ]
    assert _majors(row) == [
        "Biology", "CS", "Chemistry", "ECE", "Mechanical Engineering", "Natural Resources", "STAT",
    ]


def test_the_description_keeps_the_sentence():
    row = _award(SITE, TEMPLATE, MERIT)
    assert TEMPLATE in row["description_raw"]
    assert TEMPLATE in row["description_clean"]
    assert row["eligibility"]["eligibility_text_raw"] == row["description_raw"][:500]


def _backfilled(*sentences):
    row = _award(*sentences)
    assert row["keywords"] == []
    return enrich_opportunity(row)


@pytest.mark.parametrize("sentence", [
    TEMPLATE,
    "The training students will receive is aligned with the NSF priorities in Biotechnology and AI.",
    "The training students will receive is aligned with the NSF priority in Quantum Information Science.",
], ids=["template", "abbreviation", "quantum"])
def test_the_backfill_reads_no_nsf_priority_sentence_either(sentence):
    row = _backfilled(SITE, sentence, MERIT)
    assert row["keywords"] == ["undergraduate research"]
    assert row["metadata"]["inferred_fields"]["keywords"] == "rule:enricher"


def test_the_backfill_leaves_out_a_sentence_the_stored_description_cuts_short():
    """description_clean is the abstract's first 1,500 characters."""
    lead = f"{SITE} " + "Students present a poster at the end of the summer. " * 30
    cut = TEMPLATE.index(" and Biotechnology")
    row = _backfilled(lead[: 1500 - cut] + TEMPLATE, MERIT)
    assert row["description_clean"].endswith("NSF priorities in Artificial Intelligence")
    assert row["keywords"] == ["undergraduate research"]


def test_the_backfill_still_reads_the_sites_own_sentences():
    row = _backfilled(SITE, "Students use AI to classify colony images.", TEMPLATE, MERIT)
    assert row["keywords"] == ["artificial intelligence", "undergraduate research"]


def test_the_backfill_reads_the_sentence_on_a_row_of_another_source():
    row = {
        "id": "m184-campus", "source": "example_research_programs", "source_type": "campus_program",
        "title": "Summer Microbiology Program", "keywords": [], "eligibility": {}, "metadata": {},
        "description_clean": f"Students study how bacteria colonize a host. {TEMPLATE}",
    }
    assert enrich_opportunity(row)["keywords"] == ["artificial intelligence"]
