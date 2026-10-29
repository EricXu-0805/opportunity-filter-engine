"""M155: a match reason says so when the topics it rests on are ours.

"Matches your interests" matched the student's chips against keywords the
detail page shows as ours (a department's field, OpenAlex topics, a listing's
tags) and said nothing of it. A chip the row's own words name (its title, the
research text the detail page shows as the source's) still is the page's,
abbreviated or in full, singular or plural. The other chips' ending says how
we matched them and claims nothing of the page, which can name a topic in
words no test reads.
"Your research interests align with Prof. X's focus area" is the line a row
gets when its keywords are inferred and so are not named; it gave the row a
focus area no page states. Scores do not change.
"""
from __future__ import annotations

import pytest

from backend.data_loader import _sanitize_opportunity
from src.evidence import stamp_inferred
from src.matcher.config import MATCHER_VERSION
from src.matcher.ranker import _OUR_TOPICS, _named_re, _repeat_re, rank_opportunity, score_upside
from src.matcher.reason_keys import reason_key

STAMPS = ["derived:openalex_topics", "derived:illinois_experts_concepts", "tag:department_field"]


def _faculty(keywords, *, stamp=None, stated=""):
    opp = {
        "id": "faculty-physics-m155", "source": "uiuc_faculty", "source_type": "faculty_research",
        "opportunity_type": "research", "pi_name": "Pat Lee", "department": "Department of Physics",
        "keywords": list(keywords), "description_raw": "Faculty research profile for Pat Lee.",
        "eligibility": {}, "application": {}, "metadata": {"is_active": True},
    }
    if stated:
        opp["metadata"]["research_areas_raw"] = stated
    if stamp:
        stamp_inferred(opp["metadata"], "keywords", stamp)
    return opp


def _listing(source, source_type, *, title="Summer Research Program", keywords=("machine learning",)):
    return {
        "id": f"m155-{source}", "source": source, "source_type": source_type, "opportunity_type": "research",
        "title": title, "keywords": list(keywords), "pi_name": "Pat Lee",
        "description_raw": "Students join a ten-week summer cohort.", "eligibility": {}, "application": {},
        "metadata": {"is_active": True},
    }


def _keyed(fit, prefix):
    """The ranker's line starting with ``prefix`` and its served key."""
    line = next(reason for reason in fit if reason.startswith(prefix))
    return line, reason_key(line, "fit")["key"]


PHYSICS = {"research_interests_text": "nuclear physics", "desired_fields": ["nuclear physics"]}


@pytest.mark.parametrize("stamp", STAMPS)
def test_interests_matched_against_inferred_topics_say_so(stamp):
    _, fit, _ = score_upside(PHYSICS, _faculty(["physics"], stamp=stamp), precomputed_sim=0.0)
    assert _keyed(fit, "Matches your interests") == (
        f"Matches your interests: nuclear physics{_OUR_TOPICS}", "interests_match_ours")
    assert "Matches your interests: nuclear physics" not in fit


def test_a_profiles_own_keywords_keep_the_plain_line():
    _, fit, _ = score_upside(PHYSICS, _faculty(["physics"]), precomputed_sim=0.0)
    assert _keyed(fit, "Matches your interests") == ("Matches your interests: nuclear physics", "interests_match")
    assert not any(_OUR_TOPICS in reason for reason in fit)


@pytest.mark.parametrize(("source", "source_type", "ours"), [
    ("simplify_internships", "internship", True),
    ("nsf_reu", "summer_program", True),
    ("illinois_research_programs", "campus_program", True),
    ("uiuc_sro", "summer_program", False),
])
def test_a_listings_tags_are_ours_and_the_sros_research_area_is_its_own(source, source_type, ours):
    profile = {"research_interests_text": "", "desired_fields": ["machine learning"]}
    _, fit, _ = score_upside(profile, _listing(source, source_type), precomputed_sim=0.0)
    line = "Matches your interests: machine learning"
    assert (f"{line}{_OUR_TOPICS}" if ours else line) in fit


