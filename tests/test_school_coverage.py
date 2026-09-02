"""School coverage is unique listings PLUS unique faculty contacts — everywhere.

The switcher chip and the first-visit confirmation gate answer "how big is this
campus?", and they used to answer it with the listings half of a two-map API
response. Faculty contacts are ~97% of the corpus, so JHU showed 28 against a
real 4,581 — and the static fallback, which counted both halves, meant the chip
fell from ~4,500 to 28 the moment the live fetch landed.

These tests pin the contract at every hop: the aggregation, the wire shape, the
committed static fallback, and the cache that stands between them.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.lib.school_coverage import (
    SCHOOL_COVERAGE_SCHEMA,
    SchoolCoverage,
    coverage_payload,
    school_coverage,
)
from backend.routes import opportunities as opportunity_routes

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHOOL_STATS_PATH = REPO_ROOT / "frontend" / "src" / "lib" / "school-stats.json"

# Exercise the production release scope, not the conftest override that turns
# every dormant feature on. The count these tests pin is the one users see, and
# the static fallback is generated under production semantics — comparing the
# two under a different scope would compare two universes.
RELEASE_CONTRACT_TESTS = True


def _listing(**overrides) -> dict:
    """An actionable campus listing. Rolling, active, reviewed source type."""
    record = {
        "id": "listing-1",
        "school": "uiuc",
        "source": "uiuc_program",
        "source_type": "campus_program",
        "opportunity_type": "research",
        "title": "Summer program",
        "is_rolling": True,
        "metadata": {"is_active": True},
    }
    record.update(overrides)
    return record


def _faculty(**overrides) -> dict:
    """An actionable faculty contact."""
    record = {
        "id": "faculty-1",
        "school": "uiuc",
        "source": "uiuc_faculty",
        "source_type": "faculty_research",
        "opportunity_type": "research",
        "title": "Prof. A — CS",
        "pi_name": "A",
        "metadata": {"is_active": True},
    }
    record.update(overrides)
    return record


@pytest.fixture(autouse=True)
def _clear_coverage_cache():
    opportunity_routes._coverage_cache = None
    yield
    opportunity_routes._coverage_cache = None


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

class TestAggregation:
    def test_listings_only_school_totals_its_listings(self):
        coverage = school_coverage([
            _listing(id="l1"),
            _listing(id="l2"),
        ])
        assert coverage["uiuc"] == SchoolCoverage(
            listing_count=2, faculty_contact_count=0, unreviewed_count=0
        )
        assert coverage["uiuc"].total_count == 2

    def test_faculty_only_school_totals_its_contacts(self):
        """UC Davis is the real shape of this: a campus whose faculty directory
        is WAF-blocked has listings and no contacts; the inverse (a faculty
        directory with no program pages) is far more common. Either way the
        empty half is a verified zero, not a reason to omit the school."""
        coverage = school_coverage([
            _faculty(id="f1"),
            _faculty(id="f2"),
            _faculty(id="f3"),
        ])
        assert coverage["uiuc"].listing_count == 0
        assert coverage["uiuc"].faculty_contact_count == 3
        assert coverage["uiuc"].total_count == 3

    def test_school_with_both_totals_the_sum(self):
        coverage = school_coverage([
            _listing(id="l1"),
            _listing(id="l2"),
            _faculty(id="f1"),
            _faculty(id="f2"),
            _faculty(id="f3"),
        ])
        entry = coverage["uiuc"]
        assert entry.listing_count == 2
        assert entry.faculty_contact_count == 3
        assert entry.total_count == entry.listing_count + entry.faculty_contact_count == 5

    def test_faculty_heavy_school_is_not_understated_by_its_listing_count(self):
        """The bug, in miniature: 1 listing beside 200 contacts. A listings-only
        total reports 1 — a 201x understatement — which is what shipped."""
        records = [_listing(id="l1")] + [_faculty(id=f"f{i}") for i in range(200)]
        entry = school_coverage(records)["uiuc"]
        assert entry.listing_count == 1
        assert entry.total_count == 201

    def test_duplicate_listing_rows_do_not_inflate_the_total(self):
        """The loader canonicalizes the corpus unique-by-id before anything
        counts it, so the guard that matters is that counting goes through that
        pipeline. Same id twice must land as one product entity."""
        from backend.data_loader import _canonicalize_corpus

        raw = [_listing(id="l1"), _listing(id="l1"), _listing(id="l2")]
        assert school_coverage(_canonicalize_corpus(raw))["uiuc"].listing_count == 2

    def test_duplicate_faculty_rows_do_not_inflate_the_total(self):
        from backend.data_loader import _canonicalize_corpus

        raw = [_faculty(id="f1"), _faculty(id="f1"), _faculty(id="f1")]
        assert school_coverage(_canonicalize_corpus(raw))["uiuc"].faculty_contact_count == 1

    def test_an_unreviewed_source_type_never_counts_as_a_listing(self):
        """An unfamiliar source type proves neither an opening nor a contact.

        Two gates keep it out of the total, and this asserts the outer one holds
        while the inner one exists. Actionability rejects an unclassifiable
        record first (`record_kind_unverified`), so `unreviewed_count` reads 0
        here rather than 1. The bucket is still spelled out in
        `school_coverage` because the pre-fix route bucketed with
        `if faculty else listing` — under which this record would have been
        published as a verified opening the moment the actionability gate moved.
        """
        coverage = school_coverage([
            _listing(id="l1"),
            _faculty(id="f1"),
            _listing(id="u1", source_type="mystery_feed"),
        ])
        entry = coverage["uiuc"]
        assert entry.listing_count == 1  # NOT 2 — the mystery row is not an opening
        assert entry.total_count == 2
        assert entry.total_count == entry.listing_count + entry.faculty_contact_count

    def test_the_unreviewed_bucket_is_outside_the_total_by_construction(self):
        """The inner gate, checked directly: whatever lands in `unreviewed_count`
        is absent from `total_count`, so a future actionability change cannot
        quietly promote unclassified records into coverage."""
        entry = SchoolCoverage(
            listing_count=3, faculty_contact_count=7, unreviewed_count=99
        )
        assert entry.total_count == 10

    def test_inactive_records_are_excluded_from_both_halves(self):
        coverage = school_coverage([
            _listing(id="l1"),
            _listing(id="l2", metadata={"is_active": False}),
            _faculty(id="f1"),
            _faculty(id="f2", metadata={"is_active": False}),
        ])
        assert coverage["uiuc"].listing_count == 1
        assert coverage["uiuc"].faculty_contact_count == 1
        assert coverage["uiuc"].total_count == 2

    def test_a_school_with_nothing_is_absent_rather_than_zero(self):
        """Absence is the unknown state the client renders as "campus data in
        progress". A zero entry would be a measurement we never made."""
        coverage = school_coverage([_listing(id="l1", school="uiuc")])
        assert "mit" not in coverage
        assert set(coverage) == {"uiuc"}

    def test_national_records_belong_to_no_school(self):
        """Every school sees the open pool, so folding it into one card
        overstates that card — and summed across the grid it would be counted
        once per school."""
        coverage = school_coverage([
            _listing(id="n1", school=None, source="simplify", source_type="internship"),
            _listing(id="n2", school="", source="nsf", source_type="external_reu"),
            _listing(id="l1"),
        ])
        assert coverage == {"uiuc": SchoolCoverage(listing_count=1)}

    def test_slug_comes_from_the_school_field_not_the_source_prefix(self):
        """The source-prefix heuristic disagreed with the shard key three ways;
        this is the one that silently dropped records — a UIUC Handshake listing
        whose source prefix is `handshake`."""
        coverage = school_coverage([
            _listing(id="h1", source="handshake", source_type="internship"),
        ])
        assert coverage["uiuc"].listing_count == 1
        assert "handshake" not in coverage


