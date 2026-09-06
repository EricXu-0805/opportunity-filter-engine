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

# The shard file that holds every record not owned by one school. It is a
# publication unit exactly like a school is, so a broken nsf_reu withholds
# national and nothing else.
NATIONAL_SHARD = "national"
NATIONAL_SOURCES = frozenset(
    {"uiuc_sro", "nsf_reu", "simplify_internships"}
)

# Statuses that mean "this source ran out of the run's wall-clock budget",
# not "this source failed". The budget (#712, #714) exists so a run that
# overruns still publishes the schools that finished, instead of being killed
# mid-write by the job timeout and publishing nothing. Blocking on them here
# defeats that entirely — refresh_all exits 2 and the workflow discards the
# whole run, which is the loss the budget was written to prevent.
#
# Publishing is safe because neither status can produce a false retirement:
# a deferred source wrote nothing (its school keeps the previous refresh's
# records) and a truncated source merged its partial harvest upsert-only
# behind the richer-guard, while deactivate_stale_faculty considers ONLY
# sources reporting "ok". The run is degraded, and says so.
RELEASABLE_INCOMPLETE_STATUSES = frozenset(
    {"deferred_deadline", "partial_deadline"}
)

# refresh_all reports a source that emitted nothing while the corpus holds
# active records for it (see src/collectors/source_health.py). Releasable for
# the same reason the two above are: it cannot produce a false retirement.
SUSPICIOUS_ZERO_STATUS = "suspicious_zero"

# Sources for which emitting nothing is declared, expected behaviour — the
# only way a zero is read as legitimate. Never inferred: an undeclared source
# that has held records and now emits none is suspicious, which is the point.
# ucb_urap_projects scrapes a live application window and its own docstring
# records "0 off-season"; a seasonal empty is not a broken collector.
CONFIRMED_EMPTY_SOURCES = frozenset({"ucb_urap_projects"})
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


def shard_of_source(key: str) -> str | None:
    """Which shard file a source's records publish into, or None if unknown.

    ONE definition, because there were nearly two. The release verdict has
    always resolved a source to its publication unit; the freshness ledger
    needs the same answer, and a second implementation got it wrong for
    exactly the sources whose summary key does not look like their school:
    ``campus_graph:colgate`` and ``ucb_campus`` both resolved to None through
    SOURCE_DEFAULTS alone, which silently dropped those rows out of
    per-school aggregation.
    """
    if key in NATIONAL_SOURCES:
        return NATIONAL_SHARD
    if key.startswith("campus_graph:"):
        return key.split(":", 1)[1]
    entry = SOURCE_DEFAULTS.get(key)
    if entry and entry[0]:
        return entry[0]
    for school, keys in _ALWAYS_SPECIAL.items():
        if key in keys:
            return school
    for school, keys in _DEEP_SPECIAL.items():
        if key in keys:
            return school
    return None


def monitored_sources() -> frozenset[str]:
    """Every source a scheduled run is REQUIRED to produce, across all shards.

    The single answer to "which sources are eligible for weekly freshness
    monitoring", reused by src/collectors/source_health.py so the monitoring
    definition cannot drift away from the publication definition.

    It matters because the corpus also carries sources that are not scheduled
    producers and must not be judged on a weekly clock: ``manual`` (16
    hand-curated records, by design never re-scraped) and the
    ``*_external_research`` rows a campus crawl discovers opportunistically
    and only re-stamps when it happens to rediscover the page. Counting those
    as stale shards would report the national shard permanently degraded
    while its three real producers are fresh, and a monitor that is always
    amber is one nobody reads.
    """
    return frozenset(expected_sources(None, national=False, deep=True))


