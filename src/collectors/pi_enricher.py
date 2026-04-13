"""
PI / Contact Email enricher.

Revisits SRO detail pages and UIUC department directories to fill in
pi_name and contact_email for existing opportunities.

Usage:
    python -m src.collectors.pi_enricher              # dry run
    python -m src.collectors.pi_enricher --save       # write to opportunities.json
"""

import json
import logging
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"

HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (educational project)"}
DELAY = 2


def _fetch_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, timeout=12, headers=HEADERS)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def _extract_contact_from_sro(soup: BeautifulSoup) -> dict:
    result = {}

    contact_div = soup.select_one("div.field--name-field-contact-email-s-")
    if not contact_div:
        for div in soup.select("div.field"):
            label = div.select_one(".field__label")
            if label and "contact" in label.get_text(strip=True).lower():
                contact_div = div
                break

    if contact_div:
        item = contact_div.select_one(".field__item")
        if item:
            email_text = item.get_text(strip=True)
            emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", email_text)
            if emails:
                result["contact_email"] = emails[0]

    mentor_div = None
    for div in soup.select("div.field"):
        label = div.select_one(".field__label")
        if label:
            lt = label.get_text(strip=True).lower()
            if any(kw in lt for kw in ["mentor", "faculty", "pi", "advisor",
                                        "supervisor", "professor", "director"]):
                mentor_div = div
                break

    if mentor_div:
        item = mentor_div.select_one(".field__item")
        if item:
            name = item.get_text(strip=True)
            name = re.sub(r"(?i)^(dr\.?|prof\.?|professor)\s*", "", name).strip()
            if name and len(name) < 60 and "@" not in name:
                result["pi_name"] = name

    if "contact_email" not in result:
        full_text = soup.get_text()
        emails = re.findall(r"[a-zA-Z0-9_.+-]+@illinois\.edu", full_text)
        filtered = [e for e in emails if e != "ugresearch@illinois.edu"]
        if filtered:
            result["contact_email"] = filtered[0]

    return result


def _infer_pi_from_lab(lab_name: str) -> str | None:
    patterns = [
        r"(?:Prof(?:essor)?\.?\s+)?(\w+(?:\s+\w+)?)\s+(?:Lab|Group|Research Group)",
        r"(\w+(?:\s+\w+)?)\s+(?:Lab|Group|Research Group)",
    ]
    for p in patterns:
        m = re.search(p, lab_name, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            generic = {"research", "computing", "computer", "advanced", "applied",
                       "center", "institute", "systems", "data", "machine",
                       "science", "undergraduate", "engineering", "physics",
                       "chemistry", "biology", "summer", "program", "national"}
            words = candidate.lower().split()
            if all(w not in generic for w in words) and len(candidate) > 2:
                return candidate
    return None


def enrich_opportunities(opps: list[dict], save: bool = False) -> dict:
    stats = {"total": len(opps), "already_has_email": 0, "enriched": 0,
             "scraped": 0, "inferred_pi": 0, "failed": 0}

    for i, opp in enumerate(opps):
        if opp.get("contact_email"):
            stats["already_has_email"] += 1
            continue

        enriched = False

        if opp.get("source") == "uiuc_sro" and opp.get("url", "").startswith("https://researchops"):
            soup = _fetch_soup(opp["url"])
            stats["scraped"] += 1
            if soup:
                info = _extract_contact_from_sro(soup)
                if info.get("contact_email"):
                    opp["contact_email"] = info["contact_email"]
                    enriched = True
                if info.get("pi_name") and not opp.get("pi_name"):
                    opp["pi_name"] = info["pi_name"]
            time.sleep(DELAY)

        if not opp.get("pi_name"):
            lab = opp.get("lab_or_program", "")
            pi = _infer_pi_from_lab(lab)
            if pi:
                opp["pi_name"] = pi
                stats["inferred_pi"] += 1

        if enriched:
            stats["enriched"] += 1
        elif not opp.get("contact_email"):
            stats["failed"] += 1

        if (i + 1) % 20 == 0:
            logger.info(f"Progress: {i+1}/{len(opps)} processed, {stats['enriched']} enriched")

    if save:
        with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
            json.dump(opps, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved {len(opps)} opportunities to {PROCESSED_FILE}")

    return stats


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Enrich opportunities with PI/contact info")
    parser.add_argument("--save", action="store_true", help="Write enriched data back to file")
    parser.add_argument("--limit", type=int, default=None, help="Max opportunities to process")
    args = parser.parse_args()

    with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
        opps = json.load(f)

    if args.limit:
        opps_to_process = opps[:args.limit]
    else:
        opps_to_process = opps

    stats = enrich_opportunities(opps_to_process, save=args.save)

    print(f"\n{'='*50}")
    print("PI ENRICHER RESULTS")
    print(f"{'='*50}")
    print(f"Total opportunities:   {stats['total']}")
    print(f"Already had email:     {stats['already_has_email']}")
    print(f"Pages scraped:         {stats['scraped']}")
    print(f"Successfully enriched: {stats['enriched']}")
    print(f"PI inferred from lab:  {stats['inferred_pi']}")
    print(f"No contact found:      {stats['failed']}")
    if not args.save:
        print("\n(Use --save to write enriched data back to file)")
