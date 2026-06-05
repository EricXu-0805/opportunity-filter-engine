"""Collector for UC Berkeley URAP (Undergraduate Research Apprentice Program).

Modeled on src.collectors.uiuc_urap. Like UIUC URAP, Berkeley URAP only posts
its project/mentor list during the application window (Fall projects post in
late summer; the Fall 2026 application opens Aug 21, 2026). We emit one
"URAP overview" seed entry unconditionally so the program shows up in the
system year-round.

NOTE (Berkeley-specific): unlike UIUC, Berkeley's live project list is NOT on
this program page — it lives on a separate database-backed site,
https://urapprojects.berkeley.edu/list.php . That site has a different
structure (a searchable DB listing, not heading-delimited prose), so the
heading-walk scraper used by uiuc_urap does not apply here. Scraping individual
projects is intentionally deferred to a follow-up PR; this first version emits
only the program overview record.

Usage:
    python -m src.collectors.ucb_urap              # preview
    python -m src.collectors.ucb_urap --save       # merge into processed data
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from .base import BaseCollector, RawOpportunity

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
BASE_URL = "https://research.berkeley.edu/urap/"
# Berkeley-specific: the live project/mentor list lives on a separate host.
# Kept as a constant so the overview can point applicants at it and a future
# project-scraping PR has the entry point ready.
PROJECTS_URL = "https://urapprojects.berkeley.edu/list.php?status=Open"
HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (educational project)"}


class UCBURAPCollector(BaseCollector):
    def __init__(self, config: dict | None = None):
        super().__init__(source_name="ucb_urap", config=config or {"rate_limit_delay": 3})

    def collect(self) -> list[RawOpportunity]:
        # v1: overview-only. No network call is required (or made) — the
        # overview is static seed content. Project scraping (PROJECTS_URL) is a
        # deferred follow-up; see module docstring.
        return [self._overview_record()]

    def _overview_record(self) -> RawOpportunity:
        return RawOpportunity(
            source="ucb_urap",
            source_url=BASE_URL,
            title="URAP — Undergraduate Research Apprentice Program (UC Berkeley)",
            description_raw=(
                "URAP pairs UC Berkeley undergraduates with faculty members and "
                "research staff on faculty-led research projects for a semester. "
                "Open to all matriculated Berkeley undergraduates and all majors; "
                "concurrent-enrollment and study-abroad students are not eligible. "
                "Participation is for academic credit (1 unit per ~3 hours of "
                "research work, up to 4 units per term) rather than pay. Projects "
                "are posted in late summer; the Fall 2026 application opens "
                f"Aug 21, 2026. Current open projects are listed at {PROJECTS_URL}."
            ),
            url=BASE_URL,
            organization="UC Berkeley Office of Undergraduate Research & Scholarships (OURS)",
            extra_fields={
                "program": "URAP",
                "level": "program_overview",
                "college": "All",
                "is_rolling": False,
                "_contact_email": "urap@berkeley.edu",
            },
        )


def _hash_id(title: str, source: str) -> str:
    return hashlib.md5(f"{source}::{title}".encode()).hexdigest()[:16]


def _to_normalized(r: RawOpportunity) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    is_overview = r.extra_fields.get("level") == "program_overview"
    contact_email = r.extra_fields.pop("_contact_email", None)
    return {
        "id": _hash_id(r.title, r.source),
        "source": r.source,
        "source_url": r.source_url,
        "title": r.title,
        # R70-A: emit description_clean + description_raw so the frontend (which
        # reads `description_clean || description_raw`) renders content for
        # these program_overview records. Keep legacy `description` for back-compat.
        "description": r.description_raw,
        "description_raw": r.description_raw,
        "description_clean": (r.description_raw or "")[:1500],
        "url": r.url,
        "organization": r.organization,
        "opportunity_type": "research",
        # Berkeley-specific: URAP is credit-only (unpaid), so "no" rather than
        # the "unknown" the UIUC template uses.
        "paid": "no",
        "deadline": None,
        "is_rolling": True if is_overview else False,
        "on_campus": True,
        "contact_email": contact_email,
        "eligibility": {
            "majors": [],
            # Berkeley-specific: URAP is open to all undergraduate years, so no
            # preferred_year (the UIUC template defaults to freshman/sophomore).
            "preferred_year": [],
            "skills_required": [],
            # Berkeley-specific: matriculated international undergrads are
            # eligible (with a CPT caveat for some UCSF placements).
            "international_friendly": "yes",
            "citizenship_required": False,
        },
        "application": {
            "application_url": r.url,
            "application_effort": "medium",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_recommendation": "unknown",
        },
        "keywords": ["research", "mentorship", "undergraduate"],
        "metadata": {
            "is_active": True,
            "scraped_at": now,
            "first_seen": now,
        },
        **{k: v for k, v in r.extra_fields.items() if k not in {"is_rolling"}},
    }


def fetch_and_normalize() -> list[dict]:
    raw = UCBURAPCollector().collect()
    return [_to_normalized(r) for r in raw]


def merge_into_processed(opps: list[dict]) -> tuple[int, int]:
    if not PROCESSED_FILE.exists():
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    by_id = {o.get("id"): o for o in existing if o.get("id")}
    added = updated = 0
    for opp in opps:
        if opp["id"] not in by_id:
            existing.append(opp)
            by_id[opp["id"]] = opp
            added += 1
        else:
            old = by_id[opp["id"]]
            if old.get("description") != opp["description"] or old.get("title") != opp["title"]:
                old["title"] = opp["title"]
                old["description"] = opp["description"]
                old.setdefault("metadata", {})["last_updated"] = opp["metadata"]["scraped_at"]
                updated += 1
    with PROCESSED_FILE.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False, default=str)
    return (added, updated)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help="Merge into processed data")
    args = parser.parse_args()
    opps = fetch_and_normalize()
    print(f"Fetched {len(opps)} URAP records")
    for o in opps[:5]:
        print(f"  - {o['title'][:80]}")
    if args.save:
        a, u = merge_into_processed(opps)
        print(f"Saved: +{a} new, ~{u} updated")
