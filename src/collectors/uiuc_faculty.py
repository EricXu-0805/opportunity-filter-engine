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
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
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
    "aero": {
        "name": "Aerospace Engineering",
        "short": "AE",
        "url": "https://aerospace.illinois.edu/directory/faculty",
        "base": "https://aerospace.illinois.edu",
        "majors": ["Aerospace Engineering"],
        "keywords": ["aerospace", "aerodynamics", "propulsion", "astronautics",
                      "flight dynamics", "spacecraft"],
    },
    "cee": {
        "name": "Civil & Environmental Engineering",
        "short": "CEE",
        "url": "https://cee.illinois.edu/directory/faculty",
        "base": "https://cee.illinois.edu",
        "majors": ["Civil Engineering", "Environmental Engineering"],
        "keywords": ["civil engineering", "structural engineering",
                      "environmental engineering", "geotechnical",
                      "transportation", "water resources"],
    },
    "npre": {
        "name": "Nuclear, Plasma & Radiological Engineering",
        "short": "NPRE",
        "url": "https://npre.illinois.edu/people/faculty",
        "base": "https://npre.illinois.edu",
        "majors": ["Nuclear Engineering",
                    "Nuclear, Plasma, and Radiological Engineering"],
        "keywords": ["nuclear engineering", "plasma", "radiological", "fusion",
                      "reactor", "radiation"],
    },
    "chbe": {
        "name": "Chemical & Biomolecular Engineering",
        "short": "ChBE",
        "url": "https://chbe.illinois.edu/people/faculty",
        "base": "https://chbe.illinois.edu",
        "majors": ["Chemical Engineering",
                    "Chemical & Biomolecular Engineering"],
        "keywords": ["chemical engineering", "biomolecular", "catalysis",
                      "reaction engineering", "thermodynamics", "separations"],
    },
    "ise": {
        "name": "Industrial & Enterprise Systems Engineering",
        "short": "ISE",
        "url": "https://ise.illinois.edu/directory/faculty",
        "base": "https://ise.illinois.edu",
        "majors": ["Industrial Engineering", "Systems Engineering",
                    "Industrial & Enterprise Systems Engineering"],
        "keywords": ["industrial engineering", "operations research",
                      "optimization", "systems engineering", "manufacturing",
                      "logistics"],
    },
    "astro": {
        "name": "Department of Astronomy",
        "short": "Astronomy",
        "url": "https://astro.illinois.edu/people/faculty",
        "base": "https://astro.illinois.edu",
        "majors": ["Astronomy", "Astrophysics"],
        "keywords": ["astronomy", "astrophysics", "cosmology", "galaxies",
                      "exoplanets", "observational astronomy"],
    },
    "mcb": {
        "name": "School of Molecular & Cellular Biology",
        "short": "MCB",
        "url": "https://mcb.illinois.edu/directory/faculty",
        "base": "https://mcb.illinois.edu",
        "majors": ["Molecular & Cellular Biology", "Biochemistry", "Biology"],
        "keywords": ["molecular biology", "cell biology", "biochemistry",
                      "genetics", "neuroscience", "microbiology"],
    },
    "psych": {
        "name": "Department of Psychology",
        "short": "Psychology",
        "url": "https://psychology.illinois.edu/people/faculty",
        "base": "https://psychology.illinois.edu",
        "majors": ["Psychology"],
        "keywords": ["psychology", "cognitive science", "behavioral",
                      "neuroscience", "social psychology", "developmental"],
    },
    "ib": {
        "name": "School of Integrative Biology",
        "short": "IB",
        "url": "https://sib.illinois.edu/directory/faculty",
        "base": "https://sib.illinois.edu",
        "majors": ["Integrative Biology", "Biology",
                    "Ecology, Evolution & Conservation"],
        "keywords": ["integrative biology", "ecology", "evolution",
                      "physiology", "organismal biology", "conservation"],
    },
    "econ": {
        "name": "Department of Economics",
        "short": "Economics",
        "url": "https://economics.illinois.edu/directory/faculty",
        "base": "https://economics.illinois.edu",
        "majors": ["Economics"],
        "keywords": ["economics", "econometrics", "microeconomics",
                      "macroeconomics", "labor economics",
                      "industrial organization"],
    },
    "linguistics": {
        "name": "Department of Linguistics",
        "short": "Linguistics",
        "url": "https://linguistics.illinois.edu/directory/faculty",
        "base": "https://linguistics.illinois.edu",
        "majors": ["Linguistics"],
        "keywords": ["linguistics", "phonology", "syntax", "semantics",
                      "sociolinguistics", "computational linguistics"],
    },
    "comm": {
        "name": "Department of Communication",
        "short": "Communication",
        "url": "https://communication.illinois.edu/directory/faculty",
        "base": "https://communication.illinois.edu",
        "majors": ["Communication"],
        "keywords": ["communication", "media", "interpersonal communication",
                      "political communication", "health communication",
                      "rhetoric"],
    },
    "anthro": {
        "name": "Department of Anthropology",
        "short": "Anthropology",
        "url": "https://anthro.illinois.edu/directory/faculty",
        "base": "https://anthro.illinois.edu",
        "majors": ["Anthropology"],
        "keywords": ["anthropology", "archaeology", "biological anthropology",
                      "cultural anthropology", "linguistic anthropology"],
    },
    "atmos": {
        "name": "Department of Atmospheric Sciences",
        "short": "Atmos",
        "url": "https://atmos.illinois.edu/directory/faculty",
        "base": "https://atmos.illinois.edu",
        "majors": ["Atmospheric Sciences"],
        "keywords": ["atmospheric sciences", "meteorology", "climate",
                      "weather", "atmospheric dynamics", "remote sensing"],
    },
    "soc": {
        "name": "Department of Sociology",
        "short": "Sociology",
        "url": "https://sociology.illinois.edu/directory/faculty",
        "base": "https://sociology.illinois.edu",
        "majors": ["Sociology"],
        "keywords": ["sociology", "social inequality", "demography",
                      "social networks", "race and ethnicity",
                      "social movements"],
    },
    "geology": {
        "name": "Department of Earth Science & Environmental Change",
        "short": "Geology",
        "url": "https://geology.illinois.edu/directory/faculty",
        "base": "https://geology.illinois.edu",
        "majors": ["Geology", "Earth Science"],
        "keywords": ["geology", "earth science", "geochemistry", "geophysics",
                      "paleontology", "environmental change"],
    },
    "polisci": {
        "name": "Department of Political Science",
        "short": "PoliSci",
        "url": "https://pol.illinois.edu/directory/faculty",
        "base": "https://pol.illinois.edu",
        "majors": ["Political Science"],
        "keywords": ["political science", "american politics",
                      "comparative politics", "international relations",
                      "political theory", "public policy"],
    },
    "english": {
        "name": "Department of English",
        "short": "English",
        "url": "https://english.illinois.edu/directory/faculty",
        "base": "https://english.illinois.edu",
        "majors": ["English", "Creative Writing"],
        "keywords": ["english", "literature", "creative writing", "rhetoric",
                      "literary criticism", "writing studies"],
    },
    "philosophy": {
        "name": "Department of Philosophy",
        "short": "Philosophy",
        "url": "https://philosophy.illinois.edu/directory/faculty",
        "base": "https://philosophy.illinois.edu",
        "majors": ["Philosophy"],
        "keywords": ["philosophy", "ethics", "epistemology", "metaphysics",
                      "logic", "philosophy of science"],
    },
    "history": {
        "name": "Department of History",
        "short": "History",
        "url": "https://history.illinois.edu/directory/faculty",
        "base": "https://history.illinois.edu",
        "majors": ["History"],
        "keywords": ["history", "american history", "european history",
                      "world history", "social history", "cultural history"],
    },
}


