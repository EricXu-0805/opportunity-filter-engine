"""Deterministic guards for the uiuc_faculty collector's department registry
and the section-label filter that keeps directory headings ("Postdocs",
"Affiliates and Adjuncts") out of the faculty data. No network: the live
scrape runs in the refresh pipeline, not in CI.
"""

from __future__ import annotations

import re

from src.collectors.uiuc_faculty import (
    DEPARTMENTS,
    _clean_research_phrase,
    _dedup_faculty_by_email,
    _dedup_faculty_records,
    _demote_shared_keyword_pollution,
    _dept_broad_field,
    _derive_keywords_from_raw,
    _drop_nonperson_faculty,
    _extract_research_keywords,
    _is_junk_keyword,
    _is_section_label,
    _keywords_from_research_areas,
    _llm_research_keywords,
    _null_shared_admin_emails,
    _null_unit_inbox_emails,
    _null_wrong_person_emails,
    _rebuild_faculty_title_and_desc,
    _reenrich_broad_only_faculty,
    _research_areas_from_soup,
    _run_faculty_dq,
    _split_compound_keywords,
    _strip_fragment_keywords,
    _strip_furniture_keywords,
    _strip_pi_name_credentials,
    missing_departments,
    normalize_faculty,
)

NEWLY_ADDED = {
    "aero", "cee", "npre", "chbe", "ise", "astro", "mcb", "psych",
    "ib", "econ", "linguistics", "comm", "anthro", "atmos", "soc", "geology",
    "polisci", "english", "philosophy", "history",
}

# The exact non-person headings observed live across the new departments'
# directory pages — every one must be filtered out.
OBSERVED_SECTION_LABELS = [
    "Affiliates and Adjuncts",
    "Adjuncts and Affiliates",
    "Graduate students",
    "Administration",
    "Postdocs",
    "Doctoral Students",
    "Master's Students",
    "Human Resources",
    "Business Office",
    "Student Services",
    "Committees",
    "Grads on the Market",
    "Job Market Candidates",
    "Diversity and Inclusion",
    "Instructors and Lecturers",
    # Institution-page / memorial labels scraped as a person (variable forms,
    # matched by word boundary, not the whole-name set).
    "Beckman Institute profile",
    "Neuroscience Profile",
    "Beckman Profile Page",
    "Dean's Cabinet",
    "In Memoriam",
]

# Real names that must NEVER be mistaken for section labels, including the
# surname "Fellows" that a naive substring match on "fellows" would clip.
REAL_NAMES = [
    "Imad Al-Qadi",
    "Sayeepriyadarshini \"Sayee\" Anakk",
    "Mark Fellows",
    "Grace Gao",
    "Postdoctoral Fellow Jane Doe",
]


def test_section_labels_are_filtered():
    for label in OBSERVED_SECTION_LABELS:
        assert _is_section_label(label), f"{label!r} should be filtered"


def test_real_names_are_not_filtered():
    for name in REAL_NAMES:
        assert not _is_section_label(name), f"{name!r} wrongly filtered"


def test_normalize_drops_section_label():
    cfg = DEPARTMENTS["mcb"]
    assert normalize_faculty({"name": "Postdocs", "url": "x"}, cfg) is None


def test_null_unit_inbox_emails_nulls_unit_mailboxes_keeps_personal():
    """A department/unit/role mailbox scraped as a professor's contact (english@,
    mainoffice@physics, poultry@) is nulled — a cold email to it misfires — while
    a personal address, including the vowel-stripped and initials shapes UIUC
    uses ("fhnstck@" for Fahnestock, "geg@" for Gary E. Gladding), is preserved."""
    opps = [
        {"source": "uiuc_faculty", "department": "Department of English",
         "pi_name": "Susan Koshy", "contact_email": "english@illinois.edu"},
        {"source": "uiuc_faculty", "department": "Department of Physics",
         "pi_name": "Pengjie Wang", "contact_email": "mainoffice@physics.illinois.edu"},
        {"source": "uiuc_faculty", "department": "Department of Animal Sciences",
         "pi_name": "Carl M. Parsons", "contact_email": "poultry@illinois.edu"},
        {"source": "uiuc_faculty", "department": "Department of Anthropology",
         "pi_name": "Kathryn Clancy", "contact_email": "anthro@illinois.edu"},
        # personal addresses that must SURVIVE
        {"source": "uiuc_faculty", "department": "Department of Civil Engineering",
         "pi_name": "Larry A. Fahnestock", "contact_email": "fhnstck@illinois.edu"},
        {"source": "uiuc_faculty", "department": "Department of Physics",
         "pi_name": "Gary E. Gladding", "contact_email": "geg@illinois.edu"},
    ]
    nulled = _null_unit_inbox_emails(opps)
    assert nulled == 4
    assert [o["contact_email"] for o in opps[:4]] == [None, None, None, None]
    assert opps[4]["contact_email"] == "fhnstck@illinois.edu"
    assert opps[5]["contact_email"] == "geg@illinois.edu"


