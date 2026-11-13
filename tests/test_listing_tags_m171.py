"""M171: no line names a listing's tags as its work or focus.

A listing's keywords are ours on every collector but the SRO, stamped or not
(`keywords_are_source_topics`, the detail page's rule, which labels them
"System inference"): Simplify maps a category, NSF runs a keyword bank over
the abstract, and campus, external and manual rows carry tags typed into our
config. The similarity line ("<lab>'s work on <tags>", "<lab> also works on
<tags>" and the their/They forms) and the research-summary headline ("<PI>'s
<program> — <tags>", "This lab focuses on <tags>") still named them as the
program's own, and where they repeated a chip the dedupe dropped the interest
line M155 hedges. Neither line is written now; the interest lines carry the
match. Scores do not change.

Nor is any other headline (M183). A listing left with no topical tag, or with
stamped ones, fell back on the program's name or the description's first
sentence cut at 100 characters, which on live rows was a directory's name, a
page title, NSF's award boilerplate or our own template.

A pi_name the detail page removes (`pi_name_basis`: an inference stamp, or a
page scan on a campus program row) names no one in a line either: the lab
labels the row, and the summary neither names it nor is let in by it.
"""
from __future__ import annotations

import pytest

from backend.lib.opportunity_detail import pi_name_basis
from src.evidence import stamp_inferred
from src.matcher.config import MATCHER_VERSION
from src.matcher.ranker import _OUR_TOPICS, _line_pi, _summarize_research, rank_opportunity, score_upside
from src.matcher.reason_keys import reason_keys

# (source, source_type, opportunity_type). A row with no source_type is of no
# known kind, and its keywords are ours too: 26 live campus rows are like it.
LISTINGS = {
    "simplify": ("simplify_internships", "internship", "internship"),
    "nsf_reu": ("nsf_reu", "summer_program", "summer_program"),
    "campus_program": ("illinois_research_programs", "campus_program", "research"),
    "campus_department": ("illinois_research_programs", "campus_department", "research"),
    "ucb_department": ("ucb_research_programs", "ucb_department", "research"),
    "manual": ("manual", "manual", "summer_program"),
    "no_source_type": ("uiuc_other", None, "research"),
}
TAGS = ("robotics", "computer vision", "embedded systems")
TEXTS = {"overlap": "robotics for farms", "no overlap": "perception for drones"}
# The words of every template that named the tags as the row's work.
WORK = ("'s work on", " also works on", "closely matches their work on", "They also work on")
TAG_KEYS = {"research_summary", "lab_focus", "interest_lab_work", "lab_also_works",
            "interest_their_work", "they_also_work"}
STAMPS = ["derived:openalex_topics", "derived:illinois_experts_concepts", "tag:department_field"]


def _listing(kind, *, keywords=TAGS, title="Summer Research Program", lab="Field Robotics Program", pi="Pat Lee"):
    source, source_type, opportunity_type = LISTINGS[kind]
    row = {
        "id": f"m171-{kind}", "source": source, "opportunity_type": opportunity_type, "title": title,
        "lab_or_program": lab, "pi_name": pi, "keywords": list(keywords),
        "description_raw": "Students spend ten weeks building field robots with a mentor.",
        "eligibility": {}, "application": {}, "metadata": {"is_active": True},
    }
    if source_type:
        row["source_type"] = source_type
    return row


def _sro_twin(row):
    """The same row from the SRO, whose research area is its own words."""
    return {**row, "id": "m171-sro", "source": "uiuc_sro"}


def _faculty(*, stamp=None):
    row = {
        "id": "m171-faculty", "source": "uiuc_faculty", "source_type": "faculty_research",
        "opportunity_type": "research", "pi_name": "Pat Lee", "lab_or_program": "Field Robotics Lab",
        "department": "Department of Mechanical Engineering", "keywords": list(TAGS),
        "eligibility": {}, "application": {}, "metadata": {"is_active": True},
    }
    if stamp:
        stamp_inferred(row["metadata"], "keywords", stamp)
    return row


def _profile(text, fields=("robotics",)):
    return {"research_interests_text": text, "desired_fields": list(fields), "seeking_type": ["research"]}


def _work_lines(fit):
    return [line for line in fit if any(words in line for words in WORK)]


@pytest.mark.parametrize("labelled", [True, False], ids=["lab", "no lab"])
@pytest.mark.parametrize("text", TEXTS.values(), ids=TEXTS.keys())
@pytest.mark.parametrize("kind", LISTINGS)
def test_no_line_names_a_listings_tags_as_its_work(kind, text, labelled):
    row = _listing(kind) if labelled else _listing(kind, lab="", pi="")
    _, fit, _ = score_upside(_profile(text), row, precomputed_sim=0.5)
    assert _work_lines(fit) == []
    assert not [line for line in fit if "topics we inferred for" in line or "focus area" in line]
    assert f"Matches your interests: robotics{_OUR_TOPICS}" in fit