def _fetch_soup(url: str) -> BeautifulSoup | None:
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

# Directory pages group people under section headings ("Postdocs", "Affiliates
# and Adjuncts", …) that the generic card scraper picks up as if they were
# faculty. Matched against the WHOLE normalized name (not as a substring) so a
# real surname like "Fellows" is never clipped.
_NON_PERSON_LABELS: frozenset[str] = frozenset({
    "faculty", "staff", "administration", "emeritus", "emeriti",
    "emeritus faculty", "emeriti faculty", "affiliate faculty",
    "affiliated faculty", "adjunct faculty", "affiliates and adjuncts",
    "adjuncts and affiliates", "affiliates", "adjuncts", "lecturers",
    "instructors", "research staff", "postdoc", "postdocs",
    "postdoctoral researchers", "postdoctoral associates", "graduate student",
    "graduate students", "doctoral student", "doctoral students",
    "masters students", "master s students", "undergraduate students",
    "students", "alumni", "advisors", "directory",
    # Administrative / office aliases that surface as a directory "person"
    # with a shared mailbox (e.g. an IB "Human Resources" las-HR alias).
    "human resources", "business office", "main office", "department office",
    "graduate office", "student services", "advising", "front desk",
    "reception", "facilities", "it support", "help desk", "general inquiries",
    "office", "contact", "information", "committee", "committees", "people",
    "person", "overview", "news", "events",
    # Role-combo and job-market section headings seen in humanities/social
    # science directories (still whole-name matches, never substrings).
    "diversity and inclusion", "diversity equity and inclusion",
    "grads on the market", "graduate students on the market",
    "students on the market", "job market candidates", "job market",
    "instructors and lecturers", "lecturers and instructors",
    "postdocs and lecturers", "adjuncts and lecturers",
})