def test_null_wrong_person_emails_nulls_only_curated_ids():
    """A faculty listing that scraped a different person's email (curated by id
    after a two-pass LLM name↔local-part check) is nulled; everyone else — and
    any non-faculty row sharing the id space — is left untouched."""
    from src.collectors.uiuc_faculty import _WRONG_PERSON_EMAIL_IDS
    known = next(iter(_WRONG_PERSON_EMAIL_IDS))
    opps = [
        {"source": "uiuc_faculty", "id": known, "contact_email": "willia67@illinois.edu"},
        {"source": "uiuc_faculty", "id": "faculty-cs-not-listed", "contact_email": "daf@illinois.edu"},
    ]
    assert _null_wrong_person_emails(opps) == 1
    assert opps[0]["contact_email"] is None
    assert opps[1]["contact_email"] == "daf@illinois.edu"


def test_normalize_keeps_real_person():
    cfg = DEPARTMENTS["mcb"]
    opp = normalize_faculty(
        {"name": "Milan K. Bagchi",
         "url": "https://mcb.illinois.edu/directory/profile/mbagchi"},
        cfg,
    )
    assert opp is not None
    assert opp["pi_name"] == "Milan K. Bagchi"
    assert opp["source"] == "uiuc_faculty"
    assert opp["department"] == cfg["name"]


def test_new_departments_registered_with_valid_config():
    assert NEWLY_ADDED <= set(DEPARTMENTS)
    for key in NEWLY_ADDED:
        cfg = DEPARTMENTS[key]
        assert {"name", "short", "url", "base", "majors", "keywords"} <= set(cfg)
        assert cfg["url"].startswith("https://") and ".illinois.edu" in cfg["url"]
        assert cfg["base"] in cfg["url"]
        assert cfg["majors"] and cfg["keywords"]


def test_department_ids_do_not_collide():
    shorts = [c["short"].lower() for c in DEPARTMENTS.values()]
    assert len(shorts) == len(set(shorts)), "duplicate department short codes"


def _fac(pi_name, url, source="uiuc_faculty", description=""):
    return {
        "source": source,
        "pi_name": pi_name,
        "source_url": url,
        "description": description,
    }


def test_dedup_collapses_fuller_name_variant():
    url = "https://physics.illinois.edu/people/directory/profile/bkclark"
    out = _dedup_faculty_records([_fac("Bryan Clark", url), _fac("Bryan K. Clark", url)])
    assert [o["pi_name"] for o in out] == ["Bryan K. Clark"]


def test_dedup_collapses_nickname_variant():
    url = "https://physics.illinois.edu/people/directory/profile/eckstein"
    out = _dedup_faculty_records([_fac("Jim Eckstein", url), _fac("James N. Eckstein", url)])
    assert [o["pi_name"] for o in out] == ["James N. Eckstein"]


def test_dedup_keeps_distinct_surnames_at_same_url():
    url = "https://example.illinois.edu/lab"
    rows = [_fac("Jane Smith", url), _fac("John Doe", url)]
    assert len(_dedup_faculty_records(rows)) == 2


def test_dedup_keeps_same_name_at_different_urls():
    rows = [
        _fac("Bryan Clark", "https://a.illinois.edu/profile/1"),
        _fac("Bryan Clark", "https://b.illinois.edu/profile/2"),
    ]
    assert len(_dedup_faculty_records(rows)) == 2


def test_dedup_ignores_non_faculty_rows():
    url = "https://x.illinois.edu/p"
    rows = [_fac("Ann Lee", url, source="nsf_reu"), _fac("Ann Lee", url, source="handshake")]
    assert len(_dedup_faculty_records(rows)) == 2


def test_dedup_strips_generational_suffix():
    url = "https://physics.illinois.edu/people/directory/profile/demarco"
    out = _dedup_faculty_records([_fac("Brian DeMarco", url), _fac("Brian DeMarco Jr.", url)])
    assert len(out) == 1


def test_keyword_fallback_uses_broad_field_only():
    cfg = {"short": "TEST", "keywords": ["test field", "hot area one", "hot area two"]}
    kws = _extract_research_keywords({"name": "Jane Doe"}, cfg)
    assert kws == ["test field"]


def test_keyword_fallback_never_injects_unverified_hot_area():
    cfg = DEPARTMENTS["cs"]
    kws = _extract_research_keywords({"name": "Jane Doe"}, cfg)
    assert "machine learning" not in kws
    assert "artificial intelligence" not in kws


# DQ-1: department-block keyword pollution demotion.

def _fac_kw(department, keywords):
    return {"source": "uiuc_faculty", "department": department, "keywords": list(keywords)}


def test_dept_broad_field_resolves_known_department():
    assert _dept_broad_field("Siebel School of Computing and Data Science") == "computer science"
    assert _dept_broad_field("Electrical & Computer Engineering") == "electrical engineering"


def test_dept_broad_field_resolves_aces_and_fallback():
    assert _dept_broad_field("Department of Animal Sciences") == "animal sciences"
    # Unknown dept falls back to a normalized name.
    assert _dept_broad_field("Department of Underwater Basket Weaving") == "underwater basket weaving"


def test_demote_collapses_shared_block_to_broad_field():
    shared = ["artificial intelligence", "bioinformatics", "compilers"]
    rows = [_fac_kw("Siebel School of Computing and Data Science", shared) for _ in range(6)]
    demoted = _demote_shared_keyword_pollution(rows)
    assert demoted == 6
    assert all(r["keywords"] == ["computer science"] for r in rows)


