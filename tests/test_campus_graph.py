"""Tests for the generic campus-graph engine + the per-school configs it drives.

Exercises the seed path only (no network) — the live BFS crawl lazy-imports its
HTTP deps and is not unit-tested here. Locks in the invariants the data-quality
gate and the multi-school scope filter depend on, so adding/editing a school
config can't silently ship records that break either.

This is the Top-50 rollout's safety net: every school in
``schools.SCHOOL_CONFIGS`` is validated and normalized the same way, so the test
surface grows automatically as the registry grows — no per-school test file.
"""

from __future__ import annotations

import pytest

from src.collectors import campus_graph as cg
from src.collectors.schools import SCHOOL_CONFIGS
from src.collectors.schools.boulder import SCHOOL as BOULDER
from src.collectors.schools.princeton import SCHOOL as PRINCETON
from src.collectors.schools.uci import SCHOOL as UCI
from src.collectors.schools.ucsb import SCHOOL as UCSB
from src.collectors.schools.ucsd import SCHOOL as UCSD
from src.normalizers.school_audience import SOURCE_DEFAULTS, VALID_AUDIENCES

# --- Registry integrity ----------------------------------------------------

class TestRegistry:
    def test_registry_non_empty(self):
        assert SCHOOL_CONFIGS, "expected at least one school config"

    def test_every_config_is_structurally_valid(self):
        for cfg in SCHOOL_CONFIGS:
            assert cg.validate(cfg) == [], f"{cfg.get('school_slug')}: {cg.validate(cfg)}"

    def test_school_slugs_unique(self):
        slugs = [c["school_slug"] for c in SCHOOL_CONFIGS]
        assert len(slugs) == len(set(slugs))

    def test_every_emit_bucket_maps_to_source_defaults(self):
        """Each config's emit map must resolve to a (source, school, audience)
        whose (school, audience) matches school_audience.SOURCE_DEFAULTS — the
        contract the DQ gate enforces."""
        for cfg in SCHOOL_CONFIGS:
            for _bucket, (source, school, audience) in cfg["emit"].items():
                assert source in SOURCE_DEFAULTS, f"{source} missing from SOURCE_DEFAULTS"
                assert SOURCE_DEFAULTS[source] == (school, audience), (
                    f"{source}: config {(school, audience)} != "
                    f"SOURCE_DEFAULTS {SOURCE_DEFAULTS[source]}"
                )

    def test_program_keys_unique_within_each_school(self):
        for cfg in SCHOOL_CONFIGS:
            keys = [p["key"] for s in cfg["sources"] for p in s.get("programs", [])]
            assert len(keys) == len(set(keys)), f"{cfg['school_slug']}: dup program key"


# --- Validator catches bad configs -----------------------------------------

class TestValidator:
    def test_missing_slug_flagged(self):
        assert any("school_slug" in e for e in cg.validate({"emit": {}, "sources": []}))

    def test_bad_emit_bucket_flagged(self):
        bad = {"school_slug": "x", "emit": {"wat": ("s", "x", "campus")}, "sources": []}
        assert any("emit bucket" in e for e in cg.validate(bad))

    def test_bad_source_type_flagged(self):
        bad = {
            "school_slug": "x",
            "emit": {"campus": ("s", "x", "campus")},
            "sources": [{"source_name": "n", "source_type": "bogus", "emit": "campus",
                         "crawl": cg.STATIC, "seeds": ["http://x"], "programs": []}],
        }
        assert any("source_type" in e for e in cg.validate(bad))

    def test_source_emit_not_in_map_flagged(self):
        bad = {
            "school_slug": "x",
            "emit": {"campus": ("s", "x", "campus")},
            "sources": [{"source_name": "n", "source_type": cg.PROGRAM, "emit": "lab",
                         "crawl": cg.STATIC, "seeds": ["http://x"], "programs": []}],
        }
        assert any("not in school's emit map" in e for e in cg.validate(bad))

    def test_fetch_rejects_invalid_config(self):
        with pytest.raises(ValueError):
            cg.fetch_and_normalize({"school_slug": "x", "emit": {}, "sources": [
                {"source_name": "n", "source_type": "bogus", "emit": "campus",
                 "crawl": cg.STATIC, "seeds": [], "programs": []}]})


# --- Seed normalization (driven over the whole registry) --------------------

@pytest.fixture(scope="module")
def all_records():
    out = []
    for cfg in SCHOOL_CONFIGS:
        out.extend(cg.fetch_and_normalize(cfg, deep=False))
    return out


class TestSeedNormalization:
    def test_produces_records(self, all_records):
        assert len(all_records) >= len(SCHOOL_CONFIGS)

    def test_required_schema_fields(self, all_records):
        for o in all_records:
            assert o["id"] and o["title"] and o["url"]
            assert isinstance(o["eligibility"], dict)
            assert isinstance(o["metadata"], dict)
            assert isinstance(o["keywords"], list)
            assert "description_clean" in o
            assert len(o["description_clean"]) <= 1500

    def test_ids_unique(self, all_records):
        ids = [o["id"] for o in all_records]
        assert len(ids) == len(set(ids))

    def test_ids_namespaced_by_school(self, all_records):
        """Each id is prefixed with its school slug, so two schools can't collide
        and a record is traceable to its config."""
        slugs = {c["school_slug"] for c in SCHOOL_CONFIGS}
        for o in all_records:
            assert any(o["id"].startswith(f"{s}-") for s in slugs)

    def test_school_audience_matches_source_defaults(self, all_records):
        for o in all_records:
            assert o["audience"] in VALID_AUDIENCES
            assert (o["school"], o["audience"]) == SOURCE_DEFAULTS[o["source"]]

    def test_no_pi_or_contact_email(self, all_records):
        """Program/lab pages are not individuals — leaving pi_name/contact_email
        unset keeps them clear of any shared-email/name DQ gate."""
        for o in all_records:
            assert o.get("pi_name") is None
            assert o.get("contact_email") is None

    def test_rolling_with_no_deadline(self, all_records):
        for o in all_records:
            assert o.get("deadline") is None
            assert o.get("is_rolling") is True

    def test_source_type_never_faculty(self, all_records):
        """campus_* source_type must never read as faculty_research (that triggers
        faculty-only re-weighting in the ranker)."""
        for o in all_records:
            assert o["source_type"].startswith("campus_")
            assert "faculty" not in o["source_type"]