@pytest.mark.parametrize("stamp", STAMPS)
def test_a_chip_the_stated_research_names_is_the_pages_own(stamp):
    """Review round 1: "algebraic geometry" was hedged on a profile whose own
    research areas read "Algebra, Algebraic Geometry"."""
    profile = {"research_interests_text": "", "desired_fields": ["algebraic geometry"]}
    row = _faculty(["algebraic geometry", "galois extension"], stamp=stamp, stated="Algebra, Algebraic Geometry")
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
    assert "Matches your interests: algebraic geometry" in fit
    assert not any(_OUR_TOPICS in reason for reason in fit)


def test_a_chip_the_listings_title_names_is_its_own_and_the_rest_stay_ours():
    """Review round 1: "data science, machine learning" were both hedged on
    "Machine Learning Software Engineer Intern"."""
    profile = {"research_interests_text": "", "desired_fields": ["data science", "machine learning"]}
    row = _listing("simplify_internships", "internship", title="Machine Learning Software Engineer Intern",
                   keywords=("data science", "machine learning"))
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
    assert [reason for reason in fit if reason.startswith("Matches your interests")] == [
        "Matches your interests: machine learning",
        f"Matches your interests: data science{_OUR_TOPICS}",
    ]


def _row(keyword, title, stated):
    """A listing with this title, or a stamped faculty row stating this research."""
    if title:
        return _listing("simplify_internships", "internship", title=title, keywords=(keyword,))
    return _faculty([keyword], stamp="derived:openalex_topics", stated=stated)


@pytest.mark.parametrize(("chip", "keyword", "title", "stated"), [
    ("ml", "machine learning", "Machine Learning Software Engineer Intern", ""),
    ("machine learning", "machine learning", "AI/ML Engineer Intern", ""),
    ("computer science", "computer science", "CS Directed Reading Program", ""),
    ("environmental science", "environmental science", "Environmental Sciences Research Institute", ""),
    ("deep learning", "deep learning", "", "Large-scale DL/AI applications"),
    ("cv", "computer vision", "", "Computer vision, robotics"),
    ("llms", "large language models", "", "Natural Language Processing, Large Language Models"),
    ("compiler", "compiler", "", "Compilers, Programming Languages"),
    ("genes", "genes", "", "Gene regulation, chromatin biology"),
    ("digital library", "digital library", "", "Digital Libraries, Human Computer Interaction"),
    ("human-computer interaction", "human-computer interaction", "", "Digital Libraries, Human Computer Interaction"),
    ("human-computer interaction", "human-computer interaction", "", "Human\u2013computer interaction"),
    ("data science", "data science", "Data\u00a0Science Intern", ""),
    ("ai", "ai", "Artificial Intelligence Research Intern", ""),
    ("nlp", "nlp", "", "Natural language processing, speech"),
    ("hci", "hci", "", "Human-computer interaction, accessibility"),
    ("rl", "rl", "", "Reinforcement learning for robotics"),
    ("gene", "gene", "Genes and Behavior REU", ""),
    ("energy technologies", "energy technologies", "Energy Technology Intern", ""),
    ("processes", "processes", "Process Engineering Intern", ""),
    ("process", "process", "", "Manufacturing processes"),
    ("survey", "survey", "", "Surveys of distant galaxies"),
    ("data science", "data science", "Data\tScience Intern", ""),
    ("data science", "data science", "Data\u2009Science Intern", ""),
    ("human-computer interaction", "human-computer interaction", "", "Human - Computer Interaction"),
    ("human-computer interaction", "human-computer interaction", "", "Human\u2011computer interaction"),
    ("human\u2013computer interaction", "human\u2013computer interaction", "", "Human-computer interaction"),
    ("data\u00a0science", "data\u00a0science", "Data Science Intern", ""),
    ("c++", "c++", "C++17 Developer Intern", ""),
    ("c++ developer", "c++ developer", "C++ Developer Intern", ""),
    ("large language model", "large language model", "", "LLM agents and evaluation"),
])
def test_a_chip_the_rows_words_name_in_another_form_is_its_own(chip, keyword, title, stated):
    """Review round 2: only the chip's own spelling counted, so "ML" in a
    title, "DL" or "Compilers" in stated research left the ending on."""
    profile = {"research_interests_text": "", "desired_fields": [chip]}
    _, fit, _ = score_upside(profile, _row(keyword, title, stated), precomputed_sim=0.0)
    assert f"Matches your interests: {chip}" in fit
    assert not any(_OUR_TOPICS in reason for reason in fit)


