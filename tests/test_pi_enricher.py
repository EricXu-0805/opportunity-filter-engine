"""Tests for the PI / contact-email enricher's school-domain generalization.

Every school's faculty must get email recovery on ITS OWN institutional
domain(s) — the machinery was UIUC-gated (illinois.edu hardcoded), leaving the
other schools with zero recovery. The network (_fetch_soup) is monkeypatched.
"""

from bs4 import BeautifulSoup

from src.collectors import pi_enricher
from src.collectors.pi_enricher import (
    SCHOOL_EMAIL_DOMAINS,
    _email_re,
    _extract_contact_from_generic_page,
    _school_domains,
    enrich_opportunities,
)


def test_school_domains_from_stamped_school_field():
    assert _school_domains({"school": "stanford"}) == ("stanford.edu",)
    assert _school_domains({"school": "uw"}) == ("washington.edu", "uw.edu")


def test_school_domains_falls_back_to_source_registry():
    # Fresh records aren't school-stamped until apply_school_audience runs
    # AFTER the enricher; the source registry must fill the gap.
    assert _school_domains({"source": "gatech_faculty"}) == ("gatech.edu",)
    assert _school_domains({"source": "ucb_eecs_faculty"}) == ("berkeley.edu",)


def test_school_domains_default_for_national_records():
    # SRO/REU records (school=None) keep the historical UIUC-only scope.
    assert _school_domains({"source": "uiuc_sro"}) == ("illinois.edu",)
    assert _school_domains({"source": "nsf_reu"}) == ("illinois.edu",)
    assert _school_domains({}) == ("illinois.edu",)


def test_every_registered_school_has_email_domains():
    from src.collectors.schools import SCHOOL_CONFIGS

    slugs = {cfg["school_slug"] for cfg in SCHOOL_CONFIGS} | {"uiuc", "ucb"}
    missing = slugs - set(SCHOOL_EMAIL_DOMAINS)
    assert not missing, f"schools without email-recovery domains: {missing}"


def test_email_re_matches_subdomains_never_lookalikes():
    pat = _email_re(("utexas.edu", "illinois.edu"))
    assert pat.findall("contact jdoe@austin.utexas.edu or x") == ["jdoe@austin.utexas.edu"]
    assert pat.findall("jdoe@utexas.edu") == ["jdoe@utexas.edu"]
    assert pat.findall("x@myillinois.edu spam@notutexas.edu") == []


def test_generic_page_extracts_own_school_email_only():
    soup = BeautifulSoup(
        "<p>Prof. Jane Roe — jroe@cs.stanford.edu (assistant: bob@gmail.com, "
        "peer: pal@illinois.edu)</p>", "html.parser")
    info = _extract_contact_from_generic_page(soup, ("stanford.edu",))
    assert info["contact_email"] == "jroe@cs.stanford.edu"


def _fac(source, url, school=None):
    opp = {"source": source, "source_type": "faculty_research",
           "pi_name": "Jane Roe", "url": url}
    if school:
        opp["school"] = school
    return opp


def _stub_page(monkeypatch, html):
    fetched = []

    def fake(url):
        fetched.append(url)
        return BeautifulSoup(html, "html.parser")

    monkeypatch.setattr(pi_enricher, "_fetch_soup", fake)
    monkeypatch.setattr(pi_enricher, "DELAY", 0)
    return fetched


def test_enrich_recovers_email_for_non_uiuc_faculty(monkeypatch):
    fetched = _stub_page(monkeypatch, "<p>Contact: jroe@wisc.edu</p>")
    opps = [_fac("wisc_faculty", "https://cs.wisc.edu/people/jane-roe")]
    stats = enrich_opportunities(opps)
    assert fetched == ["https://cs.wisc.edu/people/jane-roe"]
    assert stats["enriched"] == 1
    assert opps[0]["contact_email"] == "jroe@wisc.edu"


def test_enrich_never_scrapes_off_school_urls(monkeypatch):
    fetched = _stub_page(monkeypatch, "<p>jroe@stanford.edu</p>")
    opps = [_fac("stanford_faculty", "https://scholar.google.com/jane-roe")]
    stats = enrich_opportunities(opps)
    assert fetched == []
    assert stats["scraped"] == 0
    assert opps[0].get("contact_email") is None


