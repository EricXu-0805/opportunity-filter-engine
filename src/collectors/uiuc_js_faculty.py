"""
Collector for UIUC JS-rendered faculty directories (ACES / Drupal Views AJAX).

Several UIUC ACES departments render their faculty directory client-side via
Drupal Views AJAX, so the static ``uiuc_faculty`` scraper sees only the
category navigation links (the person cards are injected after page load).
This collector drives a headless Chromium via Playwright to render the
listing, extract the person profile links (``/directory/<netid>``), and derive
the contact email from the netid slug — the slug *is* the netid, so no
per-profile render is needed (verified: dshike/callen/aantnsn2 mailto links
match their listing slugs).

Playwright is imported lazily so environments without it (e.g. the Render
scheduled refresh) import this module cleanly and skip gracefully. This
collector is run locally to land data and is intentionally NOT wired into the
default ``refresh_all`` path.

It reuses ``normalize_faculty``, ``_clean_name``, ``_is_section_label`` and
``merge_into_processed`` from ``uiuc_faculty`` for schema and filter
consistency with the static faculty collector.

Usage:
    python -m src.collectors.uiuc_js_faculty               # fetch & preview
    python -m src.collectors.uiuc_js_faculty --save        # merge into processed
    python -m src.collectors.uiuc_js_faculty --dept ansc   # single department
"""

import logging
import re
from urllib.parse import urljoin

