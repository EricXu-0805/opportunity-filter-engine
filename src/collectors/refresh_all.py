"""
Refresh all opportunity data sources.
Runs enabled collectors, merges results, and prints a summary.

Usage:
    python -m src.collectors.refresh_all              # refresh all sources
    python -m src.collectors.refresh_all --no-deep    # skip deep scraping
"""

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from src.normalizers.deactivate_past import deactivate_past
from src.normalizers.deactivate_stale_faculty import FACULTY_SOURCES, deactivate_stale_faculty
from src.normalizers.school_audience import apply_school_audience
from src.parsers.llm_tagger import apply_updates, needs_tagging, rule_based_tag

from .campus_graph import fetch_and_normalize as fetch_campus_graph
from .campus_graph import merge_into_processed as merge_campus_graph
from .nsf_reu import fetch_and_normalize as fetch_reu
from .nsf_reu import merge_into_processed as merge_reu
from .pi_enricher import enrich_opportunities as enrich_pi
from .schools import SCHOOL_CONFIGS
from .schools.umich_faculty import fetch_and_normalize as fetch_umich_faculty
from .schools.umich_faculty import merge_into_processed as merge_umich_faculty
from .simplify_internships import deactivate_stale as deactivate_simplify_stale
from .simplify_internships import fetch_and_normalize as fetch_simplify
from .simplify_internships import merge_into_processed as merge_simplify
from .ucb_anthro_faculty import fetch_and_normalize as fetch_ucb_anthro
from .ucb_arch_faculty import fetch_and_normalize as fetch_ucb_arch
from .ucb_astro_faculty import fetch_and_normalize as fetch_ucb_astro
from .ucb_bioe_faculty import fetch_and_normalize as fetch_ucb_bioe
from .ucb_campus import fetch_and_normalize as fetch_ucb_campus
from .ucb_campus import merge_into_processed as merge_ucb_campus
from .ucb_cbe_faculty import fetch_and_normalize as fetch_ucb_cbe
from .ucb_cee_faculty import fetch_and_normalize as fetch_ucb_cee
from .ucb_chem_faculty import fetch_and_normalize as fetch_ucb_chem
from .ucb_common import merge_into_processed as merge_ucb_cee
from .ucb_common import merge_into_processed as merge_ucb_chem
from .ucb_common import merge_into_processed as merge_ucb_eecs
from .ucb_common import merge_into_processed as merge_ucb_faculty
from .ucb_common import merge_into_processed as merge_ucb_stat
from .ucb_complit_faculty import fetch_and_normalize as fetch_ucb_complit
from .ucb_dcrp_faculty import fetch_and_normalize as fetch_ucb_dcrp
from .ucb_econ_faculty import fetch_and_normalize as fetch_ucb_econ
from .ucb_education_faculty import fetch_and_normalize as fetch_ucb_education
from .ucb_eecs_faculty import fetch_and_normalize as fetch_ucb_eecs
from .ucb_english_faculty import fetch_and_normalize as fetch_ucb_english
from .ucb_eps_faculty import fetch_and_normalize as fetch_ucb_eps
from .ucb_espm_faculty import fetch_and_normalize as fetch_ucb_espm
from .ucb_french_faculty import fetch_and_normalize as fetch_ucb_french
from .ucb_geog_faculty import fetch_and_normalize as fetch_ucb_geog
from .ucb_german_faculty import fetch_and_normalize as fetch_ucb_german
from .ucb_haas_faculty import fetch_and_normalize as fetch_ucb_haas
from .ucb_history_faculty import fetch_and_normalize as fetch_ucb_history
from .ucb_ib_faculty import fetch_and_normalize as fetch_ucb_ib
from .ucb_ieor_faculty import fetch_and_normalize as fetch_ucb_ieor
from .ucb_journalism_faculty import fetch_and_normalize as fetch_ucb_journalism
from .ucb_larch_faculty import fetch_and_normalize as fetch_ucb_larch
from .ucb_law_faculty import fetch_and_normalize as fetch_ucb_law
from .ucb_ling_faculty import fetch_and_normalize as fetch_ucb_ling
from .ucb_math_faculty import fetch_and_normalize as fetch_ucb_math
from .ucb_mcb_faculty import fetch_and_normalize as fetch_ucb_mcb
from .ucb_me_faculty import fetch_and_normalize as fetch_ucb_me
from .ucb_mse_faculty import fetch_and_normalize as fetch_ucb_mse
from .ucb_music_faculty import fetch_and_normalize as fetch_ucb_music
from .ucb_ne_faculty import fetch_and_normalize as fetch_ucb_ne
from .ucb_nst_faculty import fetch_and_normalize as fetch_ucb_nst
from .ucb_philos_faculty import fetch_and_normalize as fetch_ucb_philos
from .ucb_physics_faculty import fetch_and_normalize as fetch_ucb_physics
from .ucb_pmb_faculty import fetch_and_normalize as fetch_ucb_pmb
from .ucb_polisci_faculty import fetch_and_normalize as fetch_ucb_polisci
from .ucb_psych_faculty import fetch_and_normalize as fetch_ucb_psych
from .ucb_rhetoric_faculty import fetch_and_normalize as fetch_ucb_rhetoric
from .ucb_scandinavian_faculty import fetch_and_normalize as fetch_ucb_scandinavian
from .ucb_slavic_faculty import fetch_and_normalize as fetch_ucb_slavic
from .ucb_soc_faculty import fetch_and_normalize as fetch_ucb_soc
from .ucb_socwel_faculty import fetch_and_normalize as fetch_ucb_socwel
from .ucb_spanish_portuguese_faculty import fetch_and_normalize as fetch_ucb_spanish_portuguese
from .ucb_sph_faculty import fetch_and_normalize as fetch_ucb_sph
from .ucb_stat_faculty import fetch_and_normalize as fetch_ucb_stat
from .ucb_tdps_faculty import fetch_and_normalize as fetch_ucb_tdps
from .ucb_urap import fetch_and_normalize as fetch_ucb_urap
from .ucb_urap import merge_into_processed as merge_ucb_urap
from .ucb_urap_projects import fetch_and_normalize as fetch_ucb_urap_projects
from .ucb_urap_projects import merge_into_processed as merge_ucb_urap_projects
from .uiuc_drp import fetch_and_normalize as fetch_drp
from .uiuc_drp import merge_into_processed as merge_drp
from .uiuc_faculty import _null_shared_admin_emails
from .uiuc_faculty import fetch_and_normalize as fetch_faculty
from .uiuc_faculty import merge_into_processed as merge_faculty
from .uiuc_faculty import missing_departments as faculty_missing_departments
from .uiuc_html_faculty import fetch_and_normalize as fetch_html_faculty
from .uiuc_js_faculty import fetch_and_normalize as fetch_js_faculty
from .uiuc_json_faculty import fetch_and_normalize as fetch_json_faculty
from .uiuc_other import fetch_and_normalize as fetch_other
from .uiuc_other import merge_into_processed as merge_other
from .uiuc_our_rss import fetch_and_normalize as fetch_rss
from .uiuc_our_rss import merge_into_processed as merge_rss
from .uiuc_siebel import fetch_and_normalize as fetch_siebel
from .uiuc_siebel import merge_into_processed as merge_siebel
from .uiuc_sro import fetch_and_normalize as fetch_sro
from .uiuc_sro import merge_into_processed as merge_sro
from .uiuc_urap import fetch_and_normalize as fetch_urap
from .uiuc_urap import merge_into_processed as merge_urap
from .uiuc_ursa import fetch_and_normalize as fetch_ursa
from .uiuc_ursa import merge_into_processed as merge_ursa

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
STATUS_FILE = PROJECT_ROOT / "data" / "processed" / "collector_status.json"
STATUS_HISTORY_FILE = PROJECT_ROOT / "data" / "processed" / "collector_status_history.jsonl"

