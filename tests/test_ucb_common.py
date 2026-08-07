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
        "Contact Us",
        "Learn More",
        "Read More",
        "Support",
        "Research Areas",
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


class TestMergeCarriesForwardEnrichment:
    def test_broad_rescrape_does_not_clobber_prior_enrichment(self, tmp_path, monkeypatch):
        """merge_into_processed must carry richer prior keywords forward, or a
        fresh broad dept re-scrape silently wipes enrichment (the guard the
        UIUC/faculty_graph paths already had; ucb_common lacked it)."""
        import json as _json

        from src.collectors import ucb_common as uc

        pf = tmp_path / "opportunities.json"
        enriched = {
            "id": "ucb-enrich-1",
            "source": "ucb_mcb_faculty",
            "source_type": "faculty_research",
            "pi_name": "Jane Roe",
            "department": "Molecular & Cell Biology",
            "keywords": ["genomics", "genetics", "evolution"],
            "title": "Research with Prof. Jane Roe — MCB (genomics)",
            "contact_email": None,
            "metadata": {"first_seen_at": "2026-01-01T00:00:00Z", "research_areas_raw": ""},
        }
        pf.write_text(_json.dumps([enriched]))
        monkeypatch.setattr(uc, "PROCESSED_FILE", pf)

        broad_rescrape = {
            "id": "ucb-enrich-1",
            "source": "ucb_mcb_faculty",
            "source_type": "faculty_research",
            "pi_name": "Jane Roe",
            "department": "Molecular & Cell Biology",
            "keywords": ["biology"],  # dept-label-only re-scrape
            "title": "Research with Prof. Jane Roe — MCB",
            "contact_email": None,
            "metadata": {"first_seen_at": "2026-06-01T00:00:00Z", "research_areas_raw": ""},
        }
        uc.merge_into_processed([broad_rescrape])

        saved = {o["id"]: o for o in _json.loads(pf.read_text())}["ucb-enrich-1"]
        assert saved["keywords"] == ["genomics", "genetics", "evolution"]


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


# --- 429 rate-limit circuit (W7a) -------------------------------------------

class Test429Circuit:
    """fetch_soup respects Retry-After (capped) and, after consecutive 429s
    from one host, skips that host's remaining URLs for the run. In-memory
    only; other hosts are unaffected."""

    import pytest as _pytest

    @_pytest.fixture(autouse=True)
    def _clean_circuit(self):
        from src.collectors import ucb_common
        ucb_common._reset_rate_limit_circuit()
        yield
        ucb_common._reset_rate_limit_circuit()

    def _install_fake_session(self, monkeypatch, status_by_host, calls, retry_after=None):
        import requests

        from src.collectors import ucb_common

        class FakeSession:
            def __init__(self):
                self.headers = {}
                self.verify = True

            def get(self, url, timeout=None):
                calls.append(url)
                host = url.split("/")[2]
                resp = requests.Response()
                resp.status_code = status_by_host.get(host, 200)
                resp.url = url
                resp._content = b"<html><body>ok</body></html>"
                if retry_after is not None and resp.status_code == 429:
                    resp.headers["Retry-After"] = retry_after
                return resp

        monkeypatch.setattr(ucb_common.requests, "Session", FakeSession)
        monkeypatch.setattr(ucb_common.time, "sleep", lambda s: None)

    def test_circuit_opens_after_consecutive_429s_and_spares_other_hosts(self, monkeypatch):
        from src.collectors import ucb_common
        calls: list[str] = []
        self._install_fake_session(
            monkeypatch, {"limited.berkeley.edu": 429}, calls)

        for _ in range(ucb_common._RATE_LIMIT_THRESHOLD):
            assert ucb_common.fetch_soup(
                "https://limited.berkeley.edu/x", max_retries=1) is None
        n_before = len(calls)
        # circuit open: no request is issued for this host any more
        assert ucb_common.fetch_soup(
            "https://limited.berkeley.edu/y", max_retries=1) is None
        assert len(calls) == n_before
        # a different host is untouched
        assert ucb_common.fetch_soup(
            "https://fine.berkeley.edu/z", max_retries=1) is not None
        assert len(calls) == n_before + 1

    def test_success_resets_the_streak(self, monkeypatch):
        from src.collectors import ucb_common
        calls: list[str] = []
        status = {"flaky.berkeley.edu": 429}
        self._install_fake_session(monkeypatch, status, calls)

        for _ in range(ucb_common._RATE_LIMIT_THRESHOLD - 1):
            ucb_common.fetch_soup("https://flaky.berkeley.edu/x", max_retries=1)
        status["flaky.berkeley.edu"] = 200
        assert ucb_common.fetch_soup(
            "https://flaky.berkeley.edu/ok", max_retries=1) is not None
        status["flaky.berkeley.edu"] = 429
        # streak restarted — one more 429 must not open the circuit
        ucb_common.fetch_soup("https://flaky.berkeley.edu/x2", max_retries=1)
        assert "flaky.berkeley.edu" not in ucb_common._rate_limited_hosts

    def test_retry_after_respected_and_capped(self, monkeypatch):
        from src.collectors import ucb_common
        calls: list[str] = []
        self._install_fake_session(
            monkeypatch, {"slow.berkeley.edu": 429}, calls, retry_after="999")
        slept: list[float] = []
        monkeypatch.setattr(ucb_common.time, "sleep", lambda s: slept.append(s))

        ucb_common.fetch_soup("https://slow.berkeley.edu/x", max_retries=2)
        assert slept == [ucb_common._RETRY_AFTER_CAP]  # 999 capped to 120

    def test_unparseable_retry_after_falls_back_to_backoff(self, monkeypatch):
        from src.collectors import ucb_common
        calls: list[str] = []
        self._install_fake_session(
            monkeypatch, {"odd.berkeley.edu": 429}, calls,
            retry_after="Wed, 21 Oct 2026 07:28:00 GMT")
        slept: list[float] = []
        monkeypatch.setattr(ucb_common.time, "sleep", lambda s: slept.append(s))

        ucb_common.fetch_soup("https://odd.berkeley.edu/x", max_retries=2)
        assert slept == [ucb_common._RETRY_BACKOFF]