# --------------------------------------------------------------------------
# Wire contract
# --------------------------------------------------------------------------

class TestWireContract:
    def test_payload_states_its_schema_and_per_school_totals(self):
        payload = coverage_payload([_listing(id="l1"), _faculty(id="f1")])
        assert payload["schema"] == SCHOOL_COVERAGE_SCHEMA
        assert payload["schools"]["uiuc"] == {
            "listing_count": 1,
            "faculty_contact_count": 1,
            "unreviewed_count": 0,
            "total_count": 2,
        }

    def test_route_serves_the_canonical_total_not_a_listings_map(self, monkeypatch):
        """The regression guard on the original defect: the response must not
        offer a listings-only field under a name a client would mistake for the
        count. `counts` is gone; `total_count` is the number."""
        monkeypatch.setattr(
            opportunity_routes,
            "load_opportunities",
            lambda: [_listing(id="l1"), _faculty(id="f1"), _faculty(id="f2")],
        )
        payload = asyncio.run(opportunity_routes.opportunity_coverage())

        assert "counts" not in payload
        assert "faculty_contacts" not in payload
        assert payload["schema"] == SCHOOL_COVERAGE_SCHEMA
        entry = payload["schools"]["uiuc"]
        assert entry["total_count"] == 3
        assert entry["total_count"] == entry["listing_count"] + entry["faculty_contact_count"]

    def test_every_school_in_the_response_satisfies_the_invariant(self, monkeypatch):
        monkeypatch.setattr(
            opportunity_routes,
            "load_opportunities",
            lambda: [
                _listing(id="l1", school="uiuc"),
                _faculty(id="f1", school="uiuc"),
                _faculty(id="f2", school="mit", source="mit_faculty"),
                _listing(id="l2", school="ucd", source="ucd_program"),
            ],
        )
        payload = asyncio.run(opportunity_routes.opportunity_coverage())
        assert set(payload["schools"]) == {"uiuc", "mit", "ucd"}
        for slug, entry in payload["schools"].items():
            assert entry["total_count"] == (
                entry["listing_count"] + entry["faculty_contact_count"]
            ), slug

    def test_release_hidden_records_are_excluded_from_both_halves(self, monkeypatch):
        """The old test asserted this for listings only, so a release-gated
        faculty record leaking into the faculty map would not have been caught."""
        monkeypatch.setattr(
            opportunity_routes,
            "load_opportunities",
            lambda: [
                _listing(id="l1"),
                _listing(id="hidden-l", opportunity_type="fellowship"),
                _faculty(id="f1"),
                _faculty(id="hidden-f", opportunity_type="fellowship"),
            ],
        )
        payload = asyncio.run(opportunity_routes.opportunity_coverage())
        entry = payload["schools"]["uiuc"]
        assert entry["listing_count"] == 1
        assert entry["faculty_contact_count"] == 1
        assert entry["total_count"] == 2


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

