"""Offline tests for shared ucb_common boundary behavior.

Focus: normalize_faculty must reject scraped "names" that are actually
institution/place labels. An Open-Berkeley directory card occasionally
mis-selects a non-person element (a "UC Berkeley" footer link, a breadcrumb,
a section heading) as a faculty name; sharing a normalized value like
"berkeley" these records enter the corpus as pi_name="Berkeley" and trip the
joint-appointment dedup data-quality gate (TestR70ADataQuality), which blocks
the entire scheduled data refresh. Guard at the universal normalization
boundary so any of the 41 collectors is covered.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_common import _is_person_name, normalize_faculty

_CONFIG = {
    "short": "IB",
    "name": "Integrative Biology",
    "source": "ucb_ib_faculty",
    "majors": ["Biology"],
    "keywords": ["biology"],
}


def test_is_person_name_rejects_institution_labels():
    for bad in [
        "Berkeley",
        "UC Berkeley",
        "University of California",
        "Department of Statistics",
        "School of Information",
        "  ",
        "",
    ]:
        assert not _is_person_name(bad), f"should reject {bad!r}"


def test_is_person_name_keeps_real_people():
    # Including the edge case of a real person whose name contains a place token.
    for good in ["David Ackerly", "Doris Bachtrog", "Li Wei", "Berkeley Breathed"]:
        assert _is_person_name(good), f"should keep {good!r}"


def test_normalize_faculty_drops_institution_name():
    assert normalize_faculty({"name": "Berkeley", "url": "https://x/y"}, _CONFIG) is None
    assert (
        normalize_faculty({"name": "University of California", "url": "https://x/z"}, _CONFIG)
        is None
    )


def test_normalize_faculty_keeps_real_person():
    opp = normalize_faculty({"name": "David Ackerly", "url": "https://x/a"}, _CONFIG)
    assert opp is not None
    assert opp["pi_name"] == "David Ackerly"


def test_normalize_faculty_strips_navmenu_from_description():
    """Regression: nav-furniture reaching research_areas (e.g. a BioE profile
    excerpt) must not survive into description_clean — the DQ gate forbids it.
    The defensive strip on the fully assembled description guarantees this no
    matter how the phrase entered."""
    nav = [
        "Once Research Secured", "Administration & Staff", "Colloquia Calendar",
        "Affiliated Faculty", "Labs & Facilities", "Research Institutes and Centers",
    ]
    person = {
        "name": "Jane Doe",
        "url": "https://x/jane",
        "title": "Professor",
        "research_areas": (
            "tissue engineering; Labs & Facilities Research Institutes and "
            "Centers Affiliated Faculty Administration & Staff"
        ),
    }
    opp = normalize_faculty(person, _CONFIG)
    assert opp is not None
    for phrase in nav:
        assert phrase not in opp["description_clean"], f"leaked: {phrase!r}"
        assert phrase not in opp["eligibility"]["eligibility_text_raw"]
    # the real research area survives
    assert "tissue engineering" in opp["description_clean"]


def test_null_shared_and_unit_mailbox_emails():
    """UIUC-aligned DQ: a dept/coordinator inbox shared by 2+ different ucb_*
    professors, or a generic unit mailbox local-part, is nulled — so a re-scrape
    can't reintroduce a shared-email DQ failure or a misfiring cold-email target,
    without hand-maintaining NOISE_EMAILS. Personal emails are kept."""
    from src.collectors.ucb_common import (
        _null_shared_contact_emails,
        _null_unit_mailbox_emails,
    )
    opps = [
        {"source": "ucb_tdps_faculty", "source_type": "faculty_research",
         "pi_name": "Alice A", "contact_email": "tdps@berkeley.edu"},
        {"source": "ucb_tdps_faculty", "source_type": "faculty_research",
         "pi_name": "Bob B", "contact_email": "tdps@berkeley.edu"},
        {"source": "ucb_music_faculty", "source_type": "faculty_research",
         "pi_name": "Carol C", "contact_email": "office@music.berkeley.edu"},
        {"source": "ucb_music_faculty", "source_type": "faculty_research",
         "pi_name": "Dan D", "contact_email": "dan@berkeley.edu"},
    ]
    assert _null_shared_contact_emails(opps) == 2   # both tdps@ records
    assert _null_unit_mailbox_emails(opps) == 1     # office@
    assert [o["contact_email"] for o in opps] == [None, None, None, "dan@berkeley.edu"]


def test_derive_keywords_from_raw_enriches_broad_only():
    """UCB analog of UIUC's Experts enrichment: a broad-only ucb_* faculty record
    with stored research_areas_raw gets specific keywords mined from that text,
    and its title parenthetical is rebuilt to stay a subset of the keywords."""
    import re

    from src.collectors.ucb_common import _derive_keywords_from_raw
    opp = {
        "source": "ucb_stat_faculty", "source_type": "faculty_research",
        "pi_name": "Jane Doe", "department": "Department of Statistics",
        "keywords": ["statistics"],  # broad-only
        "title": "Research with Prof. Jane Doe — STAT (statistics)",
        "metadata": {"research_areas_raw":
                     "nonparametric estimation; shape-constrained inference; bayesian methods"},
    }
    n = _derive_keywords_from_raw([opp])
    assert n == 1
    assert opp["keywords"] == ["nonparametric estimation", "shape-constrained inference",
                               "bayesian methods"]
    # title parenthetical rebuilt and ⊆ keywords (the DQ invariant)
    shown = set(re.search(r"\((.+)\)$", opp["title"]).group(1).split(", "))
    assert shown <= set(opp["keywords"])
    assert "statistics" not in opp["title"]  # stale broad field dropped


def test_derive_keywords_skips_already_specific():
    from src.collectors.ucb_common import _derive_keywords_from_raw
    opp = {"source": "ucb_cs_faculty", "source_type": "faculty_research",
           "pi_name": "X Y", "department": "EECS",
           "keywords": ["machine learning", "computer vision"],
           "title": "Research with Prof. X Y — EECS (machine learning, computer vision)",
           "metadata": {"research_areas_raw": "robotics; control"}}
    assert _derive_keywords_from_raw([opp]) == 0  # already has specific keywords


def test_incommon_ca_bundle_appends_intermediates_to_certifi():
    """The CA bundle fetch_soup uses must include certifi's roots AND the bundled
    InCommon intermediates, so an incomplete-chain .edu host verifies without
    ever falling back to verify=False. Offline: just inspect the bundle file.
    """
    from pathlib import Path

    import certifi

    from src.collectors import ucb_common

    pem = Path(ucb_common.__file__).parent / "incommon_intermediates.pem"
    text = pem.read_text()
    assert text.count("BEGIN CERTIFICATE") == 2
    assert "InCommon RSA Server CA 2" in text  # UCLA Physics / UW Stat
    assert "InCommon RSA OV SSL CA 3" in text  # UCLA Statistics

    ucb_common._CA_BUNDLE = None  # force a fresh build
    bundle = ucb_common._ca_bundle()
    combined = Path(bundle).read_text()
    assert "InCommon RSA Server CA 2" in combined
    assert len(combined) > len(Path(certifi.where()).read_text())


class TestReadableExcerptChrome:
    def test_strip_page_chrome_removes_skip_and_toggle(self):
        from src.collectors.ucb_common import _strip_page_chrome
        out = _strip_page_chrome("Real content here Skip to main content Toggle navigation Home About")
        assert "skip to" not in out.lower()
        assert "toggle navigation" not in out.lower()
        assert "Real content here" in out

    def test_readable_excerpt_prefers_main_landmark(self):
        from bs4 import BeautifulSoup

        from src.collectors.ucb_common import _readable_excerpt
        html = (
            "<html><body><nav>Home About People Faculty</nav>"
            "<a href='#main'>Skip to main content</a>"
            "<main>Undergraduate research in observational astrophysics.</main>"
            "<footer>Instagram Linkedin</footer></body></html>"
        )
        soup = BeautifulSoup(html, "html.parser")
        out = _readable_excerpt(soup)
        assert out == "Undergraduate research in observational astrophysics."

    def test_readable_excerpt_drops_chrome_dump_without_main(self):
        # No main landmark and the page text carries chrome -> return nothing
        # rather than ship a nav dump into the description.
        from bs4 import BeautifulSoup

        from src.collectors.ucb_common import _readable_excerpt
        html = "<html><body><div>Skip to content Home About People Faculty Staff</div></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        assert _readable_excerpt(soup) == ""
