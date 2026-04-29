"""
Collector for UIUC Faculty Research Opportunities.

Scrapes faculty directories from key STEM departments to create
cold-email research opportunity entries. Each faculty member with
research interests becomes a potential undergrad research opportunity.

Targets: CS, ECE, Physics, Chemistry, BioE, MechSE, MatSE, CEE, STAT, Math, iSchool

Usage:
    python -m src.collectors.uiuc_faculty              # fetch & preview
    python -m src.collectors.uiuc_faculty --save       # merge into processed data
    python -m src.collectors.uiuc_faculty --dept cs    # single department
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (UIUC educational project)"}
DELAY = 1.5

DEPARTMENTS = {
    "cs": {
        "name": "Siebel School of Computing and Data Science",
        "short": "CS",
        "url": "https://cs.illinois.edu/about/people/all-faculty/department-faculty",
        "base": "https://cs.illinois.edu",
        "majors": ["CS", "Computer Engineering", "Data Science",
                    "Mathematics & Computer Science", "Statistics & Computer Science"],
        "keywords": ["computer science", "artificial intelligence", "machine learning",
                      "data science", "software engineering", "algorithms"],
    },
    "ece": {
        "name": "Electrical & Computer Engineering",
        "short": "ECE",
        "url": "https://ece.illinois.edu/about/directory/faculty-dept",
        "base": "https://ece.illinois.edu",
        "majors": ["ECE", "Electrical Engineering", "Computer Engineering"],
        "keywords": ["electrical engineering", "computer engineering", "circuits",
                      "signal processing", "communications", "power systems"],
    },
    "physics": {
        "name": "Department of Physics",
        "short": "Physics",
        "url": "https://physics.illinois.edu/people/directory/faculty",
        "base": "https://physics.illinois.edu",
        "majors": ["Physics", "Engineering Physics", "Astrophysics"],
        "keywords": ["physics", "quantum", "condensed matter", "astrophysics",
                      "particle physics", "optics"],
    },
    "chemistry": {
        "name": "Department of Chemistry",
        "short": "Chemistry",
        "url": "https://chemistry.illinois.edu/directory/faculty",
        "base": "https://chemistry.illinois.edu",
        "majors": ["Chemistry", "Chemical Engineering", "Biochemistry"],
        "keywords": ["chemistry", "organic chemistry", "biochemistry",
                      "materials chemistry", "catalysis"],
    },
    "mechse": {
        "name": "Mechanical Science & Engineering",
        "short": "MechSE",
        "url": "https://mechse.illinois.edu/people/faculty",
        "base": "https://mechse.illinois.edu",
        "majors": ["Mechanical Engineering", "Engineering Mechanics"],
        "keywords": ["mechanical engineering", "robotics", "fluid dynamics",
                      "thermodynamics", "manufacturing"],
    },
    "bioe": {
        "name": "Bioengineering",
        "short": "BioE",
        "url": "https://bioengineering.illinois.edu/people/faculty",
        "base": "https://bioengineering.illinois.edu",
        "majors": ["Bioengineering", "Biomedical Engineering"],
        "keywords": ["bioengineering", "biomedical", "bioinformatics",
                      "medical imaging", "tissue engineering"],
    },
    "matse": {
        "name": "Materials Science & Engineering",
        "short": "MatSE",
        "url": "https://matse.illinois.edu/directory/faculty",
        "base": "https://matse.illinois.edu",
        "majors": ["Materials Science", "Materials Science & Engineering"],
        "keywords": ["materials science", "nanotechnology", "polymers",
                      "ceramics", "semiconductor"],
    },
    "stat": {
        "name": "Department of Statistics",
        "short": "STAT",
        "url": "https://stat.illinois.edu/directory/faculty",
        "base": "https://stat.illinois.edu",
        "majors": ["Statistics", "Data Science", "Actuarial Science"],
        "keywords": ["statistics", "data science", "machine learning",
                      "probability", "statistical learning"],
    },
    "math": {
        "name": "Department of Mathematics",
        "short": "Math",
        "url": "https://math.illinois.edu/directory/faculty",
        "base": "https://math.illinois.edu",
        "majors": ["Mathematics", "Applied Mathematics",
                    "Mathematics & Computer Science"],
        "keywords": ["mathematics", "algebra", "analysis", "topology",
                      "combinatorics", "number theory"],
    },
    "ischool": {
        "name": "School of Information Sciences",
        "short": "iSchool",
        "url": "https://ischool.illinois.edu/people/faculty",
        "base": "https://ischool.illinois.edu",
        "majors": ["Information Sciences", "Data Science"],
        "keywords": ["information science", "data science", "HCI",
                      "information retrieval", "social computing"],
    },
}


def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetch a URL and return parsed BeautifulSoup, or None on failure."""
    try:
        resp = requests.get(url, timeout=20, headers=HEADERS)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def _extract_emails_from_text(text: str) -> list[str]:
    """Extract email addresses from text."""
    return re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)