def test_enrich_respects_scrape_budget(monkeypatch):
    fetched = _stub_page(monkeypatch, "<p>no email here</p>")
    opps = [
        _fac("uw_faculty", "https://ece.uw.edu/people/a"),
        _fac("uw_faculty", "https://ece.uw.edu/people/b"),
        _fac("uw_faculty", "https://ece.uw.edu/people/c"),
    ]
    stats = enrich_opportunities(opps, max_scrapes=2)
    assert len(fetched) == 2
    assert stats["scraped"] == 2
    assert stats["skipped_budget"] == 1


def test_enrich_fetches_nothing_after_the_deadline(monkeypatch):
    """The pass runs after every source, so the deadline is often gone by the
    time it starts; on 2026-10-01 it fetched past it until the job was killed."""
    fetched = _stub_page(monkeypatch, "<p>no email here</p>")
    opps = [
        _fac("uw_faculty", "https://ece.uw.edu/people/a"),
        _fac("uw_faculty", "https://ece.uw.edu/people/b"),
    ]
    stats = enrich_opportunities(opps, max_scrapes=1000, deadline=0.0)
    assert fetched == []
    assert stats["scraped"] == 0
    assert stats["skipped_deadline"] == 2


def test_enrich_fetches_normally_before_the_deadline(monkeypatch):
    import time

    fetched = _stub_page(monkeypatch, "<p>no email here</p>")
    opps = [_fac("uw_faculty", "https://ece.uw.edu/people/a")]
    stats = enrich_opportunities(opps, deadline=time.monotonic() + 3600)
    assert len(fetched) == 1
    assert stats["skipped_deadline"] == 0


def test_records_behind_a_rejected_certificate_skip_the_fetch_and_the_delay(monkeypatch):
    """On 2026-10-01 this pass fetched 54 www.math.ucla.edu profiles whose
    certificate failed verification, 2 s apart (DELAY follows every scrape),
    and each took a slot of the 1,000-scrape budget."""
    from src.collectors import ucb_common
    from tests.test_ucb_common import rejected_certificate

    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        raise rejected_certificate(url)

    slept: list[float] = []
    monkeypatch.setattr(pi_enricher.requests, "get", fake_get)
    monkeypatch.setattr(pi_enricher.time, "sleep", lambda s: slept.append(s))
    opps = [_fac("ucla_faculty", f"https://www.math.ucla.edu/people/ladder/p{i}", school="ucla")
            for i in range(5)]
    ucb_common.reset_certificate_circuit()
    try:
        stats = enrich_opportunities(opps, max_scrapes=3)
        report = ucb_common.rejected_certificate_report()
    finally:
        ucb_common.reset_certificate_circuit()

    assert calls == [opps[0]["url"]]
    assert slept == [pi_enricher.DELAY]
    assert (stats["scraped"], stats["skipped_certificate"], stats["skipped_budget"]) == (1, 4, 0)
    assert report == {"hosts": {"www.math.ucla.edu": 4}, "skipped": 4}


def test_profile_fetch_completes_the_incommon_chain(monkeypatch):
    """Georgia Tech's department sites omit their InCommon intermediate.

    ucb_common.fetch_soup has repaired that chain for months; this enricher
    calls requests.get itself and inherited certifi's default, so every one
    of those hosts failed verification. The 2026-08-08 run logged 210 such
    failures across arch/planning/id/music/ic/bc/cse.gatech.edu alone.
    """
    from src.collectors.ucb_common import _ca_bundle

    seen: dict = {}

    def fake_get(url, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop after capturing the request")

    monkeypatch.setattr(pi_enricher.requests, "get", fake_get)
    pi_enricher._fetch_soup("https://arch.gatech.edu/people/someone")

    assert seen.get("verify") == _ca_bundle()


def test_enrich_never_readdresses_a_tombstoned_record(monkeypatch):
    """`identity_bound: False` means the address was reviewed and rejected
    (clear_contact_claim nulls it). Scraping the page again put
    jiwon.kang@fsu.edu back next to that tombstone on the 09-21 and 09-28
    refreshes, and test_no_record_holds_an_address_and_a_tombstone failed
    each data PR after hours of scraping."""
    fetched = _stub_page(monkeypatch, "<p>Contact: jkang@fsu.edu</p>")
    opp = _fac("fsu_faculty", "https://stat.fsu.edu/person/jiwon-kang", school="fsu")
    opp["contact_email"] = None
    opp["metadata"] = {"identity_bound": False}
    stats = enrich_opportunities([opp])
    assert fetched == []
    assert opp["contact_email"] is None
    assert "email_source" not in opp["metadata"]
    assert stats["scraped"] == 0
    assert stats["skipped_tombstoned"] == 1
    assert stats["failed"] == 0
