"""
Collector for UIUC Office of Undergraduate Research blog RSS feed.
This is the lowest-friction data source — structured XML, no auth required.

RSS Feed: https://blogs.illinois.edu/xml/6204/rss.xml

Usage:
    python -m src.collectors.uiuc_our_rss              # fetch & preview
    python -m src.collectors.uiuc_our_rss --save       # fetch & merge into processed data
"""

import hashlib
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Optional

import feedparser

from .base import BaseCollector, RawOpportunity

_VERIFIED_SSL_CTX = ssl.create_default_context()

_UNVERIFIED_SSL_CTX = ssl.create_default_context()
_UNVERIFIED_SSL_CTX.check_hostname = False
_UNVERIFIED_SSL_CTX.verify_mode = ssl.CERT_NONE

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


class UIUCOURRSSCollector(BaseCollector):
    """Collects research opportunities from UIUC OUR blog RSS feed."""

    RSS_URL = "https://blogs.illinois.edu/xml/6204/rss.xml"

    def __init__(self, config: dict = None):
        super().__init__(
            source_name="uiuc_our_rss",
            config=config or {"rate_limit_delay": 1},
        )

    def collect(self) -> list[RawOpportunity]:
        """Parse RSS feed and return raw opportunities."""
        self.logger.info(f"Fetching RSS feed: {self.RSS_URL}")
        feed_data = self._fetch_feed_bytes()
        feed = feedparser.parse(feed_data)

        if feed.bozo:
            self.logger.warning(f"Feed parsing issue: {feed.bozo_exception}")
        opportunities: list[RawOpportunity] = []
        return self._entries_to_opportunities(feed, opportunities)

    def _fetch_feed_bytes(self) -> bytes:
        try:
            handler = urllib.request.HTTPSHandler(context=_VERIFIED_SSL_CTX)
            opener = urllib.request.build_opener(handler)
            return opener.open(self.RSS_URL, timeout=30).read()
        except (ssl.SSLError, urllib.error.URLError) as e:
            self.logger.warning(
                "Verified TLS fetch failed (%s); retrying without cert verification "
                "(UIUC blogs have a known cert chain issue)", e,
            )
            handler = urllib.request.HTTPSHandler(context=_UNVERIFIED_SSL_CTX)
            opener = urllib.request.build_opener(handler)
            return opener.open(self.RSS_URL, timeout=30).read()

    def _entries_to_opportunities(self, feed, opportunities: list[RawOpportunity]) -> list[RawOpportunity]:
        for entry in feed.entries:
            opp = self._parse_entry(entry)
            if opp:
                opportunities.append(opp)

        return opportunities

    def _parse_entry(self, entry) -> Optional[RawOpportunity]:
        """Convert a single RSS entry to RawOpportunity."""
        try:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6]).isoformat()

            return RawOpportunity(
                source="uiuc_our_rss",
                source_url=entry.get("link", ""),
                title=entry.get("title", "Untitled"),
                description_raw=entry.get("summary", ""),
                url=entry.get("link", ""),
                organization="University of Illinois at Urbana-Champaign",
                posted_date=published,
                location="Champaign, IL",
                extra_fields={
                    "categories": [
                        tag.term for tag in entry.get("tags", [])
                    ],
                    "author": entry.get("author", ""),
                },
            )
        except Exception as e:
            self.logger.error(f"Failed to parse entry: {e}")
            return None


def _strip_html(text: str) -> str:
    """Remove HTML tags and clean up whitespace."""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _detect_opportunity_type(title: str, desc: str) -> str:
    """Heuristic to classify the RSS entry."""
    combined = (title + " " + desc).lower()
    if any(kw in combined for kw in ["summer", "reu", "surf", "internship"]):
        return "summer_program"
    if any(kw in combined for kw in ["scholarship", "fellowship", "award"]):
        return "fellowship"
    if any(kw in combined for kw in ["workshop", "symposium", "conference", "poster"]):
        return "event"
    return "research"