@pytest.mark.parametrize("text", TEXTS.values(), ids=TEXTS.keys())
@pytest.mark.parametrize("row", [_sro_twin(_listing("nsf_reu")), _faculty()], ids=["sro", "faculty"])
def test_a_rows_own_research_areas_keep_their_lines(row, text):
    lab = "Prof. Pat Lee" if row["source"] == "uiuc_sro" else "Pat Lee"
    work = "robotics, computer vision, embedded systems"
    fit = rank_opportunity(_profile(text), row, precomputed_sim=0.5).reasons_fit
    assert (
        f"Your interest in robotics closely matches {lab}'s work on {work}" if text == TEXTS["overlap"]
        else f"{lab} also works on {work}"
    ) in fit
    assert f"Pat Lee's {row['lab_or_program']} — {work}" in fit


@pytest.mark.parametrize("stamp", STAMPS)
def test_stamped_faculty_keywords_keep_the_line_that_says_they_are_ours(stamp):
    _, fit, _ = score_upside(_profile(TEXTS["no overlap"]), _faculty(stamp=stamp), precomputed_sim=0.5)
    assert "Your research interests align with topics we inferred for Pat Lee" in fit
    assert _work_lines(fit) == []


def test_a_stamped_listing_keeps_the_line_that_says_its_tags_are_ours():
    row = _listing("nsf_reu")
    stamp_inferred(row["metadata"], "keywords", "rule:enricher")
    _, fit, _ = score_upside(_profile(TEXTS["no overlap"]), row, precomputed_sim=0.5)
    assert "Your research interests align with topics we inferred for Prof. Pat Lee" in fit


@pytest.mark.parametrize("keywords", [["undergraduate research"], ["research", "summer"]],
                         ids=["role-only", "generic-only"])
@pytest.mark.parametrize("kind", LISTINGS)
def test_a_listing_whose_tags_name_no_topic_keeps_the_focus_area(kind, keywords):
    """No tag is named, so the similarity rests on the listing's description.
    A campus row's pi_name is a page scan the detail page removes, so the
    program labels its line."""
    label = "Field Robotics Program" if LISTINGS[kind][0].endswith("_research_programs") else "Prof. Pat Lee"
    _, fit, _ = score_upside(_profile(TEXTS["no overlap"]), _listing(kind, keywords=keywords), precomputed_sim=0.5)
    assert f"Your research interests align with {label}'s focus area" in fit


@pytest.mark.parametrize(("lab", "pi"), [
    ("Field Robotics Program", "Pat Lee"), ("", "Pat Lee"), ("Field Robotics Program", ""), ("", ""),
], ids=["pi and program", "pi", "program", "tags only"])
@pytest.mark.parametrize("kind", LISTINGS)
def test_a_listing_has_no_headline_listing_its_tags(kind, lab, pi):
    row = _listing(kind, lab=lab, pi=pi)
    assert _summarize_research(row) == ""
    fit = rank_opportunity(_profile(TEXTS["no overlap"]), row, precomputed_sim=0.5).reasons_fit
    assert not [line for line in fit if "embedded systems" in line or line.startswith("This lab focuses on")]


# Tags that name no topic, or that a stamp already calls ours (M183).
NO_TOPIC_TAGS = {
    "role-only": (["undergraduate research"], None),
    "generic-only": (["research", "summer"], None),
    "no tags": ([], None),
    "stamped tags": (list(TAGS), "rule:enricher"),
}


@pytest.mark.parametrize(("lab", "pi"), [
    ("Field Robotics Program", "Pat Lee"), ("", "Pat Lee"), ("Field Robotics Program", ""), ("", ""),
], ids=["pi and program", "pi", "program", "description only"])
@pytest.mark.parametrize("tags", NO_TOPIC_TAGS)
@pytest.mark.parametrize("kind", LISTINGS)
def test_a_listing_has_no_headline_whatever_tags_remain(kind, tags, lab, pi):
    """With no topical tag left, the headline was the PI's program and the
    description's first sentence cut at 100 characters, or "This lab focuses
    on" the program's name or that sentence."""
    keywords, stamp = NO_TOPIC_TAGS[tags]
    row = _listing(kind, keywords=keywords, lab=lab, pi=pi)
    if stamp:
        stamp_inferred(row["metadata"], "keywords", stamp)
    assert _summarize_research(row) == ""
    fit = rank_opportunity(_profile(TEXTS["no overlap"]), row, precomputed_sim=0.5).reasons_fit
    assert not [line for line in fit if line.startswith(("This lab focuses on", "Pat Lee", "Field Robotics", "Students"))]


