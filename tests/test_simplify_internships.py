"""Deterministic guards for the simplify_internships collector. No network: the
listings.json fetch is mocked, so these exercise the active+visible filter, the
sponsorship -> work-authorization mapping, location/remote handling, epoch date
conversion and the opportunity-schema invariants the data-quality suite enforces.
"""

from __future__ import annotations

from src.collectors import simplify_internships as si
from src.collectors.simplify_internships import (
    _epoch_to_iso,
    _format_location,
    fetch_and_normalize,
    normalize_listing,
)

# A representative slice: an active+visible SWE role, an active+visible quant
# role requiring citizenship, an inactive row, a non-visible row, and a row
# missing required fields. Only the first two survive the filter.
FAKE_LISTINGS = [
    {
        "id": "9ca3adc3-491e-4dcb-9890-f84b262fb60f",
        "company_name": "Amazon",
        "title": "Software Development Engineer Internship",
        "url": "https://www.amazon.jobs/en/jobs/3101249",
        "locations": ["Seattle, WA", "USA"],
        "active": True,
        "is_visible": True,
        "date_posted": 1759741194,
        "sponsorship": "Offers Sponsorship",
        "terms": ["Summer 2026"],
        "category": "Software Engineering",
    },
    {
        "id": "11111111-2222-3333-4444-555555555555",
        "company_name": "Citadel",
        "title": "Quant Research Intern",
        "url": "https://citadel.com/careers/123",
        "locations": ["New York, NY"],
        "active": True,
        "is_visible": True,
        "date_posted": 1759000000,
        "sponsorship": "U.S. Citizenship is Required",
        "terms": ["Summer 2026", "N/A"],
        "category": "Quant",
    },
    {  # inactive -> filtered out
        "id": "dead0000-0000-0000-0000-000000000000",
        "company_name": "ClosedCo",
        "title": "Expired Intern",
        "url": "https://x.com",
        "locations": ["Remote"],
        "active": False,
        "is_visible": True,
        "sponsorship": "Other",
        "category": "Software",
    },
    {  # not visible -> filtered out
        "id": "hide0000-0000-0000-0000-000000000000",
        "company_name": "HiddenCo",
        "title": "Hidden Intern",
        "url": "https://y.com",
        "locations": ["Austin, TX"],
        "active": True,
        "is_visible": False,
        "sponsorship": "Other",
        "category": "Hardware",
    },
    {  # missing title -> dropped by normalize
        "id": "miss0000-0000-0000-0000-000000000000",
        "company_name": "NoTitleCo",
        "title": "",
        "url": "https://z.com",
        "locations": ["USA"],
        "active": True,
        "is_visible": True,
        "sponsorship": "Other",
        "category": "Other",
    },
]


def test_filter_keeps_only_active_and_visible(monkeypatch):
    monkeypatch.setattr(si, "fetch_listings", lambda url=si.LISTINGS_URL: FAKE_LISTINGS)
    opps = fetch_and_normalize()
    titles = {o["title"] for o in opps}

    assert titles == {
        "Software Development Engineer Internship", "Quant Research Intern",
    }
    assert all(o["opportunity_type"] == "internship" for o in opps)
    assert all(o["source"] == "simplify_internships" for o in opps)


def test_stable_id_from_listing_uuid(monkeypatch):
    monkeypatch.setattr(si, "fetch_listings", lambda url=si.LISTINGS_URL: FAKE_LISTINGS)
    opps = {o["organization"]: o for o in fetch_and_normalize()}
    assert opps["Amazon"]["id"] == "simplify-intern-9ca3adc3-491e-4dcb-9890-f84b262fb60f"


def test_sponsorship_maps_to_work_authorization():
    offers = normalize_listing(FAKE_LISTINGS[0])["eligibility"]
    assert offers["international_friendly"] == "yes"
    assert offers["citizenship_required"] is False

    citizen = normalize_listing(FAKE_LISTINGS[1])["eligibility"]
    assert citizen["international_friendly"] == "no"
    assert citizen["citizenship_required"] is True
    assert "citizenship" in citizen["work_auth_notes"].lower()


def test_category_seeds_keywords_and_majors():
    amazon = normalize_listing(FAKE_LISTINGS[0])
    assert "software engineering" in amazon["keywords"]
    assert "Computer Science" in amazon["eligibility"]["majors"]


def test_na_term_is_stripped_from_duration():
    citadel = normalize_listing(FAKE_LISTINGS[1])
    assert citadel["duration"] == "Summer 2026"  # the "N/A" term is dropped


def test_remote_and_named_location_handling():
    # A bare USA marker beside a named city is on-site at the named city.
    loc, remote = _format_location(["Seattle, WA", "USA"])
    assert loc == "Seattle, WA" and remote == "unknown"
    # Bare remote markers only -> Remote.
    loc, remote = _format_location(["USA"])
    assert loc == "Remote" and remote == "remote"
    loc, remote = _format_location([])
    assert loc == "Unknown" and remote == "unknown"


def test_epoch_to_iso_roundtrip():
    assert _epoch_to_iso(1759741194) == "2025-10-06"
    assert _epoch_to_iso(0) is None
    assert _epoch_to_iso(None) is None
    assert _epoch_to_iso("not-an-int") is None


def test_normalized_record_honors_data_quality_contract(monkeypatch):
    monkeypatch.setattr(si, "fetch_listings", lambda url=si.LISTINGS_URL: FAKE_LISTINGS)
    for o in fetch_and_normalize():
        assert "description_clean" in o
        assert len(o["description_clean"]) <= 1500
        assert o["deadline"] is None and o["is_rolling"] is True
        assert o["contact_email"] is None
        assert o["metadata"]["is_active"] is True


def test_missing_required_fields_returns_none():
    assert normalize_listing({"id": "x", "title": "", "company_name": "Y"}) is None
    assert normalize_listing({"id": "", "title": "T", "company_name": "Y"}) is None