def test_demote_leaves_small_shared_sets_alone():
    # A 2-keyword set shared by only a few peers is plausibly real — keep it.
    shared = ["computer vision", "robotics"]
    rows = [_fac_kw("Siebel School of Computing and Data Science", shared) for _ in range(4)]
    assert _demote_shared_keyword_pollution(rows) == 0
    assert all(r["keywords"] == shared for r in rows)


def test_demote_ignores_distinct_keyword_sets():
    rows = [
        _fac_kw("Department of Physics", ["nanophotonics", "biosensing"]),
        _fac_kw("Department of Physics", ["heavy ion physics", "quark gluon plasma"]),
    ]
    assert _demote_shared_keyword_pollution(rows) == 0


def test_demote_scoped_to_faculty_source():
    shared = ["a", "b"]
    rows = [{"source": "nsf_reu", "department": "X", "keywords": list(shared)} for _ in range(10)]
    assert _demote_shared_keyword_pollution(rows) == 0


# DQ-2: recover real keywords from research_areas_raw for broad-only faculty.

def test_clean_research_phrase_keeps_topical():
    assert _clean_research_phrase("Dependent Type Theory") == "dependent type theory"
    assert _clean_research_phrase("AI for Audio") == "ai for audio"
    assert _clean_research_phrase("nanophotonics") == "nanophotonics"
    assert _clean_research_phrase("Vertical cavity surface emitting lasers (VCSELs)") == "vertical cavity surface emitting lasers"


def test_clean_research_phrase_rejects_noise():
    for junk in (
        "Research Areas", "CS 498 SCU", "and freight applications",
        "My research focuses on the design", "(guitars", "Books Authored",
        "education", "lab", "in particular", "monographs",
    ):
        assert _clean_research_phrase(junk) is None, junk


def _fac_raw(pi_name, department, raw_text, keywords):
    return {
        "source": "uiuc_faculty", "pi_name": pi_name, "department": department,
        "keywords": list(keywords), "metadata": {"research_areas_raw": raw_text},
    }


def test_derive_enriches_broad_only_with_unique_phrases():
    rows = [_fac_raw(
        "Minje Kim", "Siebel School of Computing and Data Science",
        "AI for Audio, Source Separation, Model Compression", ["computer science"],
    )]
    assert _derive_keywords_from_raw(rows) == 1
    assert rows[0]["keywords"] == ["ai for audio", "source separation", "model compression"]


def test_derive_skips_dept_shared_nav_block():
    # The same phrase set repeated across many same-dept peers is a nav block.
    shared = "Architecture, Compilers and Parallel Computing, Artificial Intelligence"
    dept = "Siebel School of Computing and Data Science"
    rows = [_fac_raw(f"Prof {i}", dept, shared, ["computer science"]) for i in range(6)]
    assert _derive_keywords_from_raw(rows) == 0
    assert all(r["keywords"] == ["computer science"] for r in rows)


def test_derive_skips_rows_with_specific_keyword():
    rows = [_fac_raw(
        "Has Specific", "Department of Physics",
        "Nanophotonics, Biosensing", ["quantum optics"],
    )]
    assert _derive_keywords_from_raw(rows) == 0
    assert rows[0]["keywords"] == ["quantum optics"]


def test_derive_drops_self_name_token():
    rows = [_fac_raw(
        "Kellie Halloran", "Mechanical Science & Engineering",
        "Halloran, Biomechanics", ["mechanical engineering"],
    )]
    _derive_keywords_from_raw(rows)
    assert "halloran" not in rows[0]["keywords"]
    assert rows[0]["keywords"] == ["biomechanics"]


def test_strip_fragment_keywords_recovers_topic():
    rows = [
        {"source": "uiuc_faculty", "keywords": ["such as speech"]},
        {"source": "uiuc_faculty", "keywords": [
            "experimental fusion research", "particularly using liquid lithium"]},
        {"source": "uiuc_faculty", "keywords": ["cognition", "such as the cerebral cortex"]},
    ]
    assert _strip_fragment_keywords(rows) == 3
    assert rows[0]["keywords"] == ["speech"]
    assert rows[1]["keywords"] == ["experimental fusion research", "liquid lithium"]
    assert rows[2]["keywords"] == ["cognition", "cerebral cortex"]


def test_strip_fragment_keywords_leaves_clean_keywords_untouched():
    rows = [{"source": "uiuc_faculty", "keywords": ["machine learning", "computer vision"]}]
    assert _strip_fragment_keywords(rows) == 0
    assert rows[0]["keywords"] == ["machine learning", "computer vision"]


# R70-A regression: the routine refresh re-scrapes faculty pages and re-injects
# course-listing menus and comma-joined compound keywords. The merge-time DQ
# chain must scrub them so a fresh scrape passes the data-quality guards (it was
# previously only scrubbed by the one-off `--reenrich` CLI, never wired in).

def test_is_junk_keyword_catches_course_codes_and_entity_residue():
    # Course listings scraped from CS faculty pages, and truncated HTML-entity
    # residue, are not research areas.
    for k in [
        "cs 591 sn - systems and networking seminar",
        "cs 498 it3 (cs 498 it4",
        "math 473) - algorithms",
        "cs 598 tal - language",
        "agents &amp",
        "se&nbsp",
        "texas a&amp",
    ]:
        assert _is_junk_keyword(k), k


