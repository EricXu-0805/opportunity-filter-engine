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


# ---------------------------------------------------------------------------
# Per-unit collection ledger
#
# The school-level ``fetched`` count cannot prove absence inside any one
# department, which is why every aggregate source has always been skipped.
# The ledger below is the missing proof, produced by the collector that did
# the scraping and consumed here at the retirement boundary.
#
# It is an EXTENSION of the existing ``stale_unit_ledger`` (UIUC's
# ``{unit: count}``), not a second provenance system: the same key, the same
# consumer, the same gates. A plain ``{unit: int}`` entry still means exactly
# what it meant before.
# ---------------------------------------------------------------------------

UNIT_LEDGER_VERSION = 1

# Only these statuses may contribute to retirement authority. Everything else
# — including anything unrecognised — fails closed.
_OK = "ok"
COMPLETE = "complete"

# Recorded so a reader can tell WHY a unit was not authorised, and so a new
# failure mode cannot quietly become authority by being unrecognised.
FETCH_FAILURE_STATUSES = frozenset({
    "http_404", "http_403", "http_5xx", "timeout", "connection_error",
    "render_unavailable", "error",
})
PARSE_FAILURE_STATUSES = frozenset({"zero_rows", "suspicious_zero", "error"})
COMPLETENESS_BLOCKING = frozenset({"partial", "unknown", "truncated", "deferred"})


def _unit_id_of(record: dict) -> str | None:
    """The scrape unit that owns this record, from its own id.

    faculty_graph mints ``faculty-{id_prefix}-{short}-{namehash}`` where
    ``short`` is the config department — the thing that has one URL and one
    selector set, and therefore the only boundary at which absence can be
    observed. Reading it back off the id is deterministic lineage: no text
    similarity, no current-school guessing.

    Returns None when the id does not carry a unit, which is preserved as
    ``lineage_missing`` rather than assigned to a unit by resemblance.
    """
    rid = record.get("id")
    if not isinstance(rid, str) or not rid.startswith("faculty-"):
        return None
    parts = rid.split("-")
    # faculty, prefix, <short may contain dashes>, namehash
    if len(parts) < 4:
        return None
    if len(parts[-1]) != 8 or not all(c in "0123456789abcdef" for c in parts[-1]):
        return None
    short = "-".join(parts[2:-1])
    return short.lower() or None


def unit_retirement_authority(entry: object, baseline_active: int) -> tuple[bool, str]:
    """``(authorised, reason)`` for one unit ledger entry. Fails closed.

    Authority requires every condition to be positively satisfied:
    fetch ok AND parse ok AND validation ok AND unit identity present AND
    completeness proven AND the unit-level ratio gate passed AND a baseline to
    measure against. Anything missing, unrecognised, or merely "not failed"
    is not authority.
    """
    if isinstance(entry, int):
        # Legacy shape: a bare per-unit count. It proves how many rows the
        # unit yielded and nothing about why, so it may pass only the ratio
        # gate — which is what it has always meant.
        if entry < MIN_SCRAPE_RATIO * baseline_active:
            return False, "partial_scrape"
        return True, "count_ratio_only"
    if not isinstance(entry, dict):
        return False, "unrecognised_ledger_entry"

    if not entry.get("unit_id"):
        return False, "unit_identity_unverified"
    if entry.get("fetch_status") != _OK:
        return False, f"fetch_{entry.get('fetch_status') or 'unknown'}"
    if entry.get("parse_status") != _OK:
        return False, f"parse_{entry.get('parse_status') or 'unknown'}"
    if entry.get("validation_status") != _OK:
        return False, f"validation_{entry.get('validation_status') or 'unknown'}"
    if entry.get("completeness_status") != COMPLETE:
        return False, f"completeness_{entry.get('completeness_status') or 'unknown'}"
    # The producer's own verdict must agree. Either side may veto; neither
    # alone may authorise.
    if entry.get("retirement_authorized") is not True:
        return False, "producer_withheld_authority"

    observed = entry.get("matched_baseline_count")
    if not isinstance(observed, int):
        observed = entry.get("observed_count")
    if not isinstance(observed, int):
        return False, "observed_count_missing"
    declared_baseline = entry.get("baseline_active_count")
    baseline = declared_baseline if isinstance(declared_baseline, int) else baseline_active
    if baseline <= 0:
        return False, "baseline_unavailable"
    if observed < MIN_SCRAPE_RATIO * baseline:
        return False, "partial_scrape"
    return True, "complete_unit_observation"


