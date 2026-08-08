"""Pure release contract for one opportunity-data refresh run.

Collectors stay isolated: one source may fail without preventing sibling
collectors from finishing and writing diagnostics. Publication is stricter.
This module evaluates the completed summary and makes missing, empty, errored,
or partial target sources a structured fail-closed verdict.

The line it draws is between accuracy and coverage. Evidence that cannot be
true, a source that reported an error, and a source that emitted nothing all
block: they mean what we would publish may be wrong. A host we simply could
not reach only costs coverage — the merge layers already refuse to retire
records behind an incomplete crawl — so it degrades the verdict instead.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.normalizers.deactivate_stale_faculty import FACULTY_SOURCES
from src.normalizers.school_audience import SOURCE_DEFAULTS

from .schools import SCHOOL_CONFIGS

NATIONAL_SOURCES = frozenset(
    {"uiuc_sro", "nsf_reu", "simplify_internships"}
)
_ALWAYS_SPECIAL: dict[str, frozenset[str]] = {
    "uiuc": frozenset(
        {
            "uiuc_our_rss",
            "uiuc_urap",
            "uiuc_ursa",
            "uiuc_drp",
            "uiuc_siebel",
            "uiuc_other",
            # The static UIUC faculty directory still runs in quick mode; a
            # zero/error there must not be omitted from the publication gate.
            "uiuc_faculty",
        }
    ),
    "ucb": frozenset({"ucb_urap", "ucb_campus"}),
}
_DEEP_SPECIAL: dict[str, frozenset[str]] = {
    "ucb": frozenset({"ucb_urap_projects"}),
    "ucsb": frozenset({"ucsb_urca_projects"}),
}


@dataclass(frozen=True)
class SourcePolicy:
    summary_key: str
    school: str | None
    mode: str
    allow_confirmed_empty: bool = False


def registered_school_slugs() -> frozenset[str]:
    return frozenset(school for school, _ in SOURCE_DEFAULTS.values() if school)


def _target_schools(
    schools: set[str] | frozenset[str] | None,
    *,
    national: bool,
) -> frozenset[str]:
    if national:
        return frozenset()
    if schools is None:
        return registered_school_slugs()
    return frozenset(schools)


def expected_sources(
    schools: set[str] | frozenset[str] | None,
    *,
    national: bool,
    deep: bool,
) -> dict[str, SourcePolicy]:
    """Return the exact mandatory external source policies for this request."""

    if national and schools is not None:
        raise ValueError("national and school shards are mutually exclusive")
    targets = _target_schools(schools, national=national)
    policies: dict[str, SourcePolicy] = {}

    if national or schools is None:
        for key in NATIONAL_SOURCES:
            policies[key] = SourcePolicy(key, None, "deep" if deep else "quick")

    graph_slugs = {
        config["school_slug"]
        for config in SCHOOL_CONFIGS
        if config.get("school_slug") in targets
    }
    for slug in graph_slugs:
        key = f"campus_graph:{slug}"
        policies[key] = SourcePolicy(key, slug, "deep" if deep else "quick")

    for school in targets:
        for key in _ALWAYS_SPECIAL.get(school, ()):
            policies[key] = SourcePolicy(key, school, "deep" if deep else "quick")
        if deep:
            for key in _DEEP_SPECIAL.get(school, ()):
                policies[key] = SourcePolicy(key, school, "deep")

    if deep:
        for key in FACULTY_SOURCES:
            school = SOURCE_DEFAULTS[key][0]
            if school in targets:
                policies[key] = SourcePolicy(key, school, "deep")

    return dict(sorted(policies.items()))


def _expected_shard(
    schools: set[str] | frozenset[str] | None,
    *,
    national: bool,
) -> dict | None:
    if schools is None and not national:
        return None
    return {
        "schools": sorted(schools or ()),
        "national": national,
    }


def evaluate_refresh_summary(
    summary: dict,
    *,
    schools: set[str] | frozenset[str] | None,
    national: bool,
    deep: bool,
    require_tracking: bool = True,
) -> dict:
    """Return a serializable release verdict without raising.

    ``ready`` means the artifact may proceed to the publication boundary. It
    does not mean every downstream feature is launch-ready; professor updates
    expose their own ``release_ready`` marker and are hidden separately when
    that narrower contract is unmet.
    """

    reasons: list[str] = []
    warnings: list[str] = []
    if national and schools is not None:
        policies: dict[str, SourcePolicy] = {}
        targets = frozenset()
        reasons.append("national and school shards are mutually exclusive")
    else:
        policies = expected_sources(schools, national=national, deep=deep)
        targets = _target_schools(schools, national=national)
        if "ucd" in targets and not deep:
            reasons.append(
                "UC Davis publication requires deep mode so ucd_faculty "
                "cannot be skipped"
            )
        for target in sorted(targets):
            if not any(policy.school == target for policy in policies.values()):
                reasons.append(
                    f"requested school {target} has no mandatory producer "
                    f"for {'deep' if deep else 'quick'} mode"
                )

    if not isinstance(summary, dict):
        return {
            "ready": False,
            "status": "blocked",
            "reasons": ["refresh summary is not an object"],
            "warnings": [],
            "expected": sorted(policies),
            "observed": [],
            "policies": [asdict(policy) for policy in policies.values()],
        }

    fatal_error = summary.get("fatal_error")
    if fatal_error:
        reasons.append(f"refresh raised a fatal error: {fatal_error}")

    expected_request = {
        "schools": sorted(schools) if schools is not None else None,
        "national": national,
        "deep": deep,
    }
    if summary.get("request") != expected_request:
        reasons.append(
            f"summary request does not match invocation: "
            f"expected={expected_request}, observed={summary.get('request')}"
        )

    expected_shard = _expected_shard(schools, national=national)
    if expected_shard is not None and summary.get("shard") != expected_shard:
        reasons.append(
            f"summary shard does not match request: "
            f"expected={expected_shard}, observed={summary.get('shard')}"
        )

    sources = summary.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        reasons.append("refresh summary sources is not an object")

    for key, info in sorted(sources.items()):
        if key == "professor_tracking" and not require_tracking:
            continue
        if not isinstance(info, dict):
            reasons.append(f"source {key} summary is not an object")
        elif info.get("status") == "error":
            reasons.append(f"source {key} reported error: {info.get('error', 'unknown')}")
        elif any(
            count_key in info
            for count_key in ("raw_fetched", "emitted", "rejected")
        ):
            counts = {
                count_key: info.get(count_key)
                for count_key in ("raw_fetched", "emitted", "rejected")
            }
            if any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                for value in counts.values()
            ):
                reasons.append(
                    f"source {key} has incomplete or invalid "
                    "raw_fetched/emitted/rejected counts"
                )
            elif counts["raw_fetched"] != (
                counts["emitted"] + counts["rejected"]
            ):
                reasons.append(
                    f"source {key} count reconciliation failed: "
                    f"raw_fetched={counts['raw_fetched']}, "
                    f"emitted={counts['emitted']}, "
                    f"rejected={counts['rejected']}"
                )

    for key, policy in policies.items():
        info = sources.get(key)
        if not isinstance(info, dict):
            reasons.append(f"required source missing: {key}")
            continue
        if info.get("status") != "ok":
            # The generic error pass above supplies details for status=error.
            if info.get("status") != "error":
                reasons.append(
                    f"required source {key} has non-success status: "
                    f"{info.get('status', 'missing')}"
                )
            continue

        has_complete_ledger = all(
            count_key in info
            for count_key in ("raw_fetched", "emitted", "rejected")
        )
        # A positive raw count is not publishable output. When a producer
        # supplies reconciliation, its emitted count is the release floor;
        # otherwise the existing ``fetched`` field is already the normalized
        # list returned to refresh_all.
        fetched = info.get("emitted") if has_complete_ledger else info.get(
            "fetched"
        )
        if not isinstance(fetched, int) or isinstance(fetched, bool) or fetched < 0:
            reasons.append(f"required source {key} has no valid emitted count")
        elif fetched == 0:
            reasons.append(f"required source {key} emitted zero records")

        if deep and (key == "ucb_campus" or key.startswith("campus_graph:")):
            attempted = info.get("live_pages_attempted")
            loaded = info.get("live_pages_loaded")
            sources_expected = info.get("crawl_sources_expected")
            sources_loaded = info.get("crawl_sources_loaded")
            seed_pages_expected = info.get("seed_pages_expected")
            seed_pages_loaded = info.get("seed_pages_loaded")
            seed_pages_failed = info.get("seed_pages_failed")
            evidence_counts = (
                attempted,
                loaded,
                sources_expected,
                sources_loaded,
                seed_pages_expected,
                seed_pages_loaded,
                seed_pages_failed,
            )
            if any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                for value in evidence_counts
            ):
                reasons.append(
                    f"required deep source {key} lacks valid live-crawl evidence"
                )
            elif (
                attempted <= 0
                or sources_expected <= 0
                or seed_pages_expected <= 0
                or loaded > attempted
                or seed_pages_loaded > loaded
                or seed_pages_loaded + seed_pages_failed
                != seed_pages_expected
            ):
                reasons.append(
                    f"required deep source {key} has inconsistent live-crawl "
                    "coverage evidence"
                )
            else:
                # A host we could not reach costs coverage, never accuracy:
                # campus_graph.merge_into_processed retires discoveries only
                # for sources whose crawl came back complete, so the records
                # behind an unreachable seed are preserved untouched. Vetoing
                # the release added no protection and took the whole shard
                # down with one third-party bot wall.
                if loaded == 0:
                    warnings.append(
                        f"deep source {key} loaded no live page at all "
                        f"(0/{seed_pages_expected} seed pages, "
                        f"0/{sources_expected} crawl sources); its records "
                        "keep the previous run's verification and this run "
                        "cannot claim to have seen the school"
                    )
                else:
                    if sources_loaded != sources_expected:
                        warnings.append(
                            f"deep source {key} crawled {sources_loaded}/"
                            f"{sources_expected} configured crawl sources; the "
                            "unreached ones keep their previous records"
                        )
                    if (
                        seed_pages_loaded != seed_pages_expected
                        or seed_pages_failed != 0
                    ):
                        warnings.append(
                            f"deep source {key} loaded "
                            f"{seed_pages_loaded}/{seed_pages_expected} "
                            f"configured seed pages ({seed_pages_failed} "
                            "failed); those sources kept their previous records"
                        )
            crawl_errors = info.get("crawl_errors")
            if crawl_errors:
                warnings.append(
                    f"deep source {key} reported crawl errors: "
                    f"{sorted(crawl_errors)}"
                )
            degraded_page_errors = info.get("degraded_page_errors")
            if degraded_page_errors:
                warnings.append(
                    f"deep source {key} degraded on recursive discovered pages: "
                    f"{sorted(degraded_page_errors)}"
                )

    uiuc = sources.get("uiuc_faculty")
    if isinstance(uiuc, dict) and uiuc.get("empty_departments"):
        reasons.append(
            "uiuc_faculty reported empty departments: "
            f"{sorted(uiuc['empty_departments'])}"
        )
    if "uiuc_faculty" in policies and isinstance(uiuc, dict):
        if uiuc.get("stale_deactivation_authorized") is not False:
            reasons.append(
                "uiuc_faculty must disable stale deactivation until "
                "component-level baselines are available"
            )
        else:
            warnings.append(
                "uiuc_faculty stale deactivation remains disabled pending "
                "component-level baselines"
            )

    urca = sources.get("ucsb_urca_projects")
    if isinstance(urca, dict):
        expected_maps = urca.get("sitemaps_expected")
        loaded_maps = urca.get("sitemaps_loaded")
        unexpected = urca.get("unexpected_location_count")
        if (
            urca.get("sitemap_complete") is not True
            or not isinstance(expected_maps, int)
            or isinstance(expected_maps, bool)
            or expected_maps <= 0
            or loaded_maps != expected_maps
            or not isinstance(unexpected, int)
            or isinstance(unexpected, bool)
            or unexpected != 0
        ):
            reasons.append(
                "ucsb_urca_projects lacks complete sitemap evidence"
            )

    stale = sources.get("deactivate_stale_faculty")
    if deep:
        expected_faculty = set(policies) & FACULTY_SOURCES
        if expected_faculty and not isinstance(stale, dict):
            warnings.append(
                "faculty stale-retirement summary is missing; old faculty "
                "records must be preserved"
            )
        elif isinstance(stale, dict):
            partial = sorted(
                expected_faculty
                & set(stale.get("skipped_partial_scrape") or ())
            )
            if partial:
                reasons.append(
                    f"required faculty sources were partial: {partial}"
                )
            missing_unit_ledger = sorted(
                expected_faculty
                & set(stale.get("skipped_missing_unit_ledger") or ())
            )
            if missing_unit_ledger:
                warnings.append(
                    "faculty stale retirement is held pending per-unit "
                    f"lineage: {missing_unit_ledger}"
                )
            if (
                "uiuc_faculty" in policies
                and "uiuc_faculty"
                not in set(stale.get("deactivation_not_authorized") or ())
            ):
                reasons.append(
                    "deactivate_stale_faculty did not preserve the UIUC "
                    "safety hold"
                )

    tracking = sources.get("professor_tracking")
    if require_tracking:
        if not isinstance(tracking, dict):
            reasons.append("professor_tracking summary is missing")
        elif tracking.get("status") != "ok":
            # An error status is already detailed by the generic pass.
            if tracking.get("status") != "error":
                reasons.append("professor_tracking did not complete successfully")
        elif tracking.get("release_ready") is not True:
            warnings.append(
                "professor updates are not release-ready and must remain hidden"
            )
    elif isinstance(tracking, dict):
        warnings.append(
            "professor tracking is local-only and is not part of this "
            "opportunity-data publication"
        )

    if deep and "ucd_faculty" in policies:
        ucd = sources.get("ucd_faculty")
        if not isinstance(ucd, dict) or ucd.get(
            "raw_fetched", ucd.get("fetched")
        ) == 0:
            warnings.append(
                "ucd_faculty is degraded on hosted egress; this run cannot "
                "claim complete UC Davis coverage"
            )

    ready = not reasons
    return {
        "ready": ready,
        "status": "ready" if ready and not warnings else (
            "degraded" if ready else "blocked"
        ),
        "reasons": reasons,
        "warnings": warnings,
        "expected": sorted(policies),
        "observed": sorted(sources),
        "policies": [asdict(policy) for policy in policies.values()],
    }
