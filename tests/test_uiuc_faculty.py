"""Deterministic guards for the uiuc_faculty collector's department registry
and the section-label filter that keeps directory headings ("Postdocs",
"Affiliates and Adjuncts") out of the faculty data. No network: the live
scrape runs in the refresh pipeline, not in CI.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.collectors.uiuc_faculty import (
    DEPARTMENTS,
    _carry_forward_enrichment,
    _clean_research_phrase,
    _dedup_decredentialed_faculty,
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
    clean_pi_name,
    enforce_final_shared_keyword_invariant,
    missing_departments,
    normalize_faculty,
)
from src.evidence import FACULTY_MAJOR_LABELS_MARKER

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
        _fac_email("Susan Koshy", "Department of English", "english@illinois.edu", "u/sk"),
        _fac_email("Pengjie Wang", "Department of Physics", "mainoffice@physics.illinois.edu", "u/pw"),
        _fac_email("Carl M. Parsons", "Department of Animal Sciences", "poultry@illinois.edu", "u/cp"),
        _fac_email("Kathryn Clancy", "Department of Anthropology", "anthro@illinois.edu", "u/kc"),
        # unit inboxes at OTHER schools are the same pattern — nulled too
        _fac_email("Jane Roe", "Scheller College of Business", "dean@scheller.gatech.edu",
                   "u/jr", source="gatech_faculty"),
        _fac_email("John Poe", "Nelson Institute", "info@nelson.wisc.edu",
                   "u/jp", source="wisc_faculty"),
        # personal addresses that must SURVIVE
        _fac_email("Larry A. Fahnestock", "Department of Civil Engineering",
                   "fhnstck@illinois.edu", "u/lf"),
        _fac_email("Gary E. Gladding", "Department of Physics", "geg@illinois.edu", "u/gg"),
        _fac_email("Linda Bushnell", "Electrical & Computer Engineering",
                   "lb2@uw.edu", "u/lb", source="uw_faculty"),
    ]
    nulled = _null_unit_inbox_emails(opps)
    assert nulled == 6
    assert [o["contact_email"] for o in opps[:6]] == [None] * 6
    assert opps[6]["contact_email"] == "fhnstck@illinois.edu"
    assert opps[7]["contact_email"] == "geg@illinois.edu"
    assert opps[8]["contact_email"] == "lb2@uw.edu"


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
    assert opp["on_campus"] is None
    assert opp["eligibility"]["preferred_year"] == ["unknown"]
    assert opp["eligibility"]["international_friendly"] == "unknown"
    assert opp["eligibility"]["citizenship_required"] is None
    assert opp["eligibility"]["majors"] == []
    assert opp["metadata"][FACULTY_MAJOR_LABELS_MARKER] == cfg["majors"]
    assert opp["application"]["application_effort"] == "unknown"


def test_normalize_never_infers_skills_for_faculty():
    """Faculty must carry no inferred skills — a prior collector pass mined the
    research prose for skills (statistical->R, deep learning->PyTorch), which
    the R70A DQ gate rejects and which silently failed the first-week deep
    refresh. Even a description dense with skill-trigger words yields empty
    skills at the source, matching faculty_graph and the downstream guards."""
    cfg = DEPARTMENTS["mcb"]
    opp = normalize_faculty(
        {"name": "Jane Q. Researcher",
         "url": "https://mcb.illinois.edu/directory/profile/jresearcher",
         "research_areas": "statistical genomics, machine learning, deep learning, "
                           "bioinformatics, computational biology, epidemiology",
         "research_description": "Uses Python and R for data science and neural networks."},
        cfg,
    )
    assert opp is not None
    assert opp["eligibility"]["skills_required"] == []
    assert opp["eligibility"]["skills_preferred"] == []


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


def test_dept_broad_field_carle_avoids_junk_college_fallback():
    """Carle's derived fallback ("carle illinois college of medicine") is junk
    (contains "college"); the explicit mapping must give a clean broad field so a
    demoted Carle record never carries a junk keyword."""
    bf = _dept_broad_field("Carle Illinois College of Medicine")
    assert bf == "biomedical sciences"
    assert not _is_junk_keyword(bf)


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


def test_final_guard_catches_keyword_sets_that_collide_only_after_hygiene():
    """Regression for the 2026-07-20 scheduled DQ failure.

    The first UIUC pass sees six distinct strings; corpus-wide hygiene strips
    their whitespace differences and creates one forbidden shared set. The
    final guard must re-establish the invariant before publication.
    """

    from src.collectors.faculty_graph import clean_corpus_faculty_keywords

    rows = [
        {
            "id": f"physics-{index}",
            "source": "uiuc_faculty",
            "source_type": "faculty_research",
            "department": "Department of Physics",
            "pi_name": f"Professor {index}",
            "keywords": [
                "astrophysics",
                "cosmology",
                f"relativity{' ' * index}",
            ],
            "metadata": {"faculty_title": "Professor"},
            "eligibility": {},
        }
        for index in range(6)
    ]
    assert _demote_shared_keyword_pollution(rows) == 0
    assert clean_corpus_faculty_keywords(rows) == 5

    stats = enforce_final_shared_keyword_invariant(rows)

    assert stats["shared_keyword_demoted"] == 6
    assert all(row["keywords"] == ["physics"] for row in rows)
    assert all("physics" in row["description_clean"].lower() for row in rows)


# Same-id merge guard: a broad/empty re-scrape must not clobber committed
# OpenAlex/LLM enrichment (the P1 that would silently revert #369/#370).

def test_carry_forward_preserves_enrichment_over_broad_rescrape():
    existing = {
        "pi_name": "Gordon Baym", "department": "Department of Physics",
        "keywords": ["cold atom physics", "pulsars and gravitational waves"],
        "title": "Research with Prof. Gordon Baym — Physics (cold atom physics)",
        "description_raw": "Research areas: cold atom physics, pulsars.",
        "description_clean": "Research areas: cold atom physics, pulsars.",
    }
    incoming = {
        "pi_name": "Gordon Baym", "department": "Department of Physics",
        "keywords": ["physics"],  # a directory re-scrape with only the dept label
        "title": "Research with Prof. Gordon Baym — Physics",
        "description_raw": "Contact the professor to inquire about research.",
        "description_clean": "Contact the professor to inquire about research.",
        "contact_email": "baym@illinois.edu",  # a fresh factual field
    }
    _carry_forward_enrichment(existing, incoming)
    # Research facts survive, but legacy opening-shaped display prose must not
    # be carried back over the fresh availability-neutral projection.
    assert incoming["keywords"] == existing["keywords"]
    assert incoming["title"] == "Research with Prof. Gordon Baym — Physics"
    assert incoming["description_clean"] == "Contact the professor to inquire about research."
    # ...while the fresh factual field is untouched (still updates on merge)
    assert incoming["contact_email"] == "baym@illinois.edu"


def test_carry_forward_lets_richer_rescrape_win():
    existing = {"pi_name": "A B", "department": "Department of Physics", "keywords": ["physics"]}
    incoming = {
        "pi_name": "A B", "department": "Department of Physics",
        "keywords": ["quantum optics", "laser cooling", "bose-einstein condensates"],
    }
    _carry_forward_enrichment(existing, incoming)
    assert incoming["keywords"] == ["quantum optics", "laser cooling", "bose-einstein condensates"]


def test_carry_forward_preserves_profile_pass_email():
    """Schools like CU Experts expose emails ONLY on per-profile pages, and the
    profile pass is gated to first-week runs — a listing-only re-scrape emits no
    contact_email and must not wipe the committed one, even when the fresh
    scrape is keyword-richer (the carry is unconditional, like recent_works)."""
    existing = {
        "pi_name": "A B", "department": "Computer Science",
        "keywords": ["physics"], "contact_email": "a.b@colorado.edu",
    }
    incoming = {
        "pi_name": "A B", "department": "Computer Science",
        "keywords": ["quantum optics", "laser cooling", "bose-einstein condensates"],
    }
    _carry_forward_enrichment(existing, incoming)
    assert incoming["contact_email"] == "a.b@colorado.edu"
    assert incoming["keywords"] == ["quantum optics", "laser cooling", "bose-einstein condensates"]


def test_carry_forward_keeps_attribution_stamp_with_recent_works():
    """The publication_attribution_status stamp travels WITH the works it
    describes: carried when the works are carried, gone when a fresh scrape
    brings its own works (the stamp never labels works it didn't describe)."""
    existing = {
        "pi_name": "A B", "department": "Physics",
        "metadata": {"recent_works": [{"title": "Old Paper", "year": 2024}],
                     "publication_attribution_status": "verified_author_id"},
    }
    incoming = {"pi_name": "A B", "department": "Physics"}
    _carry_forward_enrichment(existing, incoming)
    assert incoming["metadata"]["recent_works"] == [{"title": "Old Paper", "year": 2024}]
    assert incoming["metadata"]["publication_attribution_status"] == "verified_author_id"

    # incoming already has works → neither existing works nor stamp are carried
    incoming2 = {"pi_name": "A B", "department": "Physics",
                 "metadata": {"recent_works": [{"title": "New Paper", "year": 2026}]}}
    _carry_forward_enrichment(existing, incoming2)
    assert incoming2["metadata"]["recent_works"] == [{"title": "New Paper", "year": 2026}]
    assert "publication_attribution_status" not in incoming2["metadata"]

    # legacy record with works but no stamp → works still carried, no stamp invented
    legacy = {"pi_name": "A B", "department": "Physics",
              "metadata": {"recent_works": [{"title": "Old Paper", "year": 2024}]}}
    incoming3 = {"pi_name": "A B", "department": "Physics"}
    _carry_forward_enrichment(legacy, incoming3)
    assert incoming3["metadata"]["recent_works"] == [{"title": "Old Paper", "year": 2024}]
    assert "publication_attribution_status" not in incoming3["metadata"]


def test_carry_forward_keeps_the_gate_and_the_author_id_with_the_works():
    """works_gate and publication_author_id travel with the works too.

    Losing works_gate on a re-scrape is not cosmetic: _record_gate reads a
    missing value as the oldest gate, so a record chosen by the current one
    goes back into the re-harvest queue and gets bought again — and a version
    stamp that a weekly refresh erases cannot do the job it was added for.
    """
    existing = {
        "pi_name": "A B", "department": "Physics",
        "metadata": {"recent_works": [{"title": "Old Paper", "year": 2024}],
                     "publication_attribution_status": "verified_author_id",
                     "publication_author_id": "https://openalex.org/A5019294923",
                     "works_gate": 2},
    }
    incoming = {"pi_name": "A B", "department": "Physics"}
    _carry_forward_enrichment(existing, incoming)
    assert incoming["metadata"]["works_gate"] == 2
    assert incoming["metadata"]["publication_author_id"] == \
        "https://openalex.org/A5019294923"

    # a fresh scrape with its own works keeps none of it — the gate and the id
    # describe the works they were written for, not whatever replaced them
    incoming2 = {"pi_name": "A B", "department": "Physics",
                 "metadata": {"recent_works": [{"title": "New Paper", "year": 2026}]}}
    _carry_forward_enrichment(existing, incoming2)
    assert "works_gate" not in incoming2["metadata"]
    assert "publication_author_id" not in incoming2["metadata"]


# The two shapes the publication remediation leaves on a record, as the corpus
# holds them: a professor whose trust was withdrawn and who still holds the
# candidate papers, and one the re-harvest settled with nothing citable.
_WITHDRAWN_BLOCK = {
    "from_gate": 1, "to_gate": 3,
    "withdrawn_at": "2026-09-30T17:35:43.549131+00:00",
    "prior_status": "verified_author_id", "prior_author_id": None,
}
_AMBIGUOUS_BLOCK = {
    **_WITHDRAWN_BLOCK,
    "disposition": "ambiguous",
    "resolved_at": "2026-10-01T02:41:31.958499+00:00",
    "relationships_removed": 3, "keywords_invalidated": True,
}


def _withdrawn_metadata() -> dict:
    return {
        "recent_works": [{"title": "A Stranger's Paper", "year": 2025}],
        "publication_attribution_status": "pending_remediation",
        "publication_remediation": dict(_WITHDRAWN_BLOCK),
    }


def _settled_metadata() -> dict:
    return {"works_gate": 3, "publication_remediation": dict(_AMBIGUOUS_BLOCK)}


def test_carry_forward_keeps_the_remediation_block_with_the_withdrawn_works():
    """``publication_remediation`` describes the withdrawn works and travels with
    them, like the attribution stamps do.

    Regression: the 2026-10-02 refresh (#1021) re-scraped columbia, miami and
    ucsc and dropped the block from all 5 withdrawn professors there while
    carrying their papers and their pending status, so the from/to-gate trail
    survived only in the ledger.
    """
    existing = {"pi_name": "A B", "department": "Physics", "metadata": _withdrawn_metadata()}
    incoming = {"pi_name": "A B", "department": "Physics"}
    _carry_forward_enrichment(existing, incoming)
    md = incoming["metadata"]
    assert md["publication_remediation"] == _WITHDRAWN_BLOCK
    assert md["publication_attribution_status"] == "pending_remediation"

    # A fresh scrape with its own works keeps none of it: the block would then
    # describe a withdrawal of works the record no longer holds.
    incoming2 = {"pi_name": "A B", "department": "Physics",
                 "metadata": {"recent_works": [{"title": "New Paper", "year": 2026}]}}
    _carry_forward_enrichment(existing, incoming2)
    assert "publication_remediation" not in incoming2["metadata"]


def test_carry_forward_keeps_a_settled_remediation_verdict_that_left_no_works():
    """A record the re-harvest settled as ambiguous, removed, unknown or
    needs_review holds no works, so the works carry never runs for it, and a
    re-scrape used to erase the verdict: the 33 ambiguous LAC records would
    then exist as ambiguous only in the ledger."""
    existing = {"pi_name": "A B", "department": "Physics", "metadata": _settled_metadata()}
    incoming = {"pi_name": "A B", "department": "Physics"}
    _carry_forward_enrichment(existing, incoming)
    assert incoming["metadata"]["publication_remediation"] == _AMBIGUOUS_BLOCK

    # Fail closed, as for the stamps: never onto a record that brings works of
    # its own, never over a block of its own...
    incoming2 = {"pi_name": "A B", "department": "Physics",
                 "metadata": {"recent_works": [{"title": "New Paper", "year": 2026}]}}
    _carry_forward_enrichment(existing, incoming2)
    assert "publication_remediation" not in incoming2["metadata"]
    own = {"disposition": "removed", "resolved_at": "2026-10-05T00:00:00+00:00"}
    incoming3 = {"pi_name": "A B", "department": "Physics",
                 "metadata": {"publication_remediation": dict(own)}}
    _carry_forward_enrichment(existing, incoming3)
    assert incoming3["metadata"]["publication_remediation"] == own

    # ...and a withdrawal block (no verdict) never travels without the works it
    # withdrew: it would claim a pending re-judgement the record cannot have.
    orphan = {"pi_name": "A B", "department": "Physics",
              "metadata": {"publication_remediation": dict(_WITHDRAWN_BLOCK)}}
    incoming4 = {"pi_name": "A B", "department": "Physics"}
    _carry_forward_enrichment(orphan, incoming4)
    assert "publication_remediation" not in (incoming4.get("metadata") or {})

    # Committed data is a boundary: a malformed block is not carried and does
    # not stop the merge.
    malformed = {"pi_name": "A B", "department": "Physics",
                 "metadata": {"publication_remediation": "ambiguous"}}
    incoming5 = {"pi_name": "A B", "department": "Physics"}
    _carry_forward_enrichment(malformed, incoming5)
    assert "publication_remediation" not in (incoming5.get("metadata") or {})


@pytest.mark.parametrize("state", ["withdrawn", "ambiguous"])
@pytest.mark.parametrize("collector", ["faculty_graph", "uiuc_faculty", "ucb_common"])
def test_every_faculty_upsert_keeps_the_remediation_block(tmp_path, monkeypatch, collector, state):
    """The same, through each collector's real merge into temporary storage: the
    directory re-scrape produces the record again with none of the remediation
    metadata, and the merged corpus keeps the block — and still fails closed."""
    import copy
    import json

    from src.collectors import faculty_graph, ucb_common, uiuc_faculty
    from src.publication_trust import verified_recent_works

    fresh = normalize_faculty(
        {"name": "Jane Smith", "title": "Professor",
         "url": "https://ece.illinois.edu/about/directory/faculty/jsmith",
         "research_areas": "machine learning, computer vision"},
        DEPARTMENTS["ece"],
    )
    prior = copy.deepcopy(fresh)
    remediation = _withdrawn_metadata() if state == "withdrawn" else _settled_metadata()
    prior["metadata"].update(remediation)
    path = tmp_path / "opportunities.json"
    path.write_text(json.dumps([prior]), encoding="utf-8")
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", path)

    if collector == "uiuc_faculty":
        uiuc_faculty.merge_into_processed([fresh], filepath=str(path))
    else:
        (faculty_graph if collector == "faculty_graph" else ucb_common).merge_into_processed([fresh])

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved) == 1
    md = saved[0]["metadata"]
    assert md["publication_remediation"] == remediation["publication_remediation"]
    assert verified_recent_works(saved[0]) == []
    if state == "withdrawn":
        assert md["publication_attribution_status"] == "pending_remediation"
        assert md["recent_works"] == remediation["recent_works"]
    else:
        assert "recent_works" not in md


def test_carry_forward_keeps_the_inference_stamp_with_the_keywords():
    """The ``inferred_fields.keywords`` stamp travels WITH the keywords it
    describes, exactly like ``publication_attribution_status`` travels with
    ``recent_works``.

    Regression for the 2026-08-29 refresh (#829/#830), which carried 2,829
    OpenAlex-derived keyword sets forward while dropping their stamps: JHU
    2,676 stamped records became 266, Cincinnati 432 became 13, and not one
    keyword or record was lost. Losing only the stamp is the worst of the
    three outcomes, because a stamp is the sole thing separating a topic we
    guessed from a topic the professor stated. Downstream, an unstamped
    keyword is a stated fact: ``_stated_keywords`` lets the cold email write
    "your work in X" about it, and the detail card drops the "inferred"
    caveat. A refresh that silently promotes inference to fact re-arms the
    exact false sentence #826 and #827 were built to prevent.
    """
    existing = {
        "pi_name": "A B", "department": "Radiology",
        "keywords": ["magnetic resonance imaging", "breast cancer screening"],
        "metadata": {"inferred_fields": {"keywords": "derived:openalex_topics"}},
    }
    incoming = {  # a listing-only re-scrape: the department label, nothing more
        "pi_name": "A B", "department": "Radiology", "keywords": ["radiology"],
    }
    _carry_forward_enrichment(existing, incoming)
    assert incoming["keywords"] == existing["keywords"]
    assert incoming["metadata"]["inferred_fields"]["keywords"] == "derived:openalex_topics"

    # A richer fresh scrape wins, and the stale stamp must NOT follow: those
    # keywords came off the professor's own page, so labelling them "inferred"
    # would understate what we know just as falsely as the reverse overstates.
    incoming2 = {
        "pi_name": "A B", "department": "Radiology",
        "keywords": ["diffusion tensor imaging", "quantitative MRI", "radiomics"],
    }
    _carry_forward_enrichment(existing, incoming2)
    assert incoming2["keywords"] == ["diffusion tensor imaging", "quantitative MRI", "radiomics"]
    assert "inferred_fields" not in (incoming2.get("metadata") or {})

    # A legacy stated record carries its keywords with no stamp invented.
    stated = {"pi_name": "A B", "department": "Radiology",
              "keywords": ["magnetic resonance imaging", "breast cancer screening"]}
    incoming3 = {"pi_name": "A B", "department": "Radiology", "keywords": ["radiology"]}
    _carry_forward_enrichment(stated, incoming3)
    assert incoming3["keywords"] == stated["keywords"]
    assert "inferred_fields" not in (incoming3.get("metadata") or {})