def test_is_junk_keyword_catches_cv_and_institution_residue():
    # Education-history / CV fragments scraped as keywords are not research areas.
    for k in [
        "carleton college", "virginia tech", "imperial college london",
        "college of william & mary", "national academy of engineering",
        "universidad de los andes",
        "b.a. from carleton college", "bs mathematics", "ph.d. stony brook",
        "ma (comparative literature): cornell 1994.",
        "ph.d.\tcivil engineering\tuiuc\t1979",
        "december 1989", "feenberg medal (1994)", "urbana 1995",
    ]:
        assert _is_junk_keyword(k), k


def test_is_junk_keyword_keeps_legit_areas_that_brush_the_cv_rules():
    # The digit/ampersand/degree/date rules must not clip genuine areas: "md"
    # (molecular dynamics) and "ms" (mass spectrometry) are not degree markers,
    # and a topic with a trailing year ("american cinema since 1950") is real.
    for k in ["p53 signaling", "covid-19 modeling", "5g networks",
              "networks & security", "arts & sciences", "r&d", "at&t",
              "md and kmc", "molecular dynamics", "mass spectrometry",
              "massive stars", "majorana fermions", "american cinema since 1950",
              "zero degree calorimetry", "accessibility/universal design"]:
        assert not _is_junk_keyword(k), k


def test_is_junk_keyword_catches_editorial_service_roles():
    # Editorial / leadership service titles scrape from a bio's service section
    # as topic-shaped phrases but are never research areas (found 2026-06-15
    # auditing live UIUC data: 12 faculty carried "associate editor"-class junk).
    for k in ["associate editor", "senior editor", "managing editor",
              "guest editor", "editor-in-chief", "editorial board", "co-founder",
              "cofounder", "board member",
              "computer graphics forum (cgf): associate editor"]:
        assert _is_junk_keyword(k), k


def test_is_junk_keyword_keeps_editing_research_and_plain_editorial():
    # "editing" (gene/genome/video) is a real area and must not be clipped by the
    # service-role rule; a bare "editorial" without "board" is also left alone.
    for k in ["gene editing", "genome editing", "video editing",
              "image editing", "editorial"]:
        assert not _is_junk_keyword(k), k


def test_is_junk_keyword_catches_contact_block_residue():
    # The UIUC Physics directory template scraped each professor's contact panel
    # (email, office phone, office room/building) as "research keywords" — 92
    # records, 67% of the dept (found 2026-06-26 audit). None are research areas.
    for k in [
        "adshead@illinois.edu", "bdemarco@illinois.edu", "geg@illinois.edu",
        "(217) 333-4363", "(217) 244-0646", "(217) 318-1881",
        "237b loomis laboratory", "229 loomis laboratory", "290e loomis laboratory",
        "237 d loomis laboratory", "237 medical sciences building",
        "3111 engineering sciences building",
    ]:
        assert _is_junk_keyword(k), k


def test_is_junk_keyword_keeps_areas_that_brush_the_contact_rules():
    # The email/phone/room rules must not clip genuine areas: dimensional topics
    # ("2d materials") share the leading-digit shape of a room number, and
    # lab-method areas ("laboratory automation") contain a building-type word —
    # both must survive (the room rule needs a 2-4-digit number AND a building word).
    for k in ["2d materials", "3d printing", "1d nanostructures",
              "3d printing laboratory", "802.11 networking", "h.264 video coding",
              "lab on a chip", "laboratory automation", "wet laboratory techniques",
              "high energy physics", "5g networks"]:
        assert not _is_junk_keyword(k), k


def test_strip_furniture_keywords_drops_contact_residue_and_backfills_broad():
    # Mixed record keeps its real area; contact-only record falls back to the
    # department broad field rather than being left with an empty keyword list.
    opps = [
        {"source": "uiuc_faculty", "department": "Department of Physics",
         "keywords": ["condensed matter physics", "ceperley@illinois.edu",
                      "(217) 244-0646", "229 loomis laboratory"]},
        {"source": "uiuc_faculty", "department": "Department of Physics",
         "keywords": ["327 loomis laboratory", "covey@illinois.edu"]},
    ]
    changed = _strip_furniture_keywords(opps)
    assert changed == 2
    assert opps[0]["keywords"] == ["condensed matter physics"]
    assert opps[1]["keywords"] == [_dept_broad_field("Department of Physics")]
    assert opps[1]["keywords"] == ["physics"]


def test_split_compound_keywords_atomizes_comma_joined():
    rows = [
        _fac_kw("Computer Science",
                ["compilers, architecture, and parallel computing"]),
        _fac_kw("Computer Science",
                ["computer vision, object recognition, scene understanding, graphics"]),
        _fac_kw("Computer Science", ["machine learning"]),  # already atomic, untouched
    ]
    _split_compound_keywords(rows)
    # No keyword may retain an internal comma, else the rebuilt title parenthetical
    # (which the DQ test comma-splits) fragments into tokens absent from keywords.
    for r in rows:
        assert all("," not in k for k in r["keywords"]), r["keywords"]
    assert "compilers" in rows[0]["keywords"]
    assert "architecture" in rows[0]["keywords"]
    assert "computer vision" in rows[1]["keywords"]
    assert rows[2]["keywords"] == ["machine learning"]