# --- Open-Berkeley person-template fallbacks (W7a) ---------------------------

class TestOpenBerkeleyTemplateFallback:
    """The standard field-openberkeley-person-* wrappers (verified live on
    ourenvironment.berkeley.edu person pages, 2026-07) are extracted even when
    a department config carries no bespoke selectors."""

    _OB_PROFILE = """
    <html><body class="node-type-openberkeley-person">
      <h1>David Ackerly</h1>
      <div class="field-name-field-openberkeley-person-title">
        <div class="field-item">Title: Dean and Professor</div>
      </div>
      <div class="field-name-field-openberkeley-person-email">dackerly@berkeley.edu</div>
      <div class="field-name-field-resint">
        <div class="field-items"><div class="field-item">Plant ecology, climate change</div></div>
      </div>
    </body></html>
    """

    def _soup(self):
        from bs4 import BeautifulSoup
        return BeautifulSoup(self._OB_PROFILE, "html.parser")

    def test_email_found_without_config_selector(self):
        from src.collectors.ucb_common import extract_email_from_profile
        assert extract_email_from_profile(self._soup(), _CONFIG) == "dackerly@berkeley.edu"

    def test_research_found_without_config_selector(self):
        from src.collectors.ucb_common import extract_research_interests
        assert "Plant ecology" in extract_research_interests(self._soup(), _CONFIG)

    def test_configured_selectors_still_win(self):
        from bs4 import BeautifulSoup

        from src.collectors.ucb_common import extract_research_interests
        cfg = {**_CONFIG, "selectors": {"research_interests": ["div.custom .field-item"]}}
        html = ('<div class="custom"><div class="field-item">Custom text</div></div>'
                '<div class="field-name-field-resint"><div class="field-item">OB text</div></div>')
        got = extract_research_interests(BeautifulSoup(html, "html.parser"), cfg)
        assert got == "Custom text"

    def test_enrich_recovers_missing_title_and_stamps_provenance(self, monkeypatch):
        from src.collectors import ucb_common
        monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: self._soup())
        person = {"name": "David Ackerly", "url": "https://x/people/david-ackerly"}
        ucb_common.enrich_faculty_from_profiles([person], _CONFIG)
        assert person["title"] == "Dean and Professor"  # "Title:" label stripped
        assert person["email"] == "dackerly@berkeley.edu"
        assert person["_email_source"] == "profile_page"
        assert person["_verification_scope"] == "profile"

    def test_failed_fetch_leaves_person_unstamped(self, monkeypatch):
        from src.collectors import ucb_common
        monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: None)
        person = {"name": "A B", "url": "https://x/people/a-b", "email": "kept@berkeley.edu"}
        ucb_common.enrich_faculty_from_profiles([person], _CONFIG)
        assert person["email"] == "kept@berkeley.edu"
        assert "_verification_scope" not in person
        assert "_email_source" not in person

    def test_http_200_denial_page_does_not_stamp_profile_scope(
        self,
        monkeypatch,
    ):
        from bs4 import BeautifulSoup

        from src.collectors import ucb_common

        denial = BeautifulSoup(
            "<html><title>Access denied</title>"
            "<body>Please enable JavaScript and verify you are human.</body></html>",
            "html.parser",
        )
        monkeypatch.setattr(ucb_common, "fetch_soup", lambda _url: denial)
        person = {
            "name": "David Ackerly",
            "url": "https://x/people/david-ackerly",
        }

        ucb_common.enrich_faculty_from_profiles([person], _CONFIG)

        assert "_verification_scope" not in person
        assert "_email_source" not in person

    def test_sign_in_page_echoing_name_is_not_identity_evidence(
        self,
        monkeypatch,
    ):
        from bs4 import BeautifulSoup

        from src.collectors import ucb_common

        denial = BeautifulSoup(
            "<html><title>Authentication required</title><h1>Sign in</h1>"
            "<p>Sign in to view David Ackerly</p>"
            "<p>dackerly@berkeley.edu</p></html>",
            "html.parser",
        )
        monkeypatch.setattr(ucb_common, "fetch_soup", lambda _url: denial)
        person = {
            "name": "David Ackerly",
            "url": "https://x/people/david-ackerly",
        }

        ucb_common.enrich_faculty_from_profiles([person], _CONFIG)

        assert "_verification_scope" not in person
        assert "email" not in person