def _is_section_label(name: str) -> bool:
    return re.sub(r"[^a-z]+", " ", name.lower()).strip() in _NON_PERSON_LABELS


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


def _parse_faculty_card(element, base_url: str, dept: str) -> dict | None:
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
        # No per-professor research signal: fall back to the department's broad
        # field only (keywords[0]), never its specific subfields. The old [:3]
        # slice injected hot areas like "machine learning"/"quantum" onto every
        # un-enriched professor, falsely matching them to students who named
        # those interests. One generic field is honest; specific claims we
        # cannot verify are not.
        found = dept_config.get("keywords", [])[:1]

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


def normalize_faculty(person: dict, dept_config: dict) -> dict | None:
    """Convert a scraped faculty entry into the normalized opportunity schema."""
    name = person.get("name", "")
    if not name or len(name) < 3:
        return None
    if _is_section_label(name):
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

    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
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


# Faculty profiles are sometimes scraped under two spellings of one person at
# the same profile URL — a fuller name ("Geoffrey Lindsay Herman" vs "Geoffrey
# Herman") or a nickname ("James N. Eckstein" vs "Jim Eckstein"). Because the
# record id hashes the name, each spelling becomes a separate row and the
# professor surfaces twice in matches. The helpers below collapse uiuc_faculty
# records that share a profile URL AND the same last name. source_url here is a
# per-person profile page, so the last-name guard only blocks the unlikely case
# of two distinct same-surname professors sharing one URL; differing surnames
# (or differing URLs) are never merged.
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _faculty_name_key(opp: dict) -> tuple[str, str] | None:
    """Return (source_url, last_name) identifying a professor, or None when the
    record is not faculty or lacks the URL/two-token name needed to dedup
    safely (None means the row always passes through untouched)."""
    if opp.get("source") != "uiuc_faculty":
        return None
    url = (opp.get("source_url") or "").strip()
    name = (opp.get("pi_name") or "").strip()
    if not url or not name:
        return None
    tokens = [t for t in name.replace(",", " ").split() if t]
    # Drop generational suffixes so "Brian DeMarco Jr." keys the same as "Brian DeMarco".
    while tokens and tokens[-1].lower().strip(".") in _NAME_SUFFIXES:
        tokens.pop()
    if len(tokens) < 2:
        return None
    return (url, tokens[-1].lower())


def _faculty_is_richer(a: dict, b: dict) -> bool:
    """True if faculty record ``a`` is more complete than ``b``: the fuller
    name wins (captures more of the person's full name), then the longer
    description. Used to choose which duplicate spelling to keep."""
    an, bn = len(a.get("pi_name") or ""), len(b.get("pi_name") or "")
    if an != bn:
        return an > bn
    ad = len(a.get("description") or a.get("description_raw") or "")
    bd = len(b.get("description") or b.get("description_raw") or "")
    return ad > bd


def _dedup_faculty_records(opps: list[dict]) -> list[dict]:
    """Collapse same-professor duplicate faculty rows (same profile URL + last
    name), keeping the richer record at its original position. Non-faculty rows
    and records without a safe key always pass through untouched. Survivors keep
    their original order so a re-write only removes the duplicate rows."""
    best_idx: dict[tuple[str, str], int] = {}
    for i, opp in enumerate(opps):
        key = _faculty_name_key(opp)
        if key is None:
            continue
        if key not in best_idx or _faculty_is_richer(opp, opps[best_idx[key]]):
            best_idx[key] = i
    return [
        opp
        for i, opp in enumerate(opps)
        if (key := _faculty_name_key(opp)) is None or best_idx[key] == i
    ]