def _clean_name(name: str) -> str:
    """Clean a faculty name string."""
    name = re.sub(r"(?i)^(dr\.?|prof\.?|professor)\s+", "", name).strip()
    name = re.sub(r"\s*\(.*?\)\s*", " ", name).strip()
    name = re.sub(r",?\s*(Ph\.?D\.?|M\.?D\.?|Jr\.?|Sr\.?|III|II)$", "", name).strip()
    return re.sub(r"\s{2,}", " ", name)


NOISE_EMAILS = {
    "webmaster@illinois.edu", "admissions@illinois.edu",
    "registrar@illinois.edu", "engineering@illinois.edu",
    "grainger@illinois.edu", "ugresearch@illinois.edu",
    "admin@siebelschool.illinois.edu",
}


def _get_main_content(soup: BeautifulSoup) -> BeautifulSoup:
    """Extract the main content area, stripping header/nav/footer noise."""
    for selector in ["main", "#content", "div.main-content", "div#page-content",
                      "div.region-content", "article"]:
        el = soup.select_one(selector)
        if el:
            return el
    for tag in soup.select("header, nav, footer, #mainnav, div.navbar"):
        tag.decompose()
    return soup


def _scrape_grainger_faculty_list(dept_config: dict) -> list[dict]:
    """Scrape a Grainger-style faculty directory. Returns [{name, email, url, title, ...}]."""
    url = dept_config["url"]
    base = dept_config["base"]
    dept_name = dept_config["short"]
    logger.info(f"Scraping {dept_name} faculty from {url}")

    soup = _fetch_soup(url)
    if not soup:
        return []

    content = _get_main_content(soup)
    faculty = []

    cards = content.select(
        "div.directory-item, "
        "div.person-item, "
        "div.faculty-item, "
        "div.views-row, "
        "article.node--type-person, "
        "div.person-card, "
        "li.person, "
        "div.card"
    )

    if not cards:
        cards = _find_faculty_links(content, base)

    for card in cards:
        person = _parse_faculty_card(card, base, dept_name)
        if person:
            faculty.append(person)

    if not faculty:
        faculty = _broad_faculty_extraction(content, base, dept_name)

    logger.info(f"  Found {len(faculty)} faculty in {dept_name}")
    return faculty


def _find_faculty_links(soup: BeautifulSoup, base_url: str) -> list:
    """Find faculty profile links as a fallback strategy."""
    results = []
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        if not text or len(text) < 3 or len(text) > 80:
            continue
        if any(skip in text.lower() for skip in [
            "home", "about", "research", "news", "contact", "back",
            "next", "previous", "search", "login", "menu", "view all"
        ]):
            continue
        if re.search(r"/(people|directory|faculty|profile)/", href):
            results.append(link)
    return results


def _parse_faculty_card(element, base_url: str, dept: str) -> Optional[dict]:
    """Parse a single faculty card/row into a dict."""
    result = {"department": dept}

    name_el = element.select_one(
        "h2 a, h3 a, h4 a, "
        "a.directory-item__name, "
        "span.field-content a, "
        "a.person-name, "
        "strong a, "
        "div.card-title a, "
        "a[href*='/people/'], a[href*='/directory/'], a[href*='/profile/']"
    )
    if not name_el:
        if element.name == "a":
            name_el = element
        else:
            return None

    name = name_el.get_text(strip=True)
    name = _clean_name(name)
    if not name or len(name) < 3 or len(name) > 60:
        return None
    if any(skip in name.lower() for skip in [
        "faculty", "staff", "emerit", "office", "department",
        "school", "college", "directory", "center"
    ]):
        return None

    result["name"] = name

    href = name_el.get("href", "")
    result["url"] = urljoin(base_url, href) if href else ""

    email_el = element.select_one("a[href^='mailto:']")
    if email_el:
        email = email_el.get("href", "").replace("mailto:", "").split("?")[0].strip()
        if email and email not in NOISE_EMAILS:
            result["email"] = email

    if "email" not in result:
        card_text = element.get_text()
        valid = [e for e in _extract_emails_from_text(card_text) if e not in NOISE_EMAILS]
        if valid:
            result["email"] = valid[0]

    title_el = element.select_one(
        "div.directory-item__title, "
        "span.person-title, "
        "div.field-name-field-title, "
        "p.card-text, "
        "div.views-field-field-title span"
    )
    if title_el:
        result["title"] = title_el.get_text(strip=True)

    research_el = element.select_one(
        "div.research-areas, "
        "span.research-interests, "
        "div.field-name-field-research-interests"
    )
    if research_el:
        result["research_areas"] = research_el.get_text(strip=True)

    return result


