"""Contracts for the canonical scheduled/manual refresh shard selection."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from refresh_rotation import (  # noqa: E402
    ISOLATED_WEEKLY_SHARDS,
    NATIONAL_SHARD,
    WEEKLY_ROTATION,
    normalize_publication_unit,
    normalize_requested_shard,
    registered_school_slugs,
    scheduled_shard,
    target_shards,
    validate_rotation,
)


def test_weekly_rotation_covers_every_registered_school_exactly_once():
    validate_rotation()
    scheduled = [
        slug
        for day in range(1, 7)
        for slug in WEEKLY_ROTATION[day]
    ]
    isolated = [
        slug
        for shards in ISOLATED_WEEKLY_SHARDS.values()
        for slug in shards
    ]
    combined = [*scheduled, *isolated]
    assert set(combined) == registered_school_slugs()
    assert len(combined) == len(set(combined))
    assert WEEKLY_ROTATION[7] == (NATIONAL_SHARD,)


def test_scheduled_shard_is_deterministic():
    assert scheduled_shard(2).startswith("ucb,mit,usc,umn")
    assert scheduled_shard(7) == NATIONAL_SHARD
    assert "ucd" not in scheduled_shard(6).split(",")
    assert scheduled_shard(6, isolated=True) == "ucd"
    with pytest.raises(ValueError, match="weekday"):
        scheduled_shard(8)
    with pytest.raises(ValueError, match="no isolated"):
        scheduled_shard(5, isolated=True)


@pytest.mark.parametrize(
    "payload",
    [
        "uw, national",
        "uw,national",
        "UW",
        "uw,uw",
        "uw;echo-pwned",
        "$(touch-pwned)",
        "not-a-real-school",
        "ucd,uw",
    ],
)
def test_manual_shard_rejects_injection_duplicates_and_unknowns(payload):
    with pytest.raises(ValueError):
        normalize_requested_shard(payload, allow_full=True)


def test_manual_shard_normalizes_only_valid_known_values():
    assert normalize_requested_shard("uw,wisc") == "uw,wisc"
    assert normalize_requested_shard("national") == "national"
    assert normalize_requested_shard("", allow_full=True) == ""


def test_publication_unit_accepts_only_bounded_canonical_units():
    monday = scheduled_shard(1)
    assert normalize_publication_unit(monday) == monday
    assert normalize_publication_unit("ucd") == "ucd"
    assert normalize_publication_unit("uw") == "uw"
    assert normalize_publication_unit("national") == "national"

    with pytest.raises(ValueError, match="explicit"):
        normalize_publication_unit("")
    with pytest.raises(ValueError, match="canonical"):
        normalize_publication_unit("uw,wisc")


def test_target_shards_are_bounded_to_the_authorized_selection():
    assert target_shards("uw,wisc") == ("uw", "wisc")
    assert target_shards("national") == ("national",)
    full = target_shards("")
    assert set(full) == {*registered_school_slugs(), NATIONAL_SHARD}
    assert len(full) == len(registered_school_slugs()) + 1