class TestProfileIdentityGate:
    def _soup(self, html):
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "html.parser")

    def test_strong_login_wall_phrases_ignore_body_length(self):
        from src.collectors.ucb_common import profile_page_is_denial

        filler = "substantive faculty biography " * 100
        for phrase in (
            "Authentication required",
            "Authentication is required",
            "Sign-in required",
            "Login required",
            "You must be logged in",
            "You must be signed-in",
            "Sign into account",
            "Log into your account",
            "Sign in to continue",
            "Log in to view this profile",
            "Sign in to access this profile",
            "Please enable JavaScript",
            "JavaScript is required to view this page",
            "JavaScript must be enabled",
            "Please turn on JavaScript",
            "This site requires JS",
            "Cookies are required to continue",
            "Cookies are disabled",
            "Browser must accept cookies",
            "Your browser must allow cookies",
            "Please allow cookies",
            "Enable browser cookies",
            "401 Unauthorized",
            "403: Unauthorized",
            "You are not authorized",
            "Access is restricted",
        ):
            soup = self._soup(
                f"<html><h1>Ada Lovelace</h1><p>{filler}</p>"
                f"<div class='overlay'>{phrase}</div></html>"
            )

            assert len(soup.get_text(" ", strip=True)) > 1200
            assert profile_page_is_denial(soup) is True, phrase

    def test_bare_navigation_sign_in_does_not_block_a_long_profile(self):
        from src.collectors.ucb_common import profile_page_is_denial

        filler = "substantive faculty biography " * 100
        soup = self._soup(
            f"<html><nav>Sign in</nav><h1>Ada Lovelace</h1>"
            f"<p>{filler}</p>"
            "<footer>This site uses cookies for analytics.</footer></html>"
        )

        assert len(soup.get_text(" ", strip=True)) > 1200
        assert profile_page_is_denial(soup) is False

    def test_explicit_identity_selector_disables_default_fallbacks(self):
        from src.collectors.ucb_common import profile_page_matches_person

        soup = self._soup(
            "<html><title>Ada Lovelace</title><h1>Ada Lovelace</h1>"
            "<div class='canonical-name'>Grace Hopper</div></html>"
        )

        assert profile_page_matches_person(
            soup,
            "Ada Lovelace",
            identity_selectors=".canonical-name",
        ) is False

    def test_decorated_wrong_h1_and_related_h2_cannot_be_bypassed(self):
        from src.collectors.ucb_common import profile_page_matches_person

        soup = self._soup(
            "<html><title>Ada Lovelace | Faculty</title>"
            "<h1>Grace Hopper | Faculty Profile</h1>"
            "<h2>Related faculty: Ada Lovelace</h2></html>"
        )

        assert profile_page_matches_person(soup, "Ada Lovelace") is False

    def test_long_wrong_strong_identity_blocks_matching_weak_title(self):
        from src.collectors.ucb_common import profile_page_matches_person

        suffix = (
            "Distinguished Chair in Computational Science, Electrical Systems, "
            "Applied Mathematics, Biomedical Innovation, and Public Policy, "
            "Department of Advanced Interdisciplinary Engineering"
        )
        soup = self._soup(
            "<html><title>Ada Lovelace | Faculty</title>"
            f"<h1>Grace Hopper | {suffix}</h1></html>"
        )

        assert len(soup.h1.get_text(" ", strip=True)) > 80
        assert profile_page_matches_person(soup, "Ada Lovelace") is False

    def test_any_non_generic_strong_identity_blocks_matching_weak_title(self):
        from src.collectors.ucb_common import profile_page_matches_person

        soup = self._soup(
            "<html><title>Ada Lovelace | Faculty</title>"
            "<h1>Grace</h1></html>"
        )

        assert profile_page_matches_person(soup, "Ada Lovelace") is False

    def test_generic_heading_allows_matching_browser_title(self):
        from src.collectors.ucb_common import profile_page_matches_person

        soup = self._soup(
            "<html><title>Ada Lovelace | Faculty</title>"
            "<h1>Faculty Profile</h1></html>"
        )

        assert profile_page_matches_person(soup, "Ada Lovelace") is True


