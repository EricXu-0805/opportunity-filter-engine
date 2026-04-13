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

from .uiuc_our_rss import fetch_and_normalize as fetch_rss, merge_into_processed as merge_rss
from .uiuc_sro import fetch_and_normalize as fetch_sro, merge_into_processed as merge_sro
from .pi_enricher import enrich_opportunities as enrich_pi

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"


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

    # 3. PI enrichment pass
    logger.info("=" * 50)
    logger.info("Running PI / contact email enrichment...")
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
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
            print(f"    Fetched: {info['fetched']}")
            print(f"    New:     {info['new']}")
            print(f"    Updated: {info['updated']}")
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
    summary = refresh_all(deep=not args.no_deep)
    elapsed = time.time() - start
    summary["duration_seconds"] = round(elapsed, 1)

    print_summary(summary)
    print(f"\nCompleted in {elapsed:.1f}s")
