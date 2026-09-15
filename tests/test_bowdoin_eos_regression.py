"""The Bowdoin EOS false positive, frozen so it can never come back.

On 2026-09-11 the mandated manual sample caught the retirement pass proposing
to deactivate Rachel Beane — Bass Professor of Natural Sciences, and visibly
present on the very roster the collector had just scraped. The unit scored a
perfect 6-observed-of-6-active, so every count-based completeness measure read
it as a complete scrape and treated her absence as proof of departure.

She was absent from nothing. The directory had changed how it writes her name
("Rachel J. Beane" -> "Rachel Beane"), ids are md5(dept_short + display_name),
so the rename minted a new id: one phantom departure, one phantom arrival,
count unchanged and therefore invisible.

The fixture is that page, captured verbatim. The tests below pin both halves:
identity survives the rename, and a count ratio cannot see the problem at all.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from src.collectors import faculty_graph as fg
from src.normalizers.deactivate_stale_faculty import (
    GRACE_DAYS,
    MIN_SCRAPE_RATIO,
    deactivate_stale_faculty,
    finalize_unit_ledger,
    identity_key,
    unit_retirement_authority,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bowdoin_eos_roster.html"
TODAY = date(2026, 9, 12)
LONG_AGO = (TODAY - timedelta(days=GRACE_DAYS + 40)).isoformat()
RECENT = (TODAY - timedelta(days=2)).isoformat()

DEPT = {
    "short": "EOS",
    "name": "Department of Earth and Oceanographic Science",
    "majors": ["Earth and Oceanographic Science"],
    "directory_url": "https://www.bowdoin.edu/earth-oceanographic-science/faculty-and-staff/index.html",
    "scrape": {
        "url": "https://www.bowdoin.edu/earth-oceanographic-science/faculty-and-staff/index.html",
        "selectors": {
            "card": "article.profile-card",
            "name": "h4.profile-card-name a",
            "link": "h4.profile-card-name a",
            "title": "em.profile-card-title",
        },
        "section_filter": {"heading": "h2", "include": "^faculty$"},
        "ladder_filter": {
            "drop": "emerit|adjunct|visiting|postdoc|research affiliate|teaching fellow"
        },
    },
}
SCHOOL = {
    "school_slug": "bowdoin", "organization": "Bowdoin College",
    "id_prefix": "bowdoin", "source": "bowdoin_faculty",
    "location": "Brunswick, ME", "audience": "external",
    "departments": [DEPT],
}

# The corpus as it stood: the directory still wrote her middle initial.
BEANE_URL = "https://www.bowdoin.edu/profiles/faculty/rbeane/index.html"
BASELINE_NAMES = [
    ("faculty-bowdoin-eos-b01d2a34", "Rachel J. Beane", BEANE_URL, LONG_AGO),
    ("faculty-bowdoin-eos-7e410a37", "Philip Camill",
     "https://www.bowdoin.edu/profiles/faculty/pcamill/index.html", RECENT),
    ("faculty-bowdoin-eos-b3dc8172", "Jabari Jones",
     "https://www.bowdoin.edu/profiles/faculty/j.jones/index.html", RECENT),
    ("faculty-bowdoin-eos-e5cbebe2", "Michèle LaVigne",
     "https://www.bowdoin.edu/profiles/faculty/mlavign/index.html", RECENT),
    ("faculty-bowdoin-eos-4bdbb7e4", "Emily M. Peterman",
     "https://www.bowdoin.edu/profiles/faculty/epeterma/index.html", RECENT),
    ("faculty-bowdoin-eos-b1dc4caf", "Collin Roesler",
     "https://www.bowdoin.edu/profiles/faculty/croesler/index.html", RECENT),
]


def _baseline():
    return [
        {
            "id": rid, "source": "bowdoin_faculty",
            "source_type": "faculty_research", "school": "bowdoin",
            "department": DEPT["name"], "pi_name": name, "url": url,
            "metadata": {"is_active": True, "last_seen_at": seen},
        }
        for rid, name, url, seen in BASELINE_NAMES
    ]


def _observe():
    """Parse the captured roster exactly as the engine would."""
    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser")
    fg._ACTIVE_COVERAGE = fg._new_coverage()
    try:
        specs = fg._parse_cards(
            soup, DEPT["scrape"]["selectors"], DEPT["directory_url"],
            DEPT["scrape"].get("ladder_filter"), False, None,
            DEPT["scrape"].get("section_filter"), None,
        )
        coverage = dict(fg._ACTIVE_COVERAGE)
    finally:
        fg._ACTIVE_COVERAGE = None
    produced = [r for s in specs if (r := fg._normalize(SCHOOL, DEPT, s))]
    return produced, coverage


def test_the_roster_really_does_still_contain_her():
    """If this fails the fixture drifted, and every other test here is moot."""
    html = FIXTURE.read_text(encoding="utf-8")
    assert "Rachel Beane" in html
    assert BEANE_URL in html
    produced, _ = _observe()
    assert any(r["pi_name"] == "Rachel Beane" for r in produced)


def test_the_rename_really_does_mint_a_different_id():
    """The mechanism of the false positive, pinned."""
    produced, _ = _observe()
    observed_ids = {r["id"] for r in produced}
    assert "faculty-bowdoin-eos-b01d2a34" not in observed_ids, (
        "the stored id must NOT match, or there is no false positive to guard")
    assert any(r["pi_name"] == "Rachel Beane" for r in produced)


def test_count_ratio_cannot_see_the_problem():
    """Why the old measure was insufficient — the heart of the regression.

    Six rows observed against six active records is a perfect ratio. The old
    rule authorised retirement on exactly this, and Beane would have been
    deactivated while listed on the page.
    """
    produced, _ = _observe()
    baseline = _baseline()
    assert len(produced) == len(baseline) == 6
    # The old rule, reconstructed verbatim.
    old_rule_authorises = len(produced) >= MIN_SCRAPE_RATIO * len(baseline)
    assert old_rule_authorises is True
    # And under it, her stored id is absent from the observed id set.
    observed_ids = {r["id"] for r in produced}
    assert "faculty-bowdoin-eos-b01d2a34" not in observed_ids


def test_identity_survives_the_rename():
    produced, _ = _observe()
    observed_identities = {identity_key(r) for r in produced}
    stored_beane = next(r for r in _baseline()
                        if r["id"] == "faculty-bowdoin-eos-b01d2a34")
    assert identity_key(stored_beane) in observed_identities


def test_unit_is_identity_complete_and_still_retires_nobody():
    """The strong result: the unit IS complete, and she is still preserved.

    Blocking the whole unit would also have saved her, but for the wrong
    reason — this asserts the pass can hold a unit to be fully observed and
    STILL not retire someone it actually saw.
    """
    produced, coverage = _observe()
    baseline = _baseline()
    ledger = {"eos": fg._unit_observation(
        SCHOOL, DEPT, produced, "2026-09-12T00:00:00+00:00", coverage=coverage)}
    finalize_unit_ledger(ledger, baseline, "bowdoin_faculty")

    entry = ledger["eos"]
    assert entry["coverage"]["raw_roster_rows"] == 9
    assert entry["coverage"]["parsed_faculty_rows"] == 6
    assert entry["coverage"]["classified_nonfaculty_rows"] == 3
    assert entry["coverage"]["unparsed_rows"] == 0
    assert entry["completeness_status"] == "complete"
    assert entry["retirement_authorized"] is True
    assert entry["matched_identity_count"] == 6
    assert entry["new_identity_count"] == 0
    authorised, reason = unit_retirement_authority(entry, len(baseline))
    assert authorised is True
    assert reason == "identity_complete_unit_observation"

    out = deactivate_stale_faculty(baseline, {"bowdoin_faculty": ledger},
                                   today=TODAY, dry_run=True)
    assert out["records_retirement_authorized"] == 0
    assert out["proposals"] == []
    beane = next(r for r in baseline
                 if r["id"] == "faculty-bowdoin-eos-b01d2a34")
    assert beane["metadata"]["is_active"] is True


def test_a_genuinely_departed_professor_is_still_retired_here():
    """The guard must not be a blanket refusal — absence must still work."""
    produced, coverage = _observe()
    baseline = _baseline()
    departed = {
        "id": "faculty-bowdoin-eos-11111111", "source": "bowdoin_faculty",
        "source_type": "faculty_research", "school": "bowdoin",
        "department": DEPT["name"], "pi_name": "Someone Who Left",
        "url": "https://www.bowdoin.edu/profiles/faculty/sleft/index.html",
        "metadata": {"is_active": True, "last_seen_at": LONG_AGO},
    }
    baseline.append(departed)
    ledger = {"eos": fg._unit_observation(
        SCHOOL, DEPT, produced, "2026-09-12T00:00:00+00:00", coverage=coverage)}
    finalize_unit_ledger(ledger, baseline, "bowdoin_faculty")
    out = deactivate_stale_faculty(baseline, {"bowdoin_faculty": ledger},
                                   today=TODAY)
    assert departed["metadata"]["is_active"] is False
    beane = next(r for r in baseline
                 if r["id"] == "faculty-bowdoin-eos-b01d2a34")
    assert beane["metadata"]["is_active"] is True
    assert out["newly_deactivated"] == 1


def test_one_unparsed_row_blocks_the_whole_unit():
    """Parser loss must never hide behind an aggregate."""
    produced, coverage = _observe()
    coverage = {**coverage, "unparsed_rows": 1, "raw_roster_rows": 10}
    ledger = {"eos": fg._unit_observation(
        SCHOOL, DEPT, produced, "2026-09-12T00:00:00+00:00", coverage=coverage)}
    finalize_unit_ledger(ledger, _baseline(), "bowdoin_faculty")
    assert ledger["eos"]["retirement_authorized"] is False
    authorised, reason = unit_retirement_authority(ledger["eos"], 6)
    assert authorised is False
    assert reason == "blocked_unparsed_rows"