def _broad_faculty_extraction(soup: BeautifulSoup, base_url: str, dept: str) -> list[dict]:
    """Broad extraction: find all links that look like they point to faculty profiles."""
    faculty = []
    seen_names = set()

    for link in soup.select("a[href]"):
        href = link.get("href", "")
        text = link.get_text(strip=True)

        if not text or len(text) < 4 or len(text) > 60:
            continue

        words = text.split()
        if len(words) < 2 or len(words) > 5:
            continue
        if not all(w[0].isupper() for w in words if len(w) > 1):
            continue

        if any(skip in text.lower() for skip in [
            "university", "illinois", "college", "department", "school",
            "engineering", "research", "learn more", "view all", "read more",
            "news", "events", "contact", "about"
        ]):
            continue

        name = _clean_name(text)
        if name in seen_names:
            continue
        seen_names.add(name)

        full_url = urljoin(base_url, href)
        faculty.append({
            "name": name,
            "url": full_url,
            "department": dept,
        })

    return faculty


def _enrich_faculty_from_profile(person: dict) -> dict:
    """Fetch a faculty member's profile page to extract email, research areas, etc."""
    url = person.get("url", "")
    if not url:
        return person

    soup = _fetch_soup(url)
    if not soup:
        return person

    if "email" not in person:
        for mailto in soup.select("a[href^='mailto:']"):
            email = mailto.get("href", "").replace("mailto:", "").split("?")[0].strip()
            if email and email not in NOISE_EMAILS and "@" in email:
                person["email"] = email
                break

    if "email" not in person:
        page_text = soup.get_text()
        emails = [e for e in _extract_emails_from_text(page_text)
                  if e not in NOISE_EMAILS and "illinois.edu" in e]
        if emails:
            person["email"] = emails[0]

    if "research_areas" not in person:
        for selector in [
            "div.field--name-field-research-interests",
            "div.field--name-field-research-areas",
            "div.research-interests",
            "section.research",
            "#research",
        ]:
            el = soup.select_one(selector)
            if el:
                person["research_areas"] = el.get_text(separator=", ", strip=True)[:300]
                break

    if "research_areas" not in person:
        page_text = soup.get_text()
        for marker in ["Research Interests\n", "Research Areas\n"]:
            idx = page_text.find(marker)
            if idx != -1:
                chunk = page_text[idx + len(marker):idx + len(marker) + 400].strip()
                lines = [l.strip() for l in chunk.split("\n") if l.strip()][:6]
                person["research_areas"] = ", ".join(lines)
                break

    if "research_areas" not in person:
        meta = soup.select_one("meta[name='description']")
        if meta and len(meta.get("content", "")) > 20:
            person["research_description"] = meta["content"][:300]

    if "title" not in person:
        for selector in [
            "div.field--name-field-title",
            "span.person-title",
            "div.person-position",
            "h2.subtitle",
        ]:
            el = soup.select_one(selector)
            if el:
                person["title"] = el.get_text(strip=True)
                break

    return person


_PAGE_NOISE = re.compile(
    r"(award|fellow|committee|ranked|excellent|teacher|chair|director|"
    r"member|subcommittee|advisory|incomplete list|associate in|pc member|"
    r"best paper|nomination|distinguished|present\)|2[0-9]{3})",
    re.IGNORECASE,
)


def _scrape_individual_page_keywords(url: str) -> list[str]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8, verify=False)
        resp.raise_for_status()
        html = resp.text
    except requests.RequestException:
        return []

    topics = set()
    for pattern in [
        r"(?:Research\s+(?:Interests?|Areas?|Focus))[\s:]*</(?:h[2-6]|strong|b|dt|p)>\s*(.{10,800}?)(?:<(?:h[2-6]|div\s+class=\"field)|$)",
    ]:
        for m in re.finditer(pattern, html, re.IGNORECASE | re.DOTALL):
            block = re.sub(r"<[^>]+>", "|", m.group(1))
            for chunk in block.split("|"):
                chunk = re.sub(r"\s+", " ", chunk).strip()
                if 8 < len(chunk) < 80 and not _PAGE_NOISE.search(chunk):
                    topics.add(chunk.lower())

    main = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL | re.IGNORECASE)
    if main:
        for li in re.finditer(r"<li[^>]*>\s*([^<]{8,80})\s*</li>", main.group(1)):
            text = li.group(1).strip()
            if 8 < len(text) < 80 and not _PAGE_NOISE.search(text):
                topics.add(text.lower())

    return list(topics)[:5]