from src.collectors.uiuc_faculty import (
    _clean_name,
    _is_section_label,
    merge_into_processed,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

# Each ACES department exposes the same Drupal directory shape; the listing
# path differs (faculty-members vs faculty), confirmed live per department.
JS_DEPARTMENTS = {
    "ansc": {
        "name": "Department of Animal Sciences",
        "short": "ANSC",
        "url": "https://ansc.illinois.edu/directory/faculty-members",
        "base": "https://ansc.illinois.edu",
        "majors": ["Animal Sciences"],
        "keywords": ["animal sciences", "animal nutrition", "physiology",
                     "genetics", "reproductive biology", "meat science"],
    },
    "cropsci": {
        "name": "Department of Crop Sciences",
        "short": "CropSci",
        "url": "https://cropsciences.illinois.edu/directory/faculty",
        "base": "https://cropsciences.illinois.edu",
        "majors": ["Crop Sciences", "Agronomy", "Plant Biology"],
        "keywords": ["crop sciences", "agronomy", "plant breeding",
                     "plant genetics", "soil science", "plant pathology"],
    },
    "nres": {
        "name": "Natural Resources & Environmental Sciences",
        "short": "NRES",
        "url": "https://nres.illinois.edu/directory/faculty",
        "base": "https://nres.illinois.edu",
        "majors": ["Natural Resources & Environmental Sciences",
                   "Environmental Science"],
        "keywords": ["natural resources", "environmental sciences", "ecology",
                     "conservation", "soil science", "hydrology"],
    },
    "fshn": {
        "name": "Food Science & Human Nutrition",
        "short": "FSHN",
        "url": "https://fshn.illinois.edu/directory/faculty",
        "base": "https://fshn.illinois.edu",
        "majors": ["Food Science", "Human Nutrition", "Dietetics"],
        "keywords": ["food science", "human nutrition", "dietetics",
                     "food chemistry", "food microbiology", "metabolism"],
    },
}

# UIUC netids: a leading letter then 1-10 alphanumerics (e.g. dshike, callen,
# aantnsn2, nb41). The slug at the end of /directory/<slug> must match this to
# be a person profile rather than a category page.
_NETID_RE = re.compile(r"^[a-z][a-z0-9]{1,10}$")

# Directory category slugs that share the /directory/ prefix but are section
# pages, not people. Excluded before the netid test as a cheap first filter.
_CATEGORY_SLUGS: frozenset[str] = frozenset({
    "main-contacts", "faculty-members", "faculty", "adjunct-faculty-members",
    "emeritus-faculty-members", "emeritus", "teaching-staff", "farm-staff",
    "research-staff", "staff", "graduate-students", "research-groups",
    "postdoctoral-researchers", "affiliate-faculty", "affiliates",
    "academic-professionals", "administration", "postdocs", "adjunct-faculty",
    "research-scientists", "specialists", "extension", "advisors",
})


def _render_person_links(url: str, timeout_ms: int = 45000) -> list[dict]:
    """Render a JS faculty listing and return raw ``[{h, t}]`` anchor dicts.

    Playwright is imported lazily here so the module imports cleanly in
    environments where Playwright/Chromium are not installed (the collector
    then yields no people and the caller skips gracefully).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning(
            "playwright not installed; skipping JS faculty collection. Install: "
            "pip install playwright && python -m playwright install chromium"
        )
        return []

    links: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Drupal Views injects the person cards via AJAX after load; wait
            # for the first /directory/ anchor, then settle briefly so the full
            # list is in the DOM before we read it.
            try:
                page.wait_for_selector('a[href^="/directory/"]', timeout=timeout_ms)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({h: e.getAttribute('href'), "
                "t: e.textContent.trim()}))",
            )
        except Exception as e:
            logger.warning(f"Failed to render {url}: {e}")
        finally:
            browser.close()
    return links


def _scrape_js_faculty_list(dept_config: dict) -> list[dict]:
    """Render a department listing and return ``[{name, url, email}]`` people."""
    url = dept_config["url"]
    base = dept_config["base"]
    logger.info(f"Rendering {dept_config['short']} faculty from {url}")

    people: list[dict] = []
    seen: set[str] = set()
    for link in _render_person_links(url):
        href = (link.get("h") or "").strip()
        text = (link.get("t") or "").strip()
        if not href.startswith("/directory/"):
            continue
        slug = href.rstrip("/").split("/")[-1]
        if slug in _CATEGORY_SLUGS or not _NETID_RE.match(slug):
            continue
        # Person link text is a name: keep 2-5 word anchors and drop the section
        # headings ("Emeritus Faculty", …) that share the person URL shape.
        if not (2 <= len(text.split()) <= 5):
            continue
        if href in seen:
            continue
        seen.add(href)
        name = _clean_name(text)
        if _is_section_label(name):
            continue
        people.append({
            "name": name,
            "url": urljoin(base, href),
            "email": f"{slug}@illinois.edu",
        })

    logger.info(f"  Found {len(people)} faculty in {dept_config['short']}")
    return people


def fetch_department(dept_key: str) -> list[dict]:
    """Render & normalize faculty for a single JS department."""
    if dept_key not in JS_DEPARTMENTS:
        logger.error(f"Unknown JS department: {dept_key}")
        return []

    config = JS_DEPARTMENTS[dept_key]
    normalized = []
    for person in _scrape_js_faculty_list(config):
        opp = normalize_faculty(person, config)
        if opp:
            normalized.append(opp)
    return normalized


def fetch_and_normalize(departments: list[str] = None) -> list[dict]:
    """Render faculty across JS departments and return normalized records."""
    if departments is None:
        departments = list(JS_DEPARTMENTS.keys())

    all_opps = []
    for dept_key in departments:
        try:
            dept_opps = fetch_department(dept_key)
            all_opps.extend(dept_opps)
            logger.info(f"  {JS_DEPARTMENTS[dept_key]['short']}: {len(dept_opps)} opportunities")
        except Exception as e:
            logger.error(f"Failed to collect {dept_key}: {e}")

    logger.info(f"Total JS faculty opportunities: {len(all_opps)}")
    return all_opps


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="UIUC JS-rendered Faculty Collector")
    parser.add_argument("--save", action="store_true",
                        help="Merge into processed/opportunities.json")
    parser.add_argument("--dept", type=str, default=None,
                        help=f"Single department: {', '.join(JS_DEPARTMENTS.keys())}")
    parser.add_argument("--list-depts", action="store_true",
                        help="List available departments and exit")
    args = parser.parse_args()

    if args.list_depts:
        print("\nAvailable JS departments:")
        for key, cfg in JS_DEPARTMENTS.items():
            print(f"  {key:10s} — {cfg['name']}")
            print(f"  {'':10s}   {cfg['url']}")
        raise SystemExit(0)

    depts = [args.dept] if args.dept else None
    opps = fetch_and_normalize(departments=depts)

    print(f"\nFetched {len(opps)} JS faculty research opportunities")
    for o in opps[:8]:
        email_str = o.get("contact_email") or "no email"
        print(f"\n  {o['title'][:70]}")
        print(f"    PI: {o.get('pi_name', '')} ({email_str})")
        print(f"    Dept: {o['department']}")
        print(f"    Keywords: {', '.join(o.get('keywords', []))}")

    if args.save:
        added, updated = merge_into_processed(opps)
        print(f"\nSaved: {added} new, {updated} updated")
    else:
        print("\n(Use --save to merge into processed/opportunities.json)")
