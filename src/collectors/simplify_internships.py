"""
Internship collector for the community-maintained SimplifyJobs listings.

SimplifyJobs/Summer2026-Internships publishes a machine-readable
``listings.json`` (.github/scripts/listings.json on the ``dev`` branch) that is
the canonical, openly-licensed national tech-internship board. It is a plain
GitHub raw fetch — no auth, no JS rendering — so unlike the Handshake collector
this runs fully autonomously.

We keep only listings that are ``active`` (currently open) AND ``is_visible``
(curated into the README table, i.e. maintainer-verified), which is a small,
high-quality slice (~1.4k) of the 17k-row file. Each listing carries a stable
UUID we reuse as the opportunity id so re-runs update in place rather than
duplicate.

The listing ``sponsorship`` enum maps directly onto this engine's
international/work-authorization model, which is the main reason this source is
a good fit for an opportunity matcher used by international students.

Usage:
    python -m src.collectors.simplify_internships            # fetch & preview
    python -m src.collectors.simplify_internships --save     # merge into processed
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Summer2025 path 301-redirects to the current Summer2026 repo; both serve the
# identical file. The dev branch is this repo's default (listings live there).
LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/"
    "Summer2026-Internships/dev/.github/scripts/listings.json"
)
HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (UIUC educational project)"}

# listings.json uses both canonical and legacy short-form category names; both
# alias onto the same keyword/major seeds so older rows normalize identically.
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Software Engineering": ["software engineering"],
    "Software": ["software engineering"],
    "Data Science, AI & Machine Learning": [
        "data science", "machine learning", "artificial intelligence",
    ],
    "AI/ML/Data": ["data science", "machine learning", "artificial intelligence"],
    "Hardware Engineering": ["hardware", "embedded systems"],
    "Hardware": ["hardware", "embedded systems"],
    "Quantitative Finance": ["quantitative finance"],
    "Quant": ["quantitative finance"],
    "Product Management": ["product management"],
    "Product": ["product management"],
}

_CATEGORY_MAJORS: dict[str, list[str]] = {
    "Software Engineering": ["Computer Science", "Computer Engineering"],
    "Software": ["Computer Science", "Computer Engineering"],
    "Data Science, AI & Machine Learning": [
        "Computer Science", "Statistics", "Data Science",
    ],
    "AI/ML/Data": ["Computer Science", "Statistics", "Data Science"],
    "Hardware Engineering": ["Electrical Engineering", "Computer Engineering"],
    "Hardware": ["Electrical Engineering", "Computer Engineering"],
    "Quantitative Finance": ["Mathematics", "Statistics", "Computer Science"],
    "Quant": ["Mathematics", "Statistics", "Computer Science"],
    "Product Management": ["Computer Science", "Business"],
    "Product": ["Computer Science", "Business"],
}

# The 4-value sponsorship enum -> (international_friendly, citizenship_required,
# work_auth_notes). "Does Not Offer Sponsorship" is "no" for full-time roles but
# CPT/OPT usually still covers internships, so we say so rather than hard-block.
_SPONSORSHIP_MAP: dict[str, tuple[str, bool, str]] = {
    "Offers Sponsorship": (
        "yes", False, "Employer offers visa sponsorship.",
    ),
    "Does Not Offer Sponsorship": (
        "no", False,
        "Employer does not offer visa sponsorship; CPT/OPT may still apply "
        "for internships.",
    ),
    "U.S. Citizenship is Required": (
        "no", True, "U.S. citizenship is required.",
    ),
    "Other": ("unknown", False, ""),
}


def fetch_listings(url: str = LISTINGS_URL) -> list[dict]:
    """Fetch and parse the raw listings.json array (no auth)."""
    try:
        resp = requests.get(url, timeout=40, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            logger.warning("Unexpected listings.json shape: %s", type(data))
            return []
        return data
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return []


def _format_location(locations: list[str]) -> tuple[str, str]:
    """Return (location_str, remote_option) from the locations array.

    A bare "USA"/"Remote" entry is the file's convention for a remote/nationwide
    posting; anything else is treated as an on-site city list.
    """
    locs = [x for x in (locations or []) if x]
    if not locs:
        return "Unknown", "unknown"
    remote_markers = {"usa", "remote", "united states"}
    is_remote = any(x.strip().lower() in remote_markers for x in locs)
    named = [x for x in locs if x.strip().lower() not in remote_markers]
    if named:
        location_str = ", ".join(named[:2])
        if len(named) > 2:
            location_str += f" (+{len(named) - 2} more)"
    else:
        location_str = "Remote"
    return location_str, ("remote" if is_remote and not named else "unknown")


def _epoch_to_iso(value) -> str | None:
    """Convert a Unix-epoch-seconds int to an ISO date, or None."""
    if not isinstance(value, int | float) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC).date().isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def normalize_listing(raw: dict) -> dict | None:
    """Normalize one listings.json row into the opportunity schema."""
    from src.normalizers.enricher import enrich_opportunity

    listing_id = str(raw.get("id") or "").strip()
    title = (raw.get("title") or "").strip()
    company = (raw.get("company_name") or "").strip()
    apply_url = (raw.get("url") or "").strip()
    if not listing_id or not title or not company:
        return None

    opp_id = f"simplify-intern-{listing_id}"
    now = datetime.now(UTC).isoformat()

    location_str, remote_option = _format_location(raw.get("locations"))
    category = raw.get("category") or ""
    terms = [t for t in (raw.get("terms") or []) if t and t != "N/A"]
    keywords = _CATEGORY_KEYWORDS.get(category, [])
    majors = _CATEGORY_MAJORS.get(category, [])

    sponsorship = raw.get("sponsorship") or "Other"
    intl_friendly, citizenship_required, work_auth_notes = _SPONSORSHIP_MAP.get(
        sponsorship, _SPONSORSHIP_MAP["Other"]
    )

    term_str = ", ".join(terms)
    desc_parts = [f"{title} internship at {company}."]
    if category:
        desc_parts.append(f"Field: {category}.")
    if location_str and location_str != "Unknown":
        desc_parts.append(f"Location(s): {location_str}.")
    if term_str:
        desc_parts.append(f"Term(s): {term_str}.")
    if work_auth_notes:
        desc_parts.append(work_auth_notes)
    desc_parts.append("Apply via the company link.")
    description = " ".join(desc_parts)

    opp = {
        "id": opp_id,
        "source": "simplify_internships",
        "source_url": apply_url,
        "source_type": "internship",
        "title": title,
        "organization": company,
        "department": "",
        "lab_or_program": company,
        "pi_name": None,
        "contact_email": None,
        "url": apply_url,
        "location": location_str,
        "on_campus": False,
        "remote_option": remote_option,
        "opportunity_type": "internship",
        "paid": "unknown",
        "compensation_details": "",
        "deadline": None,
        "posted_date": _epoch_to_iso(raw.get("date_posted")),
        "start_date": None,
        "duration": term_str,
        "eligibility": {
            "preferred_year": ["sophomore", "junior", "senior"],
            "min_gpa": None,
            "majors": majors,
            "skills_required": [],
            "skills_preferred": [],
            "citizenship_required": citizenship_required,
            "international_friendly": intl_friendly,
            "work_auth_notes": work_auth_notes,
            "eligibility_text_raw": description[:500],
        },
        "application": {
            "contact_method": "online",
            "requires_resume": "yes",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": apply_url,
        },
        "description_raw": description,
        "description_clean": description[:1500],
        "keywords": keywords,
        # Internships accept applications on a rolling basis until filled and
        # carry no deadline in the source, so flag rolling to avoid a blank
        # timing block in the UI.
        "is_rolling": True,
        "metadata": {
            "confidence_score": 0.75,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": f"Imported from SimplifyJobs listings ({listing_id})",
            "simplify_id": listing_id,
            "simplify_category": category,
            "simplify_sponsorship": sponsorship,
        },
    }
    return enrich_opportunity(opp)


def fetch_and_normalize(url: str = LISTINGS_URL) -> list[dict]:
    """Fetch listings, keep active+visible rows, and normalize them."""
    listings = fetch_listings(url)
    logger.info(f"Fetched {len(listings)} raw listings")

    opps = []
    seen_ids = set()
    for raw in listings:
        if not (raw.get("active") and raw.get("is_visible")):
            continue
        opp = normalize_listing(raw)
        if not opp or opp["id"] in seen_ids:
            continue
        seen_ids.add(opp["id"])
        opps.append(opp)

    logger.info(f"Normalized {len(opps)} active+visible internships")
    return opps


def merge_into_processed(new_opps: list[dict], filepath: str = None) -> tuple[int, int]:
    """Merge new internship opportunities into the processed data file."""
    filepath = filepath or str(PROCESSED_DIR / "opportunities.json")

    existing = []
    if Path(filepath).exists():
        with open(filepath, encoding="utf-8") as f:
            existing = json.load(f)

    index = {opp["id"]: opp for opp in existing}
    added, updated = 0, 0

    for opp in new_opps:
        if opp["id"] in index:
            opp["metadata"]["first_seen_at"] = index[opp["id"]].get(
                "metadata", {}
            ).get("first_seen_at", opp["metadata"]["first_seen_at"])
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

    parser = argparse.ArgumentParser(description="SimplifyJobs Internship Collector")
    parser.add_argument("--save", action="store_true",
                        help="Merge into processed/opportunities.json")
    args = parser.parse_args()

    opps = fetch_and_normalize()

    print(f"\nFetched {len(opps)} internships from SimplifyJobs")
    for o in opps[:8]:
        elig = o["eligibility"]
        print(f"\n  {o['title'][:65]}")
        print(f"    Employer: {o['organization']}")
        print(f"    Location: {o['location']}  ({o['remote_option']})")
        print(f"    Intl-friendly: {elig['international_friendly']}  "
              f"Citizenship req: {elig['citizenship_required']}")
        print(f"    Keywords: {', '.join(o.get('keywords', []))}")

    if args.save and opps:
        added, updated = merge_into_processed(opps)
        print(f"\nSaved: {added} new, {updated} updated")
    elif not args.save:
        print("\n(Use --save to merge into processed/opportunities.json)")