def _observed_ids(entry: object) -> frozenset[str] | None:
    """The entity ids this unit observation actually saw, when it recorded them."""
    if not isinstance(entry, dict):
        return None
    ids = entry.get("observed_entity_ids")
    if not isinstance(ids, list | tuple | set | frozenset):
        return None
    return frozenset(str(i) for i in ids)


def finalize_unit_ledger(ledger: dict[str, dict], opps: list[dict],
                         source: str) -> dict[str, dict]:
    """Fill in the consumer-owned half of each unit observation, in place.

    The collector attests what it SAW. Completeness is a claim about what it
    saw versus what we already hold, so it needs the corpus — and it is
    decided here, at the retirement boundary, rather than by the scraper that
    would benefit from claiming it.

    A unit present in the corpus but absent from the ledger is never
    synthesised: the pass preserves those records as unproven.
    """
    baseline_ids: dict[str, set[str]] = {}
    for opp in opps:
        if opp.get("source") != source:
            continue
        if opp.get("source_type") != "faculty_research":
            continue
        if (opp.get("metadata") or {}).get("is_active") is False:
            continue
        unit = _unit_id_of(opp)
        if unit:
            baseline_ids.setdefault(unit, set()).add(str(opp.get("id")))
    baseline = {u: len(ids) for u, ids in baseline_ids.items()}

    for unit_id, entry in ledger.items():
        if not isinstance(entry, dict):
            continue
        base = baseline.get(unit_id, 0)
        entry["baseline_active_count"] = base
        observed = entry.get("observed_count")
        if entry.get("fetch_status") != _OK or entry.get("parse_status") != _OK:
            entry["completeness_status"] = "unknown"
            entry["retirement_authorized"] = False
            continue
        if base <= 0:
            # Nothing held for this unit, so there is nothing to retire and
            # no ratio to measure against.
            entry["completeness_status"] = "unknown"
            entry["retirement_authorized"] = False
            continue
        # Coverage is measured against the baseline SET, not its size.
        #
        # A raw count is fooled by substitution: a unit that drops one
        # professor and gains one new arrival still reports "6 observed of 6
        # active" and reads as a complete scrape, so the departure looks
        # proven when the scrape may simply have failed to parse that person's
        # card. Caught on 2026-09-11 by the mandated manual sample: the
        # Bowdoin EOS unit scored 6/6 and proposed retiring a professor who
        # was still listed on the very page it had just scraped.
        #
        # Intersecting with the baseline makes an unparsed row cost coverage,
        # which is the only way absence can mean departure.
        seen = _observed_ids(entry)
        known = baseline_ids.get(unit_id, set())
        if seen is not None:
            matched = len(seen & known)
            entry["matched_baseline_count"] = matched
            entry["new_entity_count"] = len(seen - known)
            covered = matched
        else:
            covered = observed if isinstance(observed, int) else 0
        if isinstance(covered, int) and covered >= MIN_SCRAPE_RATIO * base:
            entry["completeness_status"] = COMPLETE
            entry["retirement_authorized"] = True
        else:
            entry["completeness_status"] = "partial"
            entry["retirement_authorized"] = False
            entry.setdefault(
                "failure_reason",
                f"covered {covered} of {base} active "
                f"(< {MIN_SCRAPE_RATIO:.0%})",
            )
    return ledger


