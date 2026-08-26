"""Deactivate faculty records that disappear from their source directory.

Faculty records carry no deadline, so deactivate_past never touches them, and
the faculty merges are pure upserts — a professor removed from their department
directory would otherwise stay is_active=True forever. This pass closes that
gap conservatively, with three safety gates:

  * only sources whose collector reported success in the CURRENT refresh run
    are considered (quick mode leaves the deep-only faculty sources untouched);
  * deactivation is limited to a source that represents exactly one named
    academic unit. Aggregate multi-department sources need a per-unit
    raw/emitted/rejected ledger before absence can safely retire records;
  * a single-unit source whose scrape yielded fewer than MIN_SCRAPE_RATIO of
    its currently-active record count is skipped entirely with a warning — a
    partial/broken scrape must never mass-deactivate a department;
  * only records unseen for GRACE_DAYS (≈2 missed weekly deep runs) are
    deactivated, so a single flaky scrape cannot retire anyone.

Reactivation needs no code here: the faculty merges replace the stored
metadata with the freshly normalized record (is_active=True, fresh
last_seen_at), and uiuc_faculty's row dedup — which drops that fresh row
whenever a stored row is research-richer — carries the newest sighting onto
the survivor. Either way a professor who reappears goes live again.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

# Faculty collectors wired into refresh_all; all emit source_type='faculty_research'.
# MUST stay in lockstep with the deep faculty loop in refresh_all.py — a source
# wired there but absent here would never have its stale professors retired.
# test_refresh_all guards this invariant in both directions.
FACULTY_SOURCES = frozenset({
    "uiuc_faculty",
    "ucb_eecs_faculty",
    "ucb_stat_faculty",
    "ucb_chem_faculty",
    "ucb_cee_faculty",
    "ucb_anthro_faculty",
    "ucb_arch_faculty",
    "ucb_astro_faculty",
    "ucb_bioe_faculty",
    "ucb_cbe_faculty",
    "ucb_dcrp_faculty",
    "ucb_econ_faculty",
    "ucb_eps_faculty",
    "ucb_espm_faculty",
    "ucb_ib_faculty",
    "ucb_ieor_faculty",
    "ucb_larch_faculty",
    "ucb_law_faculty",
    "ucb_ling_faculty",
    "ucb_math_faculty",
    "ucb_mcb_faculty",
    "ucb_me_faculty",
    "ucb_mse_faculty",
    "ucb_datascience_faculty",
    "ucb_ne_faculty",
    "ucb_neuro_faculty",
    "ucb_nst_faculty",
    "ucb_physics_faculty",
    "ucb_pmb_faculty",
    "ucb_polisci_faculty",
    "ucb_psych_faculty",
    "ucb_soc_faculty",
    "ucb_education_faculty",
    "ucb_english_faculty",
    "ucb_extra_faculty",
    "ucb_geog_faculty",
    "ucb_haas_faculty",
    "ucb_history_faculty",
    "ucb_journalism_faculty",
    "ucb_philos_faculty",
    "ucb_socwel_faculty",
    "ucb_sph_faculty",
    # L&S humanities/language directories (Open-Berkeley person grids).
    "ucb_music_faculty",
    "ucb_complit_faculty",
    "ucb_german_faculty",
    "ucb_french_faculty",
    "ucb_slavic_faculty",
    "ucb_tdps_faculty",
    "ucb_rhetoric_faculty",
    "ucb_spanish_portuguese_faculty",
    "ucb_scandinavian_faculty",
    "ucb_filmmedia_faculty",
    "ucb_classics_faculty",
    "ucb_publicpolicy_faculty",
    # University of Michigan — curated faculty (single source across depts).
    "umich_faculty",
    # University of Washington — live-scraped faculty (single source across depts).
    "uw_faculty",
    # Georgia Tech — live-scraped faculty (single source across depts).
    "gatech_faculty",
    # Stanford — live-scraped faculty (single source across depts).
    "stanford_faculty",
    # UT Austin — live-scraped faculty (single source across depts).
    "utexas_faculty",
    # UW-Madison — live-scraped faculty (single source across depts).
    "wisc_faculty",
    # UCLA — WordPress-REST faculty (single source across depts).
    "ucla_faculty",
    # UChicago — live-scraped + curated-API faculty (single source across depts).
    "uchicago_faculty",
    # Princeton — live-scraped faculty (central-Drupal person-card grid).
    "princeton_faculty",
    # Brown — shared Drupal people-component theme (single source across depts).
    "brown_faculty",
    # Cornell — A&S person-card + Engineering ce-block (single source across depts).
    "cornell_faculty",
    # Rice — shared web-api2 profiles JSON API (single source across depts).
    "rice_faculty",
    # Vanderbilt — shared A&S striped-table multisite (single source across depts).
    "vanderbilt_faculty",
    # Dartmouth — A&S/Thayer/Tuck directories (single source across depts).
    "dartmouth_faculty",
    # Columbia — A&S + SEAS directories (single source across depts).
    "columbia_faculty",
    # MIT — per-dept subdomain directories (single source across depts).
    "mit_faculty",
    # Harvard — FAS HWP Drupal + WP one-offs + SEAS (single source across depts).
    "harvard_faculty",
    # Yale — three YaleSites generations + SEAS Worx API (single source across depts).
    "yale_faculty",
    # CMU — central-CMS filterable/profile templates (single source across depts).
    "cmu_faculty",
    # USC — Viterbi/Dornsife + professional-school directories (single source).
    "usc_faculty",
    # Minnesota — CSE/CLA/CBS + professional-college directories (single source).
    "umn_faculty",
    # UNC-Chapel Hill — A&S + Gillings + SOM basic science + professional schools.
    "unc_faculty",
    # Ohio State — Engineering/ASC + professional-college directories (single source).
    "osu_faculty",
    # Notre Dame — Engineering/Science/A&L + Mendoza directories (single source).
    "nd_faculty",
    # Rochester — Hajim/SAS + Simon/Warner directories (single source).
    "rochester_faculty",
    # Florida — Wertheim/CLAS + professional-college directories (single source).
    "uf_faculty",
    # UMass Amherst — CICS/Engineering + campus Drupal directories (single source).
    "umass_faculty",
    # Virginia Tech — Wave-2 batch (single source across depts).
    "vt_faculty",
    # Texas A&M — Wave-2 batch (single source across depts).
    "tamu_faculty",
    # Maryland — Wave-2 batch (single source across depts).
    "umd_faculty",
    # Northeastern — Wave-2 batch (single source across depts).
    "neu_faculty",
    # Stony Brook — Wave-2 batch (single source across depts).
    "sbu_faculty",
    # Boston University — Wave-2 batch (single source across depts).
    "bu_faculty",
    # WashU — Wave-2 batch (single source across depts).
    "washu_faculty",
    # Rutgers — Wave-2 batch (single source across depts).
    "rutgers_faculty",
    # NC State — Wave-2 batch (single source across depts).
    "ncsu_faculty",
    # Penn State — Wave-2 batch (single source across depts).
    "psu_faculty",
    # Wave-2 batch 2 (single source across depts each).
    "ucsc_faculty",
    "arizona_faculty",
    "ucr_faculty",
    "asu_faculty",
    "pitt_faculty",
    "msu_faculty",
    # Wave-4 batch 1 (single source across depts each).
    "buffalo_faculty",
    "fsu_faculty",
    "usf_faculty",
    "utk_faculty",
    "clemson_faculty",
    "colostate_faculty",
    "oregonstate_faculty",
    # Wave-5 batch 1 (single source across depts each).
    "stevens_faculty",
    "njit_faculty",
    "wpi_faculty",
    "uky_faculty",
    "lehigh_faculty",
    "syracuse_faculty",
    "cincinnati_faculty",
    "unl_faculty",
    "lsu_faculty",
    "utdallas_faculty",
    "drexel_faculty",
    # Wave-3 batch 1 (single source across depts each).
    "casewestern_faculty",
    "houston_faculty",
    "iastate_faculty",
    "indiana_faculty",
    "miami_faculty",
    "rpi_faculty",
    "ucd_faculty",
    "ucf_faculty",
    "uconn_faculty",
    "udel_faculty",
    "uiowa_faculty",
    "utah_faculty",
    # Georgia — statewide-Drupal views-row directories (single source).
    "uga_faculty",
    # UCSD — live-scraped faculty (single source across depts).
    "ucsd_faculty",
    # Purdue — server-rendered faculty (single source across depts).
    "purdue_faculty",
    # Duke — render-mode Pratt engineering faculty (single source across depts).
    "duke_faculty",
    # JHU — headless Krieger TablePress directory (single source across depts).
    "jhu_faculty",
    # Northwestern — shared Weinberg Cascade theme (single source across depts).
    "northwestern_faculty",
    # UC Irvine — live-scraped faculty (single source across depts).
    "uci_faculty",
    # UC Santa Barbara — live-scraped faculty (single source across depts).
    "ucsb_faculty",
    # CU Boulder — live-scraped faculty via CU Experts/VIVO (single source).
    "boulder_faculty",
    # UPenn — live-scraped faculty (single source across depts).
    "upenn_faculty",
    # Caltech — live-scraped faculty (single source across divisions).
    "caltech_faculty",
    # LAC ranks 11-25 (2026-07-23)
    "grinnell_faculty",
    "colby_faculty",
    "hamilton_faculty",
    "vassar_faculty",
    "smith_faculty",
    "wlu_faculty",
    "colgate_faculty",
    "wesleyan_faculty",
    "haverford_faculty",
    "bates_faculty",
    "barnard_faculty",
    "coloradocollege_faculty",
    "macalester_faculty",
    "kenyon_faculty",
    "brynmawr_faculty",
    # Top-10 liberal arts colleges (2026-07-21)
    "amherst_faculty",
    "swarthmore_faculty",
    "pomona_faculty",
    "wellesley_faculty",
    "bowdoin_faculty",
    "carleton_faculty",
    "cmc_faculty",
    "middlebury_faculty",
    "davidson_faculty",
    # Wave-3 batch 1 (2026-07-20)
    "bc_faculty",
    "emory_faculty",
    "georgetown_faculty",
    "nyu_faculty",
    "tufts_faculty",
    "uva_faculty",
})

GRACE_DAYS = 14
# A weekly directory should not lose more than a few percent of its active
# roster. The former 70% threshold could retire nearly one-third of a school
# after one broken endpoint. This ratio is only meaningful after the source is
# proven to contain one named unit; aggregate sources are held below.
MIN_SCRAPE_RATIO = 0.95


def _seen_date(opp: dict) -> date | None:
    raw = (opp.get("metadata") or {}).get("last_seen_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except (TypeError, ValueError):
        return None


def _unit_of(record: dict) -> str | None:
    unit = record.get("department")
    return unit.strip() if isinstance(unit, str) and unit.strip() else None


def _retire(opp: dict, today: date) -> None:
    meta = opp.setdefault("metadata", {})
    meta["is_active"] = False
    meta["deactivated_at"] = today.isoformat()
    meta["deactivation_reason"] = "absent_from_directory_rescrape"


def deactivate_stale_faculty(
    opps: list[dict],
    fetched_counts: dict[str, int | dict[str, int]],
    today: date | None = None,
    held_sources: set[str] | frozenset[str] | None = None,
) -> dict:
    """Mark faculty absent from their directory re-scrape as inactive (in place).

    ``fetched_counts`` maps each faculty source that completed successfully in
    the current refresh run to either

      * an int — the whole scrape's record count, which authorizes retirement
        only for a source proven to be one named academic unit; or
      * ``{unit: count}`` — a per-unit ledger, which authorizes retirement
        unit by unit under the SAME gates. The department a record carries is
        finer-grained lineage than the collector component that produced it
        (UIUC's four producers own disjoint department sets), so a
        per-department count proves per-department completeness without any
        component-level provenance on the stored row. A department whose URL
        rotted scrapes 0 against N active records and is skipped; a collapsed
        component takes all of its departments to 0 and skips them all.

    Sources that did not run (or errored) must be omitted and are never
    touched. ``held_sources`` are computed and reported but never written —
    the UIUC release-contract hold, whose evidence for being lifted is exactly
    the ``would_deactivate`` list this produces.

    Returns counts for newly deactivated/kept/inactive records plus lists of
    sources (or ``source/unit``) held for partial scrapes or missing lineage.
    """
    held_sources = held_sources or frozenset()
    today = today or date.today()
    cutoff = today - timedelta(days=GRACE_DAYS)
    counts: dict = {
        "newly_deactivated": 0,
        "kept_fresh": 0,
        "already_inactive": 0,
        "skipped_partial_scrape": [],
        "skipped_missing_unit_ledger": [],
        # Ids a held source would have retired. Evidence, not an action.
        "would_deactivate": [],
    }

    by_source: dict[str, list[dict]] = {}
    for opp in opps:
        if opp.get("source_type") != "faculty_research":
            continue
        source = opp.get("source")
        if source in fetched_counts:
            by_source.setdefault(source, []).append(opp)

    for source, records in sorted(by_source.items()):
        active = [
            o for o in records
            if (o.get("metadata") or {}).get("is_active") is not False
        ]
        counts["already_inactive"] += len(records) - len(active)
        held = source in held_sources

        ledger = fetched_counts[source]
        if isinstance(ledger, dict):
            by_unit: dict[str | None, list[dict]] = {}
            for record in active:
                by_unit.setdefault(_unit_of(record), []).append(record)
            for unit, unit_records in sorted(
                by_unit.items(), key=lambda kv: (kv[0] is None, kv[0] or "")
            ):
                label = f"{source}/{unit}" if unit else f"{source}/(unnamed)"
                if unit is None or unit not in ledger:
                    # Not mentioned by the ledger: never proven scraped at all.
                    logger.warning(
                        "deactivate_stale_faculty: %s has no per-unit scrape "
                        "count — preserving records", label,
                    )
                    counts["skipped_missing_unit_ledger"].append(label)
                    continue
                if ledger[unit] < MIN_SCRAPE_RATIO * len(unit_records):
                    logger.warning(
                        "deactivate_stale_faculty: %s scrape yielded %d records "
                        "vs %d currently active (< %.0f%%) — likely partial "
                        "scrape, skipping",
                        label, ledger[unit], len(unit_records),
                        MIN_SCRAPE_RATIO * 100,
                    )
                    counts["skipped_partial_scrape"].append(label)
                    continue
                for opp in unit_records:
                    seen = _seen_date(opp)
                    if seen is None or seen >= cutoff:
                        counts["kept_fresh"] += 1
                        continue
                    if held:
                        counts["would_deactivate"].append(opp.get("id"))
                        continue
                    _retire(opp, today)
                    counts["newly_deactivated"] += 1
            continue

        # A school-wide collector can average 95% while one department is
        # completely absent (for example, 95 fresh people in department A and
        # all 5 people in department B missing). Until collectors publish a
        # trusted per-unit ledger, source-level fetched_counts cannot prove
        # absence for any individual department. Preserve the old records.
        units = {
            unit.strip()
            for record in active
            if isinstance((unit := record.get("department")), str)
            and unit.strip()
        }
        has_unnamed_unit = any(
            not isinstance(record.get("department"), str)
            or not record["department"].strip()
            for record in active
        )
        if has_unnamed_unit or len(units) != 1:
            logger.warning(
                "deactivate_stale_faculty: %s spans %d named unit(s)%s but "
                "has no trusted per-unit scrape ledger — preserving records",
                source,
                len(units),
                " plus unnamed records" if has_unnamed_unit else "",
            )
            counts["skipped_missing_unit_ledger"].append(source)
            continue

        if fetched_counts[source] < MIN_SCRAPE_RATIO * len(active):
            logger.warning(
                "deactivate_stale_faculty: %s scrape yielded %d records vs %d "
                "currently active (< %.0f%%) — likely partial scrape, skipping",
                source, fetched_counts[source], len(active),
                MIN_SCRAPE_RATIO * 100,
            )
            counts["skipped_partial_scrape"].append(source)
            continue

        for opp in active:
            seen = _seen_date(opp)
            # Missing/unparseable last_seen_at: staleness can't be established,
            # so keep the record rather than guess.
            if seen is not None and seen < cutoff:
                if held:
                    counts["would_deactivate"].append(opp.get("id"))
                    continue
                _retire(opp, today)
                counts["newly_deactivated"] += 1
            else:
                counts["kept_fresh"] += 1

    return counts