# A department-wide "Research Areas" navigation block scraped into individual
# profile pages produces byte-identical multi-keyword sets across same-department
# peers (DQ-1) — e.g. 74 CS professors all tagged the same 5 areas regardless of
# what they actually do. This is worse than the honest broad-field fallback
# because it presents specific-looking but false matches. Real per-professor
# research is diverse, so a 2+ keyword set shared by more than this many peers in
# one department is treated as a scrape artifact and demoted to the broad field.
_SHARED_KEYWORD_POLLUTION_THRESHOLD = 5

# Broad field for departments collected by the JS-rendered ACES collector, which
# are absent from DEPARTMENTS. Keyed on the record's `department` value.
_ACES_BROAD_FIELDS = {
    "Department of Animal Sciences": "animal sciences",
    "Department of Crop Sciences": "crop sciences",
    "Food Science & Human Nutrition": "food science",
    "Natural Resources & Environmental Sciences": "environmental sciences",
}


def _dept_broad_field(department: str) -> str:
    """The honest broad field for a department: its DEPARTMENTS keyword[0] when
    known, an explicit ACES mapping otherwise, falling back to the department
    name with a leading 'Department/School/College of' stripped."""
    for cfg in DEPARTMENTS.values():
        if cfg.get("name") == department:
            kws = cfg.get("keywords", [])
            return kws[0] if kws else ""
    if department in _ACES_BROAD_FIELDS:
        return _ACES_BROAD_FIELDS[department]
    name = re.sub(
        r"^(?:the\s+)?(?:department|school|college)\s+of\s+",
        "", department.strip(), flags=re.IGNORECASE,
    )
    return name.replace(" & ", " and ").strip().lower()


def _demote_shared_keyword_pollution(opps: list[dict]) -> int:
    """Demote department-block keyword pollution to the broad field (DQ-1).

    Groups uiuc_faculty rows by (department, sorted keywords) for rows with 2+
    keywords; any group larger than the threshold is a shared nav-block artifact,
    so each member's keywords are replaced with the department's broad field.
    Mutates ``opps`` in place; returns the number of records demoted."""
    groups: dict[tuple[str, tuple[str, ...]], list[dict]] = defaultdict(list)
    for opp in opps:
        if opp.get("source") != "uiuc_faculty":
            continue
        kws = tuple(sorted((k or "").lower() for k in (opp.get("keywords") or [])))
        if len(kws) >= 2:
            groups[(opp.get("department", ""), kws)].append(opp)

    demoted = 0
    for (department, _kws), members in groups.items():
        if len(members) <= _SHARED_KEYWORD_POLLUTION_THRESHOLD:
            continue
        broad = _dept_broad_field(department)
        for opp in members:
            opp["keywords"] = [broad] if broad else []
            demoted += 1
    return demoted


# DQ-2: recover real per-professor keywords from research_areas_raw for faculty
# stuck on the broad-field fallback. The text is already stored (no re-scrape);
# the fixed KEYWORD_BANK simply never matched niche areas ("nanophotonics",
# "dependent type theory", "structural health monitoring"). We parse the
# comma/line-delimited phrases and keep only clean, dept-unique topical ones.

# A phrase shared by more than this many same-department peers is a "Research
# Areas" navigation block (DQ-1), not personal research — drop it.
_SHARED_PHRASE_NAV_THRESHOLD = 3

