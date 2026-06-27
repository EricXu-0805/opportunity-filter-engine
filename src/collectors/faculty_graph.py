"""School-agnostic faculty-directory engine (curated-seed first, scrape-optional).

Generalizes the UC Berkeley department faculty collectors (``ucb_common`` +
the ``ucb_*_faculty`` configs) into a reusable engine so a new school's faculty
coverage is a config module under ``schools/`` — not a fresh collector.

Why curated-seed-first (unlike the Berkeley collectors, which scrape live):
some schools' department directories sit behind a bot wall (e.g. University of
Michigan's lsa/engin pages return Cloudflare 403 to ``requests``). A stdlib
scraper lands zero records there. So this engine inverts the Berkeley model:

  1. **Curated seed layer (always on, offline-safe, stdlib only).** Each
     department config carries a hand-verified list of real professors
     (name, title, profile URL, research areas, optional public email). These
     normalize into ``faculty_research`` records unconditionally — no network,
     so the data exists even when the directory blocks scrapers.

  2. **Best-effort scrape layer (deep mode, opt-in per department).** If a
     department config supplies a ``scrape`` block (url + CSS selectors), deep
     mode fetches and parses it to *discover* additional faculty on top of the
     curated set. Lazy-imports requests/bs4; any failure (403, timeout, markup
     drift) degrades silently to the curated seeds. Schools whose directories
     aren't walled get breadth for free; walled schools omit ``scrape`` and
     ship the curated set.

Records match the exact schema the Berkeley faculty collectors emit
(``source_type="faculty_research"``, pi_name/contact_email, eligibility +
metadata dicts) so they pass the same data-quality gate. The engine reuses
``ucb_common``'s school-agnostic helpers (person-name guard, nav-furniture
strip, funding detection, skill inference) rather than duplicating them.

A school config (see ``schools/umich_faculty.py``) is a dict:

    {
      "school_slug": "umich",
      "source": "umich_faculty",            # single source, dept in `department`
      "organization": "University of Michigan",
      "location": "Ann Arbor, MI",
      "id_prefix": "umich",
      "audience": "unknown",                # faculty = per-prof openness
      "work_auth_notes": "...",
      "departments": [
        {
          "short": "CSE",
          "name": "Computer Science & Engineering",
          "majors": ["Computer Science", ...],
          "directory_url": "https://cse.umich.edu/people/faculty/",
          "faculty": [ faculty(...), ... ],
          # optional: "scrape": {"url": ..., "selectors": {...}}
        },
        ...
      ],
    }
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from datetime import UTC, datetime

from .ucb_common import (
    _RETIRED_TITLE_RE,
    _detect_funding,
    _is_person_name,
    _strip_nav_furniture,
    infer_skills_from_research,
)

logger = logging.getLogger(__name__)

_DESC_CAP = 1500


def faculty(
    name: str,
    *,
    title: str = "Professor",
    url: str = "",
    email: str | None = None,
    research_areas: str = "",
    keywords: list[str] | None = None,
) -> dict:
    """Build one curated faculty spec.

    ``research_areas`` is free text (shown in the description + stored raw).
    ``keywords`` is the clean topical list that drives the title parenthetical
    and the matcher — keep it tidy (no page furniture / fragments) so it passes
    the faculty data-quality gate. If omitted it falls back to research_areas.
    """
    return {
        "name": name,
        "title": title,
        "url": url,
        "email": email,
        "research_areas": research_areas,
        "keywords": keywords or [],
    }


def validate(school: dict) -> list[str]:
    """Structural problems with a faculty school config (empty = healthy)."""
    errors: list[str] = []
    for field in ("school_slug", "source", "organization", "location", "id_prefix"):
        if not school.get(field):
            errors.append(f"missing {field}")
    seen_short: set[str] = set()
    for dept in school.get("departments", []):
        short = dept.get("short")
        if not short:
            errors.append("department missing 'short'")
        elif short in seen_short:
            errors.append(f"duplicate department short {short!r}")
        seen_short.add(short)
        if not dept.get("name"):
            errors.append(f"{short}: missing department name")
        if not dept.get("faculty") and not dept.get("scrape"):
            errors.append(f"{short}: no curated faculty and no scrape config")
        for person in dept.get("faculty", []):
            if not person.get("name"):
                errors.append(f"{short}: faculty entry missing name")
    return errors


# ---------------------------------------------------------------------------
# Normalization (stdlib only)
# ---------------------------------------------------------------------------

def _clean_keywords(person: dict) -> list[str]:
    """Curated keywords win; otherwise derive a couple from research areas.

    Curated lists are trusted (the config author keeps them clean); the derived
    fallback splits research_areas on separators and trims, so even a config
    that only fills research_areas yields something the title can show.
    """
    kws = [k.strip() for k in person.get("keywords", []) if k and k.strip()]
    if kws:
        # de-dupe preserving order
        return list(dict.fromkeys(kws))[:8]
    raw = _strip_nav_furniture(person.get("research_areas", ""))
    parts = [p.strip() for chunk in raw.split(";") for p in chunk.split(",")]
    return list(dict.fromkeys(p for p in parts if len(p) >= 3))[:8]


def _normalize(school: dict, dept: dict, person: dict) -> dict | None:
    """Convert one faculty spec into the normalized opportunity schema."""
    name = (person.get("name") or "").strip()
    if not _is_person_name(name):
        return None
    title = person.get("title") or "Professor"
    if _RETIRED_TITLE_RE.search(title):
        return None

    short = dept["short"]
    dept_name = dept["name"]
    profile_url = person.get("url", "")
    email = person.get("email") or None
    research_areas = _strip_nav_furniture(person.get("research_areas", ""))
    keywords = _clean_keywords(person)
    skills = infer_skills_from_research(person)

    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    name_hash = hashlib.md5(f"{short}-{name}".encode()).hexdigest()[:8]
    opp_id = f"faculty-{school['id_prefix']}-{short.lower()}-{name_hash}"

    desc_parts = [
        f"Research opportunity with {title} {name} in the {dept_name} "
        f"at {school['organization']}."
    ]
    if research_areas:
        desc_parts.append(f"Research areas: {research_areas[:200]}")
    desc_parts.append(
        "Contact the professor directly to inquire about undergraduate "
        "research positions in their lab."
    )
    description = " ".join(desc_parts)
    # Defensive second pass on the fully assembled description (mirrors
    # ucb_common.normalize_faculty): the DQ gate checks nav-furniture phrases in
    # description_clean, so stripping the final string makes a leak impossible
    # regardless of entry path — matters once a school enables the scrape layer.
    description = _strip_nav_furniture(description)

    research_summary = f" ({', '.join(keywords[:3])})" if keywords else ""
    opp_title = f"Research with Prof. {name} — {short}{research_summary}"
    paid, compensation_details = _detect_funding(f"{research_areas} {description} {title}")

    return {
        "id": opp_id,
        "source": school["source"],
        "source_url": profile_url,
        "source_type": "faculty_research",
        "title": opp_title,
        "organization": school["organization"],
        "department": dept_name,
        "lab_or_program": f"Prof. {name}'s Research Group",
        "pi_name": name,
        "contact_email": email,
        "url": profile_url,
        "location": school["location"],
        # External to this product's home users (matches the ucb_* convention);
        # multi-school scoping rides on school/audience, not on_campus.
        "on_campus": False,
        "remote_option": "unknown",
        "opportunity_type": "research",
        "paid": paid,
        "compensation_details": compensation_details,
        "deadline": None,
        "is_rolling": True,
        "posted_date": None,
        "start_date": None,
        "duration": "Semester or academic year",
        "eligibility": {
            "preferred_year": ["sophomore", "junior", "senior"],
            "min_gpa": None,
            "majors": dept.get("majors", []),
            "skills_required": skills[:3],
            "skills_preferred": skills[3:],
            "citizenship_required": False,
            "international_friendly": "unknown",
            "work_auth_notes": school.get("work_auth_notes", ""),
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
        "description_clean": description[:_DESC_CAP],
        "keywords": keywords,
        "school": school["school_slug"],
        "audience": school.get("audience", "unknown"),
        "metadata": {
            "confidence_score": 0.7 if email else 0.5,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": f"Curated from {dept_name} faculty directory ({school['organization']})",
            "faculty_title": title,
            "research_areas_raw": research_areas[:300] if research_areas else "",
            "curated": True,
        },
    }


# ---------------------------------------------------------------------------
# Best-effort scrape layer (deep mode, lazy HTTP deps)
# ---------------------------------------------------------------------------

def _scrape_directory(dept: dict) -> list[dict]:
    """Best-effort parse of a department directory into faculty specs.

    Opt-in: only runs when the department config has a ``scrape`` block. Lazy-
    imports requests/bs4 and degrades to ``[]`` on any failure (a 403 bot wall,
    timeout, or markup drift) so deep mode never breaks the curated layer.
    """
    cfg = dept.get("scrape")
    if not cfg:
        return []
    try:
        from .ucb_common import fetch_soup
    except Exception:  # noqa: BLE001
        return []
    soup = fetch_soup(cfg["url"])
    if soup is None:
        logger.info("faculty_graph: directory unreachable for %s (curated only)", dept.get("short"))
        return []
    sel = cfg.get("selectors", {})
    people: list[dict] = []
    try:
        for card in soup.select(sel.get("card", "")):
            name_el = card.select_one(sel["name"]) if sel.get("name") else None
            if not name_el:
                continue
            name = name_el.get_text(" ", strip=True)
            link_el = card.select_one(sel.get("link", "")) if sel.get("link") else name_el
            href = link_el.get("href") if link_el and link_el.has_attr("href") else ""
            title_el = card.select_one(sel["title"]) if sel.get("title") else None
            title = title_el.get_text(" ", strip=True) if title_el else "Professor"
            if _is_person_name(name):
                people.append(faculty(name, title=title, url=href or cfg["url"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("faculty_graph: scrape parse failed for %s: %s", dept.get("short"), e)
        return []
    return people


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _key_email(rec: dict) -> str:
    return (rec.get("contact_email") or "").strip().lower()


def _key_url(rec: dict) -> str:
    return (rec.get("url") or "").strip().lower()


def fetch_and_normalize(school: dict, deep: bool = False) -> list[dict]:
    """Normalize a school's curated faculty (+ best-effort scrape in deep mode).

    Joint-appointment de-dup keys on contact_email and profile URL — the things
    a single person shares when listed under two departments — NOT on bare name.
    Two genuinely different professors can share a name (e.g. Michigan has two
    "Wei Lu", one in ECE doing memristors and one in ME doing batteries, with
    different emails); a name-based key would wrongly merge them.
    """
    errors = validate(school)
    if errors:
        raise ValueError(f"{school.get('school_slug')} faculty config invalid: " + "; ".join(errors))

    records: list[dict] = []
    seen_emails: set[str] = set()
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    for dept in school.get("departments", []):
        specs = list(dept.get("faculty", []))
        if deep:
            curated_urls = {(p.get("url") or "").strip().lower() for p in specs}
            specs += [p for p in _scrape_directory(dept)
                      if (p.get("url") or "").strip().lower() not in curated_urls]
        for person in specs:
            rec = _normalize(school, dept, person)
            if rec is None:
                continue
            ek, uk = _key_email(rec), _key_url(rec)
            if rec["id"] in seen_ids:
                continue
            if ek and ek in seen_emails:
                continue
            if uk and uk in seen_urls:
                continue
            seen_ids.add(rec["id"])
            if ek:
                seen_emails.add(ek)
            if uk:
                seen_urls.add(uk)
            records.append(rec)
    return records


def merge_into_processed(new_opps: list[dict]):
    """Upsert faculty records into processed/opportunities.json by id.

    School-scoped (unlike ucb_common.merge_into_processed, which is hard-wired
    to the ucb_ prefix): intra-batch dedup already happened in
    fetch_and_normalize, and ids are stable (dept+name hash), so a re-run
    upserts cleanly. We deliberately do NOT cross-dedup against other schools'
    faculty by name — two schools can have a professor with the same name.
    """
    import json

    from .ucb_common import PROCESSED_FILE

    if not PROCESSED_FILE.exists() or not new_opps:
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    index = {o.get("id"): o for o in existing if o.get("id")}
    added = updated = 0
    for opp in new_opps:
        if opp["id"] in index:
            opp["metadata"]["first_seen_at"] = index[opp["id"]].get(
                "metadata", {}).get("first_seen_at", opp["metadata"]["first_seen_at"])
            index[opp["id"]].update(opp)
            updated += 1
        else:
            existing.append(opp)
            index[opp["id"]] = opp
            added += 1
    with PROCESSED_FILE.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False, default=str)
    return (added, updated)


def source_breakdown(opps: list[dict]) -> dict:
    return {
        "total": len(opps),
        "by_department": dict(Counter(o.get("department") for o in opps)),
        "with_email": sum(1 for o in opps if o.get("contact_email")),
    }
