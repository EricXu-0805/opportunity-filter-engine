"""Collector for UC Berkeley EECS faculty research opportunities.

First Berkeley faculty collector, modeled on src.collectors.uiuc_faculty but
intentionally scoped to a single department (EECS) and kept small/reviewable:

  * Only the EECS faculty directory is scraped.
  * No per-profile enrichment hop — Berkeley's directory lists each faculty
    member's email AND research-interest tags inline, so a single page fetch
    yields everything we need. (UIUC's collector needs a second hop per
    professor because its directory cards are sparse; Berkeley's are not.)
  * No LLM keyword fallback and none of UIUC's heavy corpus-cleanup helpers.
    Berkeley's directory is a clean card layout, so the messy-extraction
    cleanup that uiuc_faculty runs in merge_into_processed isn't needed here.

The normalized schema matches uiuc_faculty (source_type="faculty_research",
pi_name/contact_email/lab_or_program) so the existing cold-email / matching
features treat Berkeley faculty identically to UIUC faculty.

Directory page (current EECS faculty, names + email + research areas inline):
    https://www2.eecs.berkeley.edu/Faculty/Lists/faculty.html
Each entry links to a profile at /Faculty/Homepages/<lastname>.html .

Usage:
    python -m src.collectors.ucb_eecs_faculty            # fetch & preview
    python -m src.collectors.ucb_eecs_faculty --save     # merge into processed data
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (educational project)"}

# Single-department config, same shape as one entry in uiuc_faculty.DEPARTMENTS.
EECS_CONFIG = {
    "name": "Electrical Engineering and Computer Sciences",
    "short": "EECS",
    "url": "https://www2.eecs.berkeley.edu/Faculty/Lists/faculty.html",
    "base": "https://www2.eecs.berkeley.edu",
    "majors": ["EECS", "Electrical Engineering", "Computer Science",
               "Computer Engineering"],
    # Broad field used only as the honest fallback when a professor lists no
    # parseable research areas (never injected on top of real ones).
    "keywords": ["electrical engineering and computer sciences"],
}

# Directory placeholder shown when a professor lists no address — not a real
# inbox, so treat it as "no email" (lower confidence, no cold-email target).
NOISE_EMAILS = {"no_email@eecs.berkeley.edu"}

# The directory mixes retired faculty into the same card list; they are not
# viable cold-email targets for prospective undergrad researchers.
_RETIRED_TITLE_RE = re.compile(r"\b(emeritus|emerita|retired)\b", re.IGNORECASE)

# Reused verbatim from uiuc_faculty (generic, source-agnostic). Kept local so
# this collector is self-contained, matching the pattern of the other small
# collectors in this package.
_KEYWORD_BANK = [
    "machine learning", "deep learning", "computer vision", "robotics",
    "natural language processing", "data science", "cybersecurity",
    "quantum", "nanotechnology", "materials science", "renewable energy",
    "neuroscience", "genomics", "bioinformatics", "artificial intelligence",
    "internet of things", "biomedical", "remote sensing", "signal processing",
    "embedded systems", "human-computer interaction", "software engineering",
    "parallel computing", "high performance computing", "optimization",
    "control systems", "power systems", "photonics", "optics",
    "electromagnetics", "circuits", "algorithms", "databases", "networking",
    "security", "programming languages", "compilers", "operating systems",
    "computational biology", "autonomous systems", "reinforcement learning",
    "graph neural networks", "large language models",
]

_SKILL_MAP = {
    "Python": ["python", "machine learning", "deep learning", "data science",
               "natural language", "computational", "bioinformatics"],
    "C++": ["c++", "systems", "embedded", "robotics", "high performance",
            "parallel computing", "compilers"],
    "MATLAB": ["matlab", "signal processing", "control", "power systems",
               "circuits", "electromagnetics"],
    "PyTorch": ["deep learning", "neural network", "computer vision",
                "reinforcement learning", "nlp"],
    "SQL": ["database", "data management", "information systems"],
    "Linux": ["systems", "networking", "security", "cloud"],
}


def _fetch_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, timeout=20, headers=HEADERS)
        resp.raise_for_status()
        # Parse bytes, not resp.text: the server omits a charset header, so
        # requests falls back to ISO-8859-1 and mangles UTF-8 names
        # ("Björn" -> "BjÃ¶rn"). BeautifulSoup detects the encoding itself.
        return BeautifulSoup(resp.content, "html.parser")
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def _clean_name(name: str) -> str:
    name = re.sub(r"(?i)^(dr\.?|prof\.?|professor)\s+", "", name).strip()
    name = re.sub(r"\s*\(.*?\)\s*", " ", name).strip()
    name = re.sub(r",?\s*(Ph\.?D\.?|M\.?D\.?|Jr\.?|Sr\.?|III|II)$", "", name).strip()
    return re.sub(r"\s{2,}", " ", name)


def _scrape_eecs_faculty_list(soup: BeautifulSoup, base: str) -> list[dict]:
    """Parse the EECS directory into [{name, url, email, title, research_areas}].

    Berkeley-specific markup (verified against the live page): each faculty
    member is a `div.cc-image-list__item__content` containing an `h3 > a`
    (name + profile link), a `<p>` whose first `<strong>` is the rank, an
    inline email address, and one or more `a[href*='/Research/Areas/']` tags.
    """
    faculty: list[dict] = []
    for block in soup.select("div.cc-image-list__item__content"):
        name_el = block.select_one("h3 a[href*='/Faculty/Homepages/']")
        if not name_el:
            continue
        name = _clean_name(name_el.get_text(strip=True))
        if not name or len(name) < 3:
            continue

        person: dict = {"name": name, "url": urljoin(base, name_el.get("href", ""))}

        p = block.find("p")
        p_text = p.get_text(" ", strip=True) if p else ""

        # Title: first <strong> that isn't a "Label:" header (e.g. "Professor").
        if p:
            for strong in p.find_all("strong"):
                t = strong.get_text(strip=True)
                if t and not t.endswith(":"):
                    person["title"] = t
                    break

        # Email: inline in the <p>; keep only Berkeley addresses.
        emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", p_text)
        berkeley = [e for e in emails
                    if e.lower().endswith("berkeley.edu")
                    and e.lower() not in NOISE_EMAILS]
        if berkeley:
            person["email"] = berkeley[0]

        # Research areas: the linked topic tags.
        areas = [a.get_text(strip=True)
                 for a in (p.select("a[href*='/Research/Areas/']") if p else [])]
        if areas:
            person["research_areas"] = "; ".join(areas)

        faculty.append(person)

    logger.info(f"  Found {len(faculty)} EECS faculty")
    return faculty


def _extract_research_keywords(person: dict, config: dict) -> list[str]:
    text = " ".join([person.get("research_areas", ""), person.get("title", "")]).lower()
    found = [kw for kw in _KEYWORD_BANK if kw in text]
    if not found:
        # No parseable research signal: fall back to the broad department field
        # only — never inject unverifiable specific subfields (same policy as
        # uiuc_faculty).
        found = config.get("keywords", [])[:1]
    return found[:8]


def _infer_skills_from_research(person: dict) -> list[str]:
    text = person.get("research_areas", "").lower()
    skills = {skill for skill, triggers in _SKILL_MAP.items()
              if any(t in text for t in triggers)}
    return sorted(skills)[:5]


def normalize_faculty(person: dict, config: dict) -> dict | None:
    """Convert a scraped faculty entry into the normalized opportunity schema."""
    name = person.get("name", "")
    if not name or len(name) < 3:
        return None

    email = person.get("email", "")
    dept_short = config["short"]
    dept_name = config["name"]
    profile_url = person.get("url", "")
    title = person.get("title", "Professor")
    if _RETIRED_TITLE_RE.search(title):
        return None
    research_areas = person.get("research_areas", "")

    name_hash = hashlib.md5(f"{dept_short}-{name}".encode()).hexdigest()[:8]
    opp_id = f"faculty-ucb-{dept_short.lower()}-{name_hash}"

    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    keywords = _extract_research_keywords(person, config)
    skills = _infer_skills_from_research(person)

    desc_parts = [
        f"Research opportunity with {title} {name} in the {dept_name} "
        f"at UC Berkeley.",
    ]
    if research_areas:
        desc_parts.append(f"Research areas: {research_areas[:200]}")
    desc_parts.append(
        "Contact the professor directly to inquire about undergraduate "
        "research positions in their lab."
    )
    description = " ".join(desc_parts)

    research_summary = f" ({', '.join(keywords[:3])})" if keywords else ""
    opp_title = f"Research with Prof. {name} — {dept_short}{research_summary}"

    return {
        "id": opp_id,
        "source": "ucb_eecs_faculty",
        "source_url": profile_url,
        "source_type": "faculty_research",
        "title": opp_title,
        "organization": "University of California, Berkeley",
        "department": dept_name,
        "lab_or_program": f"Prof. {name}'s Research Group",
        "pi_name": name,
        "contact_email": email or None,
        "url": profile_url,
        "location": "Berkeley, CA",
        "on_campus": False,
        "remote_option": "unknown",
        "opportunity_type": "research",
        "paid": "unknown",
        "compensation_details": "",
        "deadline": None,
        "posted_date": None,
        "start_date": None,
        "duration": "Semester or academic year",
        "eligibility": {
            "preferred_year": ["sophomore", "junior", "senior"],
            "min_gpa": None,
            "majors": config["majors"],
            "skills_required": skills[:3],
            "skills_preferred": skills[3:],
            "citizenship_required": False,
            "international_friendly": "unknown",
            "work_auth_notes": "External campus (UC Berkeley) — work "
                               "authorization depends on the arrangement",
            "eligibility_text_raw": description[:500],
        },
        "application": {
            "contact_method": "email",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "low",
            "application_url": profile_url,
        },
        "description_raw": description,
        "description_clean": description[:1500],
        "keywords": keywords,
        "metadata": {
            "confidence_score": 0.7 if email else 0.5,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": f"Auto-imported from {dept_name} faculty directory",
            "faculty_title": title,
            "research_areas_raw": research_areas[:300] if research_areas else "",
        },
    }


def fetch_and_normalize() -> list[dict]:
    """Scrape EECS faculty and return normalized opportunity records."""
    soup = _fetch_soup(EECS_CONFIG["url"])
    if not soup:
        return []
    raw = _scrape_eecs_faculty_list(soup, EECS_CONFIG["base"])
    normalized = []
    for person in raw:
        opp = normalize_faculty(person, EECS_CONFIG)
        if opp:
            normalized.append(opp)
    logger.info(f"Normalized {len(normalized)} EECS faculty opportunities")
    return normalized


def merge_into_processed(new_opps: list[dict]) -> tuple[int, int]:
    """Upsert EECS faculty records into processed/opportunities.json by id."""
    if not PROCESSED_FILE.exists():
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    index = {opp.get("id"): opp for opp in existing if opp.get("id")}
    added = updated = 0
    for opp in new_opps:
        if opp["id"] in index:
            # Preserve original first_seen_at, refresh everything else.
            opp["metadata"]["first_seen_at"] = index[opp["id"]].get(
                "metadata", {}).get("first_seen_at", opp["metadata"]["first_seen_at"])
            old = index[opp["id"]]
            old.update(opp)
            updated += 1
        else:
            existing.append(opp)
            index[opp["id"]] = opp
            added += 1
    with PROCESSED_FILE.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False, default=str)
    return (added, updated)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="UC Berkeley EECS Faculty Collector")
    parser.add_argument("--save", action="store_true",
                        help="Merge into processed/opportunities.json")
    args = parser.parse_args()

    opps = fetch_and_normalize()
    print(f"\nFetched {len(opps)} EECS faculty research opportunities")
    for o in opps[:8]:
        email_str = o.get("contact_email") or "no email"
        print(f"\n  {o['title'][:70]}")
        print(f"    PI: {o.get('pi_name', '')} ({email_str})")
        print(f"    Keywords: {', '.join(o.get('keywords', []))}")

    if args.save:
        added, updated = merge_into_processed(opps)
        print(f"\nSaved: {added} new, {updated} updated")
    else:
        print("\n(Use --save to merge into processed/opportunities.json)")
