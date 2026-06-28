"""Deactivate faculty records that disappear from their source directory.

Faculty records carry no deadline, so deactivate_past never touches them, and
the faculty merges are pure upserts — a professor removed from their department
directory would otherwise stay is_active=True forever. This pass closes that
gap conservatively, with three safety gates:

  * only sources whose collector reported success in the CURRENT refresh run
    are considered (quick mode leaves the deep-only faculty sources untouched);
  * a source whose scrape yielded fewer than MIN_SCRAPE_RATIO of its
    currently-active record count is skipped entirely with a warning — a
    partial/broken scrape must never mass-deactivate a department;
  * only records unseen for GRACE_DAYS (≈2 missed weekly deep runs) are
    deactivated, so a single flaky scrape cannot retire anyone.

Reactivation needs no code here: both faculty merges replace the stored
metadata with the freshly normalized record (is_active=True, fresh
last_seen_at), so a professor who reappears in a later scrape goes live again.
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
    "ucb_ne_faculty",
    "ucb_nst_faculty",
    "ucb_physics_faculty",
    "ucb_pmb_faculty",
    "ucb_polisci_faculty",
    "ucb_psych_faculty",
    "ucb_soc_faculty",
    "ucb_education_faculty",
    "ucb_english_faculty",
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
})

GRACE_DAYS = 14
MIN_SCRAPE_RATIO = 0.7


def _seen_date(opp: dict) -> date | None:
    raw = (opp.get("metadata") or {}).get("last_seen_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except (TypeError, ValueError):
        return None


def deactivate_stale_faculty(
    opps: list[dict],
    fetched_counts: dict[str, int],
    today: date | None = None,
) -> dict:
    """Mark faculty absent from their directory re-scrape as inactive (in place).

    ``fetched_counts`` maps each faculty source that completed successfully in
    the current refresh run to the number of records its scrape yielded;
    sources that did not run (or errored) must be omitted and are never
    touched. Returns counts: {newly_deactivated, kept_fresh, already_inactive,
    skipped_partial_scrape (list of gated source names)}.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=GRACE_DAYS)
    counts: dict = {
        "newly_deactivated": 0,
        "kept_fresh": 0,
        "already_inactive": 0,
        "skipped_partial_scrape": [],
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
                meta = opp.setdefault("metadata", {})
                meta["is_active"] = False
                meta["deactivated_at"] = today.isoformat()
                meta["deactivation_reason"] = "absent_from_directory_rescrape"
                counts["newly_deactivated"] += 1
            else:
                counts["kept_fresh"] += 1

    return counts