def test_split_compound_keywords_atomizes_spaced_slash():
    # A spaced-slash list ("programming languages / formal methods / software
    # engineering") is three areas; an in-word slash ("airport/highway") is one.
    rows = [
        _fac_kw("Computer Science",
                ["programming languages / formal methods / software engineering"]),
        _fac_kw("Civil Engineering", ["airport/highway pavement design"]),
    ]
    _split_compound_keywords(rows)
    assert rows[0]["keywords"] == [
        "programming languages", "formal methods", "software engineering"]
    assert rows[1]["keywords"] == ["airport/highway pavement design"]


def test_is_junk_keyword_catches_research_question_headings():
    # Scraped "Research Questions" section headings are questions, not areas.
    for k in ["how does a tissue sense damage?",
              "what are the smallest building blocks of matter and how do they interact?",
              "how do viruses evade the immune system to cause disease?"]:
        assert _is_junk_keyword(k), k
    # a clean area with no question mark is untouched
    assert not _is_junk_keyword("tissue regeneration")


def test_run_faculty_dq_makes_a_dirty_scrape_quality_clean():
    # Mirrors the exact branch failures: course-code + comma-joined keywords, a
    # title with nav-menu pollution, and a shared department inbox on >=3 profs.
    rows = [
        {"source": "uiuc_faculty", "pi_name": "Ada Lovelace",
         "department": "Computer Science",
         "title": "Research with Prof. Ada Lovelace — CS",
         "keywords": ["compilers, architecture, and parallel computing",
                      "cs 591 sn - systems and networking seminar"],
         "metadata": {}, "contact_email": "advising@illinois.edu"},
        {"source": "uiuc_faculty", "pi_name": "Alan Turing",
         "department": "Computer Science",
         "title": "Research with Prof. Alan Turing — CS",
         "keywords": ["computer vision, object recognition, scene understanding"],
         "metadata": {}, "contact_email": "advising@illinois.edu"},
        {"source": "uiuc_faculty", "pi_name": "Grace Hopper",
         "department": "Computer Science",
         "title": "Research with Prof. Grace Hopper — CS",
         "keywords": ["machine learning"],
         "metadata": {}, "contact_email": "advising@illinois.edu"},
    ]
    _run_faculty_dq(rows)
    fac = [o for o in rows if o["source"] == "uiuc_faculty"]
    # TEST3 invariant: no junk keyword survives.
    assert not [k for o in fac for k in o["keywords"] if _is_junk_keyword(k)]
    # TEST2 invariant: every title parenthetical area is a subset of keywords.
    for o in fac:
        m = re.search(r" — .+? \((.+)\)$", o["title"])
        if m:
            shown = {t.strip().lower() for t in m.group(1).split(",")}
            kws = {(k or "").strip().lower() for k in o["keywords"]}
            assert not (shown - kws), (o["title"], o["keywords"])
    # TEST1 invariant: a shared inbox on >=3 distinct profs is nulled.
    assert all(o["contact_email"] is None for o in fac)


# DQ-4: collapse a joint-appointment professor duplicated across departments.

def _fac_email(pi_name, department, email, url):
    return {
        "source": "uiuc_faculty", "pi_name": pi_name, "department": department,
        "contact_email": email, "source_url": url, "description": "",
    }


def test_email_dedup_collapses_joint_appointment():
    rows = [
        _fac_email("David Forsyth", "Computer Science", "daf@illinois.edu", "https://cs.illinois.edu/daf"),
        _fac_email("David Forsyth", "Bioengineering", "daf@illinois.edu", "https://bioe.illinois.edu/daf"),
    ]
    out = _dedup_faculty_by_email(rows)
    assert len(out) == 1


def test_email_dedup_keeps_keyword_richer_over_broad_crosslisting():
    """A cross-appointed professor's home record (real keywords) must survive a
    cross-listing that carries only the broad field, even when the broad record
    has the longer name — keyword richness beats name length."""
    broad = _fac_email("Brent W Roberts", "Carle Illinois College of Medicine",
                       "bwrobrts@illinois.edu", "https://medicine.illinois.edu/p")
    broad["keywords"] = ["biomedical sciences"]
    rich = _fac_email("Brent Roberts", "Department of Psychology",
                      "bwrobrts@illinois.edu", "https://psychology.illinois.edu/p")
    rich["keywords"] = ["personality development", "narcissism", "conscientiousness"]
    out = _dedup_faculty_by_email([broad, rich])
    assert len(out) == 1
    assert out[0]["department"] == "Department of Psychology"
    assert "narcissism" in out[0]["keywords"]


def test_email_dedup_merges_name_variants_of_same_person():
    rows = [
        _fac_email("Pamela Martinez", "Statistics", "pamelapm@illinois.edu", "https://stat.illinois.edu/p"),
        _fac_email("Pamela P. Martinez", "Microbiology", "pamelapm@illinois.edu", "https://mcb.illinois.edu/p"),
    ]
    assert len(_dedup_faculty_by_email(rows)) == 1