STATUS_HISTORY_MAX_ENTRIES = 200


def _trim_history_to_max(path: Path, max_entries: int) -> None:
    """Drop the oldest entries when the JSONL grows past ``max_entries``.

    Cheap line-count + slice rewrite — collector_status_history.jsonl is
    written ~2x/week so this never crosses 200KB. Idempotent.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= max_entries:
            return
        with path.open("w", encoding="utf-8") as f:
            f.writelines(lines[-max_entries:])
    except OSError as e:
        logger.warning("Failed to trim collector history: %s", e)


def write_status(summary: dict) -> None:
    """Persist a per-collector run summary for the admin dashboard.

    Writes two artifacts:

      * ``collector_status.json`` — overwritten each run, contains the
        latest snapshot. The ``/admin/collector-status`` endpoint reads this.
      * ``collector_status_history.jsonl`` — append-only log capped at
        ``STATUS_HISTORY_MAX_ENTRIES`` rows (~2 years at Mon/Thu cadence).
        The ``/admin/collector-status/history`` endpoint reads this for
        the per-source freshness trend chart.
    """
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with STATUS_FILE.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, sort_keys=True)
    except OSError as e:
        logger.warning("Failed to write collector status: %s", e)
        return

    history_entry = {
        "t": summary.get("timestamp"),
        "duration_seconds": summary.get("duration_seconds"),
        "total_new": summary.get("total_new", 0),
        "total_updated": summary.get("total_updated", 0),
        "total_in_file": summary.get("total_in_file", 0),
        "sources": {
            name: {
                "status": info.get("status"),
                "new": info.get("new"),
                "updated": info.get("updated"),
                "fetched": info.get("fetched"),
            }
            for name, info in (summary.get("sources") or {}).items()
            if isinstance(info, dict)
        },
    }
    try:
        with STATUS_HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(history_entry, sort_keys=True) + "\n")
        _trim_history_to_max(STATUS_HISTORY_FILE, STATUS_HISTORY_MAX_ENTRIES)
    except OSError as e:
        logger.warning("Failed to append collector status history: %s", e)


def refresh_all(deep: bool = True) -> dict:
    """Run all enabled collectors and merge results.

    Returns a summary dict with counts per source and totals.
    """
    summary = {
        "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "sources": {},
        "total_new": 0,
        "total_updated": 0,
        "total_in_file": 0,
    }

    # 1. OUR RSS feed
    logger.info("=" * 50)
    logger.info("Collecting from UIUC OUR RSS feed...")
    try:
        rss_opps = fetch_rss()
        added, updated = merge_rss(rss_opps)
        summary["sources"]["uiuc_our_rss"] = {
            "fetched": len(rss_opps),
            "new": added,
            "updated": updated,
            "status": "ok",
        }
        summary["total_new"] += added
        summary["total_updated"] += updated
        logger.info(f"RSS: {len(rss_opps)} fetched, {added} new, {updated} updated")
    except Exception as e:
        logger.error(f"RSS collection failed: {e}")
        summary["sources"]["uiuc_our_rss"] = {"status": "error", "error": str(e)}

    # 2. SRO database (with optional deep scraping)
    logger.info("=" * 50)
    logger.info(f"Collecting from UIUC SRO database (deep={deep})...")
    try:
        sro_opps = fetch_sro(deep=deep)
        added, updated = merge_sro(sro_opps)
        summary["sources"]["uiuc_sro"] = {
            "fetched": len(sro_opps),
            "new": added,
            "updated": updated,
            "deep": deep,
            "status": "ok",
        }
        summary["total_new"] += added
        summary["total_updated"] += updated
        logger.info(f"SRO: {len(sro_opps)} fetched, {added} new, {updated} updated")
    except Exception as e:
        logger.error(f"SRO collection failed: {e}")
        summary["sources"]["uiuc_sro"] = {"status": "error", "error": str(e)}

    # 3. NSF REU database
    logger.info("=" * 50)
    logger.info("Collecting from NSF REU Awards API...")
    try:
        reu_opps = fetch_reu(max_results=500)
        added, updated = merge_reu(reu_opps)
        summary["sources"]["nsf_reu"] = {
            "fetched": len(reu_opps),
            "new": added,
            "updated": updated,
            "status": "ok",
        }
        summary["total_new"] += added
        summary["total_updated"] += updated
        logger.info(f"NSF REU: {len(reu_opps)} fetched, {added} new, {updated} updated")
    except Exception as e:
        logger.error(f"NSF REU collection failed: {e}")
        summary["sources"]["nsf_reu"] = {"status": "error", "error": str(e)}

    # 4. UIUC Faculty directories
    logger.info("=" * 50)
    logger.info("Collecting from UIUC Faculty directories...")
    try:
        faculty_opps = fetch_faculty(enrich=deep)
        # The 4 ACES departments (Animal Sci, Crop Sci, NRES, FSHN) render their
        # directory via Drupal Views AJAX, so the static scraper misses them;
        # uiuc_js_faculty drives headless Chromium to recover them. Its records
        # share source='uiuc_faculty', so they merge into the same source and its
        # count is folded into the fetched total that gates deactivate_stale_faculty
        # — otherwise those ~152 professors are retired as "absent from re-scrape".
        # Browser-backed, so deep mode only; Playwright is imported lazily and
        # yields [] when Chromium is unavailable — logged as an error so a silent
        # failure is caught before the grace window retires them.
        js_opps: list[dict] = []
        if deep:
            try:
                js_opps = fetch_js_faculty()
                if not js_opps:
                    logger.error(
                        "UIUC JS faculty scrape yielded 0 records — Playwright/Chromium "
                        "missing or directory layout changed; the 4 ACES departments will "
                        "be deactivated once their last_seen_at passes the grace window"
                    )
            except Exception as e:
                logger.error(f"UIUC JS faculty collection failed: {e}")
        # AHS, School of Social Work, and Gies publish their directories as
        # paginated JSON APIs (no per-profile HTML fetch). uiuc_json_faculty
        # returns ~430 faculty; like js_opps these share source='uiuc_faculty',
        # so they fold into the same merge + fetched count that gates
        # deactivate_stale_faculty — otherwise they'd be retired as "absent from
        # re-scrape". Cheap + reliable but grouped with the deep faculty work.
        json_opps: list[dict] = []
        if deep:
            try:
                json_opps = fetch_json_faculty()
                if not json_opps:
                    logger.error(
                        "UIUC JSON faculty scrape yielded 0 records — campus directory "
                        "APIs unreachable or schema changed; AHS/Social Work/Gies faculty "
                        "will be deactivated once their last_seen_at passes the grace window"
                    )
            except Exception as e:
                logger.error(f"UIUC JSON faculty collection failed: {e}")
        # Carle Medicine, College of Law, and LER have HTML directories the JSON
        # APIs don't cover (Law + LER enrich email per profile). Same
        # source='uiuc_faculty' contract as js/json, so folded into the same
        # merge + fetched count gating deactivate_stale_faculty.
        html_opps: list[dict] = []
        if deep:
            try:
                html_opps = fetch_html_faculty()
                if not html_opps:
                    logger.error(
                        "UIUC HTML faculty scrape yielded 0 records — Carle/Law/LER "
                        "directory layout changed; those faculty will be deactivated "
                        "once their last_seen_at passes the grace window"
                    )
            except Exception as e:
                logger.error(f"UIUC HTML faculty collection failed: {e}")
        all_faculty = faculty_opps + js_opps + json_opps + html_opps
        added, updated = merge_faculty(all_faculty)
        # Surface the silent-scrape-failure class (a declared department whose
        # directory URL rotted and now scrapes 0 — see uiuc_faculty.matse). A
        # bare warning is invisible in the run log, so list empties in the
        # summary and ERROR-log each so the refresh's audit file flags it.
        # (Checked against the static DEPARTMENTS only; the JS depts aren't in it.)
        empty_depts = faculty_missing_departments(faculty_opps)
        for dept in empty_depts:
            logger.error(
                "UIUC faculty department scraped ZERO records — likely URL rot / "
                f"directory layout change (silent failure): {dept}"
            )
        summary["sources"]["uiuc_faculty"] = {
            "fetched": len(all_faculty),
            "js_fetched": len(js_opps),
            "json_fetched": len(json_opps),
            "html_fetched": len(html_opps),
            "new": added,
            "updated": updated,
            "enriched": deep,
            "empty_departments": empty_depts,
            "status": "ok",
        }
        summary["total_new"] += added
        summary["total_updated"] += updated
        logger.info(
            f"Faculty: {len(all_faculty)} fetched "
            f"({len(faculty_opps)} static + {len(js_opps)} JS-rendered "
            f"+ {len(json_opps)} JSON-API + {len(html_opps)} HTML-dir), "
            f"{added} new, {updated} updated"
        )
    except Exception as e:
        logger.error(f"Faculty collection failed: {e}")
        summary["sources"]["uiuc_faculty"] = {"status": "error", "error": str(e)}

    # 5. Small-list collectors (URAP, URSA, DRP, Siebel program overviews).
    # ucb_urap emits one static overview record with no network call, so it is
    # safe in quick mode alongside the UIUC small lists.
    for source_name, fetch_fn, merge_fn in [
        ("uiuc_urap", fetch_urap, merge_urap),
        ("uiuc_ursa", fetch_ursa, merge_ursa),
        ("uiuc_drp", fetch_drp, merge_drp),
        ("uiuc_siebel", fetch_siebel, merge_siebel),
        ("uiuc_other", fetch_other, merge_other),
        ("ucb_urap", fetch_ucb_urap, merge_ucb_urap),
    ]:
        logger.info("=" * 50)
        logger.info(f"Collecting from {source_name}...")
        try:
            new_opps = fetch_fn()
            added, updated = merge_fn(new_opps)
            summary["sources"][source_name] = {
                "fetched": len(new_opps),
                "new": added,
                "updated": updated,
                "status": "ok",
            }
            summary["total_new"] += added
            summary["total_updated"] += updated
            logger.info(f"{source_name}: {len(new_opps)} fetched, {added} new, {updated} updated")
        except Exception as e:
            logger.error(f"{source_name} collection failed: {e}")
            summary["sources"][source_name] = {"status": "error", "error": str(e)}

    # 5a. UC Berkeley campus-wide opportunity graph (announcements, programs,
    # department pages, career boards, lab recruiting). The curated seed layer
    # runs unconditionally (no network); the keyword-prioritized BFS crawl that
    # refines status and discovers extra postings only runs in deep mode.
    logger.info("=" * 50)
    logger.info(f"Collecting from UC Berkeley campus sources (deep={deep})...")
    try:
        campus_opps = fetch_ucb_campus(deep=deep)
        added, updated = merge_ucb_campus(campus_opps)
        summary["sources"]["ucb_campus"] = {
            "fetched": len(campus_opps),
            "new": added,
            "updated": updated,
            "deep": deep,
            "status": "ok",
        }
        summary["total_new"] += added
        summary["total_updated"] += updated
        logger.info(f"UCB campus: {len(campus_opps)} fetched, {added} new, {updated} updated")
    except Exception as e:
        logger.error(f"UCB campus collection failed: {e}")
        summary["sources"]["ucb_campus"] = {"status": "error", "error": str(e)}

    # 5a-ii. Generic campus-graph schools (US-News Top-50 rollout). Same model
    # as ucb_campus — curated seed layer runs unconditionally (no network), the
    # keyword-prioritized BFS only runs in deep mode — but driven by the
    # ``schools/`` config registry so a new school is a config module, not new
    # refresh wiring. Each school is isolated: one failing config can't sink the
    # others or the rest of the run. Records carry their own school/audience from
    # the config's emit map, kept in lockstep with school_audience.SOURCE_DEFAULTS.
    logger.info("=" * 50)
    logger.info(f"Collecting from campus-graph schools (n={len(SCHOOL_CONFIGS)}, deep={deep})...")
    for school_cfg in SCHOOL_CONFIGS:
        slug = school_cfg.get("school_slug", "unknown")
        try:
            school_opps = fetch_campus_graph(school_cfg, deep=deep)
            added, updated = merge_campus_graph(school_opps)
            summary["sources"][f"campus_graph:{slug}"] = {
                "fetched": len(school_opps),
                "new": added,
                "updated": updated,
                "deep": deep,
                "status": "ok",
            }
            summary["total_new"] += added
            summary["total_updated"] += updated
            logger.info(f"campus-graph {slug}: {len(school_opps)} fetched, {added} new, {updated} updated")
        except Exception as e:
            logger.error(f"campus-graph collection failed for {slug}: {e}")
            summary["sources"][f"campus_graph:{slug}"] = {"status": "error", "error": str(e)}

    # 5b. UC Berkeley faculty directories — deep-only, same class as the
    # uiuc_faculty enrichment hop: each collector visits every profile page for
    # the email (~0.75s politeness delay each) and some scrape external campus
    # sites. All 29 department directories run here.
    #
    # Order matters for joint-appointment dedup (ucb_common drops an incoming
    # record whose email/name already exists under another ucb_* source, keeping
    # the one already merged this run). EECS must merge before STAT so the EECS
    # record (richer inline keywords) wins their shared appointments; the rest
    # follow alphabetically, so the dedup's existing-corpus-wins policy just
    # fixes which department keeps a cross-listed professor on a from-scratch
    # rebuild. Every collector shares ucb_common.merge_into_processed
    # (merge_ucb_faculty); the four originals keep their own merge_ucb_<dept>
    # aliases so the eecs-before-stat ordering test can monkeypatch them.
    #
    # Every source listed here MUST also be in
    # deactivate_stale_faculty.FACULTY_SOURCES (else its stale professors are
    # never retired) — test_refresh_all guards that invariant in both directions.
    if deep:
        for source_name, fetch_fn, merge_fn in [
            ("ucb_eecs_faculty", fetch_ucb_eecs, merge_ucb_eecs),
            ("ucb_stat_faculty", fetch_ucb_stat, merge_ucb_stat),
            ("ucb_chem_faculty", fetch_ucb_chem, merge_ucb_chem),
            ("ucb_cee_faculty", fetch_ucb_cee, merge_ucb_cee),
            ("ucb_anthro_faculty", fetch_ucb_anthro, merge_ucb_faculty),
            ("ucb_arch_faculty", fetch_ucb_arch, merge_ucb_faculty),
            ("ucb_astro_faculty", fetch_ucb_astro, merge_ucb_faculty),
            ("ucb_bioe_faculty", fetch_ucb_bioe, merge_ucb_faculty),
            ("ucb_cbe_faculty", fetch_ucb_cbe, merge_ucb_faculty),
            ("ucb_dcrp_faculty", fetch_ucb_dcrp, merge_ucb_faculty),
            ("ucb_econ_faculty", fetch_ucb_econ, merge_ucb_faculty),
            ("ucb_eps_faculty", fetch_ucb_eps, merge_ucb_faculty),
            ("ucb_espm_faculty", fetch_ucb_espm, merge_ucb_faculty),
            ("ucb_ib_faculty", fetch_ucb_ib, merge_ucb_faculty),
            ("ucb_ieor_faculty", fetch_ucb_ieor, merge_ucb_faculty),
            ("ucb_larch_faculty", fetch_ucb_larch, merge_ucb_faculty),
            ("ucb_law_faculty", fetch_ucb_law, merge_ucb_faculty),
            ("ucb_ling_faculty", fetch_ucb_ling, merge_ucb_faculty),
            ("ucb_math_faculty", fetch_ucb_math, merge_ucb_faculty),
            ("ucb_mcb_faculty", fetch_ucb_mcb, merge_ucb_faculty),
            ("ucb_me_faculty", fetch_ucb_me, merge_ucb_faculty),
            ("ucb_mse_faculty", fetch_ucb_mse, merge_ucb_faculty),
            ("ucb_ne_faculty", fetch_ucb_ne, merge_ucb_faculty),
            ("ucb_nst_faculty", fetch_ucb_nst, merge_ucb_faculty),
            ("ucb_physics_faculty", fetch_ucb_physics, merge_ucb_faculty),
            ("ucb_pmb_faculty", fetch_ucb_pmb, merge_ucb_faculty),
            ("ucb_polisci_faculty", fetch_ucb_polisci, merge_ucb_faculty),
            ("ucb_psych_faculty", fetch_ucb_psych, merge_ucb_faculty),
            ("ucb_soc_faculty", fetch_ucb_soc, merge_ucb_faculty),
            ("ucb_education_faculty", fetch_ucb_education, merge_ucb_faculty),
            ("ucb_english_faculty", fetch_ucb_english, merge_ucb_faculty),
            ("ucb_geog_faculty", fetch_ucb_geog, merge_ucb_faculty),
            ("ucb_haas_faculty", fetch_ucb_haas, merge_ucb_faculty),
            ("ucb_history_faculty", fetch_ucb_history, merge_ucb_faculty),
            ("ucb_journalism_faculty", fetch_ucb_journalism, merge_ucb_faculty),
            ("ucb_philos_faculty", fetch_ucb_philos, merge_ucb_faculty),
            ("ucb_socwel_faculty", fetch_ucb_socwel, merge_ucb_faculty),
            ("ucb_sph_faculty", fetch_ucb_sph, merge_ucb_faculty),
            ("ucb_music_faculty", fetch_ucb_music, merge_ucb_faculty),
            ("ucb_complit_faculty", fetch_ucb_complit, merge_ucb_faculty),
            ("ucb_german_faculty", fetch_ucb_german, merge_ucb_faculty),
            ("ucb_french_faculty", fetch_ucb_french, merge_ucb_faculty),
            ("ucb_slavic_faculty", fetch_ucb_slavic, merge_ucb_faculty),
            ("ucb_tdps_faculty", fetch_ucb_tdps, merge_ucb_faculty),
            ("ucb_rhetoric_faculty", fetch_ucb_rhetoric, merge_ucb_faculty),
            ("ucb_spanish_portuguese_faculty", fetch_ucb_spanish_portuguese, merge_ucb_faculty),
            ("ucb_scandinavian_faculty", fetch_ucb_scandinavian, merge_ucb_faculty),
            # University of Michigan curated faculty (via faculty_graph engine).
            # Single source across departments; its own school-scoped merge (not
            # ucb_common's) so a Michigan prof sharing a name with a Berkeley one
            # is never false-dropped.
            ("umich_faculty", fetch_umich_faculty, merge_umich_faculty),
        ]:
            logger.info("=" * 50)
            logger.info(f"Collecting from {source_name}...")
            try:
                new_opps = fetch_fn()
                added, updated = merge_fn(new_opps)
                summary["sources"][source_name] = {
                    "fetched": len(new_opps),
                    "new": added,
                    "updated": updated,
                    "status": "ok",
                }
                summary["total_new"] += added
                summary["total_updated"] += updated
                logger.info(f"{source_name}: {len(new_opps)} fetched, {added} new, {updated} updated")
            except Exception as e:
                logger.error(f"{source_name} collection failed: {e}")
                summary["sources"][source_name] = {"status": "error", "error": str(e)}

        # 5b-ii. URAP live project database (deep + seasonal). Scrapes the
        # status=Open listings at urapprojects.berkeley.edu — hundreds of
        # faculty-posted projects during the application window, 0 off-season
        # (the merge leaves the corpus untouched on an empty scrape).
        logger.info("=" * 50)
        logger.info("Collecting from UC Berkeley URAP project database...")
        try:
            urap_proj = fetch_ucb_urap_projects()
            added, updated = merge_ucb_urap_projects(urap_proj)
            summary["sources"]["ucb_urap_projects"] = {
                "fetched": len(urap_proj),
                "new": added,
                "updated": updated,
                "status": "ok",
            }
            summary["total_new"] += added
            summary["total_updated"] += updated
            logger.info(f"URAP projects: {len(urap_proj)} fetched, {added} new, {updated} updated")
        except Exception as e:
            logger.error(f"URAP projects collection failed: {e}")
            summary["sources"]["ucb_urap_projects"] = {"status": "error", "error": str(e)}

    # 5c. SimplifyJobs internships (autonomous GitHub raw fetch — no auth)
    logger.info("=" * 50)
    logger.info("Collecting from SimplifyJobs internships...")
    simplify_active_ids: set[str] = set()
    simplify_ok = False
    try:
        simplify_opps = fetch_simplify()
        if simplify_opps:
            simplify_active_ids = {o["id"] for o in simplify_opps}
            simplify_ok = True
        added, updated = merge_simplify(simplify_opps)
        summary["sources"]["simplify_internships"] = {
            "fetched": len(simplify_opps),
            "new": added,
            "updated": updated,
            "status": "ok",
        }
        summary["total_new"] += added
        summary["total_updated"] += updated
        logger.info(f"Simplify: {len(simplify_opps)} fetched, {added} new, {updated} updated")
    except Exception as e:
        logger.error(f"Simplify internships collection failed: {e}")
        summary["sources"]["simplify_internships"] = {"status": "error", "error": str(e)}

    # 6. PI enrichment pass
    logger.info("=" * 50)
    logger.info("Running PI / contact email enrichment...")
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE, encoding="utf-8") as f:
            all_opps = json.load(f)

        pi_stats = enrich_pi(all_opps, save=True)
        summary["sources"]["pi_enricher"] = {
            "scraped": pi_stats["scraped"],
            "enriched": pi_stats["enriched"],
            "already_had": pi_stats["already_has_email"],
            "status": "ok",
        }
        logger.info(f"PI enricher: {pi_stats['enriched']} new emails found")

        # The PI enricher re-scrapes profile pages for records still missing a
        # contact email and can re-attach a shared department/advising inbox the
        # faculty merge already nulled. Re-run the threshold-based null pass so a
        # shared inbox never reaches the corpus as a cold-email target.
        renulled = _null_shared_admin_emails(all_opps)
        if renulled:
            logger.info(f"Re-nulled {renulled} shared department/admin inbox(es) re-attached by PI enrichment")
        summary["sources"]["pi_enricher"]["renulled_shared_emails"] = renulled

        # R70-C: deactivate past-deadline records. Previously only run as a
        # separate CI step (.github/workflows/refresh-data.yml) so local
        # refresh runs left expired opps live in the dataset. Running it here
        # closes that gap and keeps the JSON file in sync with what would land
        # in CI on the next push.
        deact_counts = deactivate_past(all_opps)

        if simplify_ok:
            simplify_stale = deactivate_simplify_stale(all_opps, simplify_active_ids)
            summary["sources"]["simplify_internships"]["deactivated_stale"] = simplify_stale
            logger.info("Simplify: %d stale internships deactivated", simplify_stale)

        # Faculty records have no deadline, so deactivate_past never retires
        # them; this source-specific pass deactivates professors who have been
        # absent from their directory re-scrape past the grace window. Only
        # sources that reported success in THIS run are eligible.
        faculty_fetched = {
            name: info.get("fetched", 0)
            for name, info in summary["sources"].items()
            if name in FACULTY_SOURCES and info.get("status") == "ok"
        }
        stale_faculty = deactivate_stale_faculty(all_opps, faculty_fetched)
        summary["sources"]["deactivate_stale_faculty"] = {
            "newly_deactivated": stale_faculty["newly_deactivated"],
            "kept_fresh": stale_faculty["kept_fresh"],
            "skipped_partial_scrape": stale_faculty["skipped_partial_scrape"],
            "status": "ok",
        }
        logger.info(
            "deactivate_stale_faculty: %d newly deactivated, %d kept fresh, %d source(s) gated",
            stale_faculty["newly_deactivated"],
            stale_faculty["kept_fresh"],
            len(stale_faculty["skipped_partial_scrape"]),
        )

        # Multi-university Phase 1: stamp source-level school + audience on
        # every record so freshly merged rows can never reach the corpus
        # untagged (the DQ gate asserts both fields on all records).
        school_audience_counts = apply_school_audience(all_opps)
        summary["sources"]["school_audience"] = {
            "tagged": sum(school_audience_counts.values()),
            "by_source": school_audience_counts,
            "status": "ok",
        }
        logger.info(
            "school_audience: %d record(s) stamped across %d source(s)",
            sum(school_audience_counts.values()),
            len(school_audience_counts),
        )

        # Rule-based auto-tag: fill unknown paid / international-friendly / skill /
        # year fields from text heuristics (free — no LLM). Collectors leave these
        # "unknown" when the listing doesn't state them; resolving the easy ones
        # gives the matcher more signal (esp. international_friendly, the F-1
        # lever). The LLM tagging pass stays a manual opt-in (cost-controlled).
        tagged = 0
        for opp in all_opps:
            if needs_tagging(opp) and apply_updates(opp, rule_based_tag(opp)):
                tagged += 1
        summary["sources"]["auto_tagger"] = {"rule_based_tagged": tagged, "status": "ok"}
        logger.info("auto_tagger: %d record(s) rule-tagged (filled unknown fields)", tagged)

        # Observability (MASTER_PLAN §2.5): the set the matcher historically
        # mishandled — citizenship_required=True yet international_friendly still
        # "unknown". rank_all hard-filters citizenship_required, so this is a
        # defense-in-depth tripwire: a non-zero count flags a reconciliation gap a
        # future scrape introduced, not a live F-1 leak.
        unreconciled = sum(
            1 for o in all_opps
            if (o.get("eligibility") or {}).get("citizenship_required") is True
            and (o.get("eligibility") or {}).get("international_friendly") == "unknown"
        )
        summary["sources"]["intl_reconciliation"] = {
            "citizenship_required_but_intl_unknown": unreconciled,
            "status": "ok",
        }
        logger.info(
            "intl_reconciliation: %d record(s) citizenship_required + intl unknown",
            unreconciled,
        )

        with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
            json.dump(all_opps, f, indent=2, ensure_ascii=False, default=str)
        summary["sources"]["deactivate_past"] = {
            "newly_deactivated": deact_counts["newly_deactivated"],
            "already_inactive": deact_counts["already_inactive"],
            "kept_active": deact_counts["kept_active"],
            "skipped_rolling": deact_counts["skipped_rolling"],
            "status": "ok",
        }
        logger.info(
            "deactivate_past: %d newly deactivated, %d already inactive, %d kept active",
            deact_counts["newly_deactivated"],
            deact_counts["already_inactive"],
            deact_counts["kept_active"],
        )

        summary["total_in_file"] = len(all_opps)
    else:
        summary["total_in_file"] = 0

    return summary


def print_summary(summary: dict) -> None:
    """Print a human-readable summary of the refresh."""
    print("\n" + "=" * 50)
    print("REFRESH SUMMARY")
    print("=" * 50)
    print(f"Timestamp: {summary['timestamp']}")
    print()

    for source, info in summary["sources"].items():
        status = info.get("status", "unknown")
        if status == "ok":
            print(f"  {source}:")
            for label, key in (("Fetched", "fetched"), ("Scraped", "scraped"),
                               ("New", "new"), ("Updated", "updated"),
                               ("Enriched", "enriched")):
                if key in info:
                    print(f"    {label}: {info[key]}")
            if "deep" in info:
                print(f"    Deep:    {info['deep']}")
        else:
            print(f"  {source}: ERROR - {info.get('error', 'unknown')}")
        print()

    print(f"Total new:     {summary['total_new']}")
    print(f"Total updated: {summary['total_updated']}")
    print(f"Total in file: {summary['total_in_file']}")
    print("=" * 50)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Refresh all opportunity data sources")
    parser.add_argument("--no-deep", action="store_true", help="Skip deep scraping of SRO detail pages")
    args = parser.parse_args()

    start = time.time()
    try:
        summary = refresh_all(deep=not args.no_deep)
    except Exception as e:
        elapsed = time.time() - start
        summary = {
            "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "sources": {},
            "total_new": 0,
            "total_updated": 0,
            "total_in_file": 0,
            "duration_seconds": round(elapsed, 1),
            "fatal_error": str(e),
        }
        write_status(summary)
        raise

    elapsed = time.time() - start
    summary["duration_seconds"] = round(elapsed, 1)

    write_status(summary)
    try:
        print_summary(summary)
    except Exception as e:
        logger.warning("print_summary failed (non-fatal): %s", e)
    print(f"\nCompleted in {elapsed:.1f}s")