@pytest.mark.parametrize(("chip", "keyword", "title", "stated"), [
    ("data science", "data science", "Data Analytics & Programs Intern", ""),
    ("deep learning", "deep learning", "", "Neural networks for vision"),
    ("mechanical engineering", "mechanical engineering", "About Me: Robotics Intern", ""),
    ("news", "news", "New Media Intern", ""),
    ("genetics", "genetics", "Genetic Algorithms Research Intern", ""),
    ("art", "art", "Smart Grid Intern", ""),
    ("art", "art", "Artist Residency Program", ""),
    ("genetic", "genetic", "Genetics Summer Research", ""),
    ("data science", "data science", "Summer Data \u2014 Science Outreach", ""),
    ("data science", "data science", "Summer Data \u2015 Science Outreach", ""),
    ("data science", "data science", "", "Big data\nscience policy"),
    ("data science", "data science", "", "Big data\rscience policy"),
    ("c++", "c++", "Cloud Computing Intern", ""),
    ("ml", "ml", "Supermachine Learning Intern", ""),
])
def test_a_related_word_or_a_word_inside_another_does_not_name_the_chip(chip, keyword, title, stated):
    """Analytics is not data science and neural networks are not deep
    learning; "me" and "new" are words, "genetic" and "genetics" are two
    words either way round, "art" is inside "Smart" and "Artist", and an em
    dash or a line break ends a phrase."""
    profile = {"research_interests_text": "", "desired_fields": [chip]}
    _, fit, _ = score_upside(profile, _row(keyword, title, stated), precomputed_sim=0.0)
    assert f"Matches your interests: {chip}{_OUR_TOPICS}" in fit


JOINING = ("\t\u00a0\u1680" + "".join(map(chr, range(0x2000, 0x200B))) + "\u202f\u205f\u3000"
           + "\u2010\u2011\u2012\u2013")


@pytest.mark.parametrize("gap", JOINING, ids=[f"U+{ord(c):04X}" for c in JOINING])
def test_every_space_and_hyphen_joins_a_terms_words(gap):
    profile = {"research_interests_text": "", "desired_fields": ["data science"]}
    _, fit, _ = score_upside(profile, _row("data science", f"Data{gap}Science Intern", ""), precomputed_sim=0.0)
    assert "Matches your interests: data science" in fit


ENDING = "\u2014\u2015\n\r\x0b\u2028\u200b\u00ad\u2212_/."


@pytest.mark.parametrize("gap", ENDING, ids=[f"U+{ord(c):04X}" for c in ENDING])
def test_other_characters_do_not_join_a_terms_words(gap):
    profile = {"research_interests_text": "", "desired_fields": ["data science"]}
    _, fit, _ = score_upside(profile, _row("data science", f"Data{gap}Science Intern", ""), precomputed_sim=0.0)
    assert f"Matches your interests: data science{_OUR_TOPICS}" in fit


def test_a_placeholder_research_area_names_nothing():
    row = _faculty(["unknown"], stamp="derived:openalex_topics")
    row["research_areas"] = ["Unknown", " N/A "]
    _, fit, _ = score_upside({"research_interests_text": "", "desired_fields": ["unknown"]}, row, precomputed_sim=0.0)
    assert f"Matches your interests: unknown{_OUR_TOPICS}" in fit


