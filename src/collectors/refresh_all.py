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
from datetime import datetime
from pathlib import Path

from .nsf_reu import fetch_and_normalize as fetch_reu
from .nsf_reu import merge_into_processed as merge_reu
from .pi_enricher import enrich_opportunities as enrich_pi
from .uiuc_faculty import fetch_and_normalize as fetch_faculty
from .uiuc_faculty import merge_into_processed as merge_faculty
from .uiuc_our_rss import fetch_and_normalize as fetch_rss
from .uiuc_our_rss import merge_into_processed as merge_rss
from .uiuc_sro import fetch_and_normalize as fetch_sro
from .uiuc_sro import merge_into_processed as merge_sro

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
STATUS_FILE = PROJECT_ROOT / "data" / "processed" / "collector_status.json"


def write_status(summary: dict) -> None:
    """Persist a per-collector run summary for the admin dashboard."""
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with STATUS_FILE.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, sort_keys=True)
    except OSError as e:
        logger.warning("Failed to write collector status: %s", e)


def refresh_all(deep: bool = True) -> dict:
    """Run all enabled collectors and merge results.

    Returns a summary dict with counts per source and totals.
    """
    summary = {
        "timestamp": datetime.utcnow().isoformat(),
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
        added, updated = merge_faculty(faculty_opps)
        summary["sources"]["uiuc_faculty"] = {
            "fetched": len(faculty_opps),
            "new": added,
            "updated": updated,
            "enriched": deep,
            "status": "ok",
        }
        summary["total_new"] += added
        summary["total_updated"] += updated
        logger.info(f"Faculty: {len(faculty_opps)} fetched, {added} new, {updated} updated")
    except Exception as e:
        logger.error(f"Faculty collection failed: {e}")
        summary["sources"]["uiuc_faculty"] = {"status": "error", "error": str(e)}

    # 5. PI enrichment pass
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
            "timestamp": datetime.utcnow().isoformat(),
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