def record_source_aliases() -> dict[str, str]:
    """{source stamped on a record: the summary key its producer reports as}.

    The pipeline names one producer two ways, and any monitoring that joins
    stored records to run summaries has to reconcile them. A campus crawl
    reports under ``campus_graph:<slug>`` but stamps its records
    ``<slug>_research_programs``; UC Berkeley predates the shared engine and
    reports under ``ucb_campus`` while stamping ``ucb_research_programs``.
    Without this map a school's program shard looks like an unmonitored
    source on one side and a never-recorded producer on the other.
    """
    aliases: dict[str, str] = {}
    for key in expected_sources(None, national=False, deep=True):
        if key.startswith("campus_graph:"):
            slug = key.split(":", 1)[1]
            aliases[f"{slug}_research_programs"] = key
    aliases["ucb_research_programs"] = "ucb_campus"
    return aliases


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
    # Warnings are prose for a human reading a run log. Degradations are the
    # same facts keyed so the operator queue can open one incident per gap,
    # dedupe it across runs, and close it when a later run does not repeat it.
    degradations: list[dict] = []
    # Publication is per school on disk (one shard file each) but the verdict
    # used to be per run, so one school's broken source withheld every other
    # school's fresh data. Attribute each reason to the publication unit it
    # actually describes; anything structural stays unattributed and blocks
    # the lot, because then nothing in the summary can be trusted.
    unit_reasons: dict[str, list[str]] = {}

    def degrade(kind: str, source: str, detail: str, message: str) -> None:
        warnings.append(message)
        degradations.append({"kind": kind, "source": source, "detail": detail})

    def block(text: str, unit: str | None = None) -> None:
        reasons.append(text)
        if unit:
            unit_reasons.setdefault(unit, []).append(text)


    if national and schools is not None:
        policies: dict[str, SourcePolicy] = {}
        targets = frozenset()
        reasons.append("national and school shards are mutually exclusive")
    else:
        policies = expected_sources(schools, national=national, deep=deep)
        targets = _target_schools(schools, national=national)
        if "ucd" in targets and not deep:
            block(
                "UC Davis publication requires deep mode so ucd_faculty "
                "cannot be skipped",
                "ucd",
            )
        for target in sorted(targets):
            if not any(policy.school == target for policy in policies.values()):
                block(
                    f"requested school {target} has no mandatory producer "
                    f"for {'deep' if deep else 'quick'} mode",
                    target,
                )

    def unit_of(key: str) -> str | None:
        """Which shard file a source's failure actually affects.

        This run's own policy wins where it has one (it was built for this
        invocation); everything else defers to shard_of_source so the verdict
        and the freshness ledger cannot disagree about who owns a source.
        """
        if key in NATIONAL_SOURCES:
            return NATIONAL_SHARD
        policy = policies.get(key)
        if policy is not None and policy.school:
            return policy.school
        return shard_of_source(key)

    if not isinstance(summary, dict):
        return {
            "ready": False,
            "status": "blocked",
            "reasons": ["refresh summary is not an object"],
            "warnings": [],
            "degradations": [],
            "structural_reasons": ["refresh summary is not an object"],
            "by_unit": {},
            "publishable": [],
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
            block(f"source {key} summary is not an object", unit_of(key))
        elif info.get("status") == "error":
            block(
                f"source {key} reported error: {info.get('error', 'unknown')}",
                unit_of(key),
            )
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
                block(
                    f"source {key} has incomplete or invalid "
                    "raw_fetched/emitted/rejected counts",
                    unit_of(key),
                )
            elif counts["raw_fetched"] != (
                counts["emitted"] + counts["rejected"]
            ):
                block(
                    f"source {key} count reconciliation failed: "
                    f"raw_fetched={counts['raw_fetched']}, "
                    f"emitted={counts['emitted']}, "
                    f"rejected={counts['rejected']}",
                    unit_of(key),
                )

    for key, policy in policies.items():
        info = sources.get(key)
        if not isinstance(info, dict):
            block(f"required source missing: {key}", unit_of(key))
            continue
        if info.get("status") == SUSPICIOUS_ZERO_STATUS:
            # A department that emitted nothing degrades ITSELF. It used to
            # block, and because unit_of() resolves a source to its shard
            # file — one file per school — blocking withheld every sibling
            # department with it: ucb_ling_faculty's silent zero froze all
            # 3,106 UC Berkeley records for 44 days while 53 healthy
            # departments were re-scraped and discarded twice.
            #
            # A zero costs coverage, never accuracy, and the layers below
            # already prove it: merges are upsert-only so an empty harvest
            # cannot delete a record, and deactivate_stale_faculty authorizes
            # retirement only for sources reporting "ok" — which this is not —
            # so the absent records are preserved rather than retired. What
            # would publish is not wrong, there is just less of it than there
            # should be.
            #
            # Note what is NOT waived: the verdict stays degraded every run
            # until the source emits records again, its ledger
            # ``last_success_at`` does not move, and ops opens an incident
            # that only a verified successful run resolves.
            baseline = info.get("suspicious_zero_baseline")
            degrade(
                SUSPICIOUS_ZERO_STATUS,
                key,
                f"0 records, previously {baseline}"
                if isinstance(baseline, int) else "0 records",
                f"required source {key} emitted zero records while the corpus "
                f"holds {baseline if isinstance(baseline, int) else 'existing'} "
                "record(s) for it; those records are preserved untouched and "
                "the school still publishes, but this run cannot claim to "
                "have seen the source",
            )
            continue
        if info.get("status") in RELEASABLE_INCOMPLETE_STATUSES:
            degrade(
                "time_budget",
                key,
                str(info["status"]),
                f"required source {key} stopped at the run time budget "
                f"({info['status']}); its school keeps the previous refresh's "
                "records and stale retirement skips it",
            )
            continue
        if info.get("status") != "ok":
            # The generic error pass above supplies details for status=error.
            if info.get("status") != "error":
                block(
                    f"required source {key} has non-success status: "
                    f"{info.get('status', 'missing')}",
                    unit_of(key),
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
            block(
                f"required source {key} has no valid emitted count", unit_of(key)
            )
        elif fetched == 0:
            if key in CONFIRMED_EMPTY_SOURCES:
                # Declared empty-capable (a seasonal listing outside its
                # application window). Recorded, not treated as a fault.
                warnings.append(
                    f"required source {key} emitted zero records, which is "
                    "declared expected behaviour for it"
                )
            else:
                # Reached when the summary was produced without refresh_all's
                # classification pass (a recompute, a hand-built summary).
                # Fail SAFE, not closed: degrade the source rather than
                # withhold its school's other departments.
                degrade(
                    SUSPICIOUS_ZERO_STATUS,
                    key,
                    "0 records, no baseline available",
                    f"required source {key} emitted zero records; its "
                    "previously collected records are preserved untouched and "
                    "its school still publishes, but this run cannot claim "
                    "to have seen the source",
                )

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
                block(
                    f"required deep source {key} lacks valid live-crawl evidence",
                    unit_of(key),
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
                block(
                    f"required deep source {key} has inconsistent live-crawl "
                    "coverage evidence",
                    unit_of(key),
                )
            else:
                # A host we could not reach costs coverage, never accuracy:
                # campus_graph.merge_into_processed retires discoveries only
                # for sources whose crawl came back complete, so the records
                # behind an unreachable seed are preserved untouched. Vetoing
                # the release added no protection and took the whole shard
                # down with one third-party bot wall.
                if loaded == 0:
                    degrade(
                        "dark_crawl",
                        key,
                        f"0/{seed_pages_expected} seed pages, "
                        f"0/{sources_expected} crawl sources",
                        f"deep source {key} loaded no live page at all "
                        f"(0/{seed_pages_expected} seed pages, "
                        f"0/{sources_expected} crawl sources); its records "
                        "keep the previous run's verification and this run "
                        "cannot claim to have seen the school",
                    )
                else:
                    if sources_loaded != sources_expected:
                        degrade(
                            "crawl_sources_unreached",
                            key,
                            f"{sources_loaded}/{sources_expected}",
                            f"deep source {key} crawled {sources_loaded}/"
                            f"{sources_expected} configured crawl sources; the "
                            "unreached ones keep their previous records",
                        )
                    if (
                        seed_pages_loaded != seed_pages_expected
                        or seed_pages_failed != 0
                    ):
                        degrade(
                            "seed_pages_unreached",
                            key,
                            f"{seed_pages_loaded}/{seed_pages_expected}, "
                            f"{seed_pages_failed} failed",
                            f"deep source {key} loaded "
                            f"{seed_pages_loaded}/{seed_pages_expected} "
                            f"configured seed pages ({seed_pages_failed} "
                            "failed); those sources kept their previous records",
                        )
            crawl_errors = info.get("crawl_errors")
            if crawl_errors:
                degrade(
                    "crawl_errors",
                    key,
                    "; ".join(sorted(crawl_errors))[:400],
                    f"deep source {key} reported crawl errors: "
                    f"{sorted(crawl_errors)}",
                )
            degraded_page_errors = info.get("degraded_page_errors")
            if degraded_page_errors:
                warnings.append(
                    f"deep source {key} degraded on recursive discovered pages: "
                    f"{sorted(degraded_page_errors)}"
                )

    uiuc = sources.get("uiuc_faculty")
    if isinstance(uiuc, dict) and uiuc.get("empty_departments"):
        block(
            "uiuc_faculty reported empty departments: "
            f"{sorted(uiuc['empty_departments'])}",
            "uiuc",
        )
    if "uiuc_faculty" in policies and isinstance(uiuc, dict):
        if uiuc.get("stale_deactivation_authorized") is not False:
            block(
                "uiuc_faculty must disable stale deactivation until "
                "component-level baselines are available",
                "uiuc",
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
            block(
                "ucsb_urca_projects lacks complete sitemap evidence",
                unit_of("ucsb_urca_projects"),
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
            for source_key in partial:
                # A department that scraped short degrades ITSELF, for exactly
                # the reasons the suspicious-zero branch above degrades: the
                # two situations are the same situation. It used to block, and
                # because unit_of() resolves a source to its shard file — one
                # file per school — blocking withheld every sibling department
                # with it. Measured 2026-09-05: five UC Berkeley departments
                # scraping 94-100% of their stored counts withheld all 56,
                # including the 55 that had just harvested successfully, for a
                # fourth consecutive week.
                #
                # A short scrape costs coverage, never accuracy, and the layers
                # below have ALREADY acted on it — twice over:
                #
                #   * merges are upsert-only (merge_into_processed matches by
                #     id and appends; it never removes a record absent from the
                #     harvest), so a short scrape cannot delete anyone; and
                #   * this list IS deactivate_stale_faculty's record that it
                #     declined to retire from these sources. The name says so:
                #     skipped_partial_scrape. The records are preserved by the
                #     pass that produced this very signal.
                #
                # So the veto re-spends a safety budget already spent, and
                # charges the whole school for it. What publishes is not wrong;
                # the departments that were re-observed get fresh stamps, and
                # the records that were not keep the stamps they had — which is
                # the honest partial-degradation outcome, not a masked one.
                #
                # Not waived: the verdict stays degraded every run until the
                # source scrapes complete, the skipped records keep their old
                # last_seen_at and go stale on schedule, and ops opens an
                # incident keyed on the source.
                degrade(
                    "partial_scrape",
                    source_key,
                    "scrape short of the stored active count",
                    f"required source {source_key} scraped short of its stored "
                    "active count; deactivate_stale_faculty preserved its "
                    "records rather than retiring them, and the school still "
                    "publishes, but this run cannot claim the source is "
                    "complete",
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
                block(
                    "deactivate_stale_faculty did not preserve the UIUC "
                    "safety hold",
                    "uiuc",
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
    attributed = {text for texts in unit_reasons.values() for text in texts}
    # A reason nobody could pin to a shard describes the run itself — a shard
    # that does not match the request, a summary that is not an object, a
    # fatal error. Publishing anything on that evidence would be a guess.
    structural = [text for text in reasons if text not in attributed]

    units = set(unit_reasons)
    if not (national and schools is not None):
        units |= set(targets)
        if national or schools is None:
            units.add(NATIONAL_SHARD)
    by_unit = {
        unit: {
            "ready": not structural and not unit_reasons.get(unit),
            "reasons": list(unit_reasons.get(unit, ())),
        }
        for unit in sorted(units)
    }

    return {
        "ready": ready,
        "status": "ready" if ready and not warnings else (
            "degraded" if ready else "blocked"
        ),
        "reasons": reasons,
        "warnings": warnings,
        "degradations": degradations,
        "structural_reasons": structural,
        "by_unit": by_unit,
        # Exactly the shard files this run has earned the right to overwrite.
        # Everything absent keeps whatever the last good run committed.
        "publishable": sorted(
            unit for unit, verdict in by_unit.items() if verdict["ready"]
        ),
        "expected": sorted(policies),
        "observed": sorted(sources),
        "policies": [asdict(policy) for policy in policies.values()],
    }