def test_a_professors_name_names_no_topic():
    """A faculty row's title is the professor's name, and "Ai" there is a
    name, whatever its case or spacing."""
    row = _faculty(["ai"], stamp="derived:openalex_topics")
    row.update(pi_name=" PAT AI", title="Pat Ai")
    _, fit, _ = score_upside({"research_interests_text": "", "desired_fields": ["ai"]}, row, precomputed_sim=0.0)
    assert f"Matches your interests: ai{_OUR_TOPICS}" in fit


@pytest.mark.parametrize(("title", "areas"), [
    ("Summer Data", "Science of learning"),
    ("Summer Program", ["Big Data", "Science Policy"]),
])
def test_a_term_does_not_run_across_the_rows_words(title, areas):
    """Not from the title into the research text, nor from one research area
    into the next."""
    row = _listing("simplify_internships", "internship", title=title, keywords=("data science",))
    row["research_areas"] = areas
    profile = {"research_interests_text": "", "desired_fields": ["data science"]}
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
    assert f"Matches your interests: data science{_OUR_TOPICS}" in fit


@pytest.mark.parametrize("raw", [None, "  ", "N/A", "unknown", "None", "null"])
@pytest.mark.parametrize("areas", [["Algebra", "Algebraic Geometry"], "Algebra, Algebraic Geometry"])
def test_research_areas_stand_in_for_absent_stated_research(raw, areas):
    """As on the detail page: research_areas when research_areas_raw is
    missing, blank or a placeholder, and never beside it."""
    profile = {"research_interests_text": "", "desired_fields": ["algebraic geometry"]}
    row = _faculty(["algebraic geometry"], stamp="derived:openalex_topics")
    row["research_areas"] = areas
    if raw is not None:
        row["metadata"]["research_areas_raw"] = raw
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
    assert "Matches your interests: algebraic geometry" in fit
    row["metadata"]["research_areas_raw"] = "Number theory"
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
    assert f"Matches your interests: algebraic geometry{_OUR_TOPICS}" in fit


@pytest.mark.parametrize(("title", "areas"), [
    ("Machine Learning Intern", "Robotics"),
    ("Summer Intern", "Machine learning, robotics"),
])
def test_either_the_title_or_the_research_text_names_the_chip(title, areas):
    row = _listing("simplify_internships", "internship", title=title, keywords=("machine learning",))
    row["research_areas"] = areas
    profile = {"research_interests_text": "", "desired_fields": ["machine learning"]}
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
    assert "Matches your interests: machine learning" in fit


@pytest.mark.parametrize(("chip", "keyword", "title"), [
    ("hardware engineering", "hardware", "Hardware Engineer Intern"),
    ("looking for a software engineering internship", "software engineering", "Software Engineering Internship/Co-Op"),
])
def test_words_no_test_reads_leave_an_ending_that_still_holds(chip, keyword, title):
    """Review round 3: a job title, or a sentence around the topic, names the
    chip in words no test here reads. The chip matched a keyword of ours, so
    the ending says that and claims nothing of the page."""
    profile = {"research_interests_text": "", "desired_fields": [chip]}
    _, fit, _ = score_upside(profile, _row(keyword, title, ""), precomputed_sim=0.0)
    assert f"Matches your interests: {chip}{_OUR_TOPICS}" in fit
    assert _OUR_TOPICS == " \u2014 based on topics we inferred"


@pytest.mark.parametrize(("chip", "plain"), [
    ("robotics " + "y" * 291, True),
    ("robotics " + "y" * 292, False),
    (" ".join(["robotics"] + ["lab"] * 19), True),
    (" ".join(["robotics"] + ["lab"] * 20), False),
    (" " + " ".join(["robotics"] + ["lab"] * 19) + " ", True),
    ("\u3000".join(["robotics"] + ["lab"] * 20), False),
    (" ".join(["robotics"] + ["lab"] * 16 + ["end-to-end"]), True),
    (" ".join(["robotics"] + ["lab"] * 17 + ["end-to-end"]), False),
], ids=["300 characters", "301 characters", "20 words", "21 words", "20 words between spaces",
        "21 words joined by ideographic spaces", "20 pieces with a hyphen", "21 pieces with a hyphen"])