def _extract_research_keywords(person: dict, dept_config: dict) -> list[str]:
    text = " ".join([
        person.get("research_areas", ""),
        person.get("research_description", ""),
        person.get("title", ""),
    ]).lower()

    KEYWORD_BANK = [
        "machine learning", "deep learning", "computer vision", "robotics",
        "natural language processing", "data science", "cybersecurity",
        "quantum", "nanotechnology", "materials science", "renewable energy",
        "neuroscience", "genomics", "bioinformatics", "ecology",
        "artificial intelligence", "internet of things",
        "biomedical", "drug discovery", "proteomics",
        "remote sensing", "signal processing", "embedded systems",
        "human-computer interaction", "software engineering",
        "parallel computing", "high performance computing",
        "optimization", "control systems", "power systems",
        "photonics", "optics", "electromagnetics", "circuits",
        "climate", "sustainability", "fluid dynamics",
        "algorithms", "databases", "networking", "security",
        "programming languages", "compilers", "operating systems",
        "computational biology", "medical imaging",
        "autonomous systems", "reinforcement learning",
        "graph neural networks", "large language models",
    ]

    found = [kw for kw in KEYWORD_BANK if kw in text]

    if not found:
        profile_url = person.get("profile_url", "")
        if profile_url:
            scraped = _scrape_individual_page_keywords(profile_url)
            if scraped:
                return scraped

    if not found:
        found = dept_config.get("keywords", [])[:3]

    return found[:8]


def _infer_skills_from_research(person: dict) -> list[str]:
    """Infer likely required skills from research description."""
    text = " ".join([
        person.get("research_areas", ""),
        person.get("research_description", ""),
    ]).lower()

    SKILL_MAP = {
        "Python": ["python", "machine learning", "deep learning", "data science",
                    "natural language", "computational", "bioinformatics"],
        "C++": ["c++", "systems", "embedded", "robotics", "high performance",
                "parallel computing", "compilers"],
        "MATLAB": ["matlab", "signal processing", "control", "power systems",
                    "circuits", "electromagnetics"],
        "R": ["statistical", "biostatistics", "epidemiology", "ecology"],
        "PyTorch": ["deep learning", "neural network", "computer vision",
                     "reinforcement learning", "nlp"],
        "TensorFlow": ["deep learning", "machine learning", "neural network"],
        "SQL": ["database", "data management", "information systems"],
        "Linux": ["systems", "networking", "security", "cloud"],
        "Java": ["software engineering", "distributed", "android"],
        "machine learning": ["machine learning", "artificial intelligence",
                              "data science", "pattern recognition"],
        "data analysis": ["data science", "statistics", "computational",
                           "bioinformatics", "genomics"],
    }

    skills = set()
    for skill, triggers in SKILL_MAP.items():
        if any(t in text for t in triggers):
            skills.add(skill)

    return sorted(skills)[:5]