class TestCache:
    def test_counts_are_recomputed_when_the_corpus_version_changes(self, monkeypatch):
        """Keyed by corpus version, not a clock, so a cached total can never
        outlive the dataset it counted — the failure mode that would otherwise
        serve pre-refresh numbers for the rest of a TTL."""
        corpus = [_faculty(id="f1")]
        version = {"v": "1"}
        monkeypatch.setattr(opportunity_routes, "load_opportunities", lambda: corpus)
        monkeypatch.setattr(opportunity_routes, "corpus_version", lambda: version["v"])

        first = asyncio.run(opportunity_routes.opportunity_coverage())
        assert first["schools"]["uiuc"]["total_count"] == 1

        corpus.append(_faculty(id="f2"))
        # Same version: the cached answer stands.
        assert asyncio.run(
            opportunity_routes.opportunity_coverage()
        )["schools"]["uiuc"]["total_count"] == 1

        version["v"] = "2"
        assert asyncio.run(
            opportunity_routes.opportunity_coverage()
        )["schools"]["uiuc"]["total_count"] == 2

    def test_a_legacy_cached_entry_is_never_served(self, monkeypatch):
        """A pre-fix process-local cache entry holds a listings-only body. It
        must lose on the version key rather than be handed out."""
        opportunity_routes._coverage_cache = ("stale", {"counts": {"uiuc": 28}})
        monkeypatch.setattr(
            opportunity_routes, "load_opportunities", lambda: [_faculty(id="f1")]
        )
        monkeypatch.setattr(opportunity_routes, "corpus_version", lambda: "fresh")

        payload = asyncio.run(opportunity_routes.opportunity_coverage())
        assert "counts" not in payload
        assert payload["schools"]["uiuc"]["total_count"] == 1


# --------------------------------------------------------------------------
# Static fallback
# --------------------------------------------------------------------------