def test_a_chip_past_300_characters_or_20_words_is_never_named(chip, plain):
    """Words are counted after the split on spaces and hyphens."""
    _, fit, _ = score_upside({"research_interests_text": "", "desired_fields": [chip]},
                             _row("robotics", "", " ".join(chip.replace("\u3000", " ").split())), precomputed_sim=0.0)
    assert (f"Matches your interests: {chip}" in fit) is plain
    assert (f"Matches your interests: {chip}{_OUR_TOPICS}" in fit) is not plain


@pytest.mark.parametrize(("chip", "kept"), [("robotics " + "y" * 291, False), ("robotics " + "y" * 292, True)],
                         ids=["300 characters", "301 characters"])
def test_a_chip_past_300_characters_is_never_a_repeat(chip, kept):
    profile = {"research_interests_text": chip, "desired_fields": [chip]}
    _, fit, _ = score_upside(profile, _faculty([chip, "robotics"]), precomputed_sim=0.5)
    assert "closely matches" in fit[-1]
    assert (f"Matches your interests: {chip}" in fit) is kept


def test_a_chip_longer_than_any_topic_is_neither_named_nor_repeated():
    """_named_re and _repeat_re keep one pattern per chip, and a chip can run
    to 60,000 characters; neither cache holds one past _TERM_MAX."""
    chip = " ".join(["robotics"] * 40)
    row = _listing("simplify_internships", "internship", title="Summer Intern", keywords=("robotics",))
    row["research_areas"] = chip
    _named_re.cache_clear()
    _repeat_re.cache_clear()
    profile = {"research_interests_text": "robotics", "desired_fields": [chip]}
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.5)
    assert f"Matches your interests: {chip}{_OUR_TOPICS}" in fit
    assert "closely matches" in fit[-1]
    assert _named_re.cache_info().currsize == _repeat_re.cache_info().currsize == 0


ROBOTICS_AND_CV = {"research_interests_text": "perception for drones", "desired_fields": ["robotics", "computer vision"]}


@pytest.mark.parametrize(("keywords", "kept", "dropped"), [
    (("robotics", "embedded systems", "aircraft", "computer vision"),
     f"Matches your interests: computer vision{_OUR_TOPICS}", "Matches your interests: robotics"),
    (("computer vision", "embedded systems", "aircraft", "robotics"),
     "Matches your interests: robotics", f"Matches your interests: computer vision{_OUR_TOPICS}"),
])
def test_each_interest_line_is_dropped_only_as_a_repeat_of_its_own_chips(keywords, kept, dropped):
    """"…also works on" names the first three tags: the line whose chips it
    names goes, and the other stays."""
    row = _listing("simplify_internships", "internship", title="Robotics Software Intern", keywords=keywords)
    _, fit, _ = score_upside(ROBOTICS_AND_CV, row, precomputed_sim=0.5)
    assert "Prof. Pat Lee also works on" in fit[-1]
    assert kept in fit and dropped not in fit


@pytest.mark.parametrize(("chip", "title", "keywords"), [
    ("ai", "AI Engineer Intern", ("robotics", "aircraft", "embedded systems", "ai", "computer vision")),
    ("art", "Art Studio Intern", ("smart grid", "embedded systems", "robotics", "art", "computer vision")),
])
def test_a_chip_inside_another_word_of_the_similarity_line_keeps_its_line(chip, title, keywords):
    """Review round 2: "ai" is inside "aircraft", which the line names, and
    "art" inside "smart"."""
    row = _listing("simplify_internships", "internship", title=title, keywords=keywords)
    profile = {"research_interests_text": "perception for drones", "desired_fields": [chip, "computer vision"]}
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.5)
    assert "also works on" in fit[-1]
    assert f"Matches your interests: {chip}" in fit
    assert f"Matches your interests: computer vision{_OUR_TOPICS}" in fit