def test_email_dedup_keeps_distinct_people_sharing_admin_email():
    # A shared department/admin email must NOT merge different professors who
    # happen to share a surname (the nslack@illinois.edu over-merge guard).
    rows = [
        _fac_email("Deming Chen", "ECE", "nslack@illinois.edu", "https://ece.illinois.edu/dchen"),
        _fac_email("Xu Chen", "ECE", "nslack@illinois.edu", "https://ece.illinois.edu/xuchen"),
        _fac_email("Yun-Sheng Chen", "ECE", "nslack@illinois.edu", "https://ece.illinois.edu/yschen"),
    ]
    assert len(_dedup_faculty_by_email(rows)) == 3


def test_email_dedup_passes_rows_without_email():
    rows = [
        _fac_email("Jane Doe", "Physics", "", "https://physics.illinois.edu/jd"),
        _fac_email("Jane Doe", "Astronomy", "", "https://astro.illinois.edu/jd"),
    ]
    assert len(_dedup_faculty_by_email(rows)) == 2


def test_null_shared_admin_email_across_distinct_professors():
    # One inbox attached to 3 distinct professors = a department/advising inbox.
    rows = [
        _fac_email("Alice Adams", "ECE", "nslack@illinois.edu", "u/aa"),
        _fac_email("Bob Brown", "ECE", "nslack@illinois.edu", "u/bb"),
        _fac_email("Carol Clark", "ECE", "nslack@illinois.edu", "u/cc"),
        _fac_email("Dana Diaz", "ECE", "ddiaz@illinois.edu", "u/dd"),  # personal
    ]
    nulled = _null_shared_admin_emails(rows)
    assert nulled == 3
    assert all(r["contact_email"] is None for r in rows[:3])
    assert rows[3]["contact_email"] == "ddiaz@illinois.edu"  # personal email kept


def test_joint_appointment_personal_email_is_not_nulled():
    # Same professor, two department rows, one shared *personal* email = 1 distinct
    # name → below threshold → kept (must not be mistaken for an admin inbox).
    rows = [
        _fac_email("David Forsyth", "Computer Science", "daf@illinois.edu", "u/cs"),
        _fac_email("David Forsyth", "Bioengineering", "daf@illinois.edu", "u/bioe"),
    ]
    assert _null_shared_admin_emails(rows) == 0
    assert all(r["contact_email"] == "daf@illinois.edu" for r in rows)


def test_rebuild_title_drops_navmenu_for_broad_only_prof():
    rows = [{
        "source": "uiuc_faculty", "pi_name": "Sasa Misailovic",
        "department": "Siebel School of Computing and Data Science",
        "title": "Research with Prof. Sasa Misailovic — CS (bioinformatics, "
                 "artificial intelligence, parallel computing)",
        "keywords": ["computer science"],
        "description_raw": "Research opportunity with Professor Sasa Misailovic. "
                           "Research areas: Architecture, Compilers and Parallel "
                           "Computing, Bioinformatics. Contact the professor.",
        "description_clean": "stale",
        "metadata": {"faculty_title": "Professor"},
        "eligibility": {"eligibility_text_raw": "stale"},
    }]
    assert _rebuild_faculty_title_and_desc(rows) == 1
    assert rows[0]["title"] == "Research with Prof. Sasa Misailovic — CS"
    assert "bioinformatics" not in rows[0]["title"]
    assert "Research areas:" not in rows[0]["description_clean"]
    assert "Architecture" not in rows[0]["description_clean"]


def test_rebuild_title_keeps_genuine_specific_areas():
    rows = [{
        "source": "uiuc_faculty", "pi_name": "Alexander Schwing",
        "department": "Electrical & Computer Engineering",
        "title": "Research with Prof. Alexander Schwing — ECE (stale)",
        "keywords": ["machine learning", "computer vision", "robotics"],
        "metadata": {"faculty_title": "Professor"},
    }]
    _rebuild_faculty_title_and_desc(rows)
    assert rows[0]["title"] == (
        "Research with Prof. Alexander Schwing — ECE "
        "(machine learning, computer vision, robotics)"
    )
    assert "Research areas: machine learning, computer vision, robotics." in \
        rows[0]["description_raw"]


def test_strip_pi_name_credential_suffix():
    rows = [
        {"source": "uiuc_faculty", "pi_name": "Helene R Dickel Phd"},
        {"source": "uiuc_faculty", "pi_name": "John Smith MD"},
        {"source": "uiuc_faculty", "pi_name": "Jane Doe"},          # 2 tokens — untouched
        {"source": "uiuc_faculty", "pi_name": "Ada Min Lovelace"},  # real 3-token name
    ]
    assert _strip_pi_name_credentials(rows) == 2
    assert rows[0]["pi_name"] == "Helene R Dickel"
    assert rows[1]["pi_name"] == "John Smith"
    assert rows[2]["pi_name"] == "Jane Doe"
    assert rows[3]["pi_name"] == "Ada Min Lovelace"


def test_postdoc_phrase_is_treated_as_nav_noise():
    # Recruiting-level phrases describe a role, not a research topic.
    assert _clean_research_phrase("Postdoctoral research opportunities") is None
    assert _clean_research_phrase("postdoc positions") is None
    # A genuine topic with no postdoc/doctoral token still passes.
    assert _clean_research_phrase("radiation detection") == "radiation detection"


# ── Re-enrichment (re-scrape broad-only faculty → recover keywords) ──