def test_carry_forward_keeps_research_areas_raw():
    """The professor's own stated research areas survive a re-scrape that did
    not reach their detail page.

    Regression: the 2026-08-20 refresh re-harvested 16 shards through the
    listing-only path, which emits no ``research_areas_raw``. ``cur.update(opp)``
    replaces ``metadata`` wholesale, so 2,716 of 5,012 committed statements were
    erased — brown and boulder to zero, rice 555 -> 1. That prose is the sole
    input to the faculty availability signal and to cold-email grounding, so an
    entire school silently lost both. Carried unconditionally for the same
    reason ``recent_works`` is: a scrape that produced nothing is not evidence
    that the professor removed anything.
    """
    existing = {
        "pi_name": "Drew Milsom", "department": "PHYS",
        "keywords": ["computational astrophysics"],
        "metadata": {
            "research_areas_raw": (
                "While I am not currently research active, I have worked in "
                "computational astrophysics."
            ),
            "last_verified": "2026-08-15T03:59:15",
        },
    }
    incoming = {
        "pi_name": "Drew Milsom", "department": "PHYS",
        "keywords": ["computational astrophysics"],
        "metadata": {"last_verified": "2026-08-20T06:31:54"},
    }
    _carry_forward_enrichment(existing, incoming)
    assert incoming["metadata"]["research_areas_raw"] == (
        "While I am not currently research active, I have worked in "
        "computational astrophysics."
    )
    # The carried statement keeps the date it was actually observed, so nothing
    # downstream can present last week's prose as verified today.
    assert incoming["metadata"]["research_areas_verified_at"] == "2026-08-15T03:59:15"


def test_carry_forward_fresh_research_areas_win():
    """A scrape that reached the page owns the statement — including a professor
    who deleted theirs, which is why the fresh value wins even when it is
    shorter."""
    existing = {
        "pi_name": "A B", "department": "Physics",
        "metadata": {"research_areas_raw": "black hole accretion flows",
                     "last_verified": "2026-08-15T00:00:00"},
    }
    incoming = {
        "pi_name": "A B", "department": "Physics",
        "metadata": {"research_areas_raw": "quantum optics"},
    }
    _carry_forward_enrichment(existing, incoming)
    assert incoming["metadata"]["research_areas_raw"] == "quantum optics"
    # Not carried, so no stamp is invented for prose this scrape observed itself.
    assert "research_areas_verified_at" not in incoming["metadata"]


# --- M154: a department's field on a profile that states no research ---------

def _silent_profile(source: str, department: str, keywords: list[str], **metadata) -> dict:
    return {"id": "m154", "source": source, "source_type": "faculty_research", "department": department,
            "pi_name": "Avery Example", "keywords": list(keywords), "metadata": dict(metadata)}


def test_every_collector_fallback_is_stamped_as_a_department_tag():
    """Each unit config's fallback words, and the broad field the refresh-time
    keyword passes write, are ours on a row of that unit. Read off the configs,
    so a unit added later is covered too."""
    from src.collectors.uiuc_faculty import _collector_department_fields, stamp_department_field_keywords
    from src.evidence import DEPARTMENT_FIELD_METHOD, inferred_method

    pairs = _collector_department_fields()
    assert {"uiuc_faculty", "ucb_ib_faculty", "ucb_extra_faculty"} <= {source for source, _ in pairs}
    for (source, department), words in pairs.items():
        for word in words | {_dept_broad_field(department)}:
            record = stamp_department_field_keywords(_silent_profile(source, department, [word]))
            assert inferred_method(record, "keywords") == DEPARTMENT_FIELD_METHOD, (source, department, word)


@pytest.mark.parametrize("source,department,keywords", [
    # Gies writes its own broad field, and ACES NRES its config's first word,
    # where the derived broad field says "business administration" and
    # "environmental sciences".
    ("uiuc_faculty", "Department of Business Administration", ["business"]),
    ("uiuc_faculty", "Natural Resources & Environmental Sciences", ["natural resources"]),
    # What the compound split leaves of EPOL's broad field.
    ("uiuc_faculty", "Department of Education Policy, Organization & Leadership", ["organization and leadership"]),
    # A Berkeley config's word, where the derived broad field names the unit.
    ("ucb_law_faculty", "Berkeley Law", ["law"]),
    ("ucb_arch_faculty", "Architecture (College of Environmental Design)", ["architecture"]),
    ("ucb_journalism_faculty", "Graduate School of Journalism", ["journalism"]),
    # The Berkeley keyword bank reading the unit's name in a title.
    ("ucb_dcrp_faculty", "City & Regional Planning (College of Environmental Design)", ["regional planning"]),
    ("ucb_larch_faculty", "Landscape Architecture & Environmental Planning (College of Environmental Design)",
     ["landscape architecture", "environmental planning"]),
    # A program's affiliation tag beside the home department's field.
    ("uiuc_faculty", "Bioengineering", ["bioengineering", "neuroscience"]),
    ("uiuc_faculty", "Department of Psychology", ["psychology", "neuroscience"]),
    # A person two of a college's units list, kept under either.
    ("uiuc_faculty", "Department of Comparative Biosciences", ["veterinary clinical medicine"]),
    ("uiuc_faculty", "Department of Finance", ["business"]),
    ("uiuc_faculty", "School of Music", ["architecture"]),
    ("uiuc_faculty", "Department of Journalism", ["advertising"]),
    # The Berkeley bank matches a unit's name as the collector matches a title.
    ("ucb_nst_faculty", "Department of Nutritional Sciences & Toxicology", ["nutritional science"]),
])
def test_fallbacks_the_derived_broad_field_misses_are_stamped(source, department, keywords):
    from src.collectors.uiuc_faculty import stamp_department_field_keywords
    from src.evidence import DEPARTMENT_FIELD_METHOD, inferred_method

    record = stamp_department_field_keywords(_silent_profile(source, department, keywords))
    assert inferred_method(record, "keywords") == DEPARTMENT_FIELD_METHOD


def test_every_berkeley_unit_on_the_shard_has_its_fallback_registered():
    """The registry finds Berkeley's configs by module name; a unit the
    discovery misses would leave its rows' fallback shown as their research."""
    from src.collectors.uiuc_faculty import _collector_department_fields

    shard = Path(__file__).resolve().parents[1] / "data" / "processed" / "shards" / "ucb.json"
    if not shard.exists():
        pytest.skip("committed Berkeley shard not present")
    units = {(r["source"], r["department"]) for r in json.loads(shard.read_text())
             if r.get("source_type") == "faculty_research" and (r.get("metadata") or {}).get("is_active", True)}
    assert len(units) > 50
    assert not units - set(_collector_department_fields())


@pytest.mark.parametrize("record", [
    _silent_profile("uiuc_faculty", "Department of Physics", ["quantum optics"]),
    _silent_profile("uiuc_faculty", "Department of Physics", ["physics", "quantum optics"]),
    # Another school's directory tag naming the unit, in the page's casing.
    _silent_profile("umich_faculty", "Statistics", ["Statistics"]),
    # A department config's later words are subfields a page states, not its fallback.
    _silent_profile("uiuc_faculty", "Department of Chemistry", ["organic chemistry"]),
    _silent_profile("uiuc_faculty", "Department of Statistics", ["statistics", "data science"]),
    _silent_profile("ucb_extra_faculty", "Department of East Asian Languages & Cultures", ["japanese"]),
    # Our tags are UIUC's program listing and Berkeley's keyword bank, nowhere else.
    _silent_profile("stanford_faculty", "Department of Biology", ["biology", "neuroscience"]),
    _silent_profile("arizona_faculty", "Department of Ecology and Evolutionary Biology",
                    ["evolutionary biology", "ecology"]),
    # Alone, a program's word is what the UIUC bank reads off the profile.
    _silent_profile("uiuc_faculty", "Department of Psychology", ["neuroscience"],
                    research_areas_raw="Clinical-Community, Cognitive Neuroscience"),
    # A bank word the profile's research text holds may have been read there.
    _silent_profile("ucb_dcrp_faculty", "City & Regional Planning (College of Environmental Design)",
                    ["regional planning"], research_areas_raw="Regional planning and transportation policy"),
    # Another producer's stamp stays.
    _silent_profile("uiuc_faculty", "Department of Physics", ["physics"],
                    inferred_fields={"keywords": "derived:openalex_topics"}),
    {**_silent_profile("uiuc_faculty", "Department of Physics", ["physics"]), "source_type": "campus_program"},
    _silent_profile("uiuc_faculty", "Department of Physics", []),
])
def test_keywords_the_page_states_or_another_stamp_covers_are_left_alone(record):
    from copy import deepcopy

    from src.collectors.uiuc_faculty import stamp_department_field_keywords

    before = deepcopy(record)
    assert stamp_department_field_keywords(record) == before


def test_the_department_field_stamp_is_idempotent():
    from copy import deepcopy

    from src.collectors.uiuc_faculty import stamp_department_field_keywords

    once = stamp_department_field_keywords(_silent_profile("uiuc_faculty", "Department of Physics", ["physics"]))
    assert stamp_department_field_keywords(deepcopy(once)) == once


def test_research_text_that_is_only_the_department_field_is_not_carried():
    """The HTML and JSON directory collectors wrote the fallback into the
    research text too; a stored copy of it is not carried onto a fresh row,
    while text the profile stated still is."""
    from src.collectors.uiuc_faculty import _is_department_field_text

    law = _silent_profile("uiuc_faculty", "College of Law", ["law"])
    assert _is_department_field_text("law", law)
    assert _is_department_field_text("biomedical sciences",
                                     _silent_profile("uiuc_faculty", "Carle Illinois College of Medicine", []))
    assert not _is_department_field_text("law; criminal procedure", law)
    assert not _is_department_field_text("Constitutional Law", law)

    existing = {**law, "metadata": {"research_areas_raw": "law", "last_verified": "2026-10-05T00:00:00"}}
    incoming = _silent_profile("uiuc_faculty", "College of Law", ["law"])
    _carry_forward_enrichment(existing, incoming)
    assert "research_areas_raw" not in incoming["metadata"]
    assert "research_areas_verified_at" not in incoming["metadata"]

    stated = {**law, "metadata": {"research_areas_raw": "Civil Procedure; Constitutional Law"}}
    incoming = _silent_profile("uiuc_faculty", "College of Law", ["law"])
    _carry_forward_enrichment(stated, incoming)
    assert incoming["metadata"]["research_areas_raw"] == "Civil Procedure; Constitutional Law"


@pytest.mark.parametrize("unit,raw", [
    ("psych", "Cognitive Neuroscience"),
    ("mcb", "Systems neuroscience of the zebrafish"),
])
def test_a_program_word_the_bank_read_off_the_page_is_not_our_tag(unit, raw):
    from src.collectors.uiuc_faculty import DEPARTMENTS, _extract_research_keywords, stamp_department_field_keywords
    from src.evidence import inferred_method

    keywords = _extract_research_keywords({"research_areas": raw, "url": ""}, DEPARTMENTS[unit])
    assert keywords == ["neuroscience"]
    record = _silent_profile("uiuc_faculty", DEPARTMENTS[unit]["name"], keywords, research_areas_raw=raw)
    assert inferred_method(stamp_department_field_keywords(record), "keywords") is None


def test_a_media_row_storing_another_media_unit_s_field_holds_no_statement():
    from src.collectors.uiuc_faculty import _is_department_field_text

    assert _is_department_field_text(
        "journalism", _silent_profile("uiuc_faculty", "Department of Media and Cinema Studies",
                                      ["media and cinema studies"]))


def test_the_guard_reads_the_stored_row_s_keywords():
    """Stored text and keywords are the fallback; the fresh row states a topic
    without research text, so the stored text is not carried onto it."""
    existing = _silent_profile("uiuc_faculty", "College of Law", ["law"],
                               research_areas_raw="law", last_verified="2026-10-05T00:00:00")
    incoming = _silent_profile("uiuc_faculty", "College of Law", ["criminal procedure"])
    _carry_forward_enrichment(existing, incoming)
    assert incoming["keywords"] == ["criminal procedure"]
    assert "research_areas_raw" not in incoming["metadata"]


def test_department_field_text_beside_stamped_keywords_is_not_carried():
    existing = _silent_profile("uiuc_faculty", "Department of Health and Kinesiology", ["sarcopenia"],
                               research_areas_raw="health and kinesiology",
                               inferred_fields={"keywords": "derived:openalex_topics"})
    incoming = _silent_profile("uiuc_faculty", "Department of Health and Kinesiology", ["health and kinesiology"])
    _carry_forward_enrichment(existing, incoming)
    assert not incoming["metadata"].get("research_areas_raw")


def test_department_field_text_beside_other_topics_is_still_carried():
    """Until those topics are stamped as ours, the stored field keeps the
    description from saying them as the professor's research areas."""
    existing = _silent_profile("uiuc_faculty", "Department of Health and Kinesiology",
                               ["muscle mass loss", "hemodialysis"],
                               research_areas_raw="health and kinesiology", last_verified="2026-10-05T00:00:00")
    incoming = _silent_profile("uiuc_faculty", "Department of Health and Kinesiology", ["health and kinesiology"])
    _carry_forward_enrichment(existing, incoming)
    assert incoming["metadata"]["research_areas_raw"] == "health and kinesiology"


def test_carry_forward_fresh_email_still_wins():
    existing = {
        "pi_name": "A B", "department": "Computer Science",
        "keywords": ["physics"], "contact_email": "old@colorado.edu",
    }
    incoming = {
        "pi_name": "A B", "department": "Computer Science",
        "keywords": ["physics"], "contact_email": "new@colorado.edu",
    }
    _carry_forward_enrichment(existing, incoming)
    assert incoming["contact_email"] == "new@colorado.edu"


def test_is_junk_keyword_flags_journal_venues():
    for k in ["ieee transactions on image processing", "acta astronautica",
              "science advances", 'reviewer for "physical review letters"',
              "ieee robotics and automation letters", "ieee access", "ieee spectrum"]:
        assert _is_junk_keyword(k), f"{k!r} is a venue, not a research area"


def test_is_junk_keyword_keeps_ieee_protocol_and_standard_areas():
    # Bare "ieee" is only a venue when followed by a publication word; an IEEE
    # standard/protocol is a real research area and must survive (the venue
    # regex used to eat these, and the course-code rule matched "ieee 802").
    for k in ["ieee 802.11 wireless networks", "ieee standards",
              "ieee 754 floating-point arithmetic"]:
        assert not _is_junk_keyword(k), f"{k!r} is a real area, not a venue/course"


def test_is_junk_keyword_keeps_topical_areas():
    for k in ["machine learning", "computer vision", "quantum optics",
              "materials science", "control theory"]:
        assert not _is_junk_keyword(k), f"{k!r} is a real research area"


# DQ-2: recover real keywords from research_areas_raw for broad-only faculty.

def test_clean_research_phrase_keeps_topical():
    assert _clean_research_phrase("Dependent Type Theory") == "dependent type theory"
    assert _clean_research_phrase("AI for Audio") == "ai for audio"
    assert _clean_research_phrase("nanophotonics") == "nanophotonics"
    assert _clean_research_phrase("Vertical cavity surface emitting lasers (VCSELs)") == "vertical cavity surface emitting lasers"


def test_clean_research_phrase_rejects_noise():
    for junk in (
        "Research Areas", "Related News", "Springer", "Plenum", "Function", "Governments",
        "Twitter", "Article 102052", "Entomology - Research - Behavior", "Background",
        "from structural perspectives", "how actin filaments grow", "focusing on software",
        "supporting graduate TAs", "CS 498 SCU", "and freight applications",
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


def test_derive_adds_stated_areas_ahead_of_keywords_the_row_already_had():
    # Three bank substrings ("machine learning", "security") used to block a
    # professor's own stated list for good; the stated areas come first, the
    # earlier keywords survive behind them.
    rows = [_fac_raw(
        "Has Specific", "Department of Physics",
        "Nanophotonics, Biosensing", ["quantum optics"],
    )]
    assert _derive_keywords_from_raw(rows) == 1
    assert rows[0]["keywords"] == ["nanophotonics", "biosensing", "quantum optics"]


def test_derive_leaves_rows_whose_stated_areas_add_nothing():
    rows = [_fac_raw(
        "Already There", "Department of Physics",
        "Quantum Optics, Biosensing", ["biosensing", "quantum optics", "photonics"],
    )]
    assert _derive_keywords_from_raw(rows) == 0
    assert rows[0]["keywords"] == ["biosensing", "quantum optics", "photonics"]


def test_derive_rejects_colleague_names_titles_org_names_and_bare_adjectives():
    # Rows that already carry a keyword tend to have sidebar text for a raw:
    # a co-author's surname, the department's own name, the person's title,
    # a dangling adjective. None of those is a research area.
    rows = [
        _fac_raw("Susan Tolman", "Department of Mathematics",
                 "Symplectic Geometry, Kessler, Department of Mathematics, "
                 "Assistant Research Scientist, Sustainable, Temporal, "
                 "particularly curiosity, University of Wisconsin-Madison, "
                 "Panel Lead, RM Espinosa-Marzal, X Zhang, Mechanical Engineering, "
                 "Mechanical Science and Engineering, Cultures & Linguistics Building, "
                 "Anisotropic, Purdue Univeristy",
                 ["international mathematics research notices"]),
        _fac_raw("Ann Kessler", "Department of Mathematics", "Number Theory", ["number theory"]),
        _fac_raw("Rosa Espinosa Marzal", "Department of Mathematics", "Rheology", ["rheology"]),
        _fac_raw("Wei Zhang", "Department of Mathematics", "Rheology", ["rheology"]),
        _fac_raw("Mech Prof", "Mechanical Science & Engineering", "Tribology", ["tribology"]),
    ]
    _derive_keywords_from_raw(rows)
    assert rows[0]["keywords"] == ["symplectic geometry", "international mathematics research notices"]


def test_derive_never_drops_a_keyword_the_row_had_to_make_room():
    # Eight is the cap for the joined list, and the room is taken from the
    # stated areas, never from what the row already carried.
    six = ["k1 topic", "k2 topic", "k3 topic", "k4 topic", "k5 topic", "k6 topic"]
    eight = six + ["k7 topic", "parallel computing"]
    rows = [
        _fac_raw("Long List", "Department of Physics",
                 "Nanophotonics, Biosensing, Plasmonics, Metamaterials", six),
        _fac_raw("Full Already", "Department of Physics",
                 "Nanophotonics, Biosensing", eight),
        # A stated area the full row already carries must not be cut by the cap
        # on its way back in (Gropp lost "parallel computing" exactly so).
        _fac_raw("Full And Stated", "Department of Physics",
                 "Parallel Computing, Nanophotonics", eight),
    ]
    assert _derive_keywords_from_raw(rows) == 1
    assert rows[0]["keywords"] == ["nanophotonics", "biosensing"] + six
    assert rows[1]["keywords"] == eight
    assert rows[2]["keywords"] == eight


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


def test_is_junk_keyword_catches_publication_venues_and_split_fragments():
    # Profile/Pure "research interest" sections sometimes list publication venues
    # or comma-shatter prose into clauses (caught 2026-06-28 enriching Gies/ACES,
    # which the DQ suite alone did not flag). Neither is a research area.
    for k in ["Journal of Applied Psychology", 'reviewer for "journal of wind engineering"',
              "conference proceedings", "and communities", "to examine emergent behavior",
              "or related fields"]:
        assert _is_junk_keyword(k), k


def test_is_junk_keyword_keeps_areas_brushing_venue_and_connective_rules():
    # A real area may carry "and"/"to" mid-phrase or merely resemble a venue word;
    # only a *leading* connective or the whole word journal/proceedings is junk.
    for k in ["science and technology studies", "atmosphere-to-ocean coupling",
              "journalism", "topology"]:   # 'to'/'journal' only at a word boundary
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
        {"source": "uiuc_faculty", "source_type": "faculty_research",
         "department": "Department of Physics",
         "keywords": ["condensed matter physics", "ceperley@illinois.edu",
                      "(217) 244-0646", "229 loomis laboratory"]},
        {"source": "uiuc_faculty", "source_type": "faculty_research",
         "department": "Department of Physics",
         "keywords": ["327 loomis laboratory", "covey@illinois.edu"]},
    ]
    changed = _strip_furniture_keywords(opps)
    assert changed == 2
    assert opps[0]["keywords"] == ["condensed matter physics"]
    assert opps[1]["keywords"] == [_dept_broad_field("Department of Physics")]
    assert opps[1]["keywords"] == ["physics"]


