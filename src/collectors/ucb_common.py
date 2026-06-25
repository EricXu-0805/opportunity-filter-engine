"""Shared machinery for UC Berkeley faculty-directory collectors.

Berkeley runs several department directories on the same Drupal "Open Berkeley"
theme (Statistics, Chemistry, CEE, ...). They differ only in CSS selectors and a
few labels, so the scraping/enrichment/normalization logic lives here and each
department module is reduced to a config dict. EECS (a non-Drupal directory)
keeps its own card parser but shares everything else — fetching, keyword/skill
inference, normalization, and the merge path — through this module.

A department config is a dict with:
    source     str   normalized record `source` (e.g. "ucb_stat_faculty")
    name       str   full department name
    short      str   short code used in titles + record ids (e.g. "STAT")
    url        str   faculty listing URL
    base       str   site origin for resolving relative profile links
    majors     list  majors attached to each opportunity (for matching)
    keywords   list  broad-field fallback keyword(s)
    selectors  dict  CSS selectors: card, name, link, title, email_field,
                     research_interests (list of profile-page selectors)
    work_auth_notes  str, optional  eligibility note (default "")
    area_keywords    dict, optional  umbrella research-area tag -> topical
                     keywords (tag names lowercased, "(ACRONYM)" stripped)

The "Open Berkeley" listing pages expose only name + profile link + job title
— NOT email or research interests. enrich_faculty_from_profiles() recovers
both by visiting each profile page. Records with no email found ship "lite"
(contact_email=None, confidence_score=0.5).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"

# Browser-like headers. Berkeley department sites reset the connection (errno
# 54) on requests that don't look like a real browser, so we send a full set.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Transient-fetch tuning.
_TIMEOUT = 30
_MAX_RETRIES = 3
_RETRY_BACKOFF = 2.0  # seconds; doubles each attempt

# Politeness delay between individual profile-page requests.
PROFILE_DELAY = 0.75

# Shared/admin mailboxes that are not a specific professor's contact, plus the
# EECS directory's placeholder shown when a professor lists no address.
NOISE_EMAILS = frozenset({
    "webmaster@berkeley.edu", "info@berkeley.edu",
    "inquiries@stat.berkeley.edu", "info@stat.berkeley.edu",
    "webmaster@stat.berkeley.edu",
    "no_email@eecs.berkeley.edu",
    # Math lists its front-office mailbox as a second mailto on every profile;
    # without this, faculty whose personal address is non-Berkeley would resolve
    # to it (the extractor prefers a berkeley.edu address).
    "frontoffice@math.berkeley.edu",
    # Physics lists its department admin mailbox as a second mailto on every
    # profile; without this, faculty whose personal address is non-Berkeley
    # (e.g. an @lbl.gov address) would resolve to it.
    "physics_admin@berkeley.edu",
})

# Department directories mix retired faculty into the same card list; they are
# not viable cold-email targets for prospective undergrad researchers.
_RETIRED_TITLE_RE = re.compile(r"\b(emeritus|emerita|retired)\b", re.IGNORECASE)

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Generic, source-agnostic keyword/skill inference. Listing-only ("lite")
# records have no research signal and fall back to the broad department field;
# a future profile-enrichment pass that fills research_areas gets these for free.
KEYWORD_BANK = [
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
    "graph neural networks", "large language models", "statistics",
    "probability", "statistical learning", "causal inference",
    "biostatistics", "econometrics", "experimental design", "time series",
    "stochastic processes",
    "organic chemistry", "inorganic chemistry", "physical chemistry",
    "chemical biology", "catalysis", "spectroscopy",
    "structural engineering", "earthquake engineering", "geotechnical",
    "transportation", "air quality", "air pollution", "water treatment",
    "hydrology", "environmental microbiology", "construction",
    "infrastructure", "climate", "sustainability", "fluid mechanics",
    "computational mechanics", "structural health monitoring",
    "energy systems",
    "fluid dynamics", "wave mechanics", "ocean engineering", "thermodynamics",
    "heat transfer", "combustion", "manufacturing", "additive manufacturing",
    "microfabrication", "nanomanufacturing", "biomechanics", "mechatronics",
    "vibration", "acoustics", "tribology", "energy efficiency", "mems",
    "dynamics and control",
    "nuclear physics", "nuclear chemistry", "nuclear reactors", "reactor physics",
    "nuclear fuel", "radioactive waste", "fission", "fusion", "neutron detection",
    "radiation detection", "isotopes", "radiochemistry", "nuclear security",
    "nonproliferation", "molten salt reactors", "nuclear materials",
    "astronomy", "astrophysics", "cosmology", "exoplanets", "galaxies",
    "star formation", "black holes", "stellar astrophysics",
    "observational astronomy", "radio astronomy", "interstellar medium",
    "planetary science",
    "operations research", "game theory", "integer programming", "supply chain",
    "logistics", "queueing", "scheduling", "revenue management", "inventory",
    "healthcare systems",
    "molecular biology", "cell biology", "biochemistry", "biophysics",
    "immunology", "genetics", "structural biology", "microbiology", "virology",
    "developmental biology", "gene expression", "crispr", "stem cells",
    "cancer biology", "systems biology", "rna biology", "gene regulation",
    "earth science", "geology", "geophysics", "geochemistry", "seismology",
    "mineralogy", "paleontology", "stratigraphy", "tectonics",
    "planetary science", "oceanography", "climate science", "volcanology",
    "geobiology", "geomorphology",
    "plant biology", "microbiology", "genetics", "evolution",
    "evolutionary biology", "ecology", "plant-microbe interactions",
    "plant immunity", "photosynthesis", "fungal biology", "microbial ecology",
    "plant genetics", "plant pathology", "crop science",
    "environmental science", "conservation biology", "forestry", "entomology",
    "environmental policy", "wildlife biology", "natural resources",
    "fire ecology", "biodiversity", "environmental economics", "agroecology",
    "soil science", "restoration ecology", "pest management",
    "nutrition", "nutritional science", "metabolism", "metabolic biology",
    "toxicology", "obesity", "diabetes", "endocrinology", "physiology",
    "gut microbiome", "aging", "stem cells", "biochemistry",
    "psychology", "cognitive psychology", "clinical psychology",
    "social psychology", "developmental psychology", "cognitive neuroscience",
    "perception", "attention", "memory", "emotion regulation",
    "behavioral science", "psychopathology", "personality",
    "architectural design", "urban design", "sustainable design",
    "computational design", "design computation", "digital fabrication",
    "building technology", "building science", "building performance",
    "historic preservation", "architectural history", "housing", "urbanism",
    "environmental design", "materials research", "landscape architecture",
    "city planning", "urban planning",
    "urban planning", "city planning", "regional planning",
    "transportation planning", "land use", "urban design", "urbanism",
    "housing", "community development", "economic development",
    "environmental planning", "spatial analysis", "public transportation",
    "urban economics", "real estate development", "climate adaptation",
    "sustainable development", "urban policy", "geographic information systems",
    "landscape architecture",
    "landscape architecture", "environmental planning", "ecological design",
    "landscape ecology", "urban ecology", "green infrastructure",
    "ecological restoration", "landscape design", "land use",
    "stormwater management", "regional planning", "climate adaptation",
    "environmental design", "ecological planning", "resilient design",
    "urban design", "open space", "environmental justice",
]

SKILL_MAP = {
    "Python": ["python", "machine learning", "deep learning", "data science",
               "natural language", "computational", "bioinformatics"],
    "R": ["statistical", "statistics", "biostatistics", "probability"],
    "C++": ["c++", "systems", "embedded", "robotics", "high performance",
            "parallel computing", "compilers"],
    "PyTorch": ["deep learning", "neural network", "computer vision",
                "reinforcement learning", "nlp"],
    "SQL": ["database", "data management", "information systems"],
    "MATLAB": ["matlab", "signal processing", "control", "power systems",
               "circuits", "electromagnetics"],
    "Linux": ["systems", "networking", "security", "cloud"],
}


def fetch_soup(url: str) -> BeautifulSoup | None:
    """Fetch a URL with browser-like headers, retrying transient failures.

    Retries connection resets / timeouts / 5xx responses with exponential
    backoff. Returns None (never raises) if every attempt fails, so callers
    degrade to an empty result instead of crashing.
    """
    session = requests.Session()
    session.headers.update(HEADERS)
    last_err: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            # Parse bytes, not resp.text: the EECS server omits a charset
            # header, so requests falls back to ISO-8859-1 and mangles UTF-8
            # names ("Björn" -> "BjÃ¶rn"). BeautifulSoup detects the encoding.
            return BeautifulSoup(resp.content, "html.parser")
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last_err = e
        except requests.exceptions.HTTPError as e:
            # Retry only on transient server errors; client errors are terminal.
            status = e.response.status_code if e.response is not None else None
            if status is None or status < 500:
                logger.warning(f"Failed to fetch {url}: {e}")
                return None
            last_err = e
        except Exception as e:  # noqa: BLE001 — unexpected; don't crash the run
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

        if attempt < _MAX_RETRIES:
            delay = _RETRY_BACKOFF * (2 ** (attempt - 1))
            logger.warning(
                f"Fetch attempt {attempt}/{_MAX_RETRIES} for {url} failed "
                f"({last_err}); retrying in {delay:.0f}s"
            )
            time.sleep(delay)

    logger.warning(
        f"Failed to fetch {url} after {_MAX_RETRIES} attempts: {last_err}"
    )
    return None


def clean_name(name: str) -> str:
    name = re.sub(r"(?i)^(dr\.?|prof\.?|professor)\s+", "", name).strip()
    name = re.sub(r"\s*\(.*?\)\s*", " ", name).strip()
    name = re.sub(r",?\s*(Ph\.?D\.?|M\.?D\.?|Jr\.?|Sr\.?|III|II)$", "", name).strip()
    return re.sub(r"\s{2,}", " ", name)


def scrape_open_berkeley_faculty(soup: BeautifulSoup, config: dict) -> list[dict]:
    """Parse an Open-Berkeley Drupal directory into [{name, url, title}].

    Selector-driven via config["selectors"] so each department's card markup is
    config, not code. `name` and `link` are separate selectors because some
    variants put the name in an <h2>/<h3> while the href lives on a wrapping or
    sibling <a>.
    """
    sel = config["selectors"]
    base = config["base"]
    faculty: list[dict] = []
    for card in soup.select(sel["card"]):
        name_el = card.select_one(sel["name"])
        link_el = card.select_one(sel["link"])
        if not name_el or not link_el:
            continue
        name = clean_name(name_el.get_text(" ", strip=True))
        href = link_el.get("href", "")
        if not name or len(name) < 3 or not href:
            continue

        person: dict = {"name": name, "url": urljoin(base, href)}
        title_el = card.select_one(sel["title"])
        if title_el:
            person["title"] = title_el.get_text(" ", strip=True)
        faculty.append(person)

    logger.info(f"  Found {len(faculty)} {config['short']} faculty")
    return faculty


def extract_email_from_profile(soup: BeautifulSoup, config: dict) -> str | None:
    """Pull a contact email from an individual faculty profile page.

    Tries, in order: a mailto: link, the configured email field, then a
    page-wide scan. Prefers Berkeley addresses and skips shared/admin mailboxes.
    Returns None when nothing usable is found.
    """
    candidates: list[str] = []

    for a in soup.select("a[href^='mailto:']"):
        addr = a.get("href", "").replace("mailto:", "").split("?")[0].strip()
        if addr:
            candidates.append(addr)

    email_sel = config.get("selectors", {}).get("email_field")
    if email_sel:
        field = soup.select_one(email_sel)
        if field:
            candidates += EMAIL_RE.findall(field.get_text(" ", strip=True))

    if not candidates:
        candidates += EMAIL_RE.findall(soup.get_text(" ", strip=True))

    cleaned = [e.lower() for e in candidates if e.lower() not in NOISE_EMAILS]
    if not cleaned:
        return None
    berkeley = [e for e in cleaned if e.endswith("berkeley.edu")]
    return (berkeley or cleaned)[0]


def extract_research_interests(soup: BeautifulSoup, config: dict) -> str:
    """Pull research-interest text from a faculty profile page.

    Selector-driven via selectors["research_interests"] (a list: Open-Berkeley
    profiles spread the signal across a free-text interests field and a linked
    research-areas taxonomy, either of which may be absent). Selectors target
    the Drupal .field__item values so field labels ("Research Expertise and
    Interests") never pollute the text. Returns "" when the profile carries no
    research section — the record then keeps its lite broad-field keyword.
    """
    parts: list[str] = []
    for sel in config.get("selectors", {}).get("research_interests", []):
        for el in soup.select(sel):
            text = el.get_text(" ", strip=True)
            if text:
                parts.append(text)
    return "; ".join(parts)


def enrich_faculty_from_profiles(faculty: list[dict], config: dict) -> list[dict]:
    """Visit each faculty profile page to recover contact email + research interests.

    Respectful: a small delay between requests, the same robust fetcher (headers
    + retries) used for the listing. A profile that fails to fetch or lacks a
    section simply leaves person['email'] / person['research_areas'] unset
    (lite behavior).
    """
    total = len(faculty)
    found = with_interests = 0
    for i, person in enumerate(faculty):
        url = person.get("url")
        if not url:
            continue
        soup = fetch_soup(url)
        if soup:
            email = extract_email_from_profile(soup, config)
            if email:
                person["email"] = email
                found += 1
            interests = extract_research_interests(soup, config)
            if interests:
                person["research_areas"] = interests
                with_interests += 1
        if i < total - 1:
            time.sleep(PROFILE_DELAY)
        if (i + 1) % 10 == 0:
            logger.info(f"  Enriched {i + 1}/{total} profiles ({found} emails)")
    logger.info(
        f"  Recovered {found}/{total} emails and {with_interests}/{total} "
        f"research-interest sections from profile pages"
    )
    return faculty


def dedup_by_profile_url(faculty: list[dict]) -> list[dict]:
    """Drop duplicate people appearing in more than one listing section.

    Keyed by profile URL (unique per person); falls back to name when a record
    somehow lacks a URL. First occurrence wins.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    for person in faculty:
        key = person.get("url") or person.get("name", "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(person)
    return unique


# Trailing "(ACRONYM)" on a directory research-area tag, e.g. "Theory (THY)".
_AREA_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _normalize_area_tag(tag: str) -> str:
    return _AREA_PAREN_RE.sub("", tag).strip().lower()


def extract_research_keywords(person: dict, config: dict) -> list[str]:
    """Derive topical keywords from a person's research areas + title.

    Directory umbrella tags (e.g. Berkeley EECS's fixed ~22-tag vocabulary)
    rarely contain bank keywords as substrings, so config["area_keywords"]
    maps each tag explicitly first; the generic substring match over
    KEYWORD_BANK then adds anything the tags/title mention verbatim.
    """
    found: list[str] = []
    area_map = config.get("area_keywords") or {}
    if area_map:
        for area in person.get("research_areas", "").split(";"):
            for kw in area_map.get(_normalize_area_tag(area), []):
                if kw not in found:
                    found.append(kw)
    text = " ".join([person.get("research_areas", ""), person.get("title", "")]).lower()
    found += [kw for kw in KEYWORD_BANK if kw in text and kw not in found]
    if not found:
        # No parseable research signal (the common case for lite records):
        # fall back to the broad department field only.
        found = config.get("keywords", [])[:1]
    return found[:8]


def infer_skills_from_research(person: dict) -> list[str]:
    text = person.get("research_areas", "").lower()
    skills = {skill for skill, triggers in SKILL_MAP.items()
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
    keywords = extract_research_keywords(person, config)
    skills = infer_skills_from_research(person)

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
        "source": config["source"],
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
            "work_auth_notes": config.get("work_auth_notes", ""),
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


def fetch_and_normalize(config: dict, enrich: bool = True) -> list[dict]:
    """Scrape one Open-Berkeley department and return normalized records.

    With enrich=True (default), each profile page is fetched to recover the
    contact email and research interests the listing page does not expose.
    """
    soup = fetch_soup(config["url"])
    if not soup:
        return []
    raw = dedup_by_profile_url(scrape_open_berkeley_faculty(soup, config))
    if enrich:
        raw = enrich_faculty_from_profiles(raw, config)
    normalized = [n for n in (normalize_faculty(p, config) for p in raw) if n]
    logger.info(f"Normalized {len(normalized)} {config['short']} faculty opportunities")
    return normalized


def _dedup_email(opp: dict) -> str:
    return (opp.get("contact_email") or "").strip().lower()


def _dedup_name(opp: dict) -> str:
    return (opp.get("pi_name") or "").casefold().strip()


def drop_joint_appointment_duplicates(
    new_opps: list[dict], existing: list[dict]
) -> tuple[list[dict], int]:
    """Drop incoming records duplicating a ucb_* record from another source.

    Joint-appointment professors (e.g. EECS + Statistics) appear in both
    department directories, so a re-scrape would surface them twice and fail
    the data-quality gate (no two ucb_* records may share a non-null
    contact_email or a normalized pi_name — see
    tests/test_opportunity_data_quality.py). Keep policy: the record already
    in the corpus wins; refresh_all merges ucb_eecs_faculty (richer inline
    research keywords) before the ucb_common departments, so EECS is kept.

    Same-source existing records are ignored: a re-scrape of one department
    matches its own previous records by id (upsert), and must not be skipped
    here.
    """
    new_sources = {o.get("source") for o in new_opps}
    emails: set[str] = set()
    names: set[str] = set()
    for opp in existing:
        source = opp.get("source") or ""
        if not source.startswith("ucb_") or source in new_sources:
            continue
        if email := _dedup_email(opp):
            emails.add(email)
        if name := _dedup_name(opp):
            names.add(name)

    kept: list[dict] = []
    dropped = 0
    for opp in new_opps:
        if _dedup_email(opp) in emails or _dedup_name(opp) in names:
            dropped += 1
            logger.info(
                f"  Skipping joint-appointment duplicate {opp.get('pi_name')!r} "
                f"({opp.get('source')}) — already covered by another UCB source"
            )
            continue
        kept.append(opp)
    return kept, dropped


def merge_into_processed(new_opps: list[dict]) -> tuple[int, int]:
    """Upsert faculty records into processed/opportunities.json by id."""
    if not PROCESSED_FILE.exists():
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    new_opps, dropped = drop_joint_appointment_duplicates(new_opps, existing)
    if dropped:
        logger.info(f"Dropped {dropped} joint-appointment duplicate(s) before merge")
    index = {opp.get("id"): opp for opp in existing if opp.get("id")}
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


def run_cli(config: dict, description: str, fetch=None) -> None:
    """Shared command-line entry point for a department collector.

    ``fetch`` overrides the Open-Berkeley fetch path for departments with a
    bespoke parser (EECS); it receives the resolved ``enrich`` flag.
    """
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--save", action="store_true",
                        help="Merge into processed/opportunities.json")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip per-profile email enrichment (faster preview)")
    args = parser.parse_args()

    if fetch is None:
        def fetch(enrich: bool) -> list[dict]:
            return fetch_and_normalize(config, enrich=enrich)
    opps = fetch(not args.no_enrich)
    with_email = sum(1 for o in opps if o.get("contact_email"))
    print(f"\nFetched {len(opps)} {config['short']} faculty research "
          f"opportunities ({with_email} with email)")
    for o in opps[:8]:
        email = o.get("contact_email")
        email_str = f"<{email}>" if email else "(no email)"
        print(f"\n  {o['title'][:70]}")
        print(f"    PI: {o.get('pi_name', '')} {email_str}")
        print(f"    Keywords: {', '.join(o.get('keywords', []))}")

    if args.save:
        if not opps:
            # Almost certainly a fetch failure (the directory always lists
            # faculty). Never overwrite the processed file with an empty scrape.
            print("\nSkipping save: fetched 0 opportunities (likely a network "
                  "failure). processed/opportunities.json left untouched.")
        else:
            added, updated = merge_into_processed(opps)
            print(f"\nSaved: {added} new, {updated} updated")
    else:
        print("\n(Use --save to merge into processed/opportunities.json)")