def test_keywords_from_research_areas_drops_broad_and_noise():
    out = _keywords_from_research_areas(
        "Computational Linguistics, Research Areas, linguistics, Syntax of Language Contact",
        "linguistics", "Jane Doe",
    )
    assert "linguistics" not in out          # broad field dropped
    assert "research areas" not in out       # nav noise dropped
    assert "computational linguistics" in out
    assert "syntax of language contact" in out


def test_keywords_from_research_areas_drops_self_name():
    out = _keywords_from_research_areas("Doe, Robotics", "mechanical engineering", "Jane Doe")
    assert "doe" not in out
    assert out == ["robotics"]


def test_research_areas_from_soup_reads_labelled_section():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(
        '<html><body><div class="research-interests">Quantum Optics, Photonics</div></body></html>',
        "html.parser",
    )
    assert "quantum optics" in _research_areas_from_soup(soup).lower()


def test_research_areas_from_soup_empty_when_absent():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup("<html><body><p>Teaches IS 226.</p></body></html>", "html.parser")
    assert _research_areas_from_soup(soup) == ""


def test_llm_keywords_drop_ungrounded(monkeypatch):
    # The model returns a fabricated topic ("blockchain") not on the page — the
    # grounding gate must drop it and keep only page-grounded keywords.
    monkeypatch.setattr(
        "backend.lib.llm.chat_completion",
        lambda *a, **k: "computer vision, blockchain, deep learning",
    )
    page = "Professor studies computer vision and deep learning in robotics."
    out = _llm_research_keywords("computer vision and deep learning", page)
    assert "computer vision" in out
    assert "deep learning" in out
    assert "blockchain" not in out


def test_llm_keywords_empty_without_provider(monkeypatch):
    monkeypatch.setattr("backend.lib.llm.chat_completion", lambda *a, **k: None)
    assert _llm_research_keywords("computer vision", "computer vision research") == []


def test_reenrich_targets_only_broad_only(monkeypatch):
    from bs4 import BeautifulSoup

    import src.collectors.uiuc_faculty as f
    monkeypatch.setattr(f.time, "sleep", lambda *_: None)
    soup = BeautifulSoup(
        '<div class="research-interests">Synthetic Biology, Gene Editing</div>',
        "html.parser",
    )
    monkeypatch.setattr(f, "_fetch_soup", lambda url: soup)
    broad = _dept_broad_field("Bioengineering")
    opps = [
        {"source": "uiuc_faculty", "department": "Bioengineering", "pi_name": "A B",
         "url": "http://x", "keywords": [broad]},                  # broad-only -> targeted
        {"source": "uiuc_faculty", "department": "Bioengineering", "pi_name": "C D",
         "url": "http://y", "keywords": ["tissue engineering"]},   # specific -> skipped
        {"source": "simplify_internships", "keywords": []},        # non-faculty -> skipped
    ]
    enriched, attempted, changes = _reenrich_broad_only_faculty(opps, dry_run=True)
    assert attempted == 1
    assert enriched == 1
    assert {c[0] for c in changes} == {"A B"}
    assert opps[0]["keywords"] == [broad]  # dry_run must not mutate


def test_reenrich_writes_keywords_when_not_dry_run(monkeypatch):
    from bs4 import BeautifulSoup

    import src.collectors.uiuc_faculty as f
    monkeypatch.setattr(f.time, "sleep", lambda *_: None)
    soup = BeautifulSoup(
        '<div class="research-interests">Synthetic Biology, Gene Editing</div>',
        "html.parser",
    )
    monkeypatch.setattr(f, "_fetch_soup", lambda url: soup)
    broad = _dept_broad_field("Bioengineering")
    opps = [{"source": "uiuc_faculty", "department": "Bioengineering", "pi_name": "A B",
             "url": "http://x", "keywords": [broad], "metadata": {}}]
    enriched, attempted, changes = _reenrich_broad_only_faculty(opps, dry_run=False)
    assert enriched == 1
    assert opps[0]["keywords"] == ["synthetic biology", "gene editing"]
    assert "Synthetic Biology" in opps[0]["metadata"]["research_areas_raw"]


def test_clean_research_phrase_drops_page_furniture():
    # Directory nav / job titles / section headers scrape as topic-shaped phrases
    # but are never research areas — the re-enrich validation surfaced these.
    for furniture in [
        "Edit Your Profile", "Courses Taught", "Assistant Professor",
        "Interim Director", "People", "Faculty", "Graduate Students", "Resources",
        "Undergraduate Research", "Research Labs and Facilities", "Research Topics",
        "Additional Campus Affiliations", "Yale University", "Student Services",
        "English Literature Majors", "Colloquia Calendar",
        "Conferences", "Upcoming Events", "Department Calendar", "External Links",
        "Research Description", "MathSciNet Publications",
    ]:
        assert _clean_research_phrase(furniture) is None, furniture
    # Genuine areas with overlapping words must survive.
    assert _clean_research_phrase("operations research") == "operations research"
    assert _clean_research_phrase("personnel selection") == "personnel selection"
    assert _clean_research_phrase("global environmental change") == "global environmental change"


