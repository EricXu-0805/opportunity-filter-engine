"""Deterministic guards for the uiuc_faculty collector's department registry
and the section-label filter that keeps directory headings ("Postdocs",
"Affiliates and Adjuncts") out of the faculty data. No network: the live
scrape runs in the refresh pipeline, not in CI.
"""

from __future__ import annotations

from src.collectors.uiuc_faculty import (
    DEPARTMENTS,
    _dedup_faculty_records,
    _extract_research_keywords,
    _is_section_label,
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
