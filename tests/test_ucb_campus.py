"""Tests for the UC Berkeley campus-wide opportunity collector + registry.

Exercises the seed path only (no network) — the live BFS crawl lazy-imports its
HTTP deps and is not unit-tested here. Locks in the invariants the data-quality
gate and the multi-school scope filter depend on, so a registry edit can't
silently ship records that break either.
"""

from __future__ import annotations

import pytest

from src.collectors import ucb_campus
from src.collectors import ucb_sources as reg
from src.normalizers.school_audience import SOURCE_DEFAULTS, VALID_AUDIENCES


# --- Registry integrity ----------------------------------------------------

class TestRegistry:
    def test_registry_is_structurally_valid(self):
        assert reg.validate_registry() == []

    def test_all_five_source_types_present(self):
        present = {s["source_type"] for s in reg.UCB_SOURCES}
        assert reg.SOURCE_TYPES <= present, (
            f"missing source types: {reg.SOURCE_TYPES - present}"
        )

    def test_source_names_unique(self):
        names = reg.all_source_names()
        assert len(names) == len(set(names))

    def test_program_keys_unique(self):
        keys = [p["key"] for _, p in reg.iter_programs()]
        assert len(keys) == len(set(keys))

    def test_every_emit_bucket_maps_to_source_defaults(self):
        """Each emit bucket must resolve to a (source, school, audience) whose
        (school, audience) matches school_audience.SOURCE_DEFAULTS — the
        contract the DQ gate enforces."""
        for emit, (source, school, audience) in ucb_campus.EMIT_TO_SCHOOL_AUDIENCE.items():
            assert emit in reg.EMIT_BUCKETS
            assert source in SOURCE_DEFAULTS
            assert SOURCE_DEFAULTS[source] == (school, audience)


# --- Seed normalization -----------------------------------------------------

@pytest.fixture(scope="module")
def seed_records():
    return ucb_campus.fetch_and_normalize(deep=False)


class TestSeedNormalization:
    def test_produces_many_records(self, seed_records):
        # The whole point is breadth — expect well past the URAP+faculty baseline
        # delta the acceptance criteria call for.
        assert len(seed_records) >= 50

    def test_every_record_has_required_schema_fields(self, seed_records):
        for o in seed_records:
            assert o["id"] and o["title"] and o["url"]
            assert isinstance(o["eligibility"], dict)
            assert isinstance(o["metadata"], dict)
            assert isinstance(o["keywords"], list)
            assert "description_clean" in o
            assert len(o["description_clean"]) <= 1500

    def test_ids_unique(self, seed_records):
        ids = [o["id"] for o in seed_records]
        assert len(ids) == len(set(ids))

    def test_school_audience_matches_source_defaults(self, seed_records):
        for o in seed_records:
            assert o["audience"] in VALID_AUDIENCES
            assert (o["school"], o["audience"]) == SOURCE_DEFAULTS[o["source"]]

    def test_no_pi_or_contact_email(self, seed_records):
        """Program/lab pages are not individuals — leaving pi_name/contact_email
        unset keeps them out of the ucb_* shared-email/name DQ gate."""
        for o in seed_records:
            assert o.get("pi_name") is None
            assert o.get("contact_email") is None

    def test_rolling_with_no_deadline(self, seed_records):
        """No structured deadlines (cycles live in the description), so every
        record must be rolling — otherwise deactivate_past can't reason about it
        and the UI shows a blank timing block."""
        for o in seed_records:
            assert o.get("deadline") is None
            assert o.get("is_rolling") is True

    def test_clear_separation_of_levels(self, seed_records):
        """Program / lab / department / career / announcement must each be
        represented and individually addressable via ucb_source_type."""
        levels = {o["ucb_source_type"] for o in seed_records}
        assert {"program", "lab", "department", "career", "announcement"} <= levels

    def test_summer_programs_typed_for_seasonal_boost(self, seed_records):
        summer = [o for o in seed_records if o["opportunity_type"] == "summer_program"]
        assert summer, "expected some summer_program records for the seasonal boost"


# --- Source breakdown -------------------------------------------------------

class TestSourceBreakdown:
    def test_breakdown_totals_consistent(self, seed_records):
        bd = ucb_campus.source_breakdown(seed_records)
        assert bd["total"] == len(seed_records)
        assert sum(bd["by_source_type"].values()) == len(seed_records)
        assert sum(bd["by_emit_bucket"].values()) == len(seed_records)