@pytest.mark.parametrize(("chip", "keywords", "kept"), [
    ("large language model", ["large language models", "dialogue systems"], False),
    ("process", ["manufacturing processes", "dialogue systems", "robotics", "process"], False),
    ("nlp", ["natural language processing", "dialogue systems"], True),
    ("unions", ["union political action", "union strategic campaigns", "labor history", "unions"], True),
])
def test_the_bare_line_repeats_the_chip_or_its_plural_only(chip, keywords, kept):
    """"…also works on large language models" repeats the chip "large language
    model", and "manufacturing processes" the chip "process". "natural
    language processing" does not repeat what the student typed as "nlp", nor
    "union political action" the chip "unions", as on main."""
    profile = {"research_interests_text": "dialogue agents", "desired_fields": [chip]}
    _, fit, _ = score_upside(profile, _faculty(keywords), precomputed_sim=0.5)
    assert "also works on" in fit[-1]
    assert (f"Matches your interests: {chip}" in fit) is kept


@pytest.mark.parametrize("fields", [["robotics", "computer vision"], ["robotics"]])
def test_the_lab_summary_follows_the_interest_lines_and_precedes_the_rest(fields):
    """Not between the two interest lines, and right after a single one."""
    row = _listing("nsf_reu", "summer_program", title="Robotics REU",
                   keywords=("embedded systems", "aircraft", "sensors", "robotics", "computer vision"))
    row["lab_or_program"] = "Field Robotics Lab"
    profile = {"desired_fields": fields, "research_interests_text": "perception for drones"}
    fit = rank_opportunity(profile, row, precomputed_sim=0.5).reasons_fit
    interest = ["Matches your interests: robotics", f"Matches your interests: computer vision{_OUR_TOPICS}"]
    assert fit[:len(fields) + 2] == [
        *interest[:len(fields)],
        "Pat Lee's Field Robotics Lab — embedded systems, aircraft, sensors",
        "Prof. Pat Lee also works on embedded systems, aircraft, sensors",
    ]


def test_the_lab_summary_follows_two_interest_lines_and_nothing_else():
    row = _listing("nsf_reu", "summer_program", title="Robotics REU", keywords=("robotics", "computer vision"))
    row["lab_or_program"] = "Field Robotics Lab"
    fit = rank_opportunity({"desired_fields": ["robotics", "computer vision"]}, row).reasons_fit
    assert fit[:3] == [
        "Matches your interests: robotics",
        f"Matches your interests: computer vision{_OUR_TOPICS}",
        "Pat Lee's Field Robotics Lab — robotics, computer vision",
    ]


def test_a_type_match_line_is_not_an_interest_line():
    """"Matches your interest in research" does not hold the summary back."""
    row = _listing("nsf_reu", "summer_program", title="Robotics REU",
                   keywords=("embedded systems", "aircraft", "sensors", "robotics", "computer vision"))
    row["lab_or_program"] = "Field Robotics Lab"
    fit = rank_opportunity({"desired_fields": ["robotics"], "seeking_type": ["research"]}, row).reasons_fit
    assert fit[:3] == [
        "Matches your interests: robotics",
        "Pat Lee's Field Robotics Lab — embedded systems, aircraft, sensors",
        "Matches your interest in research",
    ]


def test_a_curated_programs_title_counts_as_its_own_words():
    """Our config titles a curated program after the page it links to, so a
    chip its title names is plain, as on main."""
    row = _listing("ucb_research_programs", "campus_program", title="Physics Undergraduate Research (UC Berkeley)",
                   keywords=("undergraduate research",))
    profile = {"research_interests_text": "", "desired_fields": ["undergraduate research"]}
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
    assert "Matches your interests: undergraduate research" in fit