def test_strip_furniture_keywords_covers_every_faculty_school():
    # The junk patterns are school-agnostic: a gatech_faculty record is cleaned
    # exactly like a uiuc_faculty one, while a non-faculty record (course page
    # with a scraped phone number) is never touched.
    opps = [
        {"source": "gatech_faculty", "source_type": "faculty_research",
         "department": "School of Physics",
         "keywords": ["quantum computing", "(404) 894-5200"]},
        {"source": "uiuc_our_rss", "source_type": "research_listing",
         "keywords": ["(217) 244-0646"]},
    ]
    assert _strip_furniture_keywords(opps) == 1
    assert opps[0]["keywords"] == ["quantum computing"]
    assert opps[1]["keywords"] == ["(217) 244-0646"]


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
        {"source": "uiuc_faculty", "source_type": "faculty_research",
         "pi_name": "Ada Lovelace",
         "department": "Computer Science",
         "title": "Research with Prof. Ada Lovelace — CS",
         "keywords": ["compilers, architecture, and parallel computing",
                      "cs 591 sn - systems and networking seminar"],
         "metadata": {}, "contact_email": "advising@illinois.edu"},
        {"source": "uiuc_faculty", "source_type": "faculty_research",
         "pi_name": "Alan Turing",
         "department": "Computer Science",
         "title": "Research with Prof. Alan Turing — CS",
         "keywords": ["computer vision, object recognition, scene understanding"],
         "metadata": {}, "contact_email": "advising@illinois.edu"},
        {"source": "uiuc_faculty", "source_type": "faculty_research",
         "pi_name": "Grace Hopper",
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

def _fac_email(pi_name, department, email, url, source="uiuc_faculty"):
    return {
        "source": source, "source_type": "faculty_research",
        "pi_name": pi_name, "department": department,
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


def test_null_shared_admin_email_covers_every_faculty_school():
    # A coordinator inbox scraped onto 3 distinct Stanford professors is nulled
    # like a UIUC one; a non-faculty record sharing the address is untouched.
    rows = [
        _fac_email("Alice Adams", "CS", "admissions@cs.stanford.edu", "u/aa", source="stanford_faculty"),
        _fac_email("Bob Brown", "CS", "admissions@cs.stanford.edu", "u/bb", source="stanford_faculty"),
        _fac_email("Carol Clark", "CS", "admissions@cs.stanford.edu", "u/cc", source="stanford_faculty"),
        {"source": "nsf_reu", "source_type": "research_program", "pi_name": "Dana Diaz",
         "contact_email": "admissions@cs.stanford.edu"},
    ]
    assert _null_shared_admin_emails(rows) == 3
    assert all(r["contact_email"] is None for r in rows[:3])
    assert rows[3]["contact_email"] == "admissions@cs.stanford.edu"


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
    assert rows[0]["title"] == "Sasa Misailovic — CS"
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
        "Alexander Schwing — ECE (machine learning, computer vision, robotics)"
    )
    assert "Research areas: machine learning, computer vision, robotics." in \
        rows[0]["description_raw"]
    assert "Research opportunity" not in rows[0]["description_raw"]
    assert "positions in their lab" not in rows[0]["description_raw"]


@pytest.mark.parametrize("method", ["derived:illinois_experts_concepts", "derived:openalex_topics"])
def test_rebuild_does_not_say_inferred_keywords_as_the_profiles_areas(method):
    # M161: Illinois Experts concepts are stamped as inferred; the stored
    # title and description read "Research areas: <concepts>" as stated.
    rows = [{
        "source": "uiuc_faculty", "pi_name": "Ada Example",
        "department": "Department of Animal Sciences",
        "keywords": ["Porcine Sperm", "Oviduct"],
        "metadata": {"faculty_title": "Professor", "inferred_fields": {"keywords": method}},
        "eligibility": {"eligibility_text_raw": "stale"},
    }]
    _rebuild_faculty_title_and_desc(rows)
    assert "(" not in rows[0]["title"]
    for text in (rows[0]["title"], rows[0]["description_raw"], rows[0]["eligibility"]["eligibility_text_raw"]):
        assert "Research areas" not in text and "Oviduct" not in text


def test_strip_pi_name_credential_suffix():
    rows = [
        {"source": "uiuc_faculty", "source_type": "faculty_research", "pi_name": "Helene R Dickel Phd"},
        {"source": "uiuc_faculty", "source_type": "faculty_research", "pi_name": "John Smith MD"},
        {"source": "uiuc_faculty", "source_type": "faculty_research", "pi_name": "Jane Doe"},          # 2 tokens — untouched
        {"source": "uiuc_faculty", "source_type": "faculty_research", "pi_name": "Ada Min Lovelace"},  # real 3-token name
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


def test_llm_keywords_deny_generic_noise(monkeypatch):
    # A thin/administrative page makes the model echo dictionary-of-"research"
    # fragments + an admin duty — all grounded (the words ARE on the page) but
    # carrying zero matching signal. The denylist must drop every one -> [].
    monkeypatch.setattr(
        "backend.lib.llm.chat_completion",
        lambda *a, **k: "systematic investigation, materials and sources, "
        "student success initiatives, research enterprise, mathematics",
    )
    page = (
        "Research the systematic investigation into and study of materials and "
        "sources. Dean for student success initiatives and the research "
        "enterprise. Department of Mathematics."
    )
    assert _llm_research_keywords("administrative bio text", page) == []


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
    rows = [{"source": "uiuc_faculty", "source_type": "faculty_research", "pi_name": "Kathryn Clancy she/her"}]
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


def test_carry_forward_email_needs_no_provenance_to_survive():
    """W7a invariant: provenance (metadata.email_source) is extra information,
    never a survival condition. A legacy committed email with NO stamp is
    carried onto an email-less re-harvest exactly like a stamped one — and no
    stamp is invented for it."""
    existing = {
        "pi_name": "A B", "department": "CS",
        "keywords": ["x"], "contact_email": "legacy@illinois.edu",
        "metadata": {"last_verified": "2026-01-01"},
    }
    incoming = {"pi_name": "A B", "department": "CS", "keywords": [], "metadata": {}}
    _carry_forward_enrichment(existing, incoming)
    assert incoming["contact_email"] == "legacy@illinois.edu"
    assert "email_source" not in incoming["metadata"]


def test_carry_forward_new_profile_page_stamp_travels():
    """The 'profile_page' stamp written by profile_email.apply_emails rides the
    same unconditional carry as the wayback/constructed stamps."""
    existing = {
        "pi_name": "A B", "department": "CS",
        "keywords": ["x"], "contact_email": "found@illinois.edu",
        "metadata": {"email_source": "profile_page"},
    }
    incoming = {"pi_name": "A B", "department": "CS", "keywords": [], "metadata": {}}
    _carry_forward_enrichment(existing, incoming)
    assert incoming["contact_email"] == "found@illinois.edu"
    assert incoming["metadata"]["email_source"] == "profile_page"


class TestATombstoneMeansAReviewActuallyHappened:
    """``identity_bound: False`` is a verdict, not a shrug.

    ``clear_contact_evidence`` documents it as "a collector reviewed this and
    it is NOT bound", and the W7a legacy pass-through in ``contact_visibility``
    reads it exactly that way: a stamped record loses the grandfathering that
    keeps the pre-contract corpus reachable.

    The merge path stamped it whenever a re-scrape produced no claim — including
    the overwhelmingly common case where the committed record never had one
    either, so nothing was reviewed and nothing was rejected. Measured on the
    committed corpus at 8f587a79: of 116,430 records holding a harvested
    address, 104,528 carried the tombstone with NO other evidence field, and
    ZERO carried it alongside one. Every firing was a false positive, and each
    cost a professor their reachability: 10,949 of 116,430 addresses passed
    ``verified_send_target``, so cold email — the product's core step — could
    not reach 90.6% of the people it had addresses for.
    """

    @staticmethod
    def _merge(existing: dict, incoming: dict) -> dict:
        _carry_forward_enrichment(existing, incoming)
        return (incoming.get("metadata") or {})

    def test_no_claim_on_either_side_leaves_the_record_grandfathered(self):
        """Neither side ever carried evidence, so there was nothing to reject."""
        existing = {
            "id": "f1", "pi_name": "A B", "department": "Physics",
            "contact_email": "a.b@uiuc.edu",
            "metadata": {"email_source": "profile_page"},
        }
        incoming = {
            "id": "f1", "pi_name": "A B", "department": "Physics",
            "contact_email": "a.b@uiuc.edu",
            "metadata": {"email_source": "profile_page"},
        }
        assert "identity_bound" not in self._merge(existing, incoming)

    def test_a_real_claim_that_fails_the_identity_match_is_still_tombstoned(self):
        """The case the tombstone was written for keeps working: a collector
        HAD spoken for this address, and the fresh row must not inherit the
        grandfathering that would let it flow unproven."""
        existing = {
            "id": "f2", "pi_name": "C D", "department": "Physics",
            "contact_email": "c.d@uiuc.edu",
            "metadata": {
                "identity_bound": True,
                "email_source": "bound_profile",
                "contact_verified_email": "c.d@uiuc.edu",
                "contact_source_url": "https://physics.uiuc.edu/people/cd",
                "contact_verified_at": "2026-08-01T00:00:00+00:00",
            },
        }
        # No id on the incoming row, so the stable-identity match cannot hold.
        incoming = {
            "pi_name": "C D", "department": "Physics",
            "contact_email": "c.d@uiuc.edu",
            "metadata": {},
        }
        assert self._merge(existing, incoming).get("identity_bound") is False

    def test_partial_evidence_on_the_committed_row_still_tombstones(self):
        """A stamp that never completed is a collector having spoken, and it
        must fail closed rather than fall back to grandfathering."""
        existing = {
            "id": "f3", "pi_name": "E F", "department": "Physics",
            "contact_email": "e.f@uiuc.edu",
            "metadata": {"contact_verified_at": "2026-08-01T00:00:00+00:00"},
        }
        incoming = {
            "id": "f3", "pi_name": "E F", "department": "Physics",
            "contact_email": "e.f@uiuc.edu",
            "metadata": {},
        }
        assert self._merge(existing, incoming).get("identity_bound") is False

    def test_a_new_address_over_an_unstamped_row_is_not_tombstoned(self):
        """A professor who changed address is not a rejection either: the old
        row carried no proof, so there is none to strip and nothing to warn
        about."""
        existing = {
            "id": "f4", "pi_name": "G H", "department": "Physics",
            "contact_email": "old@uiuc.edu",
            "metadata": {"email_source": "profile_page"},
        }
        incoming = {
            "id": "f4", "pi_name": "G H", "department": "Physics",
            "contact_email": "new@uiuc.edu",
            "metadata": {"email_source": "profile_page"},
        }
        assert "identity_bound" not in self._merge(existing, incoming)

    def test_a_new_address_over_a_rejected_and_nulled_row_is_not_tombstoned(self):
        """A verdict needs an address to have been about. ``clear_contact_claim``
        nulls the address in the same breath as it stamps, so a tombstone on an
        address-less row describes one that is gone; the fresh scrape's address
        is a different one nobody reviewed.

        1,093 committed records are in this shape. The 2026-09-03 refresh
        re-harvested an address for one of them, faculty-brown-colt-588aa983,
        and restamped the row's tombstone onto susan_bernstein@brown.edu. That
        row held ``contact_email: None`` for its whole life (first seen
        2026-07-12), so nothing was ever rejected: its ``identity_bound: False``
        is residue from the 2026-08-17 mass-tombstoning, and the merge was
        about to launder it into a verdict on a personal address."""
        existing = {
            "id": "f6", "pi_name": "K L", "department": "Comparative Literature",
            "contact_email": None,
            "metadata": {"identity_bound": False},
        }
        incoming = {
            "id": "f6", "pi_name": "K L", "department": "Comparative Literature",
            "contact_email": "k.l@uiuc.edu",
            "metadata": {},
        }
        assert "identity_bound" not in self._merge(existing, incoming)

    def test_a_new_address_over_a_proven_row_is_tombstoned(self):
        """The proof described the OLD address. It must not follow the new one,
        and the new one must not inherit grandfathering to flow unproven."""
        existing = {
            "id": "f5", "pi_name": "I J", "department": "Physics",
            "contact_email": "old@uiuc.edu",
            "metadata": {
                "identity_bound": True,
                "email_source": "bound_profile",
                "contact_verified_email": "old@uiuc.edu",
                "contact_source_url": "https://physics.uiuc.edu/people/ij",
                "contact_verified_at": "2026-08-01T00:00:00+00:00",
            },
        }
        incoming = {
            "id": "f5", "pi_name": "I J", "department": "Physics",
            "contact_email": "new@uiuc.edu",
            "metadata": {},
        }
        assert self._merge(existing, incoming).get("identity_bound") is False


# ---------------------------------------------------------------------------
# The professor's address, not the college's alumni-relations coordinator
#
# Three UIUC departments — ECE (3/118 contactable), Civil & Environmental
# (0/123) and Nuclear, Plasma & Radiological (0/43) — are the only ones a
# student cannot email; every other UIUC department sits at 79-100%. They share
# one page template whose sidebar lists college staff BEFORE the professor's
# own role card, so "first mailto that isn't known noise" bound a donor
# -relations coordinator's address to every professor in the department. The
# shared-inbox pass then correctly nulled it, and the extraction was never
# fixed — which is why the gap survived.
#
# It lands on exactly the wrong people: those departments supply the top of the
# match list for an engineering student, so the better the match, the less
# likely they could contact them (production top-25 for a UIUC ECE sophomore:
# 1 of 11 faculty contactable, against an 88.6% corpus baseline).
# ---------------------------------------------------------------------------

_ILLINOIS_PROFILE = """
<html><body>
  <div class="col-md column1">
    <p><strong>Nikki Slack</strong><br>Alumni &amp; Donor Relations Coordinator<br>
    <a href="mailto:nslack@illinois.edu">nslack@illinois.edu</a></p>
  </div>
  <div class="col-md column2">
    <p><strong>Heather Vazquez</strong><br>Senior Director of Advancement<br>
    <a href="mailto:hfv@illinois.edu">hfv@illinois.edu</a></p>
  </div>
  <div><div class="role cat15 primary">
    <div class="title"><strong>Professor</strong></div>
    <div class="email"><a href="mailto:jhasegaw@illinois.edu">jhasegaw@illinois.edu</a></div>
    <div class="office">2011 Beckman Institute</div>
  </div></div>
  <footer><a href="mailto:grainger-marcom@illinois.edu">Webmaster</a></footer>
</body></html>
"""


def _enrich_with_page(monkeypatch, html, person=None):
    from bs4 import BeautifulSoup

    import src.collectors.uiuc_faculty as f
    monkeypatch.setattr(f.time, "sleep", lambda *_: None)
    monkeypatch.setattr(f, "_fetch_soup", lambda url: BeautifulSoup(html, "html.parser"))
    return f._enrich_faculty_from_profile(
        dict(person or {"pi_name": "Mark Hasegawa-Johnson",
                        "url": "https://ece.illinois.edu/about/directory/faculty/jhasegaw"})
    )


def test_the_professors_own_role_card_wins_over_the_staff_sidebar(monkeypatch):
    assert _enrich_with_page(monkeypatch, _ILLINOIS_PROFILE)["email"] == "jhasegaw@illinois.edu"


def test_a_staff_address_is_never_bound_to_a_professor(monkeypatch):
    # Stated separately from the line above because it is the harm, not the
    # mechanism: nslack@ on 118 ECE records is one person's inbox wearing 118
    # professors' names, and a student emailing it reaches none of them.
    got = _enrich_with_page(monkeypatch, _ILLINOIS_PROFILE)["email"]
    assert got not in {"nslack@illinois.edu", "hfv@illinois.edu",
                       "grainger-marcom@illinois.edu"}


def test_pages_without_a_role_card_still_use_the_first_mailto(monkeypatch):
    # Statistics, Math and iSchool profiles carry no role card and their first
    # mailto is already the right person. Verified live on real profile URLs
    # before this change: where a role card DOES exist (Physics, MechSE,
    # Bioengineering) it agrees with what the corpus already holds, so this
    # only ever changes the three departments the sidebar was shadowing.
    page = '<html><body><a href="mailto:sahlgren@illinois.edu">x</a></body></html>'
    assert _enrich_with_page(monkeypatch, page)["email"] == "sahlgren@illinois.edu"


def test_a_role_card_without_an_email_falls_through(monkeypatch):
    page = ('<html><body><div class="role primary"><div class="title">Professor</div></div>'
            '<a href="mailto:someone@illinois.edu">x</a></body></html>')
    assert _enrich_with_page(monkeypatch, page)["email"] == "someone@illinois.edu"


def test_an_already_known_email_is_not_overwritten(monkeypatch):
    person = {"pi_name": "X", "url": "http://x", "email": "already@illinois.edu"}
    assert _enrich_with_page(monkeypatch, _ILLINOIS_PROFILE, person)["email"] == "already@illinois.edu"


def _seen(pi_name, url, last_seen, keywords=(), metadata_extra=None):
    meta = {"last_seen_at": last_seen, "is_active": True}
    meta.update(metadata_extra or {})
    return {
        "source": "uiuc_faculty",
        "source_type": "faculty_research",
        "id": f"faculty-test-{pi_name.lower().replace(' ', '-')}",
        "pi_name": pi_name,
        "source_url": url,
        "url": url,
        "department": "Department of Physics",
        "keywords": list(keywords),
        "metadata": meta,
    }


_PROFILE = "https://physics.illinois.edu/people/directory/profile/jcovey"


def test_dedup_moves_the_newest_sighting_onto_the_kept_row():
    stored = _seen("Jacob P. Covey", _PROFILE, "2026-07-27T07:34:46",
                   keywords=["cold atom physics", "quantum computing"])
    fresh = _seen("Jacob Covey", _PROFILE, "2026-08-24T06:20:11")
    out = _dedup_faculty_records([stored, fresh])
    assert [o["pi_name"] for o in out] == ["Jacob P. Covey"]
    assert out[0]["metadata"]["last_seen_at"] == "2026-08-24T06:20:11"


def test_dedup_never_backdates_the_kept_row():
    stored = _seen("Jacob P. Covey", _PROFILE, "2026-08-24T06:20:11",
                   keywords=["cold atom physics", "quantum computing"])
    stale = _seen("Jacob Covey", _PROFILE, "2026-07-27T07:34:46")
    out = _dedup_faculty_records([stored, stale])
    assert out[0]["metadata"]["last_seen_at"] == "2026-08-24T06:20:11"


def test_dedup_lifts_a_retirement_the_new_sighting_disproves():
    retired = _seen(
        "Jacob P. Covey", _PROFILE, "2026-07-27T07:34:46",
        keywords=["cold atom physics", "quantum computing"],
        metadata_extra={
            "is_active": False,
            "deactivated_at": "2026-08-10",
            "deactivation_reason": "absent_from_directory_rescrape",
        },
    )
    fresh = _seen("Jacob Covey", _PROFILE, "2026-08-24T06:20:11")
    out = _dedup_faculty_records([retired, fresh])
    meta = out[0]["metadata"]
    assert meta["is_active"] is True
    assert "deactivated_at" not in meta
    assert "deactivation_reason" not in meta


def test_dedup_keeps_a_retirement_the_dropped_row_agrees_with():
    retired = _seen(
        "Jacob P. Covey", _PROFILE, "2026-07-27T07:34:46",
        keywords=["cold atom physics", "quantum computing"],
        metadata_extra={
            "is_active": False,
            "deactivated_at": "2026-08-10",
            "deactivation_reason": "absent_from_directory_rescrape",
        },
    )
    also_gone = _seen("Jacob Covey", _PROFILE, "2026-08-24T06:20:11",
                      metadata_extra={"is_active": False})
    out = _dedup_faculty_records([retired, also_gone])
    assert out[0]["metadata"]["is_active"] is False
    assert out[0]["metadata"]["last_seen_at"] == "2026-08-24T06:20:11"


def test_dedup_tolerates_a_row_with_no_usable_sighting():
    stored = _seen("Jacob P. Covey", _PROFILE, "2026-07-27T07:34:46",
                   keywords=["cold atom physics", "quantum computing"])
    broken = _seen("Jacob Covey", _PROFILE, "not-a-timestamp")
    out = _dedup_faculty_records([stored, broken])
    assert out[0]["metadata"]["last_seen_at"] == "2026-07-27T07:34:46"


def test_email_dedup_moves_the_newest_sighting_too():
    stored = _seen("Jacob P. Covey", _PROFILE, "2026-07-27T07:34:46",
                   keywords=["cold atom physics", "quantum computing"])
    fresh = _seen("Jacob Covey", "https://mrl.illinois.edu/people/covey",
                  "2026-08-24T06:20:11")
    stored["contact_email"] = fresh["contact_email"] = "jcovey@illinois.edu"
    out = _dedup_faculty_by_email([stored, fresh])
    assert [o["pi_name"] for o in out] == ["Jacob P. Covey"]
    assert out[0]["metadata"]["last_seen_at"] == "2026-08-24T06:20:11"


def test_a_professor_seen_this_run_is_never_proposed_for_retirement():
    """The whole point of the carry: dedup feeds deactivate_stale_faculty."""
    from datetime import date

    from src.normalizers.deactivate_stale_faculty import deactivate_stale_faculty

    stored = _seen("Jacob P. Covey", _PROFILE, "2026-07-27T07:34:46",
                   keywords=["cold atom physics", "quantum computing"])
    fresh = _seen("Jacob Covey", _PROFILE, "2026-08-24T06:20:11")
    peers = [
        _seen(f"Peer {i} Physicist",
              f"https://physics.illinois.edu/people/directory/profile/p{i}",
              "2026-08-24T06:20:11")
        for i in range(19)
    ]
    corpus = _dedup_faculty_records([stored, fresh] + peers)
    result = deactivate_stale_faculty(
        corpus,
        {"uiuc_faculty": {"Department of Physics": len(corpus)}},
        today=date(2026, 8, 24),
        held_sources={"uiuc_faculty"},
    )
    assert result["would_deactivate"] == []
    assert result["newly_deactivated"] == 0


def test_research_areas_stop_at_page_chrome_and_never_cut_mid_token():
    # Verbatim from the corpus, 2026-09-02: what the marker path stored for
    # Hanghang Tong and Ram Alagappan.
    from src.collectors.uiuc_faculty import _trim_research_areas

    tong = ("Large scale data mining and machine learning, especially for graph and multimedia "
            "data with applications to social networks analysis, healthcare, cyber-security and "
            "e-commerce., Research Areas, Artificial Intelligence, Data and Information Systems, "
            "Recent Courses Taught, CS 412 CSP (CS 412 P3, CS 41")
    out = _trim_research_areas(tong)
    assert "Recent Courses Taught" not in out and "CS 41" not in out
    assert "Research Areas" not in out.split(", ")
    assert out.endswith(("e-commerce.", "Data and Information Systems"))
    assert "Artificial Intelligence" in out

    alagappan = ("Storage systems, Distributed systems, Operating systems, Research Areas, Systems and "
                 "Networking, Teaching Honors, List of Teachers Ranked as Excellent, CS598: Storage Systems")
    assert _trim_research_areas(alagappan) == \
        "Storage systems, Distributed systems, Operating systems, Systems and Networking"

    # the cap lands on an item boundary, not inside one
    long = ", ".join(f"topic number {i:02d}" for i in range(40))
    capped = _trim_research_areas(long, 300)
    assert len(capped) <= 300 and not capped.endswith((" ", ",")) and capped.split(", ")[-1].startswith("topic number")


def test_an_oxford_comma_fragment_is_the_area_without_its_conjunction():
    from src.collectors.uiuc_faculty import _trim_research_areas

    assert _trim_research_areas("Signal processing, and acoustics, Remote sensing, & imaging") == \
        "Signal processing, acoustics, Remote sensing, imaging"


def test_research_areas_marker_path_drops_the_sections_that_follow():
    from bs4 import BeautifulSoup

    from src.collectors.uiuc_faculty import _research_areas_from_soup

    html = """<html><body><h2>Research Interests</h2>
    <p>Storage systems</p><p>Distributed systems</p>
    <h2>Research Areas</h2><p>Systems and Networking</p>
    <h2>Recent Courses Taught</h2><p>CS 598: Storage Systems</p><p>CS 423</p>
    </body></html>"""
    out = _research_areas_from_soup(BeautifulSoup(html, "html.parser"))
    assert out == "Storage systems, Distributed systems, Systems and Networking", out


def test_a_name_is_cleaned_for_every_school_not_just_uiuc():
    """The rule was gated on source == 'uiuc_faculty' while the greeting it
    protects is school-agnostic, so 509 of the 513 professors carrying a
    credential — every one outside UIUC — were addressed "Dear Professor
    Megan Kobel, PhD, AuD,". _is_faculty_record is the gate every other
    school-agnostic pass in this file already uses."""
    rows = [
        {"source": "pitt_faculty", "source_type": "faculty_research",
         "pi_name": "Megan Kobel, PhD, AuD"},
        {"source": "uiuc_faculty", "source_type": "faculty_research",
         "pi_name": "Adina Cox PhD"},
        {"source": "simplify_internships", "source_type": "internship",
         "pi_name": "Acme Corp, Inc"},
    ]
    assert _strip_pi_name_credentials(rows) == 2
    assert rows[0]["pi_name"] == "Megan Kobel"
    assert rows[1]["pi_name"] == "Adina Cox"
    assert rows[2]["pi_name"] == "Acme Corp, Inc"


def test_cleaning_a_name_never_eats_a_surname():
    """Ma, Ng and Ho are surnames AND degree abbreviations. Stripping them
    unconditionally cost 123 professors their surname in an early draft of
    this rule, so an ambiguous token needs a comma to introduce it."""
    for name in ("Xiaolong Ma", "Chao Ma", "Shewry, Teresa", "Mark S. Massa, S.J.",
                 "Thomas H. Welsh, Jr", "Jay Stauffer, Jr."):
        assert clean_pi_name(name) == name, name


def test_cleaning_a_name_strips_what_a_letter_should_not_carry():
    assert clean_pi_name("Elise N. Erickson PhD CNM FACNM") == "Elise N. Erickson"
    assert clean_pi_name("Erica Hansen, AuD, CCC-A, F-AAA") == "Erica Hansen"
    assert clean_pi_name("Michelle O'Malley (she/her/hers)") == "Michelle O'Malley"
    assert clean_pi_name("Kiera James PhD »") == "Kiera James"
    assert clean_pi_name("Ashby  Fox") == "Ashby Fox"
    # A comma may introduce an ambiguous one; a bare surname may not.
    assert clean_pi_name("Megan Kobel, MS") == "Megan Kobel"


def test_dedup_decredentialed_faculty_collapses_one_person_keeping_the_email():
    """Stripping "PhD" can reveal that two rows were always one professor."""
    opps = [
        {
            "id": "a", "school": "ucla", "source_type": "faculty_research",
            "source_url": "https://snaoz.astro.ucla.edu/index.html",
            "pi_name": "Smadar Naoz",
        },
        {
            "id": "b", "school": "ucla", "source_type": "faculty_research",
            "source_url": "https://snaoz.astro.ucla.edu/index.html",
            "pi_name": "Smadar Naoz", "contact_email": "snaoz@astro.ucla.edu",
        },
    ]
    kept, dropped = _dedup_decredentialed_faculty(opps)
    assert dropped == 1
    assert [o["id"] for o in kept] == ["b"]


def test_dedup_decredentialed_faculty_keeps_namesakes_on_a_listing_page():
    """Most collectors point a whole department at one URL, so a shared surname
    there is two different people. Only the full name may collapse a row."""
    opps = [
        {
            "id": "a", "school": "asu", "source_type": "faculty_research",
            "source_url": "https://sms.asu.edu/People/Faculty", "pi_name": "Wei Wang",
        },
        {
            "id": "b", "school": "asu", "source_type": "faculty_research",
            "source_url": "https://sms.asu.edu/People/Faculty", "pi_name": "Xu Wang",
        },
    ]
    kept, dropped = _dedup_decredentialed_faculty(opps)
    assert dropped == 0
    assert len(kept) == 2


# --- Atmospheric Sciences and Earth Science moved hosts. The 2026-10-12 and
# 10-19 refreshes read zero rows from them (and on 10-19 from iSchool) because
# the list fetch failed TLS verification on the runner, not because a page
# changed shape: atmos.illinois.edu and geology.illinois.edu share a host whose
# certificate had lapsed on 10-12, and on 10-19 the runner's certifi 2026.10.18
# lacked the emSign root that host's and iSchool's InCommon chain ends at. Both
# old addresses now redirect to climas.illinois.edu / esec.illinois.edu, which
# have their own certificates. The page fixtures are trimmed copies of the three
# list pages saved 2026-10-22, every address replaced by a placeholder. ---

UIUC_FIXTURES = Path(__file__).parent / "fixtures" / "uiuc"
MOVED_UNIT_PAGES = {
    "https://climas.illinois.edu/directory/faculty": "climas_faculty.html",
    "https://esec.illinois.edu/directory/faculty": "esec_faculty.html",
    "https://ischool.illinois.edu/people/faculty": "ischool_faculty.html",
}
# The id and name of every row these three units held in
# data/processed/shards/uiuc.json after the 2026-10-05 refresh, the last one
# that read them. A refresh writes today's row back, so these tests read the
# ids from this frozen copy, never from the shard.
MOVED_UNITS_STORED = {r["id"]: r["pi_name"] for r in json.loads(
    (UIUC_FIXTURES / "stored_faculty.json").read_text(encoding="utf-8"))}
# Stored iSchool rows whose person today's page does not list: three last seen
# 2026-07-27 and two already inactive.
ISCHOOL_NOT_LISTED = {
    "faculty-ischool-31477607", "faculty-ischool-8e4c484c", "faculty-ischool-ef0622f9",
    "faculty-ischool-0f911cb7", "faculty-ischool-109aa653",
}


@pytest.fixture
def moved_units(monkeypatch) -> dict[str, list[dict]]:
    import src.collectors.uiuc_faculty as f

    def fetch(url):
        name = MOVED_UNIT_PAGES.get(url)
        return BeautifulSoup((UIUC_FIXTURES / name).read_text(encoding="utf-8"),
                             "html.parser") if name else None

    monkeypatch.setattr(f, "_fetch_soup", fetch)
    monkeypatch.setattr(f, "_scrape_individual_page_keywords", lambda url: [])
    return {key: f.fetch_department(key, enrich=False)
            for key in ("atmos", "geology", "ischool")}


def _stored_ids(short: str) -> set[str]:
    return {i for i in MOVED_UNITS_STORED if i.startswith(f"faculty-{short.lower()}-")}


def test_atmos_and_geology_read_the_hosts_their_old_addresses_redirect_to():
    assert {k: (DEPARTMENTS[k]["url"], DEPARTMENTS[k]["base"], DEPARTMENTS[k]["short"])
            for k in ("atmos", "geology")} == {
        "atmos": ("https://climas.illinois.edu/directory/faculty",
                  "https://climas.illinois.edu", "Atmos"),
        "geology": ("https://esec.illinois.edu/directory/faculty",
                    "https://esec.illinois.edu", "Geology"),
    }


def test_atmos_carries_the_name_its_site_now_gives_itself():
    from src.collectors.uiuc_experts import TARGET_DEPARTMENTS

    for key, page in (("atmos", "climas_faculty.html"), ("geology", "esec_faculty.html")):
        site = BeautifulSoup((UIUC_FIXTURES / page).read_text(encoding="utf-8"), "html.parser")
        assert DEPARTMENTS[key]["name"] == site.select_one('a[slot="site-name"]').get_text(strip=True)
        # The monthly Illinois Experts pass selects rows by this exact string.
        assert DEPARTMENTS[key]["name"] in TARGET_DEPARTMENTS


def test_every_stored_professor_the_moved_pages_list_keeps_their_id(moved_units):
    for key, missing in (("atmos", set()), ("geology", set()), ("ischool", ISCHOOL_NOT_LISTED)):
        stored = _stored_ids(DEPARTMENTS[key]["short"])
        fresh = {r["id"]: r["pi_name"] for r in moved_units[key]}
        assert missing <= stored
        assert stored - set(fresh) == missing, key
        assert {i: fresh[i] for i in stored - missing} == {
            i: MOVED_UNITS_STORED[i] for i in stored - missing}


def test_the_moved_units_read_every_person_their_pages_list(moved_units):
    atmos, geology, ischool = (moved_units[k] for k in ("atmos", "geology", "ischool"))
    # Lei Zhao is listed under Affiliate and again under Adjunct Faculty.
    assert (len(atmos), len({r["id"] for r in atmos})) == (39, 38)
    assert len(geology) == 21
    assert len(ischool) == 78
    for rows, host in ((atmos, "https://climas.illinois.edu/directory/profile/"),
                       (geology, "https://esec.illinois.edu/directory/profile/")):
        assert all(r["url"].startswith(host) and r["contact_email"] for r in rows)
    assert {r["department"] for r in atmos} == {
        "Department of Climate, Meteorology & Atmospheric Sciences"}
    assert not {"Dean's Cabinet", "Adjuncts & Affiliates", "Doctoral Students",
                "Committees"} & {r["pi_name"] for r in ischool}
    assert missing_departments([*atmos, *geology, *ischool],
                               departments=["atmos", "geology", "ischool"]) == []


def test_the_people_new_to_atmos_and_geology_are_stored_under_other_departments(moved_units):
    """Each of these shares an address and a surname with a row another UIUC
    department already holds (Proistosescu under Geology, Fouke under IB,
    Killeen under ECE, Lombardo and Zhao under CEE, Trujillo-Falcón under
    Communication), so the email dedup keeps one row per person."""
    new = {key: {r["pi_name"] for r in moved_units[key]
                 if r["id"] not in _stored_ids(DEPARTMENTS[key]["short"])}
           for key in ("atmos", "geology")}
    assert new == {
        "atmos": {"Cristian Proistosescu", "Joseph Trujillo-Falcón", "Franklin Lombardo",
                  "Lei Zhao", "Timothy Killeen"},
        "geology": {"Bruce W Fouke"},
    }


# --- M143: CLIMAS and ESEC (Illinois DirectoryCore) titles and research areas.
# Every person on these directories was stored as "Professor" because the card
# title selector named a class no card carries, and 37 of their 53 rows stored
# the site's header menu as research areas: the profile pages match none of the
# research selectors, so the "Research Areas" text marker was searched on the
# whole page and first found the menu link of that name. ---

def _card_titles(page: str) -> list[str]:
    soup = BeautifulSoup((UIUC_FIXTURES / page).read_text(encoding="utf-8"), "html.parser")
    out = []
    for card in soup.select("article.profile-card"):
        el = card.select_one("div.field-name-field-dircore-appt-title .field__item")
        out.append(el.get_text(strip=True) if el else None)
    return out


def test_directorycore_cards_give_each_person_the_title_their_card_states(moved_units):
    for key, page in (("atmos", "climas_faculty.html"), ("geology", "esec_faculty.html")):
        titles = [r["metadata"]["faculty_title"] for r in moved_units[key]]
        # One card has no title field; it gets none.
        assert titles == [t or "" for t in _card_titles(page)], key
    atmos = Counter(r["metadata"]["faculty_title"] for r in moved_units["atmos"])
    geology = Counter(r["metadata"]["faculty_title"] for r in moved_units["geology"])
    assert atmos["Professor Emeritus"] == 3 and atmos["Director Emeritus"] == 1
    assert atmos["Harry E. Preble Professor Emeritus"] == 1
    assert {"Lecturer", "Senior Lecturer", "Geochemistry Lab Coordinator"} <= set(geology)


def _directorycore_profile(main_fields: str) -> BeautifulSoup:
    """A DirectoryCore profile page: the site header menu links "Research Areas"
    and its entries, then the person's fields inside <main>."""
    return BeautifulSoup(f"""<html><body><ilw-page><ilw-header><ilw-header-menu><ul>
      <li><ilw-header-menu-section><a href="/research">Research</a><ul>
        <li><a href="/research/areas">Research Areas</a></li>
        <li><a href="/research/equipment">Research Equipment</a></li>
        <li><a href="/research/undergraduate">Undergraduate Research</a></li>
      </ul></ilw-header-menu-section></li>
      <li><ilw-header-menu-section><a href="/resources">Resources</a><ul>
        <li><a href="/about">About the Department</a></li>
      </ul></ilw-header-menu-section></li>
    </ul></ilw-header-menu></ilw-header>
    <main id="main-content"><article class="profile fixed-width">
      <h1>Person Example</h1>
      <div class="field field-name-field-dircore-appt-title"><div class="field__item">Professor</div></div>
      {main_fields}
      <div class="field field-name-field-dircore-biography"><h2 class="profile-label">Biography</h2>
        <p>Studies clouds.</p></div>
    </article></main></ilw-page></body></html>""", "html.parser")


def test_a_directorycore_profile_gives_its_research_fields_never_its_menu():
    areas = """<div class="field field-name-field-dircore-research-areas">
      <h2 class="profile-label">Research Areas</h2>
      <div class="field__items"><div class="field__item"><a href="/research/areas/aerosols">Aerosols</a></div>
      <div class="field__item"><a href="/research/areas/cloud-physics">Cloud Physics</a></div></div></div>"""
    interests = """<div class="field field-name-field-dircore-rinterests">
      <h2 class="profile-label">Research Interests</h2>
      <div class="field__item"><p>aerosol mixing state</p><p>particle-resolved modelling</p></div></div>"""
    assert _research_areas_from_soup(_directorycore_profile(areas)) == "Aerosols, Cloud Physics"
    assert _research_areas_from_soup(_directorycore_profile(areas + interests)) == \
        "aerosol mixing state, particle-resolved modelling"
    # A profile with neither field states no research areas; the menu entries
    # after the "Research Areas" link are not read as its areas, and a heading
    # of that name in the page body is read in the link's place.
    assert _research_areas_from_soup(_directorycore_profile("")) == ""
    assert _research_areas_from_soup(_directorycore_profile(
        "<h2>Research Areas</h2><p>Mesoscale meteorology</p>")) == "Mesoscale meteorology"


def test_a_research_heading_is_still_read_when_the_menu_also_links_one():
    page = _directorycore_profile(
        "<h2>Research Interests</h2><p>Severe convective storms</p><p>Radar meteorology</p>"
        "<h2>Courses Taught</h2><p>ATMS 100</p>")
    assert _research_areas_from_soup(page) == "Severe convective storms, Radar meteorology"


def test_each_directorycore_research_field_is_read_by_its_own_selector():
    # The office line after the field is no section title, so a text-marker
    # scan from the field's heading would run on into it.
    office = """<div class="field field-name-field-dircore-office"><div class="field__item">3074 Example Hall</div></div>"""
    areas = """<div class="field field-name-field-dircore-research-areas">
      <h2 class="profile-label">Research Areas</h2>
      <div class="field__items"><div class="field__item"><a href="/research/areas/aerosols">Aerosols</a></div>
      <div class="field__item"><a href="/research/areas/cloud-physics">Cloud Physics</a></div></div></div>"""
    interests = """<div class="field field-name-field-dircore-rinterests">
      <h2 class="profile-label">Research Interests</h2>
      <div class="field__item"><p>aerosol mixing state</p><p>particle-resolved modelling</p></div></div>"""
    assert _research_areas_from_soup(_directorycore_profile(areas + office)) == "Aerosols, Cloud Physics"
    assert _research_areas_from_soup(_directorycore_profile(interests + office)) == \
        "aerosol mixing state, particle-resolved modelling"


def test_a_heading_that_is_its_own_anchor_or_an_in_page_toggle_is_still_a_title():
    for heading in ('<h3><a name="ri">Research Interests</a></h3>',
                    '<a href="#ri" class="accordion-toggle">Research Interests</a>'):
        page = _directorycore_profile(
            heading + '<div id="ri"><p>Neural coding</p><p>Decision making</p></div>'
            "<h2>Courses Taught</h2><p>ATMS 100</p>")
        assert _research_areas_from_soup(page) == "Neural coding, Decision making", heading


def test_stored_site_menu_text_is_not_carried_onto_a_fresh_row():
    for menu in ("Research Equipment, Undergraduate Research",
                 "Labs & Facilities, Field Research, Related Research Programs, Colloquium, "
                 "Directions to the Department & Colloquia, Undergraduate Research"):
        existing = {"pi_name": "A B", "department": "Department of Example",
                    "metadata": {"research_areas_raw": menu, "last_verified": "2026-10-05T06:00:00"}}
        incoming = {"pi_name": "A B", "department": "Department of Example",
                    "metadata": {"research_areas_raw": ""}}
        _carry_forward_enrichment(existing, incoming)
        assert incoming["metadata"]["research_areas_raw"] == ""
        assert "research_areas_verified_at" not in incoming["metadata"]


def test_a_stated_research_line_with_a_menu_word_in_it_is_still_carried():
    line = "Sediment transport, Field Research, Undergraduate Research"
    existing = {"pi_name": "A B", "department": "Department of Example",
                "metadata": {"research_areas_raw": line, "last_verified": "2026-10-05T06:00:00"}}
    incoming = {"pi_name": "A B", "department": "Department of Example", "metadata": {}}
    _carry_forward_enrichment(existing, incoming)
    assert incoming["metadata"]["research_areas_raw"] == line
    assert incoming["metadata"]["research_areas_verified_at"] == "2026-10-05T06:00:00"


# --- M150: before M143's marker read skipped link text, a profile with no
# research field of its own stored what its site header menu lists after the
# "Research Areas" link: a run of site sections (Economics, Statistics,
# Mathematics, Political Science, History) or the unit's whole research-area
# menu (Siebel School, ECE, Aerospace, NPRE, ChBE). M143 reads no menu any
# more, but every stored run was carried onto the fresh row of a person whose
# profile states nothing. Synthetic units' menus, people and addresses. ---

_SECTION_MENU = ('<li><a href="/research/areas">Research Areas</a></li>'
                 '<li><a href="/research/centers">Example Research Centers</a></li>'
                 '<li><a href="/research/undergraduate">Undergraduate Research</a></li>')
_UNIT_AREAS = ("Algorithms and Theory", "Artificial Intelligence", "Computer Systems", "Data Science",
               "Example Computing", "Human-Computer Interaction", "Programming Languages",
               "Scientific Computing", "Security and Privacy")
_AREA_MENU = ('<li><a href="/research/areas">Research Areas</a><ul>' + "".join(
    f'<li><a href="/research/areas/{i}">{area}</a></li>' for i, area in enumerate(_UNIT_AREAS)) + "</ul></li>")
# What the old read stored: the eight lines after the menu link.
_WHOLE_AREA_MENU = ", ".join(_UNIT_AREAS[:8])


def _menu_page(menu: str, body: str, main: bool = True) -> str:
    """A page of a unit site: its header menu (``menu`` under "Research"), then ``body``."""
    header = f"""<header><nav><ul>
      <li class="dropdown"><a href="/research">Research</a><ul>{menu}</ul></li>
      <li class="dropdown"><a href="/people">People</a><ul><li><a href="/people/faculty">Faculty</a></li></ul></li>
    </ul></nav></header>"""
    return (f"<html><body>{header}<main id='main-content'>{body}</main></body></html>" if main
            else f"<html><body>{header}<div class='view-content'>{body}</div></body></html>")


def _fetch_unit(monkeypatch, key: str, menu: str, people: list[tuple[str, str]],
                profiles: dict[str, str] | None = None, main: bool = True, intro: str = "") -> list[dict]:
    """The unit's list page lists ``people`` ((slug, name)) after ``intro``; with
    ``profiles`` the run reads each person's profile page ({slug: fields in its main})."""
    import src.collectors.uiuc_faculty as f

    cfg = DEPARTMENTS[key]
    cards = "".join(
        _section_card(slug, name, "Professor") if main else
        f'<div class="directory-item"><h3><a href="/directory/profile/{slug}">{name}</a></h3>'
        f'<a href="mailto:{slug}@illinois.edu">{slug}@illinois.edu</a></div>'
        for slug, name in people)

    def fetch(url):
        if url == cfg["url"]:
            return BeautifulSoup(_menu_page(menu, "<h1>Faculty</h1>" + intro + cards, main), "html.parser")
        slug = url.rsplit("/", 1)[-1]
        if profiles is not None and slug in profiles and url == f"{cfg['base']}/directory/profile/{slug}":
            return BeautifulSoup(_menu_page(menu, f"<h1>Profile</h1>{profiles[slug]}"), "html.parser")
        return None

    monkeypatch.setattr(f, "_fetch_soup", fetch)
    monkeypatch.setattr(f, "_scrape_individual_page_keywords", lambda url: [])
    monkeypatch.setattr(f, "DELAY", 0)
    return f.fetch_department(key, enrich=profiles is not None)


def _stored_unit_row(key: str, name: str, slug: str, areas: str, keywords: list[str]) -> dict:
    """The row the 2026-10-05 refresh stored for this person."""
    cfg = DEPARTMENTS[key]
    row = normalize_faculty({"name": name, "email": f"{slug}@illinois.edu", "research_areas": areas,
                             "url": f"{cfg['base']}/directory/profile/{slug}"}, cfg, keywords=keywords)
    row["metadata"].update(last_seen_at="2026-10-05T14:18:05", last_verified="2026-10-05T14:18:05",
                           first_seen_at="2026-01-10T00:00:00")
    return row


def test_a_stored_site_menu_is_not_carried_when_the_profile_states_no_research(tmp_path, monkeypatch):
    # Political Science: the profile has no research field, so the fresh row
    # states none and the stored menu was carried onto it.
    for main in (True, False):
        stored = [_stored_unit_row("polisci", "Avery Example", "person1",
                                   "Example Research Centers, Undergraduate Research", ["political science"])]
        fresh = _fetch_unit(monkeypatch, "polisci", _SECTION_MENU, [("person1", "Avery Example")],
                            profiles={"person1": "<div class='field field-name-field-dircore-office'>"
                                                 "<div class='field__item'>101 Example Hall</div></div>"},
                            main=main)
        row = _merge(tmp_path, stored, fresh)["Avery Example"]
        assert row["metadata"]["research_areas_raw"] == "", main
        assert "research_areas_verified_at" not in row["metadata"]
        assert "_site_menu_areas" not in row["metadata"]


def test_site_menu_entries_come_out_of_a_stored_value_and_the_persons_own_items_stay(tmp_path, monkeypatch):
    # Economics' stored menu held one entry M143's label list knows and others
    # it does not, so M143 carried the whole value.
    mixed = _stored_unit_row("econ", "Blair Sample", "person2",
                             "Labor Economics, Example Research Centers, Undergraduate Research",
                             ["labor economics", "economics"])
    mixed["metadata"]["research_areas_verified_at"] = "2026-08-20T06:00:00"
    stored = [
        _stored_unit_row("econ", "Avery Example", "person1",
                         "Example Research Centers, Undergraduate Research", ["economics"]),
        mixed,
    ]
    fresh = _fetch_unit(monkeypatch, "econ", _SECTION_MENU,
                        [("person1", "Avery Example"), ("person2", "Blair Sample")])
    rows = _merge(tmp_path, stored, fresh)
    assert rows["Avery Example"]["metadata"]["research_areas_raw"] == ""
    blair = rows["Blair Sample"]
    assert blair["metadata"]["research_areas_raw"] == "Labor Economics"
    # The person's own item keeps the day it was observed.
    assert blair["metadata"]["research_areas_verified_at"] == "2026-08-20T06:00:00"
    assert "labor economics" in blair["keywords"]


def test_a_departments_whole_research_area_menu_is_not_stored_as_a_persons_areas(tmp_path, monkeypatch):
    menu_words = ["algorithms and theory", "artificial intelligence", "computer systems", "data science"]
    gone = _stored_unit_row("cs", "Blair Sample", "person2", _WHOLE_AREA_MENU, menu_words)
    gone["metadata"]["research_areas_verified_at"] = "2026-08-20T06:00:00"
    stored = [
        _stored_unit_row("cs", "Avery Example", "person1", _WHOLE_AREA_MENU, menu_words),
        gone,  # not listed this run
        # Keywords another source gave the person stay with them.
        _stored_unit_row("cs", "Casey Placeholder", "person3", _WHOLE_AREA_MENU,
                         ["Artificial Intelligence", "Neural Network Pruning"]),
    ]
    fresh = _fetch_unit(monkeypatch, "cs", _AREA_MENU,
                        [("person1", "Avery Example"), ("person3", "Casey Placeholder")],
                        profiles={"person1": "", "person3": ""})
    rows = _merge(tmp_path, stored, fresh)
    avery = rows["Avery Example"]
    assert avery["metadata"]["research_areas_raw"] == ""
    assert avery["keywords"] == ["computer science"]
    assert "intelligence" not in avery["title"].lower() + avery["description_clean"].lower()
    assert rows["Blair Sample"]["metadata"]["research_areas_raw"] == ""
    assert "research_areas_verified_at" not in rows["Blair Sample"]["metadata"]
    assert rows["Blair Sample"]["keywords"] == ["computer science"]
    casey = rows["Casey Placeholder"]
    assert casey["metadata"]["research_areas_raw"] == ""
    assert casey["keywords"] == ["Artificial Intelligence", "Neural Network Pruning"]
    assert all("_site_menu_areas" not in r["metadata"] for r in rows.values())


def test_a_persons_own_research_line_and_list_of_department_areas_are_kept(tmp_path, monkeypatch):
    own_list = "Artificial Intelligence, Security and Privacy"
    line = "Sediment transport modelling, River ecology"
    stored = [
        _stored_unit_row("cs", "Avery Example", "person1", own_list, ["artificial intelligence"]),
        _stored_unit_row("cs", "Blair Sample", "person2", line, ["computer science"]),
        _stored_unit_row("cs", "Casey Placeholder", "person3", _WHOLE_AREA_MENU, ["computer science"]),
    ]
    whole_section = "<h2>Research Areas</h2><ul>" + "".join(f"<li>{a}</li>" for a in _UNIT_AREAS[:8]) + "</ul>"
    fresh = _fetch_unit(monkeypatch, "cs", _AREA_MENU,
                        [("person1", "Avery Example"), ("person2", "Blair Sample"),
                         ("person3", "Casey Placeholder"), ("person4", "Devon Example")],
                        profiles={"person1": "", "person2": "", "person3": whole_section,
                                  "person4": "<h2>Research Areas</h2><ul><li>Computer Systems</li>"
                                             "<li>Data Science</li></ul>"})
    rows = _merge(tmp_path, stored, fresh)
    # Stored: a few of the department's areas, and a research line.
    assert rows["Avery Example"]["metadata"]["research_areas_raw"] == own_list
    assert "artificial intelligence" in rows["Avery Example"]["keywords"]
    assert rows["Blair Sample"]["metadata"]["research_areas_raw"] == line
    # Read off the person's own page this run, even the department's whole list.
    assert rows["Casey Placeholder"]["metadata"]["research_areas_raw"] == _WHOLE_AREA_MENU
    assert rows["Devon Example"]["metadata"]["research_areas_raw"] == "Computer Systems, Data Science"
    # A menu with one area after its research link: that area alone is no run.
    # Nor is a heading in the list page's own text: only the menu was misread.
    one = ('<li><a href="/research/areas">Research Areas</a><ul>'
           '<li><a href="/research/areas/ai">Artificial Intelligence</a></li></ul></li>')
    body_heading = ("<h2>Research Areas</h2><p>Artificial Intelligence</p>"
                    "<p>Security and Privacy</p><h2>Faculty</h2>")
    for menu, intro in ((one, ""), (_SECTION_MENU, body_heading)):
        fresh = _fetch_unit(monkeypatch, "cs", menu, [("person1", "Avery Example")], intro=intro)
        rows = _merge(tmp_path, [_stored_unit_row("cs", "Avery Example", "person1", own_list,
                                                  ["artificial intelligence"])], fresh)
        assert rows["Avery Example"]["metadata"]["research_areas_raw"] == own_list, intro


def test_a_menu_of_long_entries_comes_out_whole(tmp_path, monkeypatch):
    # The old read stored what fits in 400 characters after the link, cut to
    # whole items under 300; a shorter menu read would leave the last ones as
    # the person's own.
    import src.collectors.uiuc_faculty as f

    areas = ("Computational Biology and Bioinformatics", "Computer Architecture and Hardware Systems",
             "Database Systems and Information Retrieval", "Distributed Systems and Networking",
             "Human Factors and Interactive Computing", "Machine Learning and Statistical Inference",
             "Programming Languages and Formal Methods", "Scientific Computing and Numerical Analysis")
    menu = ('<li><a href="/research/areas">Research Areas</a><ul>' + "".join(
        f'<li><a href="/research/areas/{i}">{area}</a></li>' for i, area in enumerate(areas)) + "</ul></li>")
    stored_menu = f._trim_research_areas(", ".join(areas))
    assert stored_menu.count(",") >= 5 and len(stored_menu) > 200
    stored = [_stored_unit_row("cs", "Avery Example", "person1", stored_menu,
                               ["computational biology and bioinformatics"])]
    fresh = _fetch_unit(monkeypatch, "cs", menu, [("person1", "Avery Example")], profiles={"person1": ""})
    row = _merge(tmp_path, stored, fresh)["Avery Example"]
    assert row["metadata"]["research_areas_raw"] == ""
    assert row["keywords"] == ["computer science"]


def test_keywords_made_only_of_the_menus_words_go_back_to_the_broad_field(tmp_path, monkeypatch):
    # "interaction" is part of a menu entry, not an entry of its own.
    stored = [_stored_unit_row("cs", "Avery Example", "person1", _WHOLE_AREA_MENU,
                               ["interaction", "programming languages"])]
    fresh = _fetch_unit(monkeypatch, "cs", _AREA_MENU, [("person1", "Avery Example")], profiles={"person1": ""})
    row = _merge(tmp_path, stored, fresh)["Avery Example"]
    assert row["metadata"]["research_areas_raw"] == ""
    assert row["keywords"] == ["computer science"]


def test_a_title_is_not_read_as_a_research_area(monkeypatch):
    import src.collectors.uiuc_faculty as f

    monkeypatch.setattr(f, "_scrape_individual_page_keywords", lambda url: [])
    cfg = DEPARTMENTS["ib"]
    rec = normalize_faculty({"name": "Ann Example", "email": "person1@illinois.edu",
                             "title": "Professor, Evolution, Ecology, and Behavior"}, cfg)
    assert rec["metadata"]["faculty_title"] == "Professor, Evolution, Ecology, and Behavior"
    assert rec["keywords"] == cfg["keywords"][:1]


# --- M148: DirectoryCore list pages group their cards under section headings
# (Faculty, Affiliate Faculty, Emeritus Faculty, In Memoriam). A card under the
# In Memoriam heading was stored as an active professor with a contact email,
# and the card-name skip list matched substrings, so a surname containing
# "school" was dropped. Synthetic people, placeholder addresses. ---

def _section_card(slug: str, name: str, title: str | None) -> str:
    title_field = (
        '<div class="field field-name-field-dircore-appt-title"><div class="field__items">'
        f'<div class="field__item">{title}</div></div></div>' if title else "")
    return f"""<div><article class="profile-card">
      <a href="/directory/profile/{slug}" class="profile-card__link">
        <div class="field field-name-field-dircore-display-name"><div class="field__items">
        <div class="field__item">{name}</div></div></div></a>
      <div class="profile-card__info">{title_field}
        <div class="field field-name-field-dircore-email"><div class="field__items"><div class="field__item">
        <a href="mailto:{slug}@illinois.edu">{slug}@illinois.edu</a></div></div></div></div>
    </article></div>"""


def _sectioned_page(sections: list[tuple[str | None, list[tuple[str, str, str | None]]]]) -> str:
    """A DirectoryCore list page: the page's h1, then one view per section with
    its heading in the view header (the first section has none)."""
    views = "".join(
        '<div class="views-element-container"><div class="js-view-dom-id-x">'
        + (f'<header><h2 style="clear: both;">{heading}</h2></header>' if heading else "")
        + "".join(_section_card(*card) for card in cards)
        + "</div></div>"
        for heading, cards in sections)
    return f"""<html><body><header><h2>Site menu</h2></header>
      <main id="main-content"><h1>Faculty</h1>{views}</main></body></html>"""


MEMORIAL_PAGE = _sectioned_page([
    (None, [("person1", "Avery Example", "Professor"),
            ("person2", "Blair Sample", "Associate Professor"),
            ("person3", "Casey Placeholder", "Lecturer")]),
    ("Emeritus Faculty", [("person4", "Devon Example", None)]),
    ("In Memoriam", [("person5", "Morgan Example", None)]),
])


def _fetch_psych(monkeypatch, html: str | None) -> list[dict]:
    import src.collectors.uiuc_faculty as f

    page = DEPARTMENTS["psych"]["url"]
    monkeypatch.setattr(f, "_fetch_soup", lambda url: (
        BeautifulSoup(html, "html.parser") if html is not None and url == page else None))
    monkeypatch.setattr(f, "_scrape_individual_page_keywords", lambda url: [])
    return f.fetch_department("psych", enrich=False)


def _stored_psych_row(name: str, slug: str, **extra) -> dict:
    """The row an earlier refresh stored for this card: active, with its address."""
    row = normalize_faculty({"name": name, "email": f"{slug}@illinois.edu",
                             "url": f"{DEPARTMENTS['psych']['base']}/directory/profile/{slug}"},
                            DEPARTMENTS["psych"], keywords=["psychology"])
    row["metadata"].update(last_seen_at="2026-10-05T14:18:05", last_verified="2026-10-05T14:18:05",
                           first_seen_at="2026-01-10T00:00:00")
    for key, value in extra.items():
        row[key] = value
    return row


def _merge(tmp_path, stored: list[dict], fresh: list[dict]) -> dict[str, dict]:
    from src.collectors.uiuc_faculty import merge_into_processed

    path = tmp_path / "uiuc.json"
    path.write_text(json.dumps(stored), encoding="utf-8")
    merge_into_processed(fresh, str(path))
    return {r["pi_name"]: r for r in json.loads(path.read_text(encoding="utf-8"))}


def test_a_card_under_in_memoriam_retires_the_stored_row_and_drops_its_address(tmp_path, monkeypatch):
    fresh = _fetch_psych(monkeypatch, MEMORIAL_PAGE)
    rows = _merge(tmp_path, [_stored_psych_row("Morgan Example", "person5")], fresh)
    row = rows["Morgan Example"]
    assert row["metadata"]["is_active"] is False
    assert row["metadata"].get("deactivation_reason") == "listed_in_memoriam"
    assert row["metadata"].get("deactivated_at")
    # Neither the card's mailto, nor its profile netid, nor the stored address.
    assert row["contact_email"] is None
    assert row["metadata"]["first_seen_at"] == "2026-01-10T00:00:00"


def test_a_row_already_retired_as_in_memoriam_keeps_the_day_it_was_first_read(tmp_path, monkeypatch):
    stored = _stored_psych_row("Morgan Example", "person5", contact_email=None)
    stored["metadata"].update(is_active=False, deactivated_at="2026-10-12",
                              deactivation_reason="listed_in_memoriam")
    row = _merge(tmp_path, [stored], _fetch_psych(monkeypatch, MEMORIAL_PAGE))["Morgan Example"]
    assert (row["metadata"]["is_active"], row["metadata"].get("deactivated_at"), row["contact_email"]) == \
        (False, "2026-10-12", None)


def test_a_richer_duplicate_of_an_in_memoriam_card_is_retired_with_it(tmp_path, monkeypatch):
    # Same profile page, a name variant stored under another id: the row dedup
    # keeps the keyword-richer stored copy, which must not stay contactable.
    variant = _stored_psych_row("Morgan Q. Example", "person5")
    variant["keywords"] = ["implicit memory", "attitude formation", "social cognition"]
    rows = _merge(tmp_path, [variant], _fetch_psych(monkeypatch, MEMORIAL_PAGE))
    assert "Morgan Example" not in rows
    row = rows["Morgan Q. Example"]
    assert row["metadata"]["is_active"] is False
    assert row["metadata"]["deactivation_reason"] == "listed_in_memoriam"
    assert row["contact_email"] is None
    # The same card, so the surviving row records the section it was read under.
    assert row["metadata"].get("directory_section") == "In Memoriam"


def test_every_directory_row_records_the_section_heading_it_was_listed_under(monkeypatch):
    sections = {r["pi_name"]: r["metadata"].get("directory_section")
                for r in _fetch_psych(monkeypatch, MEMORIAL_PAGE)}
    # The page's own h1 heads the first view; the site menu above <main> is no section.
    assert sections == {"Avery Example": "Faculty", "Blair Sample": "Faculty",
                        "Casey Placeholder": "Faculty", "Devon Example": "Emeritus Faculty",
                        "Morgan Example": "In Memoriam"}


def test_an_ordinary_faculty_card_is_unchanged(tmp_path, monkeypatch):
    # Guard (holds before the In Memoriam and emeritus rules too): the rules touch no one else.
    fresh = _fetch_psych(monkeypatch, MEMORIAL_PAGE)
    stored = [_stored_psych_row("Avery Example", "person1")]
    rows = _merge(tmp_path, stored, fresh)
    for name, slug, title in (("Avery Example", "person1", "Professor"),
                              ("Blair Sample", "person2", "Associate Professor"),
                              ("Casey Placeholder", "person3", "Lecturer")):
        row = rows[name]
        assert row["metadata"]["is_active"] is True, name
        assert row["contact_email"] == f"{slug}@illinois.edu", name
        assert row["metadata"]["faculty_title"] == title, name
        assert "deactivation_reason" not in row["metadata"], name


def test_a_page_read_that_failed_changes_nobody(tmp_path, monkeypatch):
    # Guard (holds before the In Memoriam rule too): only a page that was read retires anyone.
    stored = [_stored_psych_row("Morgan Example", "person5"), _stored_psych_row("Avery Example", "person1")]
    fresh = _fetch_psych(monkeypatch, None)
    assert fresh == []
    rows = _merge(tmp_path, stored, fresh)
    for name, slug in (("Morgan Example", "person5"), ("Avery Example", "person1")):
        assert rows[name]["metadata"]["is_active"] is True
        assert rows[name]["metadata"]["last_seen_at"] == "2026-10-05T14:18:05"
        assert rows[name]["contact_email"] == f"{slug}@illinois.edu"


def test_a_page_mostly_under_an_in_memoriam_heading_retires_no_one(monkeypatch):
    # Guard (holds before the In Memoriam rule too): a memorial block above a
    # list without its own heading is not this list's heading, so reading it
    # as one would retire the whole unit.
    page = _sectioned_page([("In Memoriam", [("person1", "Avery Example", "Professor"),
                                             ("person2", "Blair Sample", "Professor"),
                                             ("person3", "Casey Placeholder", None)])])
    for row in _fetch_psych(monkeypatch, page):
        assert row["metadata"]["is_active"] is True, row["pi_name"]
        assert row["contact_email"], row["pi_name"]


def test_a_surname_containing_a_skip_word_is_kept_and_role_cards_still_are_not(monkeypatch):
    # A name with no skip word: a filter that drops every other card still
    # leaves one, so the page never falls through to the broad extractor.
    people = [("person0", "Avery Example", "Professor"),
              ("person1", "Robin Schoolfield", "Professor"), ("person2", "Dana Demeritt", "Professor"),
              ("person3", "Alex Officer", "Lecturer"), ("person4", "Kim Staffieri", "Professor"),
              ("person5", "Jo Collegeman", "Professor"), ("person6", "Lee Centerwall", "Professor"),
              ("person7", "Lane Overschool", "Professor"), ("person8", "Jo MacStafford", "Professor")]
    # Plurals, and words run together: "Faculty<br>Directory" reads "FacultyDirectory".
    roles = [("office1", "Department Office", None), ("office2", "School of Example Studies", None),
             ("office3", "Emeritus Faculty", None), ("office4", "Example Research Center", None),
             ("office5", "Departments", None), ("office6", "Offices", None),
             ("office7", "Colleges", None), ("office8", "Schools of Example Studies", None),
             ("office9", "Research Centers", None), ("office10", "Faculty<br/>Directory", None),
             ("office11", "Research<br/>Centers", None), ("office12", "FACULTYDIRECTORY", None)]
    names = {r["pi_name"] for r in _fetch_psych(monkeypatch, _sectioned_page([(None, people + roles)]))}
    assert names == {name for _, name, _ in people}


def test_a_lower_level_heading_after_in_memoriam_starts_a_section_of_its_own(monkeypatch):
    # Eight cards under the page's h1, one under an h2 "In Memoriam", three
    # under an h4: the nearest heading of any level is the card's section.
    faculty = [(f"person{i}", name, "Professor") for i, name in enumerate(
        ("Avery Example", "Blair Sample", "Casey Placeholder", "Devon Example", "Emery Sample",
         "Finley Placeholder", "Gray Example", "Harper Sample"), start=1)]
    affiliates = [("person10", "Quinn Sample", "Affiliate Professor"),
                  ("person11", "Reese Placeholder", "Affiliate Professor"),
                  ("person12", "Sage Example", "Affiliate Professor")]
    page = _sectioned_page([(None, faculty), ("In Memoriam", [("person9", "Morgan Example", None)]),
                            ("Affiliate Faculty", affiliates)])
    page = page.replace('<h2 style="clear: both;">Affiliate Faculty</h2>', "<h4>Affiliate Faculty</h4>")
    assert "<h4>Affiliate Faculty</h4>" in page
    rows = {r["pi_name"]: r for r in _fetch_psych(monkeypatch, page)}
    assert len(rows) == 12
    assert {n for n, r in rows.items() if r["metadata"]["is_active"] is False} == {"Morgan Example"}
    for _, name, _ in affiliates:
        assert rows[name]["metadata"].get("directory_section") == "Affiliate Faculty", name
        assert rows[name]["contact_email"], name


def _heading_card(slug: str, name: str) -> str:
    """A card that carries its own name and title as headings."""
    return (f'<div class="views-row"><h3><a href="/directory/profile/{slug}">{name}</a></h3>'
            f'<h5>Professor</h5><a href="mailto:{slug}@illinois.edu">{slug}@illinois.edu</a></div>')


def test_a_cards_own_headings_are_never_read_as_a_section(monkeypatch):
    page = ("<html><body><main><h1>People</h1><h2>Faculty</h2>"
            + _heading_card("person1", "Avery Example") + _heading_card("person2", "Blair Sample")
            + _heading_card("person3", "Casey Placeholder")
            + "<h2>In Memoriam</h2>" + _heading_card("person4", "Morgan Example")
            + "<h4>Affiliate Faculty</h4>" + _heading_card("person5", "Quinn Sample")
            + _heading_card("person6", "Reese Placeholder") + "</main></body></html>")
    rows = {r["pi_name"]: r for r in _fetch_psych(monkeypatch, page)}
    assert {n: r["metadata"].get("directory_section") for n, r in rows.items()} == {
        "Avery Example": "Faculty", "Blair Sample": "Faculty", "Casey Placeholder": "Faculty",
        "Morgan Example": "In Memoriam",
        "Quinn Sample": "Affiliate Faculty", "Reese Placeholder": "Affiliate Faculty"}
    assert {n for n, r in rows.items() if r["metadata"]["is_active"] is False} == {"Morgan Example"}


def test_a_richer_duplicate_holding_a_verified_address_keeps_no_trace_of_it(tmp_path, monkeypatch):
    from backend.lib.contact_visibility import build_identity_bound_contact_evidence

    variant = _stored_psych_row("Morgan Q. Example", "person5")
    variant["keywords"] = ["implicit memory", "attitude formation", "social cognition"]
    evidence = build_identity_bound_contact_evidence(
        email="person5@illinois.edu", email_source="bound_directory_card",
        contact_source_url=variant["source_url"], contact_verified_at="2026-10-05T14:18:05+00:00")
    assert evidence
    variant["metadata"].update(evidence)
    rows = _merge(tmp_path, [variant], _fetch_psych(monkeypatch, MEMORIAL_PAGE))
    assert "Morgan Example" not in rows
    row = rows["Morgan Q. Example"]
    assert row["metadata"].get("deactivation_reason") == "listed_in_memoriam"
    # Neither the address field nor the proof that named it.
    assert "person5@illinois.edu" not in json.dumps(row)


def test_the_enrichment_pass_after_the_merge_never_puts_the_address_back(tmp_path, monkeypatch):
    # refresh_all runs pi_enricher over the merged corpus. It fills an address
    # into a faculty row without one from that row's profile page, and the
    # In Memoriam person's page still shows theirs.
    from src.collectors import pi_enricher

    stored = [_stored_psych_row("Morgan Example", "person5"),
              _stored_psych_row("Jordan Sample", "person6", contact_email=None)]
    rows = _merge(tmp_path, stored, _fetch_psych(monkeypatch, MEMORIAL_PAGE))
    fetched: list[str] = []

    def profile_page(url):
        fetched.append(url)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return BeautifulSoup(f'<a href="mailto:{slug}@illinois.edu">{slug}@illinois.edu</a>', "html.parser")

    monkeypatch.setattr(pi_enricher, "_fetch_soup", profile_page)
    monkeypatch.setattr(pi_enricher, "DELAY", 0)
    pi_enricher.enrich_opportunities(list(rows.values()))
    assert rows["Morgan Example"]["contact_email"] is None
    assert "person5@illinois.edu" not in json.dumps(rows["Morgan Example"])
    assert not any(url.endswith("/person5") for url in fetched)
    # The same pass still finds the address of a current professor without one.
    assert rows["Jordan Sample"]["contact_email"] == "person6@illinois.edu"


# --- M149: emeritus and retired faculty are not listed, as at every other
# school, except someone the directory lists as still running an active lab.
# The card's own heading or title says so; the stored row is retired by it
# (UIUC never retires a row for being absent). Synthetic people. ---

EMERITUS_PAGE = _sectioned_page([
    (None, [("person1", "Avery Example", "Professor"),
            ("person2", "Blair Sample", "Associate Professor"),
            ("person3", "Casey Placeholder", "Lecturer"),
            ("person6", "Emery Sample", "Professor Emeritus")]),
    ("Emeritus Faculty with active research labs", [("person7", "Finley Placeholder", "Professor Emeritus")]),
    ("Emeritus Faculty", [("person4", "Devon Example", None), ("person8", "Gray Example", "Associate Professor")]),
])


def _emeritus(row: dict) -> tuple:
    md = row["metadata"]
    return md["is_active"], md.get("deactivation_reason"), bool(md.get("deactivated_at"))


@pytest.mark.parametrize("heading", ["Emeritus Faculty", "Emeriti", "Emeriti Faculty",
                                     "Emeritus/Emerita and Retired Faculty", "Emeriti/Emeritae", "EMERITI FACULTY"])
def test_a_card_under_an_emeritus_heading_retires_the_stored_row_and_keeps_its_address(tmp_path, monkeypatch, heading):
    page = EMERITUS_PAGE.replace('<h2 style="clear: both;">Emeritus Faculty</h2>', f'<h2 style="clear: both;">{heading}</h2>')
    rows = _merge(tmp_path, [_stored_psych_row("Devon Example", "person4")], _fetch_psych(monkeypatch, page))
    # Untitled: the heading says it (a card titled with a current rank stays listed, round 3 below).
    row = rows["Devon Example"]
    assert _emeritus(row) == (False, "listed_as_emeritus", True)
    # Alive and theirs; an inactive row is never offered as a contact.
    assert row["contact_email"] == "person4@illinois.edu"
    assert row["metadata"]["first_seen_at"] == "2026-01-10T00:00:00"
    assert row["metadata"]["directory_section"] == heading


@pytest.mark.parametrize("title", ["Professor Emeritus", "Associate Professor Emerita", "Research Associate Professor (retired)",
                                   "Retired", "professor emeritus of example studies", "Emeriti Faculty"])
def test_a_card_whose_title_says_emeritus_is_retired_under_an_ordinary_heading(tmp_path, monkeypatch, title):
    page = EMERITUS_PAGE.replace(">Professor Emeritus</div>", f">{title}</div>", 1)
    rows = _merge(tmp_path, [_stored_psych_row("Emery Sample", "person6")], _fetch_psych(monkeypatch, page))
    row = rows["Emery Sample"]
    assert row["metadata"]["directory_section"] == "Faculty"
    assert _emeritus(row) == (False, "listed_as_emeritus", True)
    assert row["metadata"]["faculty_title"] == title
    assert row["contact_email"] == "person6@illinois.edu"


def test_an_emeritus_listed_with_an_active_research_lab_stays_listed_with_their_title(tmp_path, monkeypatch):
    # Guard (holds before the emeritus rule too, which retired no one): the
    # rule's one exception. The same person also listed under the plain
    # Emeritus heading further down the page is still one listed row.
    page = EMERITUS_PAGE.replace("</main>", "".join((
        '<div class="views-element-container"><header><h2>Emeritus Faculty</h2></header>',
        _section_card("person7", "Finley Placeholder", "Professor Emeritus"), "</div></main>")))
    rows = _merge(tmp_path, [_stored_psych_row("Finley Placeholder", "person7")], _fetch_psych(monkeypatch, page))
    row = rows["Finley Placeholder"]
    assert row["metadata"]["is_active"] is True
    assert "deactivation_reason" not in row["metadata"]
    assert row["metadata"]["faculty_title"] == "Professor Emeritus"
    assert row["contact_email"] == "person7@illinois.edu"


def test_a_person_listed_under_an_emeritus_and_an_ordinary_heading_stays_listed_whichever_comes_first(tmp_path, monkeypatch):
    # The ordinary card is a current role, as at every other school, where each
    # card is judged on its own; also when the emeritus card's title says so.
    for emeritus_title in (None, "Professor Emeritus"):
        for sections in ([("Emeritus Faculty", [("person4", "Devon Example", emeritus_title)]),
                          ("Research Faculty", [("person4", "Devon Example", None)])],
                         [("Research Faculty", [("person4", "Devon Example", None)]),
                          ("Emeritus Faculty", [("person4", "Devon Example", emeritus_title)])]):
            page = _sectioned_page([(None, [("person1", "Avery Example", "Professor"),
                                            ("person2", "Blair Sample", "Professor"),
                                            ("person3", "Casey Placeholder", "Professor")])] + sections)
            row = _merge(tmp_path, [_stored_psych_row("Devon Example", "person4")],
                         _fetch_psych(monkeypatch, page))["Devon Example"]
            assert _emeritus(row) == (True, None, False), (emeritus_title, sections[0][0])
            assert row["contact_email"] == "person4@illinois.edu"


def test_a_row_already_retired_as_emeritus_keeps_the_day_it_was_first_read(tmp_path, monkeypatch):
    # Also when the page lists the person a second time, by an emeritus title
    # under another heading.
    twice = EMERITUS_PAGE.replace("</main>", "".join((
        '<div class="views-element-container"><header><h2>Research Faculty</h2></header>',
        _section_card("person4", "Devon Example", "Professor Emeritus"), "</div></main>")))
    for page in (EMERITUS_PAGE, twice):
        stored = _stored_psych_row("Devon Example", "person4")
        stored["metadata"].update(is_active=False, deactivated_at="2026-10-12", deactivation_reason="listed_as_emeritus")
        row = _merge(tmp_path, [stored], _fetch_psych(monkeypatch, page))["Devon Example"]
        assert (row["metadata"]["is_active"], row["metadata"].get("deactivated_at"), row["contact_email"]) == \
            (False, "2026-10-12", "person4@illinois.edu")


def test_a_richer_duplicate_of_an_emeritus_card_is_retired_with_it_and_keeps_its_first_day(tmp_path, monkeypatch):
    # Same profile page, a name variant stored under another id: the row dedup
    # keeps the keyword-richer stored copy, which must not stay listed.
    variant = _stored_psych_row("Devon Q. Example", "person4")
    variant["keywords"] = ["implicit memory", "attitude formation", "social cognition"]
    rows = _merge(tmp_path, [variant], _fetch_psych(monkeypatch, EMERITUS_PAGE))
    assert "Devon Example" not in rows
    row = rows["Devon Q. Example"]
    assert _emeritus(row) == (False, "listed_as_emeritus", True)
    assert row["contact_email"] == "person4@illinois.edu"
    row["metadata"]["deactivated_at"] = "2026-10-12"
    again = _merge(tmp_path, [row], _fetch_psych(monkeypatch, EMERITUS_PAGE))["Devon Q. Example"]
    assert (again["metadata"]["is_active"], again["metadata"]["deactivated_at"]) == (False, "2026-10-12")


def test_an_unmarked_listing_in_another_department_never_lifts_an_emeritus_retirement_and_an_active_lab_is_never_retired():
    # The carry alone, between rows the merge did not mark as listed with a
    # current role this run (stored rows); a marked one lifts it (merge test below).
    from src.collectors.uiuc_faculty import _carry_newest_liveness

    def row(url, seen, **md):
        return {"source_url": url, "metadata": {"last_seen_at": seen, "is_active": True, **md}}

    retired = dict(is_active=False, deactivated_at="2026-10-12", deactivation_reason="listed_as_emeritus")
    # A newer plain listing in another department does not contradict the emeritus heading...
    survivor = row("https://a.example/profile/person4", "2026-10-20T00:00:00", **retired)
    _carry_newest_liveness(survivor, row("https://b.example/profile/person4", "2026-10-21T00:00:00",
                                         directory_section="Faculty"))
    assert _emeritus(survivor) == (False, "listed_as_emeritus", True)
    # ...the same card listed again, or a listing with an active lab, does.
    for url, section in (("https://a.example/profile/person4", "Faculty"),
                         ("https://b.example/profile/person4", "Emeritus Faculty with active research labs")):
        survivor = row("https://a.example/profile/person4", "2026-10-20T00:00:00", **retired)
        _carry_newest_liveness(survivor, row(url, "2026-10-21T00:00:00", directory_section=section))
        assert _emeritus(survivor) == (True, None, False), section
    # A newer emeritus card of the same person never retires their active-lab row.
    lab = row("https://b.example/profile/person4", "2026-10-20T00:00:00",
              directory_section="Emeritus Faculty with active research labs")
    _carry_newest_liveness(lab, row("https://a.example/profile/person4", "2026-10-21T00:00:00", **retired))
    assert _emeritus(lab) == (True, None, False)


def test_a_profile_page_title_that_says_emeritus_retires_an_untitled_card(tmp_path, monkeypatch):
    import src.collectors.uiuc_faculty as f

    page = _sectioned_page([(None, [("person1", "Avery Example", "Professor"), ("person2", "Blair Sample", None),
                                    ("person3", "Casey Placeholder", None)])])
    profile = ('<html><body><main><div class="field field-name-field-dircore-appt-title"><div class="field__items">'
               '<div class="field__item">{}</div></div></div></main></body></html>')
    titles = {"person2": "Professor Emerita", "person3": "Assistant Professor"}
    base = DEPARTMENTS["psych"]["base"]

    def fetch(url):
        if url == DEPARTMENTS["psych"]["url"]:
            return BeautifulSoup(page, "html.parser")
        slug = url.rsplit("/", 1)[-1]
        return BeautifulSoup(profile.format(titles[slug]), "html.parser") if url == f"{base}/directory/profile/{slug}" \
            and slug in titles else None

    monkeypatch.setattr(f, "_fetch_soup", fetch)
    monkeypatch.setattr(f, "_scrape_individual_page_keywords", lambda url: [])
    monkeypatch.setattr(f, "DELAY", 0)
    rows = _merge(tmp_path, [_stored_psych_row("Blair Sample", "person2")], f.fetch_department("psych", enrich=True))
    assert rows["Blair Sample"]["metadata"]["faculty_title"] == "Professor Emerita"
    assert _emeritus(rows["Blair Sample"]) == (False, "listed_as_emeritus", True)
    assert rows["Casey Placeholder"]["metadata"]["faculty_title"] == "Assistant Professor"
    assert _emeritus(rows["Casey Placeholder"]) == (True, None, False)


def test_a_failed_or_partial_page_read_retires_no_emeritus(tmp_path, monkeypatch):
    # Guard (holds before the emeritus rule too): only what a page that was
    # read states retires anyone. A failed read; a page that lists no emeritus
    # card (the stored one is absent, not listed as emeritus); a page mostly
    # under an emeritus heading, whose heading is not read as one.
    stored = [_stored_psych_row("Devon Example", "person4"), _stored_psych_row("Avery Example", "person1")]
    assert _fetch_psych(monkeypatch, None) == []
    partial = _sectioned_page([(None, [("person1", "Avery Example", "Professor"),
                                       ("person2", "Blair Sample", "Professor")])])
    for fresh in ([], _fetch_psych(monkeypatch, partial)):
        rows = _merge(tmp_path, stored, fresh)
        assert rows["Devon Example"]["metadata"]["is_active"] is True
        assert rows["Devon Example"]["metadata"]["last_seen_at"] == "2026-10-05T14:18:05"
        assert rows["Devon Example"]["contact_email"] == "person4@illinois.edu"
    mostly = _sectioned_page([("Emeritus Faculty", [("person1", "Avery Example", "Professor"),
                                                    ("person2", "Blair Sample", "Professor"),
                                                    ("person3", "Casey Placeholder", None)])])
    for row in _fetch_psych(monkeypatch, mostly):
        assert _emeritus(row) == (True, None, False), row["pi_name"]


def test_in_memoriam_outranks_an_emeritus_title():
    # Guard (holds before the emeritus rule too): still no address.
    row = normalize_faculty({"name": "Morgan Example", "title": "Professor Emeritus", "email": "person5@illinois.edu",
                             "directory_section": "In Memoriam", "in_memoriam": True},
                            DEPARTMENTS["psych"], keywords=["psychology"])
    assert (row["metadata"]["deactivation_reason"], row["contact_email"]) == ("listed_in_memoriam", None)


def test_a_row_retired_through_another_departments_emeritus_card_keeps_its_first_day(tmp_path):
    # Communication lists the person as Professor Emeritus, Psychology under its
    # Emeritus heading; the address folds both into the richer Communication
    # row, which a refresh retires again every week from the same cards.
    def card(dept, **person):
        return normalize_faculty({"name": "Devon Example", "email": "person4@illinois.edu",
                                  "url": f"{DEPARTMENTS[dept]['base']}/directory/profile/person4", **person},
                                 DEPARTMENTS[dept], keywords=["communication"])

    stored = card("comm", title="Professor Emeritus")
    stored["keywords"] = ["persuasion", "health communication", "media effects"]
    stored["metadata"].update(is_active=False, deactivated_at="2026-10-12", deactivation_reason="listed_as_emeritus",
                              last_seen_at="2026-10-05T14:18:05")
    fresh = [card("comm", title="Professor Emeritus"),
             card("psych", title="Professor Emeritus", directory_section="Emeritus Faculty")]
    assert fresh[0]["metadata"]["is_active"] is False and fresh[1]["metadata"]["is_active"] is False
    rows = _merge(tmp_path, [stored], fresh)
    assert list(rows) == ["Devon Example"]
    row = rows["Devon Example"]
    assert row["department"] == DEPARTMENTS["comm"]["name"]
    assert (row["metadata"]["is_active"], row["metadata"]["deactivation_reason"], row["metadata"]["deactivated_at"]) == \
        (False, "listed_as_emeritus", "2026-10-12")


# --- M149 round 2: a current role always wins. A title retires only when all
# its ranks are emeritus or retired; a person listed this run with a current
# role, on the same page or another department's, stays listed whatever order
# the departments are read in. Synthetic people. ---

MIXED_TITLES = ["Research Professor, Professor Emeritus", "Associate Professor Emeritus, Associate Research Professor",
                "Dean Emeritus and Professor of Finance", "Emeritus Dean, Professor",
                "Professor Emeritus; Example Family Professor of Global Studies",
                "Professor Emerita and Director of the Example Center",
                "Affiliate Faculty of Example Education Professor Emerita of Example Studies"]
ALL_EMERITUS_TITLES = ["Professor Emeritus", "Emeritus Professor of Example Studies", "Example Family Professor Emeritus",
                       "Associate Professor Emerita", "Retired", "Professor of Viola, Retired", "Director Emeritus",
                       "Example Chair Emeritus, Professor Emeritus of Biochemistry, and Professor Emeritus of Chemistry",
                       "Professor Emeritus (Economics, Geography, Urban and Regional Planning)",
                       "Example Distinguished Professor of Marketing Emeritus", "Research Associate Professor (retired)",
                       "Example Endowed Chair Emeritus Professor Emeritus of Example Studies",
                       "Professor of Example Studies, Emeritus; Research Professor Emeritus"]


def _json_card(title: str) -> dict:
    # The JSON/HTML collectors' path: a title and no heading.
    return normalize_faculty({"name": "Emery Sample", "title": title, "email": "person6@illinois.edu"},
                             DEPARTMENTS["psych"], keywords=["psychology"])


@pytest.mark.parametrize("title", MIXED_TITLES)
def test_a_title_with_a_current_rank_beside_an_emeritus_one_stays_listed(tmp_path, monkeypatch, title):
    page = EMERITUS_PAGE.replace(">Professor Emeritus</div>", f">{title}</div>", 1)
    row = _merge(tmp_path, [_stored_psych_row("Emery Sample", "person6")], _fetch_psych(monkeypatch, page))["Emery Sample"]
    assert row["metadata"]["directory_section"] == "Faculty"
    assert _emeritus(row) == (True, None, False)
    assert row["metadata"]["faculty_title"] == title
    assert _emeritus(_json_card(title)) == (True, None, False)


@pytest.mark.parametrize("title", ALL_EMERITUS_TITLES)
def test_a_title_whose_ranks_are_all_emeritus_still_retires(tmp_path, monkeypatch, title):
    # Guard (holds on round 1 too, which retired every emeritus word): the
    # current-rank reading does not keep a plain emeritus title listed.
    page = EMERITUS_PAGE.replace(">Professor Emeritus</div>", f">{title}</div>", 1)
    row = _merge(tmp_path, [_stored_psych_row("Emery Sample", "person6")], _fetch_psych(monkeypatch, page))["Emery Sample"]
    assert _emeritus(row) == (False, "listed_as_emeritus", True)
    assert row["contact_email"] == "person6@illinois.edu"
    assert _emeritus(_json_card(title)) == (False, "listed_as_emeritus", True)


def _read_in_order(cards: list[dict]) -> list[dict]:
    # Rows carry the time their department was read: later departments, later.
    for minute, card in enumerate(cards):
        card["metadata"]["last_seen_at"] = f"2026-10-24T10:{minute:02d}:00"
    return cards


def test_another_departments_ordinary_listing_keeps_the_person_listed_in_either_read_order(tmp_path):
    # Communication lists the person as a professor, Psychology under its
    # Emeritus heading; one address folds both into one row, whichever is richer.
    def card(dept, **person):
        return normalize_faculty({"name": "Devon Example", "email": "person4@illinois.edu",
                                  "url": f"{DEPARTMENTS[dept]['base']}/directory/profile/person4", **person},
                                 DEPARTMENTS[dept], keywords=["communication"])

    for richer in ("comm", "psych"):
        for order in (("comm", "psych"), ("psych", "comm")):
            stored = card(richer, title="Professor")
            stored["keywords"] = ["persuasion", "health communication", "media effects"]
            stored["metadata"]["last_seen_at"] = "2026-10-05T14:18:05"
            fresh = {"comm": card("comm", title="Professor"),
                     "psych": card("psych", title="Professor Emeritus", directory_section="Emeritus Faculty")}
            rows = _merge(tmp_path, [stored], _read_in_order([fresh[d] for d in order]))
            assert list(rows) == ["Devon Example"], (richer, order)
            row = rows["Devon Example"]
            assert row["department"] == DEPARTMENTS[richer]["name"], (richer, order)
            assert _emeritus(row) == (True, None, False), (richer, order)
            assert row["contact_email"] == "person4@illinois.edu"
            # The merge's mark is never written, nor left on the cards.
            assert not any("_listed_current" in r["metadata"] for r in [row, *fresh.values()])


def test_a_program_pages_listing_never_lifts_the_home_departments_emeritus_row(tmp_path):
    # Neuroscience lists the person as a professor; their home department under
    # its Emeritus heading. The home department's page decides: the program card
    # folds into the home row by address and the row stays retired with the home
    # card's own title, whichever is read first.
    from src.collectors.uiuc_faculty import _dedup_program_affiliations

    def card(dept, **person):
        return normalize_faculty({"name": "Devon Example", "email": "person4@illinois.edu",
                                  "url": f"{DEPARTMENTS[dept]['base']}/directory/profile/person4", **person},
                                 DEPARTMENTS[dept], keywords=["psychology"])

    def fresh():
        return {"neuroscience": card("neuroscience", title="Professor, Psychology", directory_section="Faculty Members"),
                "psych": card("psych", title="Professor Emeritus", directory_section="Emeritus Faculty")}

    for order in (("neuroscience", "psych"), ("psych", "neuroscience")):
        cards = fresh()
        kept = _dedup_program_affiliations(_read_in_order([cards[d] for d in order]))
        assert [r["department"] for r in kept] == [DEPARTMENTS["psych"]["name"]], order
        row = _merge(tmp_path, [], kept)["Devon Example"]
        assert _emeritus(row) == (False, "listed_as_emeritus", True), order
        md = row["metadata"]
        assert (md["faculty_title"], md["directory_section"]) == ("Professor Emeritus", "Emeritus Faculty"), order
        assert row["contact_email"] == "person4@illinois.edu" and "neuroscience" in row["keywords"], order
    # A program card no dedup above matched (the home row comes from a collector
    # the program dedup does not see) folds at the merge: the same, whichever row
    # is richer and whichever is read first.
    for richer in ("neuroscience", "psych"):
        for order in (("neuroscience", "psych"), ("psych", "neuroscience")):
            stored = card(richer, title="Professor")
            stored["keywords"] = ["cognition", "memory", "attention"]
            stored["metadata"]["last_seen_at"] = "2026-10-05T14:18:05"
            cards = fresh()
            rows = _merge(tmp_path, [stored], _read_in_order([cards[d] for d in order]))
            case = (richer, order)
            assert list(rows) == ["Devon Example"] and rows["Devon Example"]["department"] == DEPARTMENTS[richer]["name"], case
            assert _emeritus(rows["Devon Example"]) == (False, "listed_as_emeritus", True), case


# --- M149 round 3: an emeritus heading retires only a card whose own title
# states no current rank; In Memoriam outranks emeritus in any read order.
# Synthetic people. ---

@pytest.mark.parametrize("title", ["Associate Professor", "Emeritus Professor and Example Director",
                                   "Example Endowed Chair and Professor Emeritus"])
def test_a_card_under_an_emeritus_heading_whose_title_states_a_current_rank_stays_listed(tmp_path, monkeypatch, title):
    page = EMERITUS_PAGE.replace(_section_card("person8", "Gray Example", "Associate Professor"),
                                 _section_card("person8", "Gray Example", title))
    rows = _merge(tmp_path, [_stored_psych_row("Gray Example", "person8")], _fetch_psych(monkeypatch, page))
    row = rows["Gray Example"]
    assert row["metadata"]["directory_section"] == "Emeritus Faculty"
    assert row["metadata"]["faculty_title"] == title
    assert _emeritus(row) == (True, None, False)
    assert row["contact_email"] == "person8@illinois.edu"


@pytest.mark.parametrize("title", [None, "Academic Hourly", "Professor Emeritus", "Research Professor Emeritus"])
def test_a_card_under_an_emeritus_heading_with_no_current_rank_in_its_title_still_retires(tmp_path, monkeypatch, title):
    # Guard (holds on round 2 too, where the heading alone retired): no title,
    # one with no rank, or ranks that are all emeritus.
    page = EMERITUS_PAGE.replace(_section_card("person8", "Gray Example", "Associate Professor"),
                                 _section_card("person8", "Gray Example", title))
    row = _merge(tmp_path, [_stored_psych_row("Gray Example", "person8")], _fetch_psych(monkeypatch, page))["Gray Example"]
    assert _emeritus(row) == (False, "listed_as_emeritus", True)
    assert row["contact_email"] == "person8@illinois.edu"


def test_a_person_under_in_memoriam_and_another_heading_on_one_page_is_retired_in_memoriam_whichever_comes_first(
        tmp_path, monkeypatch):
    for heading, title in (("Emeritus Faculty", None), ("Emeritus Faculty", "Professor Emeritus"),
                           ("Research Faculty", "Professor")):
        for sections in ([("In Memoriam", [("person5", "Morgan Example", None)]),
                          (heading, [("person5", "Morgan Example", title)])],
                         [(heading, [("person5", "Morgan Example", title)]),
                          ("In Memoriam", [("person5", "Morgan Example", None)])]):
            page = _sectioned_page([(None, [("person1", "Avery Example", "Professor"),
                                            ("person2", "Blair Sample", "Professor"),
                                            ("person3", "Casey Placeholder", "Professor")])] + sections)
            row = _merge(tmp_path, [_stored_psych_row("Morgan Example", "person5")],
                         _fetch_psych(monkeypatch, page))["Morgan Example"]
            assert (row["metadata"]["is_active"], row["metadata"].get("deactivation_reason"), row["contact_email"]) == \
                (False, "listed_in_memoriam", None), (heading, title, sections[0][0])


def test_in_memoriam_outranks_an_emeritus_card_folded_into_the_same_row_in_either_read_order(tmp_path):
    # Two spellings of one person on one profile page, one card under In
    # Memoriam and one under Emeritus Faculty: the profile dedup folds them
    # into the richer row, which is never relabelled emeritus nor re-dated.
    url = f"{DEPARTMENTS['psych']['base']}/directory/profile/person5"

    def card(name, **person):
        return normalize_faculty({"name": name, "email": "person5@illinois.edu", "url": url,
                                  "title": "Professor Emeritus", **person}, DEPARTMENTS["psych"], keywords=["psychology"])

    def memoriam():
        return card("Morgan Example", directory_section="In Memoriam", in_memoriam=True)

    def emeritus():
        return card("Morgan Q. Example", directory_section="Emeritus Faculty", emeritus=True)

    richer_keywords = ["implicit memory", "attitude formation", "social cognition"]
    for richer in ("Morgan Example", "Morgan Q. Example"):
        for order in ((memoriam, emeritus), (emeritus, memoriam)):
            fresh = _read_in_order([make() for make in order])
            for r in fresh:
                if r["pi_name"] == richer:
                    r["keywords"] = list(richer_keywords)
            rows = _merge(tmp_path, [], fresh)
            assert list(rows) == [richer], (richer, order[0].__name__)
            row = rows[richer]
            assert (row["metadata"]["is_active"], row["metadata"].get("deactivation_reason"), row["contact_email"]) == \
                (False, "listed_in_memoriam", None), (richer, order[0].__name__)
    # A row already retired as In Memoriam keeps its first day when a newer
    # emeritus or In Memoriam card of the other spelling folds into it.
    for make in (emeritus, memoriam):
        stored = card("Morgan R. Example", directory_section="In Memoriam", in_memoriam=True)
        stored["keywords"] = list(richer_keywords)
        stored["metadata"].update(deactivated_at="2026-10-12", last_seen_at="2026-10-05T14:18:05")
        fresh = make()
        rows = _merge(tmp_path, [stored], [fresh])
        assert list(rows) == ["Morgan R. Example"], fresh["pi_name"]
        md = rows["Morgan R. Example"]["metadata"]
        assert (md["is_active"], md["deactivation_reason"], md["deactivated_at"], rows["Morgan R. Example"]["contact_email"]) \
            == (False, "listed_in_memoriam", "2026-10-12", None), fresh["pi_name"]


# --- M149 round 4: an Engineering directory (Physics) card's title sits in
# div.title beside the name link the page is read by; in a research-area
# section the same field names a subarea. Synthetic people. ---

def _person_item(slug: str, name: str, title: str, area: bool = False) -> str:
    if area:
        # A research-area section's card, as Physics renders it: no netid, and
        # the title field holds the card's subarea (data-discipline).
        return f"""<div class="item person" data-dept="Physics" data-discipline="{title}" id="page-{slug}">
      <div class="photo"></div>
      <div class="details">
        <div class="name"><a href="https://physics.illinois.edu/people/directory/profile/{slug}" target="_top">{name}</a></div>
        <div class="title">{title}</div>
      </div>
    </div>"""
    return f"""<div class="item person cat15 phys" id="id-{slug}" data-netid="{slug}">
      <div class="photo"></div>
      <div class="details">
        <div class="name"><a href="/people/directory/profile/{slug}">{name}</a></div>
        <div class="pronouns hide-empty" data-value=""></div>
        <div class="title">{title}</div>
        <div class="area"><ul><li class="primary"><a href="https://physics.illinois.edu/research/groups-and-centers/example">Example Physics</a></li></ul></div>
        <div class="contact"><div class="email"><a href="mailto:{slug}@illinois.edu" aria-label="Send email to {slug}@illinois.edu">
          <span class="fa-stack fa-lg"><i class="fa fa-envelope fa-stack-1x fa-inverse"></i></span></a></div></div>
      </div>
    </div>"""


def _person_items_page(sections: list[tuple[str, str, list[tuple[str, str, str]]]]) -> str:
    return "<html><body><main>" + "".join(
        f'<{tag}>{heading}</{tag}><div class="directory-list directory-list-3">'
        + "".join(_person_item(*card) for card in cards) + "</div>"
        for tag, heading, cards in sections) + "</main></body></html>"


PERSON_ITEMS_PAGE = _person_items_page([
    ("h3", "Faculty", [("person1", "Avery Example", "Associate Professor<p>Example Faculty Fellow"),
                       ("person2", "Blair Sample", "Professor"),
                       ("person3", "Casey Placeholder", "Research Professor")]),
    ("h3", "Example Information Science", [("person4", "Devon Example", "Example Matter Theory", True)]),
    ("h2", "Emeriti/Emeritae", [("person5", "Emery Sample", "Example Endowed Chair Emeritus of Physics and Research Professor"),
                                ("person6", "Finley Placeholder", "Professor Emeritus")]),
    ("h2", "Affiliated Faculty", [("person7", "Gray Example", "Professor Emeritus in Example Studies and Physics"),
                                  ("person8", "Harper Sample", "Professor in Example Studies")]),
])
_ROLE_PROFILE = """<html><body><main><div class="directory-profile"><div class="roles">
  <strong><h2>Primary Research Area</h2><ul><li>Example Matter Physics</li></ul></strong>
  <div class="role cat21 primary"><div class="title"><strong>{}</strong></div>
  <div class="email"><a href="mailto:{slug}@illinois.edu">{slug}@illinois.edu</a></div></div>
</div></div></main></body></html>"""


def _fetch_physics(monkeypatch, profiles: dict[str, str] | None = None, page: str = PERSON_ITEMS_PAGE) -> list[dict]:
    import src.collectors.uiuc_faculty as f

    base = DEPARTMENTS["physics"]["base"]

    def fetch(url):
        if url == DEPARTMENTS["physics"]["url"]:
            return BeautifulSoup(page, "html.parser")
        slug = url.rsplit("/", 1)[-1]
        if profiles and slug in profiles and url == f"{base}/people/directory/profile/{slug}":
            return BeautifulSoup(_ROLE_PROFILE.format(profiles[slug], slug=slug), "html.parser")
        return None

    monkeypatch.setattr(f, "_fetch_soup", fetch)
    monkeypatch.setattr(f, "_scrape_individual_page_keywords", lambda url: [])
    monkeypatch.setattr(f, "DELAY", 0)
    return f.fetch_department("physics", enrich=profiles is not None)


def _stored_physics_row(name: str, slug: str) -> dict:
    row = normalize_faculty({"name": name, "email": f"{slug}@illinois.edu",
                             "url": f"{DEPARTMENTS['physics']['base']}/people/directory/profile/{slug}"},
                            DEPARTMENTS["physics"], keywords=["physics"])
    row["metadata"].update(last_seen_at="2026-10-05T14:18:05", last_verified="2026-10-05T14:18:05",
                           first_seen_at="2026-01-10T00:00:00")
    return row


def test_an_engineering_directory_card_gives_the_title_beside_its_name_link(monkeypatch):
    rows = {r["pi_name"]: r for r in _fetch_physics(monkeypatch)}
    titles = {name: r["metadata"]["faculty_title"] for name, r in rows.items()}
    assert titles["Avery Example"] == "Associate Professor; Example Faculty Fellow"
    assert titles["Blair Sample"] == "Professor"
    assert titles["Casey Placeholder"] == "Research Professor"
    assert titles["Harper Sample"] == "Professor in Example Studies"
    assert rows["Avery Example"]["metadata"]["directory_section"] == "Faculty"


def test_a_research_subarea_in_the_title_field_is_no_title_and_the_profiles_role_title_is_read(monkeypatch):
    # The subarea card gets the title its profile's role card states; read as a
    # title, the subarea would have kept the profile from being consulted.
    rows = {r["pi_name"]: r for r in _fetch_physics(monkeypatch, profiles={"person4": "Assistant Professor"})}
    assert rows["Devon Example"]["metadata"]["directory_section"] == "Example Information Science"
    assert rows["Devon Example"]["metadata"]["faculty_title"] == "Assistant Professor"
    assert all("Example Matter Theory" not in r["metadata"]["faculty_title"] for r in rows.values())


def test_a_current_rank_in_an_engineering_directory_title_keeps_a_card_under_emeriti_listed(tmp_path, monkeypatch):
    stored = [_stored_physics_row(name, slug) for name, slug in
              (("Emery Sample", "person5"), ("Finley Placeholder", "person6"), ("Gray Example", "person7"))]
    rows = _merge(tmp_path, stored, _fetch_physics(monkeypatch))
    mixed = rows["Emery Sample"]
    assert mixed["metadata"]["directory_section"] == "Emeriti/Emeritae"
    assert _emeritus(mixed) == (True, None, False)
    assert mixed["metadata"]["faculty_title"] == "Example Endowed Chair Emeritus of Physics and Research Professor"
    # Ranks all emeritus: retired, under the heading or (by the title) under an ordinary one.
    assert _emeritus(rows["Finley Placeholder"]) == (False, "listed_as_emeritus", True)
    assert _emeritus(rows["Gray Example"]) == (False, "listed_as_emeritus", True)
    assert rows["Gray Example"]["metadata"]["directory_section"] == "Affiliated Faculty"
    assert rows["Gray Example"]["contact_email"] == "person7@illinois.edu"


# --- M149 round 5: each line of a div.title is a title of its own; a person
# listed with a current role shows that card's title, not an emeritus card's.
# Synthetic people. ---

def test_each_line_of_an_engineering_directory_title_is_a_title_of_its_own_and_an_inline_tag_breaks_none(monkeypatch):
    # Run together, "Professor Example Family Faculty Scholar" reads like a name.
    page = _person_items_page([("h3", "Faculty", [
        ("person1", "Avery Example", "Professor<p>Example <em>Family</em> Faculty Scholar</p>"),
        ("person2", "Blair Sample", "Research <strong>Professor</strong><br>Director, Example Center"),
        ("person3", "Casey Placeholder", "Assistant Professor")])])
    rows = {r["pi_name"]: r for r in _fetch_physics(monkeypatch, page=page)}
    assert rows["Avery Example"]["metadata"]["faculty_title"] == "Professor; Example Family Faculty Scholar"
    assert rows["Blair Sample"]["metadata"]["faculty_title"] == "Research Professor; Director, Example Center"
    assert rows["Casey Placeholder"]["metadata"]["faculty_title"] == "Assistant Professor"


def test_a_person_listed_twice_on_a_page_shows_the_current_cards_title_whichever_comes_last(tmp_path, monkeypatch):
    research = ("h3", "Research Faculty", [("person5", "Emery Sample", "Research Professor")])
    emeriti = ("h2", "Emeriti/Emeritae", [("person5", "Emery Sample", "Professor Emeritus")])
    for sections in ([research, emeriti], [emeriti, research]):
        page = _person_items_page([("h3", "Faculty", [("person1", "Avery Example", "Professor"),
                                                      ("person2", "Blair Sample", "Professor"),
                                                      ("person3", "Casey Placeholder", "Professor")])] + sections)
        row = _merge(tmp_path, [_stored_physics_row("Emery Sample", "person5")],
                     _fetch_physics(monkeypatch, page=page))["Emery Sample"]
        assert _emeritus(row) == (True, None, False), sections[0][1]
        md = row["metadata"]
        assert (md["faculty_title"], md["directory_section"]) == ("Research Professor", "Research Faculty"), sections[0][1]
    # The row is the current card, not the emeritus card relabelled, and keeps
    # the richer research areas either card states.
    def card(title, section, keywords):
        return normalize_faculty({"name": "Emery Sample", "email": "person5@illinois.edu", "title": title,
                                  "directory_section": section}, DEPARTMENTS["physics"], keywords=keywords)

    for richer in ("current", "emeritus"):
        for emeritus_last in (True, False):
            more = ["example nuclear physics", "example detectors", "example accelerators"]
            current = card("Research Professor", "Example Nuclear Physics", more if richer == "current" else ["physics"])
            emeritus = card("Professor Emeritus", "Emeriti/Emeritae", more if richer == "emeritus" else ["physics"])
            cards = _read_in_order([current, emeritus] if emeritus_last else [emeritus, current])
            expected = {k: v for k, v in current["metadata"].items() if k != "first_seen_at"}
            row = _merge(tmp_path, [], cards)["Emery Sample"]
            case = (richer, emeritus_last)
            assert {k: v for k, v in row["metadata"].items() if k != "first_seen_at"} == expected, case
            assert row["keywords"] == more, case


def test_a_listed_person_folded_with_their_emeritus_row_keeps_the_title_the_rows_own_profile_states(tmp_path):
    # Communication lists the person as a professor; Psychology under its
    # Emeritus heading, or as an emeritus with an active lab. One address folds
    # both into one row, whichever is richer and whichever is read first. The
    # person stays listed, but the row shows only the title its own card states:
    # the Communication card is for another profile.
    def card(dept, **person):
        return normalize_faculty({"name": "Devon Example", "email": "person4@illinois.edu",
                                  "url": f"{DEPARTMENTS[dept]['base']}/directory/profile/person4", **person},
                                 DEPARTMENTS[dept], keywords=["communication"])

    for psych_section in ("Emeritus Faculty", "Emeritus Faculty with active research labs"):
        for richer in ("comm", "psych"):
            for order in (("comm", "psych"), ("psych", "comm")):
                stored = card(richer, title="Professor")
                stored["keywords"] = ["persuasion", "health communication", "media effects"]
                stored["metadata"]["last_seen_at"] = "2026-10-05T14:18:05"
                fresh = {"comm": card("comm", title="Professor of Communication", directory_section="Faculty"),
                         "psych": card("psych", title="Professor Emeritus", directory_section=psych_section)}
                row = _merge(tmp_path, [stored], _read_in_order([fresh[d] for d in order]))["Devon Example"]
                case = (psych_section, richer, order)
                assert row["department"] == DEPARTMENTS[richer]["name"], case
                assert _emeritus(row) == (True, None, False), case
                md = row["metadata"]
                assert (md["faculty_title"], md["directory_section"]) == {
                    "comm": ("Professor of Communication", "Faculty"),
                    "psych": ("Professor Emeritus", psych_section)}[richer], case


# --- M149 round 6: a row shows another card's title only when that card is
# for the row's own profile; a listed row's current title always stays.
# Synthetic people. ---

def test_a_current_card_for_the_rows_own_profile_gives_a_row_shown_only_as_emeritus_its_title(tmp_path, monkeypatch):
    # Guard: one page lists the person under two name forms that link the same
    # profile, the fuller under an emeritus heading (or as an emeritus with an
    # active lab). The fuller row is kept, stays listed and shows the Research
    # Faculty card's title, whichever comes first.
    research = ("h3", "Research Faculty", [("person5", "Emery Sample", "Research Professor")])
    for heading in ("Emeriti/Emeritae", "Emeritus Faculty with active research labs"):
        emeriti = ("h2", heading, [("person5", "Emery Q. Sample", "Professor Emeritus")])
        for sections in ([research, emeriti], [emeriti, research]):
            page = _person_items_page([("h3", "Faculty", [("person1", "Avery Example", "Professor"),
                                                          ("person2", "Blair Sample", "Professor"),
                                                          ("person3", "Casey Placeholder", "Professor")])] + sections)
            rows = _merge(tmp_path, [], _fetch_physics(monkeypatch, page=page))
            case = (heading, sections[0][1])
            assert "Emery Sample" not in rows, case
            row = rows["Emery Q. Sample"]
            assert _emeritus(row) == (True, None, False), case
            md = row["metadata"]
            assert (md["faculty_title"], md["directory_section"]) == ("Research Professor", "Research Faculty"), case
            assert not {"source_url", "_listed_current"} & set(md), case


def test_a_listed_rows_title_is_the_one_its_own_profiles_card_states_this_run_never_another_profiles(tmp_path):
    # A stored row shows the title this run's card for the same profile states
    # (M149b: a stored title, the old "Professor" default among them, never
    # outlives it), and keeps its own when only another profile's card states
    # another title. The card may be an emeritus listed with an active lab.
    url = f"{DEPARTMENTS['physics']['base']}/people/directory/profile/person5"
    for title, section in (("Research Professor", "Research Faculty"),
                           ("Professor Emeritus", "Emeritus Faculty with active research labs")):
        stored = normalize_faculty({"name": "Emery Q. Sample", "email": "person5@illinois.edu", "url": url,
                                    "title": "Professor"}, DEPARTMENTS["physics"], keywords=["physics"])
        stored["metadata"]["last_seen_at"] = "2026-10-05T14:18:05"
        fresh = normalize_faculty({"name": "Emery Sample", "email": "person5@illinois.edu", "url": url,
                                   "title": title, "directory_section": section},
                                  DEPARTMENTS["physics"], keywords=["physics"])
        rows = _merge(tmp_path, [stored], [fresh])
        assert list(rows) == ["Emery Q. Sample"], title
        assert _emeritus(rows["Emery Q. Sample"]) == (True, None, False), title
        assert rows["Emery Q. Sample"]["metadata"]["faculty_title"] == title

    def card(dept, **person):
        return normalize_faculty({"name": "Devon Example", "email": "person4@illinois.edu",
                                  "url": f"{DEPARTMENTS[dept]['base']}/directory/profile/person4", **person},
                                 DEPARTMENTS[dept], keywords=["communication"])

    stored = card("comm", title="Professor of Communication", directory_section="Faculty")
    stored["keywords"] = ["persuasion", "health communication", "media effects"]
    stored["metadata"]["last_seen_at"] = "2026-10-05T14:18:05"
    rows = _merge(tmp_path, [stored], [card("psych", title="Research Professor", directory_section="Research Faculty")])
    assert list(rows) == ["Devon Example"] and rows["Devon Example"]["department"] == DEPARTMENTS["comm"]["name"]
    assert _emeritus(rows["Devon Example"]) == (True, None, False)
    md = rows["Devon Example"]["metadata"]
    assert (md["faculty_title"], md["directory_section"]) == ("Professor of Communication", "Faculty")


# --- M149b: a title the card (or the profile the run reads) states is read; one
# that states none gives no title, never a default rank. Synthetic people. ---

def test_an_engineering_directory_card_with_a_netid_states_its_title_abbreviated_or_without_a_rank(monkeypatch):
    # The directory's own record of the person (data-netid): its div.title is the
    # title. A research-area card's (no netid) names a subarea: no title.
    page = _person_items_page([
        ("h3", "Faculty", [("person1", "Avery Example", "Asst Prof"), ("person2", "Blair Sample", "RES PROF"),
                           ("person3", "Casey Placeholder", "Example Partnership Coordinator")]),
        ("h3", "Affiliates and Adjuncts", [("person8", "Harper Sample", "Department Affiliate")]),
        ("h3", "Example Information Science", [("person4", "Devon Example", "Example Matter Theory", True)]),
    ])
    titles = {r["pi_name"]: r["metadata"]["faculty_title"] for r in _fetch_physics(monkeypatch, page=page)}
    assert titles == {"Avery Example": "Asst Prof", "Blair Sample": "RES PROF",
                      "Casey Placeholder": "Example Partnership Coordinator",
                      "Harper Sample": "Department Affiliate", "Devon Example": ""}


def test_a_netid_cards_group_list_is_no_title(monkeypatch):
    # Bioengineering cards list groups in a second div.title; with the title
    # field missing, the groups ("Bioengineering") are not read as one.
    page = _person_items_page([("h3", "Faculty", [("person1", "Avery Example", "Professor")])]).replace(
        '<div class="title">Professor</div>', '<div class="title groups"><ul><li>Bioengineering</li></ul></div>')
    assert [r["metadata"]["faculty_title"] for r in _fetch_physics(monkeypatch, page=page)] == [""]


def test_an_abbreviated_current_rank_keeps_a_card_under_an_emeritus_heading_listed(tmp_path, monkeypatch):
    # "RES PROF" is a current rank (consumers read "Prof" as one); "PROF EMERITUS" is not.
    page = _person_items_page([
        ("h3", "Faculty", [("person1", "Avery Example", "Professor"), ("person2", "Blair Sample", "Professor"),
                           ("person3", "Casey Placeholder", "Professor")]),
        ("h2", "Emeritus Faculty", [("person5", "Emery Sample", "RES PROF"),
                                    ("person6", "Finley Placeholder", "PROF EMERITUS")])])
    rows = _merge(tmp_path, [], _fetch_physics(monkeypatch, page=page))
    assert _emeritus(rows["Emery Sample"]) == (True, None, False)
    assert _emeritus(rows["Finley Placeholder"]) == (False, "listed_as_emeritus", True)


ISCHOOL_TEASERS_PAGE = """<html><body><main><div class="component component--profile-listing">
  <div class="profile-teaser"><div class="profile-teaser__image-container">
    <a class="profile-teaser__image-link" href="/people/avery-example"><img alt="Avery Example"/></a></div>
    <div class="profile-teaser__text-container">
      <div class="profile-teaser__name"><a class="profile-teaser__link" href="/people/avery-example">Avery Example</a></div>
      <div class="profile-teaser__title">Teaching Assistant Professor and Example Program Director</div>
      <div class="profile-teaser__education">PhD, Example Studies</div></div></div>
  <div class="profile-teaser"><div class="profile-teaser__text-container">
      <div class="profile-teaser__name"><a class="profile-teaser__link" href="/people/blair-sample">Blair Sample</a></div>
      <div class="profile-teaser__title">Lecturer</div></div></div>
</div></main></body></html>"""


def test_an_ischool_teaser_states_the_title_under_its_name_link(monkeypatch):
    import src.collectors.uiuc_faculty as f

    monkeypatch.setattr(f, "_fetch_soup", lambda url: BeautifulSoup(ISCHOOL_TEASERS_PAGE, "html.parser")
                        if url == DEPARTMENTS["ischool"]["url"] else None)
    titles = {r["pi_name"]: r["metadata"]["faculty_title"] for r in f.fetch_department("ischool", enrich=False)}
    assert titles == {"Avery Example": "Teaching Assistant Professor and Example Program Director",
                      "Blair Sample": "Lecturer"}


def test_a_card_that_states_no_title_gets_none_and_its_text_names_no_rank():
    row = normalize_faculty({"name": "Avery Example", "url": f"{DEPARTMENTS['physics']['base']}/people/person1"},
                            DEPARTMENTS["physics"], keywords=["physics"])
    assert row["metadata"]["faculty_title"] == ""
    assert "Professor" not in row["description_raw"] and "for Avery Example in" in row["description_raw"]


def test_a_stored_title_does_not_outlive_this_runs_card_for_the_same_profile_and_the_title_it_states_is_kept(tmp_path):
    # The stored row (fuller name: the richer one, so the fold keeps it) carries
    # the "Professor" the old default wrote; this run's card for the same profile
    # decides the title: the one it states, none when it states none.
    url = f"{DEPARTMENTS['physics']['base']}/people/directory/profile/person5"
    for stated in ("Associate Professor", ""):
        stored = normalize_faculty({"name": "Emery Q. Sample", "email": "person5@illinois.edu", "url": url,
                                    "title": "Professor"}, DEPARTMENTS["physics"], keywords=["physics"])
        stored["metadata"]["last_seen_at"] = "2026-10-05T14:18:05"
        fresh = normalize_faculty({"name": "Emery Sample", "email": "person5@illinois.edu", "url": url,
                                   "directory_section": "Faculty"}, DEPARTMENTS["physics"], keywords=["physics"])
        fresh["metadata"]["faculty_title"] = stated
        rows = _merge(tmp_path, [stored], [fresh])
        assert list(rows) == ["Emery Q. Sample"], stated
        assert rows["Emery Q. Sample"]["metadata"]["faculty_title"] == stated
        assert _emeritus(rows["Emery Q. Sample"]) == (True, None, False), stated


def test_a_card_of_this_run_that_states_no_title_leaves_the_title_another_of_its_cards_states(tmp_path):
    url = f"{DEPARTMENTS['physics']['base']}/people/directory/profile/person1"

    def card(name, title, section):
        row = normalize_faculty({"name": name, "email": "person1@illinois.edu", "url": url, "title": title,
                                 "directory_section": section}, DEPARTMENTS["physics"], keywords=["physics"])
        row["metadata"]["faculty_title"] = title
        return row

    # Listed again under a research area, on a card stating none: the same row.
    rows = _merge(tmp_path, [], [card("Avery Example", "Associate Professor", "Faculty"),
                                 card("Avery Example", "", "Example Information Science")])
    assert rows["Avery Example"]["metadata"]["faculty_title"] == "Associate Professor"
    # A second spelling of the same profile read later this run, stating none: folded.
    rows = _merge(tmp_path, [], [card("Avery Q. Example", "Associate Professor", "Faculty"),
                                 card("Avery Example", "", "Example Information Science")])
    assert list(rows) == ["Avery Q. Example"]
    assert rows["Avery Q. Example"]["metadata"]["faculty_title"] == "Associate Professor"


def test_only_a_uiuc_rows_title_follows_a_newer_card_for_its_own_profile():
    # Other schools' rows (faculty_graph's collapse uses the same carry) keep
    # their title: their collectors never wrote a default rank.
    from src.collectors.uiuc_faculty import _carry_newest_liveness

    def row(source, seen, title):
        return {"source": source, "source_url": "https://a.example/profile/person4",
                "metadata": {"last_seen_at": seen, "is_active": True, "faculty_title": title}}

    for source, kept in (("uiuc_faculty", ""), ("example_faculty", "Professor")):
        survivor = row(source, "2026-10-05T00:00:00", "Professor")
        _carry_newest_liveness(survivor, row(source, "2026-10-26T00:00:00", ""))
        assert survivor["metadata"]["faculty_title"] == kept, source


def test_a_stored_default_title_does_not_survive_this_runs_untitled_card_for_the_same_id(tmp_path):
    url = f"{DEPARTMENTS['physics']['base']}/people/directory/profile/person1"
    stored = normalize_faculty({"name": "Avery Example", "email": "person1@illinois.edu", "url": url,
                                "title": "Professor"}, DEPARTMENTS["physics"], keywords=["physics"])
    stored["metadata"]["last_seen_at"] = "2026-10-05T14:18:05"
    fresh = normalize_faculty({"name": "Avery Example", "email": "person1@illinois.edu", "url": url,
                               "directory_section": "Faculty"}, DEPARTMENTS["physics"], keywords=["physics"])
    assert stored["id"] == fresh["id"]
    assert _merge(tmp_path, [stored], [fresh])["Avery Example"]["metadata"]["faculty_title"] == ""


def test_a_title_a_later_card_states_is_never_replaced_by_an_earlier_cards(tmp_path):
    url = f"{DEPARTMENTS['physics']['base']}/people/directory/profile/person1"

    def card(title, section):
        return normalize_faculty({"name": "Avery Example", "email": "person1@illinois.edu", "url": url,
                                  "title": title, "directory_section": section}, DEPARTMENTS["physics"],
                                 keywords=["physics"])

    rows = _merge(tmp_path, [], [card("Research Professor", "Research Faculty"), card("Associate Professor", "Faculty")])
    md = rows["Avery Example"]["metadata"]
    assert (md["faculty_title"], md["directory_section"]) == ("Associate Professor", "Faculty")