# Page-furniture / non-topical labels that show up in scraped research-area text.
_RESEARCH_AREA_NAV_NOISE = re.compile(
    r"research area|book|monograph|selected article|articles? in|\bjournal|"
    r"conference proceeding|linkedin|website|\bgroup\b|laborator|\blab\b|"
    r"master of|bachelor|\bphd\b|usmle|step 1|review method|curriculum|teaching|"
    r"biography|publication|award|honor|wiki|original edition|focuses on|"
    r"in particular|crowd-?sourc|\bcontri|\bestab|^education|education$|"
    r"our research|spec lab|click here|\bcv\b|\bsee\b|emphasis",
    re.IGNORECASE,
)
_COURSE_CODE_RE = re.compile(r"\b[A-Za-z]{2,4}\s?\d{3}\b")
# Phrases opening with a conjunction/preposition/pronoun are sentence fragments,
# not topics (e.g. "and freight applications", "including best practices").
_LEADING_NONTOPICAL_RE = re.compile(
    r"^(?:and|or|including|with|the|our|some|in|of|for|to|a|an|my|we|is|are|"
    r"that|this|by|emphasis)\b",
    re.IGNORECASE,
)
_RESEARCH_FUNCTION_WORDS = frozenset({
    "the", "of", "and", "to", "for", "with", "in", "on", "a", "an", "my", "i",
    "we", "is", "are", "through", "at", "that", "this", "by", "including",
})
_GENERIC_SINGLE_WORDS = frozenset({
    "education", "learning", "teaching", "solution", "solutions", "design",
    "analysis", "modeling", "modelling", "research", "science", "methods",
    "applications", "systems", "theory", "technology", "development",
    "management", "computation",
})


def _split_research_phrases(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,\n;]", text) if p.strip()]


def _clean_research_phrase(phrase: str) -> str | None:
    """Normalize one scraped phrase into a clean topical keyword, or None when it
    is navigation furniture, a sentence fragment, a course code, or too generic."""
    p = re.sub(r"\s*\([^)]*\)", "", phrase).strip().strip(".;:,").strip()
    if "(" in p or ")" in p or _COURSE_CODE_RE.search(p):
        return None
    if not re.match(r"^[A-Za-z][A-Za-z0-9 &/\-]+$", p):
        return None
    words = p.split()
    if not (1 <= len(words) <= 5) or not (4 <= len(p) <= 46):
        return None
    if _RESEARCH_AREA_NAV_NOISE.search(p) or _LEADING_NONTOPICAL_RE.match(p):
        return None
    if sum(1 for w in words if w.lower() in _RESEARCH_FUNCTION_WORDS) >= 2:
        return None
    if len(words) == 1 and (p.lower() in _GENERIC_SINGLE_WORDS or len(p) < 6):
        return None
    return p.lower()


def _derive_keywords_from_raw(opps: list[dict]) -> int:
    """Enrich broad-field-only faculty with real keywords parsed from their stored
    research_areas_raw text (DQ-2). Mutates ``opps`` in place; returns the count
    of records enriched. Skips dept-shared (nav-block) phrases to avoid
    re-introducing DQ-1 pollution, and self-name tokens to avoid collaborator
    surnames leaking in as topics."""
    fac = [o for o in opps if o.get("source") == "uiuc_faculty"]

    dept_phrase_counts: dict[str, Counter] = defaultdict(Counter)
    for o in fac:
        raw_text = (o.get("metadata") or {}).get("research_areas_raw") or ""
        for p in _split_research_phrases(raw_text):
            dept_phrase_counts[o.get("department", "")][p.lower()] += 1

    enriched = 0
    for o in fac:
        broad = _dept_broad_field(o.get("department", ""))
        kws = [k.lower() for k in (o.get("keywords") or [])]
        if kws not in ([], [broad]):
            continue  # already carries a specific keyword, or no broad fallback

        raw_text = (o.get("metadata") or {}).get("research_areas_raw") or ""
        if not raw_text.strip():
            continue
        parts = _split_research_phrases(raw_text)
        if len(raw_text) >= 295 and parts:
            parts = parts[:-1]  # the 300-char cap usually truncates the last phrase

        name_tokens = {t.lower() for t in re.split(r"\W+", o.get("pi_name") or "") if t}
        counts = dept_phrase_counts[o.get("department", "")]
        derived: list[str] = []
        for p in parts:
            if counts[p.lower()] > _SHARED_PHRASE_NAV_THRESHOLD:
                continue
            cleaned = _clean_research_phrase(p)
            if not cleaned or cleaned == broad or cleaned in derived:
                continue
            if cleaned in name_tokens:  # a collaborator/self surname, not a topic
                continue
            derived.append(cleaned)
            if len(derived) >= 4:
                break
        if derived:
            o["keywords"] = derived
            enriched += 1
    return enriched


