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


class TestBrowserDetection:
    """The workflow installs Chromium only when the shard needs it. That list
    used to be a hardcoded alternation in refresh-data.yml missing 11
    render-mode schools; they collected anyway only because the install is
    per-RUN and every shard happened to contain a listed school. Nothing
    enforced that coincidence, and the failure it guards is silent:
    _render_soup lazy-imports Playwright and degrades to None, which is
    indistinguishable from an unreachable directory, while the source still
    reports "ok". Derived from the configs, it cannot drift."""

    def test_every_render_config_is_detected(self):
        import importlib
        import pkgutil

        import src.collectors.schools as schools_pkg
        from scripts.refresh_rotation import browser_schools

        detected = browser_schools()
        for module in pkgutil.iter_modules(schools_pkg.__path__):
            if not module.name.endswith("_faculty"):
                continue
            config = getattr(
                importlib.import_module(f"src.collectors.schools.{module.name}"),
                "SCHOOL", None,
            )
            if not isinstance(config, dict):
                continue
            renders = any(
                isinstance(block, dict)
                and (
                    block.get("render")
                    or (isinstance(block.get("profile_enrich"), dict)
                        and block["profile_enrich"].get("render"))
                )
                for dept in config.get("departments", [])
                for block in dept.values()
            )
            if renders:
                assert config["school_slug"] in detected, (
                    f"{config['school_slug']} renders but the workflow would "
                    "not install Chromium for its shard — its render "
                    "departments would silently collect nothing"
                )

    def test_uiuc_is_detected_despite_having_no_render_config(self):
        # uiuc_js_faculty drives Playwright directly (ACES Drupal Views AJAX),
        # outside the faculty_graph engine, so config inspection cannot see it.
        from scripts.refresh_rotation import browser_schools

        assert "uiuc" in browser_schools()

    def test_national_day_skips_the_browser_install(self):
        from scripts.refresh_rotation import shard_needs_browser

        assert shard_needs_browser("national") is False

    def test_full_refresh_installs_the_browser(self):
        from scripts.refresh_rotation import shard_needs_browser

        assert shard_needs_browser("") is True

    def test_browserless_single_school_skips_the_install(self):
        from scripts.refresh_rotation import shard_needs_browser

        assert shard_needs_browser("wisc") is False