# --- Per-school: Princeton (the reference config) ---------------------------

class TestPrinceton:
    @pytest.fixture(scope="class")
    def recs(self):
        return cg.fetch_and_normalize(PRINCETON, deep=False)

    def test_in_registry(self):
        assert PRINCETON in SCHOOL_CONFIGS

    def test_all_levels_represented(self, recs):
        levels = {o["campus_source_type"] for o in recs}
        assert {"announcement", "program", "department", "career", "lab"} <= levels

    def test_summer_programs_present(self, recs):
        assert any(o["opportunity_type"] == "summer_program" for o in recs)

    def test_every_record_is_princeton_scoped(self, recs):
        for o in recs:
            # campus + lab buckets are princeton-homed; open (if any) is national.
            assert o["school"] in ("princeton", None)
            assert o["organization"]
            assert o["location"] == "Princeton, NJ"

    def test_breakdown_totals_consistent(self, recs):
        bd = cg.source_breakdown(recs)
        assert bd["total"] == len(recs)
        assert sum(bd["by_source_type"].values()) == len(recs)
        assert sum(bd["by_opportunity_type"].values()) == len(recs)


# --- Per-school: UC San Diego (first UC-system rollout school) --------------

class TestUcsd:
    @pytest.fixture(scope="class")
    def recs(self):
        return cg.fetch_and_normalize(UCSD, deep=False)

    def test_in_registry(self):
        assert UCSD in SCHOOL_CONFIGS

    def test_all_levels_represented(self, recs):
        levels = {o["campus_source_type"] for o in recs}
        assert {"announcement", "program", "department", "career", "lab"} <= levels

    def test_summer_programs_present(self, recs):
        assert any(o["opportunity_type"] == "summer_program" for o in recs)

    def test_every_record_is_ucsd_scoped(self, recs):
        for o in recs:
            # campus + lab buckets are ucsd-homed; open (if any) is national.
            assert o["school"] in ("ucsd", None)
            assert o["organization"]
            assert o["location"] == "La Jolla, CA"

    def test_breakdown_totals_consistent(self, recs):
        bd = cg.source_breakdown(recs)
        assert bd["total"] == len(recs)
        assert sum(bd["by_source_type"].values()) == len(recs)
        assert sum(bd["by_opportunity_type"].values()) == len(recs)


class TestUci:
    @pytest.fixture(scope="class")
    def recs(self):
        return cg.fetch_and_normalize(UCI, deep=False)

    def test_in_registry(self):
        assert UCI in SCHOOL_CONFIGS

    def test_all_levels_represented(self, recs):
        levels = {o["campus_source_type"] for o in recs}
        assert {"announcement", "program", "department", "career", "lab"} <= levels

    def test_summer_programs_present(self, recs):
        assert any(o["opportunity_type"] == "summer_program" for o in recs)

    def test_every_record_is_uci_scoped(self, recs):
        for o in recs:
            assert o["school"] in ("uci", None)
            assert o["organization"]
            assert o["location"] == "Irvine, CA"

    def test_breakdown_totals_consistent(self, recs):
        bd = cg.source_breakdown(recs)
        assert bd["total"] == len(recs)
        assert sum(bd["by_source_type"].values()) == len(recs)


class TestUcsb:
    @pytest.fixture(scope="class")
    def recs(self):
        return cg.fetch_and_normalize(UCSB, deep=False)

    def test_in_registry(self):
        assert UCSB in SCHOOL_CONFIGS

    def test_levels_represented(self, recs):
        levels = {o["campus_source_type"] for o in recs}
        assert {"announcement", "program", "department", "lab"} <= levels

    def test_summer_programs_present(self, recs):
        assert any(o["opportunity_type"] == "summer_program" for o in recs)

    def test_open_bucket_is_national(self, recs):
        # Cal-Bridge is a statewide consortium — emitted open (school None).
        assert any(o["school"] is None for o in recs)

    def test_every_record_is_ucsb_scoped(self, recs):
        for o in recs:
            assert o["school"] in ("ucsb", None)
            assert o["organization"]
            assert o["location"] == "Santa Barbara, CA"

    def test_breakdown_totals_consistent(self, recs):
        bd = cg.source_breakdown(recs)
        assert bd["total"] == len(recs)
        assert sum(bd["by_source_type"].values()) == len(recs)


class TestBoulder:
    @pytest.fixture(scope="class")
    def recs(self):
        return cg.fetch_and_normalize(BOULDER, deep=False)

    def test_in_registry(self):
        assert BOULDER in SCHOOL_CONFIGS

    def test_all_levels_represented(self, recs):
        levels = {o["campus_source_type"] for o in recs}
        assert {"announcement", "program", "department", "career", "lab"} <= levels

    def test_every_record_is_boulder_scoped(self, recs):
        for o in recs:
            assert o["school"] in ("boulder", None)
            assert o["organization"]
            assert o["location"] == "Boulder, CO"

    def test_breakdown_totals_consistent(self, recs):
        bd = cg.source_breakdown(recs)
        assert bd["total"] == len(recs)
        assert sum(bd["by_source_type"].values()) == len(recs)