# DQ-4: a professor with a joint appointment appears in two department
# directories, each giving a DIFFERENT profile URL — so the URL+name dedup above
# never collapses them and the same person surfaces twice (and could be cold-
# emailed twice). They do, however, share one contact_email. Keying on
# (email, first_token, last_token) collapses the joint appointments. The FIRST
# name must match too: a shared department/admin email (e.g. "nslack@illinois.edu"
# attached to a dozen ECE professors) must never merge distinct people who happen
# to share a surname — only true name-variants of one person (David Forsyth in CS
# & BioE; Pamela / Pamela P. Martinez) collapse.
def _faculty_email_key(opp: dict) -> tuple[str, str, str] | None:
    if opp.get("source") != "uiuc_faculty":
        return None
    email = (opp.get("contact_email") or "").strip().lower()
    name = (opp.get("pi_name") or "").strip()
    if not email or not name:
        return None
    tokens = [t for t in name.replace(",", " ").split() if t]
    while tokens and tokens[-1].lower().strip(".") in _NAME_SUFFIXES:
        tokens.pop()
    if len(tokens) < 2:
        return None
    return (email, tokens[0].lower().strip("."), tokens[-1].lower())


def _dedup_faculty_by_email(opps: list[dict]) -> list[dict]:
    """Collapse same-professor faculty rows that share a contact_email + last
    name across departments (different profile URLs), keeping the richer record
    at its original position. Rows without a safe email key pass through."""
    best_idx: dict[tuple[str, str, str], int] = {}
    for i, opp in enumerate(opps):
        key = _faculty_email_key(opp)
        if key is None:
            continue
        if key not in best_idx or _faculty_is_richer(opp, opps[best_idx[key]]):
            best_idx[key] = i
    return [
        opp
        for i, opp in enumerate(opps)
        if (key := _faculty_email_key(opp)) is None or best_idx[key] == i
    ]


# An email attached to this many *distinct* professors is a department/advising
# inbox scraped in place of a personal address, not one person's contact (e.g.
# amwhit@illinois.edu on 123 profs, nslack@illinois.edu on 116). Counting
# distinct names — not rows — keeps a real professor's joint-appointment rows
# (one name, one shared personal email) from being mistaken for an admin inbox.
_SHARED_ADMIN_EMAIL_THRESHOLD = 3


def _null_shared_admin_emails(opps: list[dict]) -> int:
    """Null contact_email when it is shared by many distinct professors — a
    scraped department/advising inbox, not a personal address. A 'Dear Professor
    X' cold email sent to a shared coordinator inbox misfires; an empty recipient
    (the modal then disables send) is safer than a confidently wrong one. Mutates
    ``opps`` in place; returns the count nulled."""
    names_by_email: dict[str, set[str]] = defaultdict(set)
    for opp in opps:
        if opp.get("source") != "uiuc_faculty":
            continue
        email = (opp.get("contact_email") or "").strip().lower()
        if email:
            names_by_email[email].add((opp.get("pi_name") or "").strip().lower())

    shared = {
        email for email, names in names_by_email.items()
        if len(names) >= _SHARED_ADMIN_EMAIL_THRESHOLD
    }
    nulled = 0
    for opp in opps:
        if opp.get("source") != "uiuc_faculty":
            continue
        if (opp.get("contact_email") or "").strip().lower() in shared:
            opp["contact_email"] = None
            nulled += 1
    return nulled


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
    before = len(all_opps)
    all_opps = _dedup_faculty_records(all_opps)
    removed = before - len(all_opps)
    if removed:
        logger.info(f"Removed {removed} duplicate faculty record(s) sharing a profile URL")

    before_email = len(all_opps)
    all_opps = _dedup_faculty_by_email(all_opps)
    removed_email = before_email - len(all_opps)
    if removed_email:
        logger.info(f"Removed {removed_email} cross-department duplicate faculty record(s) sharing a contact email")

    nulled_emails = _null_shared_admin_emails(all_opps)
    if nulled_emails:
        logger.info(f"Nulled {nulled_emails} faculty contact email(s) that were shared department/admin inboxes")

    demoted = _demote_shared_keyword_pollution(all_opps)
    if demoted:
        logger.info(f"Demoted {demoted} faculty record(s) with shared department-block keywords to the broad field")

    enriched = _derive_keywords_from_raw(all_opps)
    if enriched:
        logger.info(f"Enriched {enriched} broad-field faculty record(s) with keywords derived from research_areas_raw")

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