@pytest.mark.parametrize(("row", "headline"), [
    (_sro_twin(_listing("nsf_reu")), "Pat Lee's Field Robotics Program — robotics, computer vision, embedded systems"),
    (_faculty(), "Pat Lee's Field Robotics Lab — robotics, computer vision, embedded systems"),
    (_faculty(stamp="derived:openalex_topics"), "Pat Lee's Field Robotics Lab (Department of Mechanical Engineering)"),
], ids=["sro", "faculty", "stamped faculty"])
def test_the_sros_and_facultys_headlines_stay(row, headline):
    assert _summarize_research(row) == headline
    assert headline in rank_opportunity(_profile(TEXTS["no overlap"]), row, precomputed_sim=0.5).reasons_fit


def test_the_sro_has_no_headline_once_a_stamp_calls_its_tags_ours():
    row = _sro_twin(_listing("nsf_reu"))
    stamp_inferred(row["metadata"], "keywords", "rule:enricher")
    assert _summarize_research(row) == ""


@pytest.mark.parametrize(("title", "line"), [
    ("Software Engineering Intern", "Matches your interests: software engineering"),
    ("Platform Intern", f"Matches your interests: software engineering{_OUR_TOPICS}"),
], ids=["title names the chip", "title does not"])
def test_a_chip_the_tags_repeat_keeps_its_interest_line(title, line):
    """A student who types one interest saw no interest line on such cards:
    "<company>'s work on <chip>" repeated the chip, and the dedupe dropped
    the line."""
    row = _listing("simplify", title=title, keywords=["software engineering"], lab="Example Software Co", pi="")
    profile = _profile("software engineering", ["software engineering"])
    fit = rank_opportunity(profile, row, precomputed_sim=0.5).reasons_fit
    assert fit[0] == line
    assert _work_lines(fit) == []


def test_two_chips_the_tags_repeat_keep_both_interest_lines():
    row = _listing("simplify", title="Software Engineering Intern", keywords=["software engineering", "data science"],
                   lab="Example Software Co", pi="")
    profile = _profile("software engineering and data science", ["software engineering", "data science"])
    fit = rank_opportunity(profile, row, precomputed_sim=0.5).reasons_fit
    assert fit[:2] == [
        "Matches your interests: software engineering", f"Matches your interests: data science{_OUR_TOPICS}",
    ]


def test_a_listings_interest_lines_lead_its_card_and_nothing_follows_them_in():
    row = _listing("nsf_reu", title="Robotics REU")
    profile = _profile(TEXTS["no overlap"], ["robotics", "computer vision"])
    fit = rank_opportunity(profile, row, precomputed_sim=0.5).reasons_fit
    assert fit[:2] == ["Matches your interests: robotics", f"Matches your interests: computer vision{_OUR_TOPICS}"]
    assert not [line for line in fit[2:] if line.startswith(("Matches your interests", "Your ", "Pat Lee"))]


@pytest.mark.parametrize("text", [*TEXTS.values(), ""], ids=[*TEXTS.keys(), "no text"])
@pytest.mark.parametrize("kind", LISTINGS)
def test_only_the_sentences_change(kind, text):
    """Scores, bucket and gaps are the SRO twin's, which keeps its lines."""
    profile = {**_profile(text), "year": "junior", "major": "Mechanical Engineering"}
    row = _listing(kind)
    for sim in (0.0, 0.5):
        assert score_upside(profile, row, precomputed_sim=sim)[0] == score_upside(
            profile, _sro_twin(row), precomputed_sim=sim)[0]
        ours = rank_opportunity(profile, row, precomputed_sim=sim)
        twin = rank_opportunity(profile, _sro_twin(row), precomputed_sim=sim)
        assert (ours.final_score, ours.bucket, ours.reasons_gap) == (twin.final_score, twin.bucket, twin.reasons_gap)
        assert ours.reasons_fit != twin.reasons_fit


@pytest.mark.parametrize("text", TEXTS.values(), ids=TEXTS.keys())
@pytest.mark.parametrize("kind", LISTINGS)
def test_a_listings_lines_are_keyed_and_none_by_a_tag_template(kind, text):
    row = _listing(kind)
    fit = rank_opportunity(_profile(text), row, precomputed_sim=0.5).reasons_fit
    keys = reason_keys(fit, "fit", record=row)
    assert None not in keys
    assert not {key["key"] for key in keys} & TAG_KEYS


def test_a_pi_name_derived_from_the_company_heads_no_line_about_the_tags():
    """Simplify takes the word before "Group" in the company as pi_name, and the
    page drops it; the headline named it only because it is in the company."""
    row = _listing("simplify", title="Data Science Intern", keywords=["data science"],
                   lab="Example Analytics Group", pi="Example")
    stamp_inferred(row["metadata"], "pi_name", "rule:lab_title_surname")
    fit = rank_opportunity(_profile("data science", ["data science"]), row, precomputed_sim=0.5).reasons_fit
    assert not [line for line in fit if line.startswith("Example Analytics Group") or "Prof. Example" in line]
    assert "Matches your interests: data science" in fit