# --- Additive contact provenance (W7a) ---------------------------------------

class TestContactProvenance:
    """Provenance is extra information, never a gate: a person spec without
    hints — listing-supplied email, un-migrated collector, legacy record —
    normalizes exactly as before and KEEPS its email."""

    def test_email_without_provenance_is_first_class(self):
        person = {"name": "Jane Doe", "url": "https://x/p/jane",
                  "title": "Professor", "email": "jdoe@berkeley.edu"}
        opp = normalize_faculty(person, _CONFIG)
        assert opp["contact_email"] == "jdoe@berkeley.edu"
        assert "email_source" not in opp["metadata"]
        assert "verification_scope" not in opp["metadata"]

    def test_hints_copied_into_metadata(self):
        person = {"name": "Jane Doe", "url": "https://x/p/jane",
                  "title": "Professor", "email": "jdoe@berkeley.edu",
                  "_email_source": "profile_page", "_verification_scope": "profile"}
        opp = normalize_faculty(person, _CONFIG)
        assert opp["contact_email"] == "jdoe@berkeley.edu"
        assert opp["metadata"]["email_source"] == "profile_page"
        assert opp["metadata"]["verification_scope"] == "profile"

    def test_email_source_not_stamped_without_email(self):
        person = {"name": "Jane Doe", "url": "https://x/p/jane",
                  "title": "Professor", "_email_source": "profile_page"}
        opp = normalize_faculty(person, _CONFIG)
        assert opp["contact_email"] is None
        assert "email_source" not in opp["metadata"]

    def test_clear_contact_claim_drops_stale_provenance(self):
        from src.collectors.ucb_common import clear_contact_claim
        opp = {"contact_email": "shared@berkeley.edu",
               "metadata": {"email_source": "profile_page", "faculty_title": "Professor"}}
        clear_contact_claim(opp)
        assert opp["contact_email"] is None
        assert "email_source" not in opp["metadata"]
        assert opp["metadata"]["faculty_title"] == "Professor"  # rest untouched

    def test_nulling_paths_clear_provenance(self):
        from src.collectors.ucb_common import (
            _null_shared_contact_emails,
            _null_unit_mailbox_emails,
        )
        opps = [
            {"source": "ucb_tdps_faculty", "source_type": "faculty_research",
             "pi_name": "Alice A", "contact_email": "tdps@berkeley.edu",
             "metadata": {"email_source": "profile_page"}},
            {"source": "ucb_tdps_faculty", "source_type": "faculty_research",
             "pi_name": "Bob B", "contact_email": "tdps@berkeley.edu",
             "metadata": {}},
            {"source": "ucb_music_faculty", "source_type": "faculty_research",
             "pi_name": "Carol C", "contact_email": "office@music.berkeley.edu",
             "metadata": {"email_source": "profile_page"}},
        ]
        assert _null_shared_contact_emails(opps) == 2
        assert _null_unit_mailbox_emails(opps) == 1
        assert all(o["contact_email"] is None for o in opps)
        assert all("email_source" not in o["metadata"] for o in opps)