def _detect_deadline(text: str) -> Optional[str]:
    """Try to extract a deadline from description text."""
    patterns = [
        r"(?:deadline|due|apply by|applications? due)[:\s]*(\w+ \d{1,2},?\s*\d{4})",
        r"(\w+ \d{1,2},?\s*\d{4})\s*(?:deadline)",
        r"(?:due|deadline)[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _detect_international_friendly(text: str) -> str:
    """Heuristic for international student eligibility."""
    lower = text.lower()
    if any(kw in lower for kw in ["u.s. citizen", "us citizen", "citizenship required",
                                    "permanent resident only", "us only"]):
        return "no"
    if any(kw in lower for kw in ["international students welcome", "open to all students",
                                    "international students eligible", "all students"]):
        return "yes"
    return "unknown"


def raw_to_normalized(raw: RawOpportunity) -> dict:
    """Convert a RawOpportunity from RSS into the normalized nested schema."""
    from src.normalizers.enricher import enrich_opportunity

    desc_clean = _strip_html(raw.description_raw)
    opp_type = _detect_opportunity_type(raw.title, desc_clean)
    deadline = _detect_deadline(desc_clean)
    intl = _detect_international_friendly(desc_clean)

    url_hash = hashlib.md5(raw.url.encode()).hexdigest()[:8]
    opp_id = f"rss-our-{url_hash}"

    now = datetime.utcnow().isoformat()

    opp = {
        "id": opp_id,
        "source": "uiuc_our_rss",
        "source_url": raw.url,
        "source_type": "rss",
        "title": raw.title.strip(),
        "organization": raw.organization or "UIUC",
        "department": "",
        "lab_or_program": "",
        "pi_name": None,
        "url": raw.url,
        "location": raw.location or "Champaign, IL",
        "on_campus": True,
        "remote_option": "unknown",
        "opportunity_type": opp_type,
        "paid": "unknown",
        "compensation_details": "",
        "deadline": deadline,
        "posted_date": raw.posted_date or now[:10],
        "start_date": None,
        "duration": None,
        "eligibility": {
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
            "min_gpa": None,
            "majors": [],
            "skills_required": [],
            "skills_preferred": [],
            "citizenship_required": intl == "no",
            "international_friendly": intl,
            "work_auth_notes": "",
            "eligibility_text_raw": desc_clean[:300],
        },
        "application": {
            "contact_method": "unknown",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": raw.url,
        },
        "description_raw": raw.description_raw,
        "description_clean": desc_clean[:500],
        "keywords": raw.extra_fields.get("categories", []),
        "metadata": {
            "confidence_score": 0.65,  # RSS auto-parsed = lower confidence than manual
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": "Auto-imported from UIUC OUR RSS feed",
        },
    }
    return enrich_opportunity(opp)


def fetch_and_normalize() -> list[dict]:
    """Fetch RSS feed and return normalized opportunity records."""
    collector = UIUCOURRSSCollector()
    raw_opps = collector.collect()
    logger.info(f"Fetched {len(raw_opps)} entries from RSS")

    normalized = []
    for raw in raw_opps:
        try:
            norm = raw_to_normalized(raw)
            normalized.append(norm)
        except Exception as e:
            logger.error(f"Failed to normalize '{raw.title}': {e}")

    return normalized


def merge_into_processed(new_opps: list[dict], filepath: str = None) -> tuple[int, int]:
    """Merge new opportunities into the processed data file."""
    filepath = filepath or str(PROCESSED_DIR / "opportunities.json")

    existing = []
    if Path(filepath).exists():
        with open(filepath, encoding="utf-8") as f:
            existing = json.load(f)

    index = {opp["id"]: opp for opp in existing}
    added, updated = 0, 0

    for opp in new_opps:
        if opp["id"] in index:
            # Update last_seen timestamp
            opp["metadata"]["first_seen_at"] = index[opp["id"]].get("metadata", {}).get("first_seen_at", opp["metadata"]["first_seen_at"])
            index[opp["id"]] = opp
            updated += 1
        else:
            index[opp["id"]] = opp
            added += 1

    all_opps = list(index.values())
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_opps, f, indent=2, ensure_ascii=False, default=str)

    return added, updated


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="UIUC OUR RSS Collector")
    parser.add_argument("--save", action="store_true", help="Merge fetched data into processed/opportunities.json")
    args = parser.parse_args()

    opps = fetch_and_normalize()
    print(f"\nFetched and normalized {len(opps)} opportunities from RSS\n")

    # Preview
    for i, opp in enumerate(opps[:5]):
        opp_type = opp["opportunity_type"]
        intl = opp["eligibility"]["international_friendly"]
        deadline = opp.get("deadline") or "none found"
        print(f"[{i+1}] {opp['title'][:60]}")
        print(f"    Type: {opp_type} | Intl: {intl} | Deadline: {deadline}")
        print(f"    URL: {opp['url']}")
        print()

    if args.save:
        added, updated = merge_into_processed(opps)
        print(f"Saved to processed: {added} new, {updated} updated")
    else:
        print("(Use --save to merge into processed/opportunities.json)")