def _pi_stamped(row, method):
    stamp_inferred(row["metadata"], "pi_name", method)
    return row


ROLE_ONLY = ["undergraduate research"]
# pi_name the detail page removes (`pi_name_basis`), and the label a line gives
# the row instead: the word before "Group" in a company, the words before
# "Laboratory" in an SRO lab, a heading a page scan took for a name, and any
# name on a campus program row.
REMOVED_PI = {
    "company word": (_pi_stamped(_listing("simplify", keywords=ROLE_ONLY, lab="Example Analytics Group", pi="Example"),
                                 "rule:lab_title_surname"), "Example Analytics Group"),
    "sro lab words": (_pi_stamped(_sro_twin(_listing("nsf_reu", keywords=ROLE_ONLY, lab="Example Nuclear Laboratory",
                                                     pi="Example Nuclear")), "rule:lab_title_surname"),
                      "Example Nuclear Laboratory"),
    "page scan": (_pi_stamped(_listing("campus_program", keywords=ROLE_ONLY, pi="Team Projects"), "rule:page_scan_name"),
                  "Field Robotics Program"),
    "campus row": (_listing("campus_program", keywords=ROLE_ONLY, pi="Team Projects"), "Field Robotics Program"),
}


@pytest.mark.parametrize("case", REMOVED_PI)
def test_a_pi_name_the_page_removes_gives_the_line_to_the_lab(case):
    row, lab = REMOVED_PI[case]
    fit = rank_opportunity(_profile(TEXTS["no overlap"]), row, precomputed_sim=0.5).reasons_fit
    assert f"Your research interests align with {lab}'s focus area" in fit
    assert not [line for line in fit if f"Prof. {row['pi_name']}" in line or line.startswith(f"{row['pi_name']}'s")]


@pytest.mark.parametrize("case", REMOVED_PI)
def test_a_pi_name_the_page_removes_neither_heads_nor_lets_in_the_summary(case):
    """The summary named the PI ("Team Projects's Field Robotics Program: …"),
    or was let in as one that does because the derived word is in the lab.
    The campus rows' "This lab focuses on Field Robotics Program" is gone too:
    a listing has no headline (M183)."""
    row, lab = REMOVED_PI[case]
    fit = rank_opportunity(_profile(TEXTS["no overlap"]), row, precomputed_sim=0.5).reasons_fit
    assert [line for line in fit if line.startswith((lab, "This lab focuses on", row["pi_name"]))] == []


@pytest.mark.parametrize("text", TEXTS.values(), ids=TEXTS.keys())
def test_the_sros_work_line_names_its_lab_and_not_the_word_taken_from_it(text):
    row = _pi_stamped(_sro_twin(_listing("nsf_reu", lab="Example Nuclear Laboratory", pi="Example Nuclear")),
                      "rule:lab_title_surname")
    work = "robotics, computer vision, embedded systems"
    _, fit, _ = score_upside(_profile(text), row, precomputed_sim=0.5)
    assert (
        f"Your interest in robotics closely matches Example Nuclear Laboratory's work on {work}"
        if text == TEXTS["overlap"] else f"Example Nuclear Laboratory also works on {work}"
    ) in fit


@pytest.mark.parametrize(("row", "named"), [
    *((row, "") for row, _ in REMOVED_PI.values()),
    *(({**_listing("campus_program", pi="Team Projects"), "source": source}, "")
      for source in ("duke_labs", "duke_external_research")),
    (_pi_stamped(_listing("manual"), "llm:contact_extraction"), ""),
    (_listing("nsf_reu"), "Pat Lee"),
    (_sro_twin(_listing("nsf_reu")), "Pat Lee"),
    (_faculty(), "Pat Lee"),
], ids=[*REMOVED_PI, "lab suffix", "external suffix", "any stamp", "nsf award", "sro", "faculty"])
def test_a_line_names_the_pi_the_detail_page_shows_and_no_other(row, named):
    assert _line_pi(row) == named
    assert (pi_name_basis(row) is None) == bool(named)


@pytest.mark.parametrize("placeholder", ["N/A", "Unknown", "Learn More"])
def test_a_placeholder_pi_name_names_no_one(placeholder):
    row = _listing("nsf_reu", keywords=ROLE_ONLY, pi=placeholder)
    fit = rank_opportunity(_profile(TEXTS["no overlap"]), row, precomputed_sim=0.5).reasons_fit
    assert "Your research interests align with Field Robotics Program's focus area" in fit
    assert not [line for line in fit if placeholder in line]


def test_the_matcher_version_moved_for_the_sentences():
    assert int(MATCHER_VERSION.split(".")[0]) >= 38