def _bucket_for(reason: str) -> str:
    """Which preservation bucket a withheld-authority reason belongs to."""
    if reason.startswith("parse_suspicious_zero") or reason == "parse_zero_rows":
        return "records_preserved_suspicious_zero"
    if reason in ("partial_scrape",) or reason.startswith("completeness_"):
        return "records_preserved_partial"
    if reason == "unit_identity_unverified":
        return "records_preserved_missing_lineage"
    return "records_preserved_failed_source"


def deactivate_stale_faculty(
    opps: list[dict],
    fetched_counts: dict[str, int | dict[str, int] | dict[str, dict]],
    today: date | None = None,
    held_sources: set[str] | frozenset[str] | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Mark faculty absent from their directory re-scrape as inactive (in place).

    ``fetched_counts`` maps each faculty source that completed successfully in
    the current refresh run to one of

      * an int — the whole scrape's record count, which authorizes retirement
        only for a source proven to be one named academic unit; or
      * ``{unit: count}`` — a per-unit count ledger, which authorizes
        retirement unit by unit under the ratio gate; or
      * ``{unit_id: observation}`` — the full per-unit collection ledger, where
        each observation carries its own fetch/parse/validation/completeness
        status and the ids it actually saw. This is the only shape that can
        distinguish "this professor is gone" from "this collector did not see
        this professor", because only it records WHY a unit yielded what it did.

    With the full ledger the unit is identified from the record's own id
    (``faculty-{prefix}-{short}-{hash}``), which is the scrape boundary — one
    URL, one selector set. A record whose id carries no unit is preserved as
    ``lineage_missing`` rather than attached to a unit by resemblance.

    Sources that did not run (or errored) must be omitted and are never
    touched. ``held_sources`` are computed and reported but never written.
    ``dry_run`` computes and reports everything and mutates nothing.

    Returns counts for newly deactivated/kept/inactive records, the
    preservation buckets, and — for every proposed retirement — the evidence
    that authorised it.
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
        # Dry-run / audit surface.
        "dry_run": bool(dry_run),
        "records_considered": 0,
        "records_retirement_authorized": 0,
        "records_preserved_partial": 0,
        "records_preserved_suspicious_zero": 0,
        "records_preserved_missing_lineage": 0,
        "records_preserved_failed_source": 0,
        "proposals": [],
        "units_authorized": [],
        "units_withheld": [],
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
            rich = any(isinstance(v, dict) for v in ledger.values())
            by_unit: dict[str | None, list[dict]] = {}
            for record in active:
                key = _unit_id_of(record) if rich else _unit_of(record)
                by_unit.setdefault(key, []).append(record)

            for unit, unit_records in sorted(
                by_unit.items(), key=lambda kv: (kv[0] is None, kv[0] or "")
            ):
                counts["records_considered"] += len(unit_records)
                label = f"{source}/{unit}" if unit else f"{source}/(unnamed)"
                if unit is None:
                    # No unit identity on the record: never proven scraped by
                    # anything, so nothing may retire it.
                    logger.warning(
                        "deactivate_stale_faculty: %s has no unit lineage — "
                        "preserving records", label,
                    )
                    counts["skipped_missing_unit_ledger"].append(label)
                    counts["records_preserved_missing_lineage"] += len(unit_records)
                    counts["kept_fresh"] += len(unit_records)
                    continue
                if unit not in ledger:
                    logger.warning(
                        "deactivate_stale_faculty: %s has no per-unit scrape "
                        "record — preserving records", label,
                    )
                    counts["skipped_missing_unit_ledger"].append(label)
                    counts["records_preserved_failed_source"] += len(unit_records)
                    counts["kept_fresh"] += len(unit_records)
                    continue

                entry = ledger[unit]
                authorized, reason = unit_retirement_authority(
                    entry, len(unit_records),
                )
                if not authorized:
                    logger.warning(
                        "deactivate_stale_faculty: %s not authorised (%s) — "
                        "preserving %d record(s)", label, reason, len(unit_records),
                    )
                    bucket = _bucket_for(reason)
                    counts[bucket] += len(unit_records)
                    counts["kept_fresh"] += len(unit_records)
                    counts["units_withheld"].append(
                        {"unit": label, "reason": reason,
                         "records_preserved": len(unit_records)})
                    if reason == "partial_scrape":
                        counts["skipped_partial_scrape"].append(label)
                    continue

                counts["units_authorized"].append(
                    {"unit": label, "reason": reason,
                     "records": len(unit_records)})
                seen_ids = _observed_ids(entry)
                for opp in unit_records:
                    seen = _seen_date(opp)
                    # Prefer the observation set when the collector recorded
                    # one: "absent from a complete scrape" is a stronger claim
                    # than "its timestamp is old".
                    if seen_ids is not None:
                        observed_now = str(opp.get("id")) in seen_ids
                    else:
                        observed_now = not (seen is not None and seen < cutoff)
                    if observed_now or seen is None:
                        counts["kept_fresh"] += 1
                        continue
                    if seen >= cutoff:
                        counts["kept_fresh"] += 1
                        continue
                    counts["records_retirement_authorized"] += 1
                    counts["proposals"].append({
                        "entity_id": opp.get("id"),
                        "school": opp.get("school"),
                        "source": source,
                        "unit_id": unit,
                        "unit_name": (entry.get("unit_name")
                                      if isinstance(entry, dict) else None),
                        "department": opp.get("department"),
                        "last_seen_at": (opp.get("metadata") or {}).get(
                            "last_seen_at"),
                        "baseline_active_count": (
                            entry.get("baseline_active_count")
                            if isinstance(entry, dict) else None),
                        "observed_count": (entry.get("observed_count")
                                           if isinstance(entry, dict) else entry),
                        "observed_entity_ids_recorded": seen_ids is not None,
                        "run_id": (entry.get("run_id")
                                   if isinstance(entry, dict) else None),
                        "collector_version": (entry.get("collector_version")
                                              if isinstance(entry, dict) else None),
                        "reason": "absent_from_complete_unit_observation",
                        "authority": reason,
                    })
                    if held or dry_run:
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
        counts["records_considered"] += len(active)
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
            counts["records_preserved_missing_lineage"] += len(active)
            continue

        if fetched_counts[source] < MIN_SCRAPE_RATIO * len(active):
            logger.warning(
                "deactivate_stale_faculty: %s scrape yielded %d records vs %d "
                "currently active (< %.0f%%) — likely partial scrape, skipping",
                source, fetched_counts[source], len(active),
                MIN_SCRAPE_RATIO * 100,
            )
            counts["skipped_partial_scrape"].append(source)
            counts["records_preserved_partial"] += len(active)
            continue

        for opp in active:
            seen = _seen_date(opp)
            # Missing/unparseable last_seen_at: staleness can't be established,
            # so keep the record rather than guess.
            if seen is not None and seen < cutoff:
                counts["records_retirement_authorized"] += 1
                counts["proposals"].append({
                    "entity_id": opp.get("id"),
                    "school": opp.get("school"),
                    "source": source,
                    "unit_id": next(iter(units)),
                    "unit_name": next(iter(units)),
                    "department": opp.get("department"),
                    "last_seen_at": (opp.get("metadata") or {}).get("last_seen_at"),
                    "baseline_active_count": len(active),
                    "observed_count": fetched_counts[source],
                    "observed_entity_ids_recorded": False,
                    "run_id": None,
                    "collector_version": None,
                    "reason": "absent_from_complete_unit_observation",
                    "authority": "single_named_unit_count_ratio",
                })
                if held or dry_run:
                    counts["would_deactivate"].append(opp.get("id"))
                    continue
                _retire(opp, today)
                counts["newly_deactivated"] += 1
            else:
                counts["kept_fresh"] += 1

    return counts