class TestStaticFallback:
    @pytest.fixture(scope="class")
    def committed(self) -> dict:
        return json.loads(SCHOOL_STATS_PATH.read_text())

    def test_committed_fallback_declares_the_current_schema(self, committed):
        assert committed["schema"] == SCHOOL_COVERAGE_SCHEMA
        assert isinstance(committed["national_count"], int)
        assert committed["schools"]

    def test_committed_fallback_follows_the_listings_plus_faculty_definition(self, committed):
        for slug, entry in committed["schools"].items():
            assert entry["total_count"] == (
                entry["listing_count"] + entry["faculty_contact_count"]
            ), slug

    def test_committed_fallback_is_not_a_legacy_listings_only_artifact(self, committed):
        """The pre-fix file was `{slug: {campus, national}}` — a shape with no
        room for the split, which is how it went unnoticed that the live number
        meant something else."""
        assert "campus" not in json.dumps(committed["schools"])[:200]
        for slug, entry in committed["schools"].items():
            assert set(entry) == {
                "listing_count",
                "faculty_contact_count",
                "unreviewed_count",
                "total_count",
            }, slug
        # A faculty-heavy school proves the faculty half is really in there: if
        # this file had been generated listings-only, jhu would read ~27.
        jhu = committed["schools"].get("jhu")
        if jhu:
            assert jhu["faculty_contact_count"] > 100 * max(jhu["listing_count"], 1)
            assert jhu["total_count"] > 1000

    def test_committed_fallback_matches_what_the_generator_produces_now(self):
        """The fallback and the live API are one claim made at two times, so the
        only way they stay equal is being generated from the same function. This
        is the drift alarm: a data refresh that does not regenerate the fallback
        fails here rather than shipping a stale first paint."""
        result = subprocess.run(
            [sys.executable, "scripts/gen_school_stats.py", "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout

    def test_live_and_fallback_agree_school_for_school_on_the_real_corpus(self, committed):
        """The end-to-end consistency invariant: same school, same dataset, same
        coverage number on both sides. This is the assertion the original bug
        would have failed by two orders of magnitude on almost every school."""
        from backend.data_loader import load_opportunities

        live = coverage_payload(load_opportunities())
        assert live["schools"] == committed["schools"]


# --------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------

class TestHttpSurface:
    @pytest.fixture
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient

        from backend.main import app

        monkeypatch.setattr(
            opportunity_routes,
            "load_opportunities",
            lambda: [_listing(id="l1"), _faculty(id="f1"), _faculty(id="f2")],
        )
        return TestClient(app)

    def test_the_served_body_carries_the_schema_and_the_total(self, client):
        """Serialized through the response model, not just returned from the
        function — the alias is what puts `schema` on the wire, and the client's
        legacy-body gate reads exactly that key."""
        body = client.get("/api/opportunities/coverage").json()
        assert body["schema"] == SCHOOL_COVERAGE_SCHEMA
        assert body["schools"]["uiuc"] == {
            "listing_count": 1,
            "faculty_contact_count": 2,
            "unreviewed_count": 0,
            "total_count": 3,
        }

    def test_the_body_offers_no_field_a_client_could_mistake_for_the_total(self, client):
        """`counts` was a per-school listings map sitting where a caller
        reasonably expected the count. Nothing in the response may read that way
        again — the only school-level number is `total_count` and the two named
        halves it is the sum of."""
        body = client.get("/api/opportunities/coverage").json()
        assert set(body) == {"schema", "schools"}
        assert "counts" not in body
        for entry in body["schools"].values():
            assert set(entry) == {
                "listing_count",
                "faculty_contact_count",
                "unreviewed_count",
                "total_count",
            }

    def test_count_semantics_do_not_depend_on_who_is_asking(self, client):
        """Coverage describes the corpus, not the caller. An anonymous visitor
        on their first paint and a signed-in student must be told the same size
        for the same campus, or the first-visit gate and the switcher would
        disagree across a sign-in."""
        anonymous = client.get("/api/opportunities/coverage").json()
        signed_in = client.get(
            "/api/opportunities/coverage",
            headers={"Authorization": "Bearer some-student-token"},
        ).json()
        other_session = client.get(
            "/api/opportunities/coverage",
            headers={"Cookie": "session=someone-else"},
        ).json()
        assert anonymous == signed_in == other_session