def normalize_faculty(person: dict, dept_config: dict) -> Optional[dict]:
    """Convert a scraped faculty entry into the normalized opportunity schema."""
    name = person.get("name", "")
    if not name or len(name) < 3:
        return None

    email = person.get("email", "")
    if not email and person.get("url", ""):
        netid_match = re.search(r"/([a-z][a-z0-9]{1,10})/?$", person.get("url", ""))
        if netid_match:
            email = f"{netid_match.group(1)}@illinois.edu"
    dept_short = dept_config["short"]
    dept_name = dept_config["name"]
    profile_url = person.get("url", "")
    title = person.get("title", "Professor")
    research_areas = person.get("research_areas", "")

    name_hash = hashlib.md5(f"{dept_short}-{name}".encode()).hexdigest()[:8]
    opp_id = f"faculty-{dept_short.lower()}-{name_hash}"

    now = datetime.utcnow().isoformat()
    keywords = _extract_research_keywords(person, dept_config)
    skills = _infer_skills_from_research(person)

    desc_parts = [
        f"Research opportunity with {title} {name} in the {dept_name} at UIUC.",
    ]
    if research_areas:
        desc_parts.append(f"Research areas: {research_areas[:200]}")
    desc_parts.append(
        "Contact the professor directly to inquire about undergraduate "
        "research positions in their lab."
    )
    description = " ".join(desc_parts)

    research_summary = ""
    if keywords:
        research_summary = f" ({', '.join(keywords[:3])})"
    opp_title = f"Research with Prof. {name} — {dept_short}{research_summary}"

    return {
        "id": opp_id,
        "source": "uiuc_faculty",
        "source_url": profile_url,
        "source_type": "faculty_research",
        "title": opp_title,
        "organization": "University of Illinois Urbana-Champaign",
        "department": dept_name,
        "lab_or_program": f"Prof. {name}'s Research Group",
        "pi_name": name,
        "contact_email": email or None,
        "url": profile_url,
        "location": "Urbana-Champaign, IL",
        "on_campus": True,
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
            "majors": dept_config["majors"],
            "skills_required": skills[:3],
            "skills_preferred": skills[3:],
            "citizenship_required": False,
            "international_friendly": "yes",
            "work_auth_notes": "On-campus research — no work authorization required",
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
        "description_clean": description[:500],
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


def fetch_department(dept_key: str, enrich: bool = True) -> list[dict]:
    """Fetch and normalize faculty from a single department."""
    if dept_key not in DEPARTMENTS:
        logger.error(f"Unknown department: {dept_key}")
        return []

    config = DEPARTMENTS[dept_key]
    raw_faculty = _scrape_grainger_faculty_list(config)

    if enrich and raw_faculty:
        logger.info(f"  Enriching {len(raw_faculty)} {config['short']} profiles...")
        for i, person in enumerate(raw_faculty):
            if "email" not in person or "research_areas" not in person:
                person = _enrich_faculty_from_profile(person)
                raw_faculty[i] = person
                if i < len(raw_faculty) - 1:
                    time.sleep(DELAY)
            if (i + 1) % 10 == 0:
                logger.info(f"    Enriched {i+1}/{len(raw_faculty)}")

    normalized = []
    for person in raw_faculty:
        opp = normalize_faculty(person, config)
        if opp:
            normalized.append(opp)

    return normalized


def fetch_and_normalize(departments: list[str] = None,
                        enrich: bool = True) -> list[dict]:
    """Fetch faculty from multiple departments and return normalized records."""
    if departments is None:
        departments = list(DEPARTMENTS.keys())

    all_opps = []
    for dept_key in departments:
        try:
            dept_opps = fetch_department(dept_key, enrich=enrich)
            all_opps.extend(dept_opps)
            logger.info(f"  {DEPARTMENTS[dept_key]['short']}: {len(dept_opps)} opportunities")
        except Exception as e:
            logger.error(f"Failed to collect {dept_key}: {e}")

    logger.info(f"Total faculty opportunities: {len(all_opps)}")
    return all_opps


def merge_into_processed(new_opps: list[dict], filepath: str = None) -> tuple[int, int]:
    """Merge new faculty opportunities into the processed data file."""
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

    parser = argparse.ArgumentParser(description="UIUC Faculty Research Collector")
    parser.add_argument("--save", action="store_true",
                        help="Merge into processed/opportunities.json")
    parser.add_argument("--dept", type=str, default=None,
                        help=f"Single department: {', '.join(DEPARTMENTS.keys())}")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip profile page enrichment (faster but less data)")
    parser.add_argument("--list-depts", action="store_true",
                        help="List available departments and exit")
    args = parser.parse_args()

    if args.list_depts:
        print("\nAvailable departments:")
        for key, cfg in DEPARTMENTS.items():
            print(f"  {key:12s} — {cfg['name']}")
            print(f"  {'':12s}   {cfg['url']}")
        exit(0)

    depts = [args.dept] if args.dept else None
    opps = fetch_and_normalize(departments=depts, enrich=not args.no_enrich)

    print(f"\nFetched {len(opps)} faculty research opportunities")

    for o in opps[:8]:
        email_str = o.get("contact_email") or "no email"
        print(f"\n  {o['title'][:70]}")
        print(f"    PI: {o.get('pi_name', '')} ({email_str})")
        print(f"    Dept: {o['department']}")
        print(f"    Keywords: {', '.join(o.get('keywords', []))}")
        print(f"    Skills: {', '.join(o['eligibility']['skills_required'])}")

    if args.save:
        added, updated = merge_into_processed(opps)
        print(f"\nSaved: {added} new, {updated} updated")
    else:
        print("\n(Use --save to merge into processed/opportunities.json)")
