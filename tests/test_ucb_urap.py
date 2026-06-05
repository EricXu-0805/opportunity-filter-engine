"""Offline tests for src.collectors.ucb_urap.

The v1 collector is overview-only and makes no network call, so these tests
need no mocking. They lock in the source name, the deterministic id, and the
Berkeley-specific normalized schema (credit-only / open-to-all-years), which
are the fields most likely to drift if someone copies more UIUC defaults in.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors.ucb_urap import (
    UCBURAPCollector,
    _hash_id,
    _to_normalized,
    fetch_and_normalize,
)


def test_collect_emits_single_overview_record():
    raw = UCBURAPCollector(config={"rate_limit_delay": 0}).collect()
    assert len(raw) == 1
    r = raw[0]
    assert r.source == "ucb_urap"
    assert r.extra_fields["level"] == "program_overview"


def test_hash_id_is_deterministic():
    a = _hash_id("URAP overview", "ucb_urap")
    b = _hash_id("URAP overview", "ucb_urap")
    assert a == b and len(a) == 16


def test_normalized_record_has_berkeley_schema():
    opps = fetch_and_normalize()
    assert len(opps) == 1
    opp = opps[0]
    assert opp["source"] == "ucb_urap"
    assert opp["opportunity_type"] == "research"
    # Berkeley-specific defaults that diverge from the UIUC template.
    assert opp["paid"] == "no"
    assert opp["eligibility"]["preferred_year"] == []
    assert opp["contact_email"] == "urap@berkeley.edu"
    # program_overview records stay active/rolling so they're discoverable.
    assert opp["is_rolling"] is True
    assert opp["on_campus"] is True
    assert opp["metadata"]["is_active"] is True
    # frontend reads description_clean || description_raw — both must be present.
    assert opp["description_clean"]
    assert opp["description_raw"]