@pytest.mark.parametrize("stamp", STAMPS)
def test_inferred_keywords_give_the_row_no_focus_area(stamp):
    _, fit, _ = score_upside(PHYSICS, _faculty(["physics"], stamp=stamp), precomputed_sim=0.5)
    assert _keyed(fit, "Your research interests") == (
        "Your research interests align with topics we inferred for Pat Lee", "interests_lab_ours")
    assert not any("focus area" in reason for reason in fit)


@pytest.mark.parametrize("chip", ["cs", "topics"])
def test_a_chip_inside_the_lines_wording_keeps_its_own_line(chip):
    """The bare line is dropped only as a repeat of topics the similarity line
    names; "topics we inferred for ..." names none, though "cs" is in "topics"."""
    profile = {"research_interests_text": f"{chip} research", "desired_fields": [chip]}
    _, fit, _ = score_upside(profile, _faculty([chip], stamp="tag:department_field"), precomputed_sim=0.5)
    assert f"Matches your interests: {chip}{_OUR_TOPICS}" in fit


def test_a_chip_inside_the_focus_area_line_keeps_its_own_line():
    """"research" is inside "Your research interests align with ...'s focus area",
    which names no topic."""
    profile = {"research_interests_text": "research", "desired_fields": ["research"]}
    row = _listing("illinois_research_programs", "campus_program", keywords=("research",))
    _, fit, _ = score_upside(profile, row, precomputed_sim=0.5)
    assert "Matches your interests: research" in fit
    assert "Your research interests align with Prof. Pat Lee's focus area" in fit


@pytest.mark.parametrize("keywords", [[], ["undergraduate research"], ["research", "summer"]],
                         ids=["none", "role-only", "generic-only"])
def test_unstamped_keywords_that_name_no_topic_keep_the_focus_area(keywords):
    """display_kw is empty without a stamp: the similarity rests on the
    listing's own description."""
    row = _listing("illinois_research_programs", "campus_program", keywords=keywords)
    _, fit, _ = score_upside({"research_interests_text": "neural decoding"}, row, precomputed_sim=0.6)
    assert _keyed(fit, "Your research interests") == (
        "Your research interests align with Prof. Pat Lee's focus area", "interests_lab_focus")


@pytest.mark.parametrize("stamp", STAMPS)
def test_only_the_sentences_change(stamp):
    for sim in (0.0, 0.5):
        stamped, fit, gap = score_upside(PHYSICS, _faculty(["physics"], stamp=stamp), precomputed_sim=sim)
        plain, plain_fit, plain_gap = score_upside(PHYSICS, _faculty(["physics"]), precomputed_sim=sim)
        assert stamped == plain and len(fit) == len(plain_fit) and gap == plain_gap


def test_a_department_field_the_loader_tags_is_matched_as_ours():
    """A UIUC profile that states no research keeps its department's field as
    keywords; the loader stamps it ours (M154), and the served reason says so."""
    row = {
        "id": "faculty-law-m155", "source": "uiuc_faculty", "source_type": "faculty_research",
        "opportunity_type": "research", "organization": "University of Illinois Urbana-Champaign",
        "school": "uiuc", "department": "College of Law", "pi_name": "Pat Lee", "keywords": ["law"],
        "eligibility": {}, "application": {}, "metadata": {"is_active": True},
    }
    result = rank_opportunity({"major": "Political Science", "desired_fields": ["law"]}, _sanitize_opportunity(row))
    assert f"Matches your interests: law{_OUR_TOPICS}" in result.reasons_fit


def test_the_new_lines_key_with_the_students_terms_and_the_rows_label():
    assert reason_key(f"Matches your interests: nuclear physics, optics{_OUR_TOPICS}", "fit") == {
        "key": "interests_match_ours", "params": {"terms": "nuclear physics, optics"}}
    assert reason_key("Your research interests align with topics we inferred for Prof. Pat Lee", "fit") == {
        "key": "interests_lab_ours", "params": {"lab": "Prof. Pat Lee"}}


def test_the_matcher_version_moved_for_the_new_sentences():
    assert int(MATCHER_VERSION.split(".")[0]) >= 29