def test_drop_nonperson_faculty_removes_section_headings():
    rows = [
        {"source": "uiuc_faculty", "pi_name": "Awards", "keywords": []},
        {"source": "uiuc_faculty", "pi_name": "TESL History", "keywords": []},
        {"source": "uiuc_faculty", "pi_name": "ZJUI", "keywords": []},
        {"source": "uiuc_faculty", "pi_name": "Undergraduate Student Ambassadors", "keywords": []},
        {"source": "uiuc_faculty", "pi_name": "Kathryn Clancy", "keywords": ["biological anthropology"]},
        {"source": "simplify_internships", "pi_name": "Awards"},  # non-faculty passes through
    ]
    kept, dropped = _drop_nonperson_faculty(rows)
    assert dropped == 4
    kept_names = [r.get("pi_name") for r in kept]
    assert kept_names == ["Kathryn Clancy", "Awards"]  # real prof + non-faculty row


def test_strip_pronoun_suffix_from_pi_name():
    rows = [{"source": "uiuc_faculty", "pi_name": "Kathryn Clancy she/her"}]
    assert _strip_pi_name_credentials(rows) == 1
    assert rows[0]["pi_name"] == "Kathryn Clancy"


def test_is_junk_keyword_catches_furniture_truncation_fragments():
    junk = [
        "tondeur lectures in mathematics", "adjuncts & affiliates",
        "introduction to islam", "undergraduate research opportunities",
        "molecular mechanisms of", "columbia uni", "universi", "traffic fl",
        "communication conc", "nature has done exactly that",
        "i study model theory", "working with peter teichner", "assembling carbon",
    ]
    for k in junk:
        assert _is_junk_keyword(k), k


def test_is_junk_keyword_preserves_genuine_areas():
    # Includes the live-page verifier's over-strict false-positives, which are
    # real research areas and must survive, plus words that overlap furniture.
    real = [
        "endocrinology", "optics", "quantum fisher information", "thermodynamics",
        "metabolic regulation", "galaxies and ism", "water resources",
        "machine teaching", "major histocompatibility complex", "media studies",
        "resource recovery from wastewater", "x-ray ct", "functional mri",
        "stable isotope ecology and paleoecology",
    ]
    for k in real:
        assert not _is_junk_keyword(k), k


# --- missing_departments: the silent-scrape-failure guard (MatSE rotted its URL
# and scraped 0 unnoticed). These are offline; the live scrape runs in the refresh
# pipeline, where refresh_all surfaces the empties in the run summary. ---

def test_missing_departments_flags_an_empty_dept():
    present = [{"department": v["name"]} for k, v in DEPARTMENTS.items() if k != "matse"]
    assert missing_departments(present) == [DEPARTMENTS["matse"]["name"]]


def test_missing_departments_empty_when_all_present():
    present = [{"department": v["name"]} for v in DEPARTMENTS.values()]
    assert missing_departments(present) == []


def test_missing_departments_total_failure_lists_all():
    assert set(missing_departments([])) == {v["name"] for v in DEPARTMENTS.values()}


def test_missing_departments_honors_subset():
    assert missing_departments([], departments=["matse"]) == [DEPARTMENTS["matse"]["name"]]
    assert missing_departments(
        [{"department": DEPARTMENTS["matse"]["name"]}], departments=["matse"]
    ) == []


def test_neuroscience_is_a_program_department():
    # The interdisciplinary Neuroscience program must declare its dedup contract,
    # else _dedup_program_affiliations silently treats its faculty as new people.
    neuro = DEPARTMENTS["neuroscience"]
    assert neuro.get("program") is True
    assert neuro["affiliation_keyword"] == "neuroscience"


def test_dedup_program_affiliations_tags_home_and_keeps_new():
    from src.collectors.uiuc_faculty import _dedup_program_affiliations

    prog = DEPARTMENTS["neuroscience"]["name"]
    opps = [
        {"id": "ece-a", "department": "Electrical & Computer Engineering",
         "source": "uiuc_faculty", "contact_email": "a@illinois.edu",
         "keywords": ["signal processing"]},
        # cross-listed duplicate of the ECE person — case-insensitive email match
        {"id": "neuro-a", "department": prog, "source": "uiuc_faculty",
         "contact_email": "A@illinois.edu", "keywords": ["neuroscience"]},
        # genuinely new program faculty (no home-dept record)
        {"id": "neuro-new", "department": prog, "source": "uiuc_faculty",
         "contact_email": "new@illinois.edu", "keywords": ["neuroscience"]},
        # emailless program record can't be matched → kept
        {"id": "neuro-noemail", "department": prog, "source": "uiuc_faculty",
         "contact_email": None, "keywords": ["neuroscience"]},
    ]
    out = _dedup_program_affiliations(opps)
    ids = {o["id"] for o in out}
    assert "neuro-a" not in ids, "cross-listed duplicate should be dropped"
    assert {"ece-a", "neuro-new", "neuro-noemail"} <= ids
    ece = next(o for o in out if o["id"] == "ece-a")
    assert "neuroscience" in ece["keywords"], "home record must be tagged"
    # idempotent: the tag is not duplicated on a second pass
    assert _dedup_program_affiliations(out) == out or \
        ece["keywords"].count("neuroscience") == 1


def test_dedup_program_affiliations_noop_without_program_depts():
    from src.collectors.uiuc_faculty import _dedup_program_affiliations

    opps = [
        {"id": "x", "department": "Physics", "source": "uiuc_faculty",
         "contact_email": "x@illinois.edu", "keywords": ["optics"]},
    ]
    assert _dedup_program_affiliations(list(opps)) == opps
