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
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from backend.lib.contact_visibility import (
    CONTACT_EVIDENCE_FIELDS,
    IDENTITY_BOUND_EMAIL_SOURCES,
    build_identity_bound_contact_evidence,
    verified_send_target,
)

from ..evidence import is_professor_rank
from .atomic_json import atomic_write_json

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"

# Browser-like headers. Berkeley department sites reset the connection (errno
# 54) on requests that don't look like a real browser, so we send a full set.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
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

_PROFILE_DENIAL_RE = re.compile(
    r"\b(?:access denied|request blocked|verify you are human|"
    r"attention required|captcha|cloudflare ray id|forbidden|"
    r"(?:401|403)\s*(?:[-:]\s*)?unauthorized|"
    r"(?:you\s+are\s+)?not\s+authori[sz]ed|"
    r"access\s+(?:is\s+)?restricted|restricted\s+access)\b",
    re.IGNORECASE,
)
_PROFILE_LOGIN_WALL_RE = re.compile(
    r"\b(?:"
    # Authentication/login walls.
    r"authentication\s+(?:is\s+)?required|"
    r"(?:sign|log)[\s-]*in\s+(?:is\s+)?required|"
    r"must\s+be\s+(?:logged|signed)[\s-]+in|"
    r"(?:sign|log)[\s-]*in\s*(?:to)?\s+(?:your\s+)?account|"
    r"(?:sign|log)[\s-]*in\s+(?:to\s+)?(?:continue|view|access)|"
    # JavaScript challenge/interstitial families.
    r"(?:please\s+)?(?:enable|turn\s+on)\s+(?:javascript|js)|"
    r"(?:javascript|js)\s+(?:(?:is\s+)?required(?:\s+to\s+"
    r"(?:continue|view|access))?|must\s+be\s+enabled|is\s+disabled)|"
    r"(?:this\s+)?site\s+requires\s+(?:javascript|js)|"
    # Cookie challenge/interstitial families.
    r"cookies?\s+(?:(?:are|is)\s+required|(?:are\s+)?disabled|"
    r"must\s+be\s+enabled)(?:\s+to\s+(?:continue|view|access))?|"
    r"(?:your\s+)?browser\s+(?:must|needs?\s+to)\s+"
    r"(?:accept|allow)\s+cookies|"
    r"(?:please\s+)?(?:enable|allow|accept)\s+(?:browser\s+)?cookies"
    r")\b",
    re.IGNORECASE,
)
_PROFILE_BARE_LOGIN_RE = re.compile(
    r"\b(?:sign[\s-]?in|log[\s-]?in|login)\b",
    re.IGNORECASE,
)
_NAME_NOISE = frozenset(
    {"prof", "professor", "dr", "phd", "md", "jr", "sr", "ii", "iii"}
)
_NON_PERSON_IDENTITY_TOKENS = frozenset(
    {
        "about",
        "academic",
        "contact",
        "department",
        "directory",
        "engineering",
        "faculty",
        "group",
        "home",
        "institute",
        "laboratory",
        "lab",
        "people",
        "profile",
        "program",
        "publications",
        "research",
        "school",
        "teaching",
        "university",
    }
)


def _profile_page_text(soup: object) -> str:
    if soup is None:
        return ""
    try:
        body = soup.get_text(" ", strip=True)
    except Exception:  # noqa: BLE001
        return ""
    return re.sub(r"\s+", " ", body).strip()


def profile_page_is_denial(soup: object) -> bool:
    body = _profile_page_text(soup)
    if (
        not body
        or _PROFILE_DENIAL_RE.search(body) is not None
        or _PROFILE_LOGIN_WALL_RE.search(body) is not None
    ):
        return True
    try:
        headings = " ".join(
            element.get_text(" ", strip=True)
            for element in soup.select("title, h1")
        )
    except Exception:  # noqa: BLE001
        headings = ""
    return (
        _PROFILE_BARE_LOGIN_RE.search(headings) is not None
        or (
            len(body) < 1200
            and _PROFILE_BARE_LOGIN_RE.search(body) is not None
        )
    )


def profile_page_matches_person(
    soup: object,
    expected_name: object,
    *,
    identity_selectors: object = None,
) -> bool:
    """Return whether an HTTP-200 page contains real identity evidence.

    A WAF/login/challenge response is still valid HTML and often returns 200.
    It must not advance a professor's 60-day profile-verification TTL merely
    because BeautifulSoup could parse it.
    """

    if not isinstance(expected_name, str):
        return False
    if profile_page_is_denial(soup):
        return False

    def tokens(value: str) -> list[str]:
        normalized = unicodedata.normalize("NFKD", value).casefold()
        normalized = "".join(
            char for char in normalized
            if not unicodedata.combining(char)
        )
        return [
            token
            for token in re.findall(r"[a-z0-9]+", normalized)
            if token not in _NAME_NOISE
        ]

    expected = tokens(expected_name)
    if not expected:
        return False
    default_strong_selectors = [
        "h1",
        "[itemprop='name']",
        ".person-name",
        ".profile-name",
        ".page-title",
        ".page--title",
    ]
    default_weak_selectors = ["title"]
    if identity_selectors is not None:
        if isinstance(identity_selectors, str):
            selectors = [identity_selectors] if identity_selectors.strip() else []
        elif isinstance(identity_selectors, (list, tuple)):
            selectors = [
                selector
                for selector in identity_selectors
                if isinstance(selector, str) and selector.strip()
            ]
        else:
            selectors = []
        strong_selectors = selectors
        weak_selectors: list[str] = []
    else:
        strong_selectors = default_strong_selectors
        weak_selectors = default_weak_selectors

    def candidates_for(selectors: list[str]) -> list[str]:
        return [
            re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()
            for selector in selectors
            for element in soup.select(selector)
            if element.get_text(" ", strip=True)
        ]

    try:
        strong_candidates = candidates_for(strong_selectors)
        weak_candidates = candidates_for(weak_selectors)
    except Exception:  # noqa: BLE001
        return False

    def matches(candidate: str) -> bool:
        observed = set(tokens(candidate))
        if len(expected) == 1:
            return len(expected[0]) >= 3 and expected[0] in observed
        if expected[0] in observed and expected[-1] in observed:
            # First + last survive middle-initial, credential, and "Last,
            # First" formatting differences.
            return True
        return False

    def clearly_other_person(candidate: str) -> bool:
        # Headings commonly suffix a real name with role/site furniture
        # ("Grace Hopper | Faculty Profile"). Remove that decoration before
        # deciding whether the authoritative node clearly names somebody else;
        # its presence must not turn a wrong-person page into an ambiguous
        # generic heading that a weaker <title> can override.
        observed = [
            token
            for token in tokens(candidate)
            if token not in _NON_PERSON_IDENTITY_TOKENS
        ]
        return not matches(candidate) and bool(observed)

    # A strong identity node naming a different person makes the page
    # ambiguous. Do not let a browser title or other weaker node override it.
    if any(clearly_other_person(candidate) for candidate in strong_candidates):
        return False
    if any(matches(candidate) for candidate in strong_candidates):
        return True
    return any(matches(candidate) for candidate in weak_candidates)

# Some university hosts (several InCommon-issued .edu certs — UCLA's Physics and
# Statistics sites, UW Statistics) ship an *incomplete* certificate chain: they
# present only their leaf, omitting the InCommon intermediate that links it to a
# public Sectigo/USERTrust root. A browser fixes this by AIA-fetching the missing
# intermediate; stdlib requests does not, so the handshake fails verification.
# We supply the two legitimate InCommon intermediates ourselves, appended to the
# normal certifi trust store, so the chain completes and verification stays FULLY
# ON (a bad/expired cert is still rejected). This is NOT verify=False.
_CA_BUNDLE: str | None = None


def _ca_bundle() -> str:
    """Path to a CA bundle = certifi roots + the bundled InCommon intermediates.

    Built once and cached. Falls back to certifi's default if anything goes
    wrong, so a missing intermediate file can never break the normal trust path.
    """
    global _CA_BUNDLE
    if _CA_BUNDLE is not None:
        return _CA_BUNDLE
    import certifi
    base = certifi.where()
    try:
        import tempfile
        intermediates = (Path(__file__).parent / "incommon_intermediates.pem").read_text()
        combined = Path(base).read_text() + "\n" + intermediates
        fd, path = tempfile.mkstemp(suffix="-ca.pem", prefix="ofe-")
        with open(fd, "w", encoding="utf-8") as f:
            f.write(combined)
        _CA_BUNDLE = path
    except Exception as e:  # noqa: BLE001 — never let trust setup crash a run
        logger.warning(f"InCommon CA bundle unavailable ({e}); using certifi default")
        _CA_BUNDLE = base
    return _CA_BUNDLE

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
    # Psychology lists its department admin inbox on every profile; without this
    # it attaches to many professors and trips the shared-admin-email DQ gate.
    "psychadmin@berkeley.edu",
    # Philosophy lists its department mailbox as a second mailto on every
    # profile; the professor's personal address is the first mailto.
    "phildept@berkeley.edu",
    # History (and its cross-listed area-studies depts) list a department
    # mailbox as a second mailto on every profile; the personal address is first.
    "history@berkeley.edu",
    # Public Health lists its school-wide contact mailbox as a second mailto on
    # every profile; the professor's personal address is the first mailto.
    "publichealth@berkeley.edu",
})

# Department directories mix retired faculty into the same card list; they are
# not viable cold-email targets for prospective undergrad researchers.
_RETIRED_TITLE_RE = re.compile(r"\b(emeritus|emerita|retired)\b", re.IGNORECASE)

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Standard "Open Berkeley" person-grid selectors. Most L&S humanities/language
# directories render their roster as `div.node-openberkeley-person` cards with
# the name in an <h2>/<h3> (sometimes wrapping the profile <a>) and the email /
# research-interest fields in the openberkeley field divs. The combined name
# selector tolerates both the "<h2>name</h2> + sibling /people/ link" and the
# "<h3><a>name</a></h3>" variants. Verified Jun 2026 against music, complit,
# german, french, slavic, tdps, rhetoric, spanish-portuguese, scandinavian.
# A department whose markup deviates keeps its own bespoke parser instead.
OPENBERKELEY_PERSON_SELECTORS = {
    "card": "div.node-openberkeley-person",
    "name": "h2 a, h3 a, h2, h3",
    "link": "a[href*='/people/']",
    "title": "div.field-name-field-openberkeley-person-title",
    "email_field": "div.field-name-field-openberkeley-person-email",
    "research_interests": [
        "div.field-name-body .field-item",
        "div.field-name-field-research-interests .field-item",
    ],
}

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
    "economics", "microeconomics", "macroeconomics", "industrial organization",
    "labor economics", "development economics", "behavioral economics",
    "public economics", "international economics", "economic theory", "finance",
    "antitrust", "welfare economics", "auctions", "market design",
    "psychology", "cognitive psychology", "clinical psychology",
    "social psychology", "developmental psychology", "cognitive neuroscience",
    "perception", "attention", "memory", "emotion regulation",
    "behavioral science", "psychopathology", "personality",
    "investigative journalism", "data journalism", "computational journalism",
    "documentary film", "documentary", "photojournalism",
    "narrative nonfiction", "science journalism", "environmental journalism",
    "health journalism", "broadcast journalism", "political reporting",
    "media studies", "press freedom", "audio storytelling",
    "visual journalism", "magazine journalism", "digital media",
    "social work", "social welfare", "social policy", "child welfare",
    "family policy", "welfare policy", "poverty", "child poverty",
    "homelessness", "foster care", "child abuse", "gerontology",
    "mental health", "substance use", "trauma", "social services",
    "racial equity", "health disparities", "community mental health",
    "behavioral health", "social determinants of health", "immigrant families",
    "aging and health", "youth development",
    "mathematics education", "science education", "stem education",
    "literacy", "language and literacy", "second language acquisition",
    "bilingual education", "higher education", "educational policy",
    "education policy", "educational psychology", "learning sciences",
    "teacher education", "educational equity", "curriculum",
    "early childhood education", "special education", "educational technology",
    "critical pedagogy", "educational leadership", "sociology of education",
    "child development", "numeracy", "cognition and development",
    "educational measurement", "school reform", "quantitative methods",
    "english literature", "american literature", "comparative literature",
    "poetry", "poetics", "fiction", "the novel", "narrative", "drama",
    "theater", "theatre", "rhetoric", "literary theory", "literary criticism",
    "critical theory", "medieval literature", "renaissance literature",
    "early modern literature", "victorian literature", "romanticism",
    "modernism", "postcolonial", "african american literature",
    "creative writing", "film studies", "digital humanities",
    "gender and sexuality", "environmental humanities", "shakespeare",
    "eighteenth-century literature", "nineteenth-century literature",
    "contemporary literature", "media studies",
    "metaphysics", "epistemology", "philosophy of mind",
    "philosophy of language", "philosophy of science", "philosophy of physics",
    "philosophy of mathematics", "philosophy of biology", "political philosophy",
    "moral philosophy", "moral psychology", "metaethics", "normative ethics",
    "applied ethics", "bioethics", "ancient philosophy", "early modern philosophy",
    "philosophy of action", "philosophy of logic", "mathematical logic",
    "aesthetics", "phenomenology", "feminist philosophy", "decision theory",
    "epistemology and metaphysics",
    "history of science", "early modern europe", "late modern europe",
    "modern europe", "medieval", "byzantine", "ancient greece",
    "ancient history", "east asia", "south asia", "southeast asia",
    "middle east", "north america", "latin america", "africa",
    "environmental history", "intellectual history", "cultural history",
    "social history", "economic history", "political history",
    "gender history", "jewish history", "history of capitalism",
    "colonialism", "empire", "migration",
    "public health", "epidemiology", "global health",
    "health policy", "environmental health", "occupational health",
    "infectious disease", "infectious diseases", "chronic disease",
    "health equity", "health disparities", "social determinants of health",
    "maternal and child health", "reproductive health", "community health",
    "health economics", "health services research", "implementation science",
    "vaccines", "immunization", "disease surveillance", "outbreak",
    "cancer epidemiology", "molecular epidemiology", "social epidemiology",
    "exposure assessment", "health behavior",
    "tobacco control", "substance use",
    "maternal health", "one health", "antimicrobial resistance",
    "health informatics", "digital health", "behavioral health",
    "geography", "geographic information systems", "gis", "political ecology",
    "cartography", "human geography", "physical geography", "urban geography",
    "biogeography", "geospatial analysis", "land use", "environmental justice",
    "critical geography",
    "anthropology", "archaeology", "biological anthropology",
    "sociocultural anthropology", "medical anthropology",
    "linguistic anthropology", "cultural anthropology", "ethnography",
    "folklore", "bioarchaeology", "paleoanthropology",
    "linguistics", "phonology", "phonetics", "syntax", "semantics",
    "morphology", "psycholinguistics", "computational linguistics",
    "historical linguistics", "sociolinguistics", "language documentation",
    "pragmatics", "language acquisition",
    "sociology", "social movements", "inequality", "race and ethnicity",
    "immigration", "demography", "social stratification", "political sociology",
    "economic sociology", "criminology", "urban sociology", "gender",
    "social networks", "historical sociology",
    "political science", "international relations", "comparative politics",
    "political economy", "political theory", "american politics",
    "public policy", "political behavior", "democracy", "elections",
    "formal theory", "international political economy", "political methodology",
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


# Per-host 429 circuit: repeated rate-limit responses mean the host is telling
# us to go away for longer than a retry backoff — keep hammering it and every
# remaining URL burns its full retry budget for nothing (and invites a ban).
# After _RATE_LIMIT_THRESHOLD consecutive 429s from one host, the rest of that
# host's URLs are skipped for this run. In-memory only: state lives for the
# process (= one refresh run), nothing is persisted, no other host is affected.
_RATE_LIMIT_THRESHOLD = 5
_RETRY_AFTER_CAP = 120.0  # seconds; don't let a hostile header stall the run
_consecutive_429: dict[str, int] = {}
_rate_limited_hosts: set[str] = set()


def _reset_rate_limit_circuit() -> None:
    _consecutive_429.clear()
    _rate_limited_hosts.clear()


def _retry_after_seconds(resp) -> float | None:
    """Delay-seconds form of Retry-After, capped; None when absent/unusable
    (the HTTP-date form is rare on rate limiters and not worth parsing)."""
    raw = (resp.headers.get("Retry-After") or "").strip() if resp is not None else ""
    try:
        val = float(raw)
    except ValueError:
        return None
    return min(val, _RETRY_AFTER_CAP) if val >= 0 else None


def _mark_fetched_soup_observation(
    soup: BeautifulSoup,
    *,
    requested_url: str,
    final_url: str,
    observed_at: datetime | str | None = None,
) -> BeautifulSoup:
    """Attach fetch-scoped facts used by reviewed parser fixtures and callers."""

    observed = datetime.now(UTC) if observed_at is None else observed_at
    if isinstance(observed, datetime):
        if observed.tzinfo is not None and observed.utcoffset() is not None:
            observed = observed.astimezone(UTC).isoformat()
        else:
            # Keep a naive fixture naive so the evidence builder rejects it.
            # Treating local wall time as UTC would silently manufacture proof.
            observed = observed.isoformat()
    soup._ofe_requested_url = requested_url
    soup._ofe_final_url = final_url
    soup._ofe_observed_at = observed
    return soup


def fetch_soup(url: str, ua: str | None = None, insecure: bool = False,
               timeout: int | None = None, max_retries: int | None = None) -> BeautifulSoup | None:
    """Fetch a URL with browser-like headers, retrying transient failures.

    Retries connection resets / timeouts / 5xx responses with exponential
    backoff. Returns None (never raises) if every attempt fails, so callers
    degrade to an empty result instead of crashing.

    ``ua`` overrides the browser User-Agent: some WAFs (Penn's Cloudflare/
    Imperva fronts) 403 a Chrome UA whose TLS fingerprint isn't Chrome's while
    letting an honest tool UA ("curl/8.7.1") straight through.

    ``insecure`` skips TLS verification for hosts serving an incomplete
    certificate chain (cmsw.mit.edu omits its intermediate — browsers repair
    it via AIA fetching, requests cannot). Scrape-only, opt-in per source.
    """
    host = (urlsplit(url).hostname or "").lower()
    if host in _rate_limited_hosts:
        logger.info(f"Skipping {url}: rate-limit circuit open for {host}")
        return None
    session = requests.Session()
    session.headers.update(HEADERS)
    if ua:
        session.headers["User-Agent"] = ua
    session.verify = False if insecure else _ca_bundle()
    if insecure:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    # The optional per-call overrides let a caller that fetches THOUSANDS of
    # optional pages (the per-profile enrichment pass) fail fast on slow/dead
    # hosts — a 30s read-timeout x 3 retries per bad profile otherwise balloons
    # a multi-department scrape into many hours. Listing scrapes keep the robust
    # module defaults.
    eff_timeout = timeout if timeout is not None else _TIMEOUT
    eff_retries = max_retries if max_retries is not None else _MAX_RETRIES
    last_err: Exception | None = None
    retry_after: float | None = None
    for attempt in range(1, eff_retries + 1):
        retry_after = None
        try:
            resp = session.get(url, timeout=eff_timeout)
            resp.raise_for_status()
            _consecutive_429.pop(host, None)
            # Parse bytes, not resp.text: the EECS server omits a charset
            # header, so requests falls back to ISO-8859-1 and mangles UTF-8
            # names ("Björn" -> "BjÃ¶rn"). BeautifulSoup detects the encoding.
            soup = BeautifulSoup(resp.content, "html.parser")
            # Trusted contact evidence must cite the response that was actually
            # parsed, not the pre-redirect request URL. Keep this fetch-scoped
            # observation off the normalized record; reviewed parsers consume it
            # only when name and email share one explicit row/card.
            return _mark_fetched_soup_observation(
                soup,
                requested_url=url,
                final_url=str(resp.url),
            )
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last_err = e
        except requests.exceptions.HTTPError as e:
            # Retry transient server errors and 429 rate-limits (a shared Varnish
            # cache returns 429 under burst load, then recovers); other 4xx client
            # errors are terminal.
            status = e.response.status_code if e.response is not None else None
            if status is None or (status < 500 and status != 429):
                logger.warning(f"Failed to fetch {url}: {e}")
                return None
            if status == 429 and host:
                streak = _consecutive_429.get(host, 0) + 1
                _consecutive_429[host] = streak
                if streak >= _RATE_LIMIT_THRESHOLD:
                    _rate_limited_hosts.add(host)
                    logger.warning(
                        f"{host}: {streak} consecutive 429s — skipping this "
                        f"host's remaining URLs for this run"
                    )
                    return None
                retry_after = _retry_after_seconds(e.response)
            last_err = e
        except Exception as e:  # noqa: BLE001 — unexpected; don't crash the run
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

        if attempt < eff_retries:
            delay = _RETRY_BACKOFF * (2 ** (attempt - 1))
            if retry_after is not None:
                delay = max(delay, retry_after)
            logger.warning(
                f"Fetch attempt {attempt}/{eff_retries} for {url} failed "
                f"({last_err}); retrying in {delay:.0f}s"
            )
            time.sleep(delay)

    logger.warning(
        f"Failed to fetch {url} after {eff_retries} attempts: {last_err}"
    )
    return None


def clean_name(name: str) -> str:
    name = re.sub(r"(?i)^(dr\.?|prof\.?|professor)\s+", "", name).strip()
    name = re.sub(r"\s*\(.*?\)\s*", " ", name).strip()
    name = re.sub(r",?\s*(Ph\.?D\.?|M\.?D\.?|Jr\.?|Sr\.?|III|II)$", "", name).strip()
    return re.sub(r"\s{2,}", " ", name)


# A directory card's name selector occasionally matches a non-person element —
# a "UC Berkeley" footer link, a breadcrumb, a section heading — yielding a
# "name" like "Berkeley". These are never valid PI names and, sharing a
# normalized value, trip the joint-appointment dedup gate and block the refresh.
_INSTITUTION_WORDS = frozenset({
    "berkeley", "uc", "ucb", "university", "universities", "college",
    "department", "institute", "school", "campus", "california", "faculty",
    "directory", "of", "the", "and", "for", "at",
})
_INSTITUTION_PREFIX_RE = re.compile(
    r"(?i)^\s*(department|school|college|division|office|center|institute|"
    r"university|faculty|directory)\b"
)
_NON_PERSON_NAME_PREFIX_RE = re.compile(
    r"(?i)^\s*(?:contact(?:\s+us)?|email(?:\s+us)?|get\s+in\s+touch|"
    r"learn\s+more|read\s+more|view\s+(?:profile|details|bio|more)|"
    r"click\s+here|find\s+out\s+more|support|help(?:\s+desk)?|"
    r"research\s+areas?|publications?|teaching|biograph(?:y|ies)|"
    r"news|events|resources?)\s*$"
)


def _is_person_name(name: str) -> bool:
    """True when `name` plausibly names a person, not an institution/place.

    A real name carries at least one token that isn't an institution/place word
    and doesn't lead with an institutional phrase ("Department of …"). A bare
    place/institution label ("Berkeley", "UC Berkeley", "University of
    California") fails both tests.
    """
    name = (name or "").strip()
    if len(name) < 3:
        return False
    if len(name) > 70:  # a legend/footer/abbreviations row, never a person name
        return False
    if "@" in name:  # an email address grabbed as the name (mailto-only card)
        return False
    if "%" in name:  # a Drupal token leaked unrendered ("%AutoEntityLabel: <uuid>%")
        return False
    # An HTTP error/placeholder page parsed as a person ("403 - Page Not
    # Available", "n/a"): no real name leads with a 3-digit status code or is a
    # bare placeholder token.
    low = name.lower().strip()
    if re.match(r"\s*[45]0[0-9]\b", name) or "page not " in low or low in {
        "n/a", "na", "null", "none", "undefined", "unknown", "not available",
    }:
        return False
    if _INSTITUTION_PREFIX_RE.match(name) or _NON_PERSON_NAME_PREFIX_RE.match(name):
        return False
    tokens = re.findall(r"[a-z]+", name.lower())
    return bool(tokens) and any(t not in _INSTITUTION_WORDS for t in tokens)


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


# Open-Berkeley person pages share one identity template across departments
# (body class ``node-type-openberkeley-person``; verified live on
# ourenvironment.berkeley.edu /people/<slug>, 2026-07): the standard
# ``field-openberkeley-person-*`` wrappers below carry the person's email,
# rank, and research interests. Tried as fallbacks so a department config
# without bespoke selectors still extracts from the platform template; on
# non-Open-Berkeley pages they simply match nothing.
_OPENBERKELEY_EMAIL_SEL = "div.field-name-field-openberkeley-person-email"
_OPENBERKELEY_TITLE_SEL = "div.field-name-field-openberkeley-person-title"
_SCRAPED_TITLE_LABEL_RE = re.compile(
    r"^\s*(?:position\s+)?title\s*:\s*",
    re.IGNORECASE,
)


def _clean_scraped_title(value: object) -> str:
    """Remove Open-Berkeley field labels without changing the real title."""

    if not isinstance(value, str):
        return ""
    return _SCRAPED_TITLE_LABEL_RE.sub("", value).strip()
_OPENBERKELEY_RESEARCH_SELS = (
    "div.field-name-field-openberkeley-person-research-interests .field-item",
    "div.field-name-field-resint .field-item",
)


def extract_email_from_profile(soup: BeautifulSoup, config: dict) -> str | None:
    """Pull a contact email from an individual faculty profile page.

    Tries, in order: a mailto: link, the configured email field (with the
    standard Open-Berkeley person-email field as fallback), then a page-wide
    scan. Prefers Berkeley addresses and skips shared/admin mailboxes.
    Returns None when nothing usable is found.
    """
    candidates: list[str] = []

    for a in soup.select("a[href^='mailto:']"):
        addr = a.get("href", "").replace("mailto:", "").split("?")[0].strip()
        if addr:
            candidates.append(addr)

    email_sel = config.get("selectors", {}).get("email_field")
    for sel in dict.fromkeys(s for s in (email_sel, _OPENBERKELEY_EMAIL_SEL) if s):
        field = soup.select_one(sel)
        if field:
            candidates += EMAIL_RE.findall(field.get_text(" ", strip=True))

    if not candidates:
        candidates += EMAIL_RE.findall(soup.get_text(" ", strip=True))

    cleaned = [e.lower() for e in candidates if e.lower() not in NOISE_EMAILS]
    if not cleaned:
        return None
    berkeley = [e for e in cleaned if e.endswith("berkeley.edu")]
    return (berkeley or cleaned)[0]


def _allowed_contact_domains(config: dict) -> tuple[str, ...]:
    return tuple(config.get("allowed_email_domains") or (
        "berkeley.edu",
        "lbl.gov",
        "msri.org",
        "slmath.org",
    ))


_BOUND_ROLE_LOCALPART_RE = re.compile(
    r"(?:office|admin|administrator|support|help|helpdesk|webmaster|"
    r"webmanager|noreply|donotreply|inquiries|reception|frontdesk|"
    r"mailbox|chair|info|contact|advising|staff|hr|undergrad|"
    r"undergraduate|graduate|grad|admissions|communications|outreach|"
    r"media|press|events|alumni|development|coordinator|recruitment|"
    r"jobs|careers|assistant|manager|secretary|faculty|directory|team|"
    r"group|lab)$",
    flags=re.IGNORECASE,
)


def _department_contact_markers(config: dict) -> set[str]:
    structural = {
        "department",
        "school",
        "college",
        "division",
        "program",
        "institute",
        "center",
        "and",
        "the",
        "for",
        "of",
    }
    return {
        token
        for token in re.findall(
            r"[a-z]+",
            str(config.get("name") or "").casefold(),
        )
        if len(token) >= 3 and token not in structural
    }


def _clean_bound_contact(email: object, config: dict) -> str | None:
    if not isinstance(email, str):
        return None
    cleaned = email.strip().casefold().removeprefix("mailto:")
    cleaned = cleaned.split("?", 1)[0]
    if not EMAIL_RE.fullmatch(cleaned) or cleaned in NOISE_EMAILS:
        return None
    local_part = re.sub(r"[^a-z]", "", cleaned.partition("@")[0])
    department_markers = _department_contact_markers(config)
    short_marker = re.sub(r"[^a-z]", "", str(config.get("short") or "").casefold())
    if (
        local_part in _UNIT_MAILBOX_LOCALPARTS
        or local_part in department_markers
        or (short_marker and local_part == short_marker)
        or _BOUND_ROLE_LOCALPART_RE.search(local_part) is not None
    ):
        return None
    domain = cleaned.partition("@")[2]
    if not any(
        domain == allowed or domain.endswith(f".{allowed}")
        for allowed in _allowed_contact_domains(config)
    ):
        return None
    return cleaned


def unique_bound_contact(candidates: object, config: dict) -> str | None:
    """Return one canonical personal address, or fail on ambiguity.

    Repeated renderings of the same address are harmless. Two distinct usable
    addresses inside one row/card are not enough to prove which belongs to the
    selected person, so reviewed producers must not choose the first one.
    """

    raw_candidates = (
        [candidates]
        if isinstance(candidates, str)
        else list(candidates)
        if isinstance(candidates, (list, tuple, set, frozenset))
        else []
    )
    cleaned = {
        candidate
        for raw in raw_candidates
        if (candidate := _clean_bound_contact(raw, config)) is not None
    }
    return next(iter(cleaned)) if len(cleaned) == 1 else None


def unique_bound_mailto_contact(elements: object, config: dict) -> str | None:
    """Validate mailto hrefs and visible addresses as one unambiguous claim."""

    if not isinstance(elements, (list, tuple)):
        return None
    candidates: list[str] = []
    for element in elements:
        href = element.get("href") if hasattr(element, "get") else None
        if (
            not isinstance(href, str)
            or href != href.strip()
            or any(character.isspace() for character in href)
            or re.search(r"%0[ad]", href, flags=re.IGNORECASE)
        ):
            return None
        try:
            parsed = urlsplit(href)
        except ValueError:
            return None
        if parsed.scheme.casefold() != "mailto" or parsed.fragment:
            return None
        try:
            query = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=False,
            )
        except ValueError:
            return None
        if any(
            key.strip().casefold() in {"to", "cc", "bcc"}
            for key, _value in query
        ):
            return None
        href_email = _clean_bound_contact(parsed.path, config)
        if href_email is None:
            return None

        visible_raw = EMAIL_RE.findall(
            element.get_text(" ", strip=True)
            if hasattr(element, "get_text")
            else ""
        )
        if visible_raw:
            visible = [
                _clean_bound_contact(value, config)
                for value in visible_raw
            ]
            if any(value is None for value in visible) or set(visible) != {
                href_email
            }:
                return None
        candidates.append(href_email)
    return unique_bound_contact(candidates, config)


def unique_bound_container_contact(
    container: object,
    config: dict,
    *,
    nested_record_selector: str,
) -> str | None:
    """Return one address only when visible text and mailto hrefs agree."""

    if not hasattr(container, "get_text") or not hasattr(container, "select"):
        return None
    if (
        not nested_record_selector
        or container.select_one(nested_record_selector) is not None
    ):
        # A descendant record container makes name/email scope ambiguous:
        # descendant selectors could otherwise bind the child email to parent.
        return None
    visible_raw = EMAIL_RE.findall(container.get_text(" ", strip=True))
    visible = [_clean_bound_contact(value, config) for value in visible_raw]
    if any(value is None for value in visible):
        return None

    mailto_elements = []
    for element in container.select("a[href]"):
        href = element.get("href")
        if not isinstance(href, str):
            continue
        try:
            is_mailto = urlsplit(href).scheme.casefold() == "mailto"
        except ValueError:
            is_mailto = False
        if is_mailto:
            mailto_elements.append(element)
    candidates = [value for value in visible if value is not None]
    if mailto_elements:
        mailto_email = unique_bound_mailto_contact(mailto_elements, config)
        if mailto_email is None:
            return None
        candidates.append(mailto_email)
    return unique_bound_contact(candidates, config)


def _fetch_contact_observation(
    soup: BeautifulSoup,
    requested_url: str,
) -> tuple[str, str] | None:
    """Return ``(final_url, observed_at)`` from this exact fetch event.

    Synthetic/legacy soups have no observation metadata and therefore cannot
    mint contact evidence. Redirects across hosts fail closed; a reviewed
    listing parser may follow a same-host canonical redirect and cites the
    final response URL.
    """

    observed_request = getattr(soup, "_ofe_requested_url", None)
    final_url = getattr(soup, "_ofe_final_url", None)
    observed_at = getattr(soup, "_ofe_observed_at", None)
    if not all(
        isinstance(value, str) and value
        for value in (observed_request, final_url, observed_at, requested_url)
    ):
        return None
    if observed_request != requested_url:
        return None
    try:
        requested_host = (urlsplit(requested_url).hostname or "").casefold()
        final_host = (urlsplit(final_url).hostname or "").casefold()
    except ValueError:
        return None
    if not requested_host or requested_host != final_host:
        return None
    return final_url, observed_at


def stamp_bound_directory_contact(
    person: dict,
    email: object,
    config: dict,
    *,
    source_soup: BeautifulSoup,
    requested_url: str,
    email_source: str = "bound_directory_card",
) -> bool:
    """Attach one complete, same-row/card contact observation to ``person``.

    The caller must invoke this inside the parser boundary where the person's
    name and the address were read from the same explicit record container.
    The claim is stored under one internal key and normalized later as the
    six-field ``contact_email`` + evidence bundle. No partial evidence fields
    are written when validation fails.
    """

    if not _is_person_name(str(person.get("name") or "")):
        return False
    cleaned = unique_bound_contact(email, config)
    observation = _fetch_contact_observation(source_soup, requested_url)
    if (
        cleaned is None
        or observation is None
        or email_source not in IDENTITY_BOUND_EMAIL_SOURCES
        or not email_source.startswith("bound_directory_")
    ):
        return False
    final_url, observed_at = observation
    evidence = build_identity_bound_contact_evidence(
        email=cleaned,
        email_source=email_source,
        contact_source_url=final_url,
        contact_verified_at=observed_at,
    )
    if evidence is None:
        return False
    person["_contact_claim"] = {
        "contact_email": cleaned,
        "metadata": evidence,
    }
    return True


def _trusted_person_contact(person: dict, config: dict) -> dict | None:
    """Return a collector claim only when its complete bundle revalidates."""

    claim = person.get("_contact_claim")
    if not isinstance(claim, dict):
        return None
    email = _clean_bound_contact(claim.get("contact_email"), config)
    metadata = claim.get("metadata")
    if email is None or not isinstance(metadata, dict):
        return None
    rebuilt = build_identity_bound_contact_evidence(
        email=email,
        email_source=metadata.get("email_source"),
        contact_source_url=metadata.get("contact_source_url"),
        contact_verified_at=metadata.get("contact_verified_at"),
    )
    if rebuilt is None or any(
        metadata.get(field) != value for field, value in rebuilt.items()
    ):
        return None
    verified_email = metadata.get("contact_verified_email")
    if (
        not isinstance(verified_email, str)
        or verified_email.casefold() != email
    ):
        return None
    return {
        "contact_email": email,
        "metadata": rebuilt,
    }


def record_contact_claim(record: dict) -> dict | None:
    """Return a fresh normalized claim, preserving its original timestamp."""

    email = verified_send_target(record)
    metadata = record.get("metadata")
    if not email or not isinstance(metadata, dict):
        return None
    return {
        "contact_email": email,
        "metadata": {
            field: metadata[field]
            for field in CONTACT_EVIDENCE_FIELDS
        },
    }


def clear_contact_evidence(record: dict) -> None:
    """Remove all five proof fields while preserving the current email."""

    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return
    cleaned = {
        key: value
        for key, value in metadata.items()
        if key not in CONTACT_EVIDENCE_FIELDS
    }
    record["metadata"] = cleaned


def apply_record_contact_claim(record: dict, claim: dict) -> bool:
    """Commit a previously validated claim to a normalized record in one update."""

    email = claim.get("contact_email") if isinstance(claim, dict) else None
    metadata = claim.get("metadata") if isinstance(claim, dict) else None
    if not isinstance(email, str) or not isinstance(metadata, dict):
        return False
    rebuilt = build_identity_bound_contact_evidence(
        email=email,
        email_source=metadata.get("email_source"),
        contact_source_url=metadata.get("contact_source_url"),
        contact_verified_at=metadata.get("contact_verified_at"),
    )
    if rebuilt is None or any(
        metadata.get(field) != value for field, value in rebuilt.items()
    ):
        return False
    base_metadata = record.get("metadata")
    clean_metadata = {
        key: value
        for key, value in (
            base_metadata.items() if isinstance(base_metadata, dict) else ()
        )
        if key not in CONTACT_EVIDENCE_FIELDS
    }
    clean_metadata.update(rebuilt)
    record.update({
        "contact_email": rebuilt["contact_verified_email"],
        "metadata": clean_metadata,
    })
    return True


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
    if not parts:
        # Standard Open-Berkeley person-template fields, for configs without
        # bespoke research selectors (matches nothing on other platforms).
        for sel in _OPENBERKELEY_RESEARCH_SELS:
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
            # Provenance hints, not gates: normalize_faculty copies them into
            # metadata when present; a person without them (unenriched
            # collector, listing-supplied email) normalizes exactly as before.
            profile_verified = profile_page_matches_person(
                soup,
                person.get("name"),
            )
            if profile_verified:
                person["_verification_scope"] = "profile"
            email = extract_email_from_profile(soup, config)
            if email and profile_verified:
                person["email"] = email
                person["_email_source"] = "profile_page"
                found += 1
            interests = extract_research_interests(soup, config)
            if interests and profile_verified:
                person["research_areas"] = interests
                with_interests += 1
            if profile_verified and not (person.get("title") or "").strip():
                field = soup.select_one(_OPENBERKELEY_TITLE_SEL)
                title = _clean_scraped_title(
                    field.get_text(" ", strip=True) if field else ""
                )
                if title:
                    person["title"] = title
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


# Page-furniture / nav phrases that a bespoke profile parser occasionally pulls
# into research text when a profile's accordion/section markup deviates from the
# norm (observed on a BioE profile). They are never research areas; strip them so
# they can't leak into description_clean (the DQ gate forbids them). Kept in sync
# with tests/test_opportunity_data_quality.py::test_faculty_description_has_no_navmenu_leak.
_NAV_FURNITURE = (
    "Once Research Secured", "Administration & Staff", "Colloquia Calendar",
    "Affiliated Faculty", "Labs & Facilities", "Research Institutes and Centers",
)


def _strip_nav_furniture(text: str) -> str:
    """Remove known nav/section-furniture phrases from scraped research text."""
    if not text:
        return text
    for phrase in _NAV_FURNITURE:
        text = re.sub(re.escape(phrase), " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip(" ;,")


# Site chrome that leaks into a page-text excerpt when a scrape grabs the whole
# <body>: skip-links, the nav toggle, the mobile menu open/close controls, the
# search box. Not content — rendered raw after "From the program page:" it reads
# as a broken scrape and pollutes any text signal built from the description.
_PAGE_CHROME_RE = re.compile(
    r"\bskip to (?:main )?content\b|\btoggle navigation\b|"
    r"\b(?:expand|collapse) main menu\b|\bclose menu\b|\bmain menu\b|"
    r"\bsubmit search\b|\bsearch terms\b",
    re.IGNORECASE,
)


def _strip_page_chrome(text: str) -> str:
    """Remove skip-link / nav-toggle / menu chrome phrases from excerpt text."""
    if not text:
        return text
    return re.sub(r"\s{2,}", " ", _PAGE_CHROME_RE.sub(" ", text)).strip(" ;,|")


def _readable_excerpt(soup, limit: int = 400) -> str:
    """A short page-text excerpt with nav/header/footer chrome excluded, for the
    "From the program page:" supplement. Prefers a semantic main-content
    landmark (so the whole menu block is structurally skipped); when a page has
    none, its full text is chrome-heavy, so we return "" rather than ship a nav
    dump. Non-mutating — the caller's soup keeps its nav links for crawling."""
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")
    if main is not None:
        return _strip_page_chrome(main.get_text(" ", strip=True))[:limit]
    text = soup.get_text(" ", strip=True)
    if _PAGE_CHROME_RE.search(text):
        return ""
    return _strip_page_chrome(text)[:limit]


# Funding-signal detection. Faculty directories almost never state compensation
# (it's lab/grant-specific — the reason paid defaults to "unknown"). So we only
# UPGRADE paid when the scraped text carries explicit funding language, and
# otherwise keep "unknown" but return a helpful note instead of a blank field.
_FUNDING_PAID_RE = re.compile(
    r"\b(salary|salaried|hourly\s+wage|paid\s+position|paid\s+research|"
    r"paid\s+undergraduate|paid\s+intern)\b",
    re.IGNORECASE,
)
_FUNDING_STIPEND_RE = re.compile(
    r"\b(stipend|funded\s+position|funding\s+available|work[-\s]?study|"
    r"research\s+assistantship|\bRA\s+position)\b",
    re.IGNORECASE,
)
_FUNDING_DEFAULT_NOTE = (
    "Funding varies by lab — ask about paid RA, work-study, or course-credit "
    "(199 units) options when you reach out."
)


def _detect_funding(text: str) -> tuple[str, str]:
    """Return (paid, compensation_details) from scraped text.

    Only an explicit signal upgrades ``paid`` off "unknown"; conservative by
    design so we never fabricate a compensation claim a directory didn't make.
    """
    t = text or ""
    if _FUNDING_PAID_RE.search(t):
        return "yes", "Listing mentions a paid position — confirm details with the professor."
    if _FUNDING_STIPEND_RE.search(t):
        return "stipend", "Listing mentions funding/stipend — confirm details with the professor."
    return "unknown", _FUNDING_DEFAULT_NOTE


def normalize_faculty(person: dict, config: dict) -> dict | None:
    """Convert a scraped faculty entry into the normalized opportunity schema."""
    name = person.get("name", "")
    if not _is_person_name(name):
        return None

    trusted_contact = _trusted_person_contact(person, config)
    email = (
        trusted_contact["contact_email"]
        if trusted_contact is not None
        else person.get("email", "")
    )
    dept_short = config["short"]
    dept_name = config["name"]
    profile_url = person.get("url", "")
    # A missing rank stays missing (truthfulness W11): "" means the directory
    # stated no rank, and every consumer renders rank-neutrally for it — never
    # fabricated as "Professor". _clean_scraped_title also normalizes again at
    # this schema boundary so a missed parser path (listing vs. profile
    # templates disagree on whether the field label is included in text,
    # "Title:" vs "Position title:") can never leak the label into the
    # user-facing description or metadata.
    title = _clean_scraped_title(person.get("title"))
    if _RETIRED_TITLE_RE.search(title):
        return None
    research_areas = _strip_nav_furniture(person.get("research_areas", ""))

    name_hash = hashlib.md5(f"{dept_short}-{name}".encode()).hexdigest()[:8]
    opp_id = f"faculty-ucb-{dept_short.lower()}-{name_hash}"

    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    keywords = extract_research_keywords(person, config)
    # Faculty are cold-email research contacts, not postings with required
    # skills — inferring skills from research-topic prose is false-precise (a
    # Statistics professor whose interests say "statistics"/"probability" gets a
    # bare skills_required=["R"]) and degrades their match score. Mirrors the
    # R70A DQ gate and faculty_graph.normalize_person, which already ship []; the
    # enricher/llm_tagger skill backfills are likewise faculty-gated.
    skills: list[str] = []

    professor_rank = is_professor_rank(title)
    desc_parts = [
        f"Research opportunity with {title + ' ' if title else ''}{name} in the {dept_name} "
        f"at UC Berkeley.",
    ]
    if research_areas:
        desc_parts.append(f"Research areas: {research_areas[:200]}")
    desc_parts.append(
        "Contact the professor directly to inquire about undergraduate "
        "research positions in their lab." if professor_rank else
        "Contact them directly to inquire about undergraduate "
        "research opportunities."
    )
    description = " ".join(desc_parts)
    # Defensive second pass: strip nav-furniture from the FULLY ASSEMBLED
    # description, not just research_areas. The DQ gate checks these phrases in
    # description_clean, so stripping the final string guarantees no leak no
    # matter how a phrase enters (a profile excerpt path that bypassed the
    # research_areas strip, a phrase straddling the "Research areas:" join, etc.).
    description = _strip_nav_furniture(description)

    research_summary = f" ({', '.join(keywords[:3])})" if keywords else ""
    # "Prof." is a rank claim, earned only by a source-stated professor rank
    # (truthfulness W11); the actual rank ships in metadata.faculty_title.
    honorific = "Prof. " if professor_rank else ""
    opp_title = f"Research with {honorific}{name} — {dept_short}{research_summary}"

    paid, compensation_details = _detect_funding(f"{research_areas} {description} {title}")

    metadata = {
        "confidence_score": 0.7 if email else 0.5,
        "last_verified": now,
        "first_seen_at": now,
        "last_seen_at": now,
        "is_active": True,
        "manually_reviewed": False,
        "notes": f"Auto-imported from {dept_name} faculty directory",
        "faculty_title": title,
        "research_areas_raw": research_areas[:300] if research_areas else "",
    }
    # Additive provenance: enrich_faculty_from_profiles leaves hints about
    # where the record's fields were extracted. A person without them (email
    # straight off the listing, un-enriched collector, every legacy record)
    # normalizes identically — provenance is extra information, never a
    # condition for keeping the email.
    if person.get("_verification_scope") == "profile":
        metadata["verification_scope"] = "profile"
    if trusted_contact is not None:
        metadata.update(trusted_contact["metadata"])
    else:
        email_source = person.get("_email_source")
        if email and isinstance(email_source, str) and email_source:
            metadata["email_source"] = email_source

    return {
        "id": opp_id,
        "source": config["source"],
        "source_url": profile_url,
        "source_type": "faculty_research",
        "title": opp_title,
        "organization": "University of California, Berkeley",
        "department": dept_name,
        # No fabricated lab entity (truthfulness W11): a lab name only ever
        # comes from source text; none is scraped here, so none is asserted.
        "lab_or_program": "",
        "pi_name": name,
        "contact_email": email or None,
        "url": profile_url,
        "location": "Berkeley, CA",
        "on_campus": False,
        "remote_option": "unknown",
        "opportunity_type": "research",
        "paid": paid,
        "compensation_details": compensation_details,
        "deadline": None,
        "posted_date": None,
        "start_date": None,
        "duration": "Semester or academic year",
        "eligibility": {
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
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
        "metadata": metadata,
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


# Generic department/unit/role mailbox local-parts that scrape in place of a
# professor's personal address (office@, advising@, boxoffice@). A "Dear Prof. X"
# cold email to a unit inbox misfires, so null it (the send modal then disables).
# Distinct from the frequency pass below — these are single-record inboxes it
# never sees. Mirrors uiuc_faculty._UNIT_MAILBOX_LOCALPARTS.
_UNIT_MAILBOX_LOCALPARTS = frozenset({
    "office", "mainoffice", "frontoffice", "dean", "info", "contact", "admin",
    "administration", "advising", "gradoffice", "undergrad", "undergraduate",
    "hr", "reception", "frontdesk", "dept", "department", "inquiries",
    "generalinquiries", "mailbox", "webmaster", "help", "support", "boxoffice",
    "chair", "staff", "webmanager", "helpdesk", "noreply", "donotreply",
    "communications", "graduate", "grad", "admissions", "outreach", "media",
    "press", "events", "alumni", "development",
})


def _is_ucb_faculty(opp: dict) -> bool:
    return (opp.get("source") or "").startswith("ucb_") and \
        opp.get("source_type") == "faculty_research"


def clear_contact_claim(opp: dict) -> None:
    """Null a rejected address and remove its five proof fields atomically."""

    clear_contact_evidence(opp)
    opp["contact_email"] = None


def _null_shared_contact_emails(opps: list[dict]) -> int:
    """Null a contact_email shared by 2+ distinct ucb_* faculty — a scraped
    department/coordinator inbox, never a personal address (two different people
    don't share one). Adapts uiuc_faculty._null_shared_admin_emails, but at a
    threshold of 2 (not 3) because the ucb_* data-quality gate forbids *any* two
    records sharing an email; this ends the manual NOISE_EMAILS whack-a-mole
    (tdps@, tdpsboxoffice@, psychadmin@, ...) by catching unknown mailboxes
    automatically. Same-person joint appointments are already collapsed by
    drop_joint_appointment_duplicates, so a remaining shared email is a mailbox.
    Mutates in place; returns the count nulled."""
    names_by_email: dict[str, set[str]] = {}
    for opp in opps:
        if not _is_ucb_faculty(opp):
            continue
        if email := _dedup_email(opp):
            names_by_email.setdefault(email, set()).add(_dedup_name(opp))
    shared = {e for e, names in names_by_email.items() if len(names) >= 2}
    nulled = 0
    for opp in opps:
        if _is_ucb_faculty(opp) and _dedup_email(opp) in shared:
            clear_contact_claim(opp)
            nulled += 1
    return nulled


def _null_unit_mailbox_emails(opps: list[dict]) -> int:
    """Null a ucb_* faculty contact_email whose local-part is a generic unit/role
    mailbox (office@, advising@, boxoffice@) — a single-record inbox the frequency
    pass never sees. Mutates in place; returns the count nulled."""
    nulled = 0
    for opp in opps:
        if not _is_ucb_faculty(opp):
            continue
        email = _dedup_email(opp)
        if email and email.split("@", 1)[0] in _UNIT_MAILBOX_LOCALPARTS:
            clear_contact_claim(opp)
            nulled += 1
    return nulled


def collapse_ucb_joint_appointments(opps: list[dict]) -> dict:
    """Deterministically collapse SAME-person joint-appointment duplicates among
    ucb_* faculty, so no two ``faculty_research`` records share a non-null
    contact_email or a normalized pi_name — regardless of the order collectors
    merged or enrichment filled emails.

    A Berkeley professor cross-appointed in two departments (e.g. Tony Keaveny
    in both ``ucb_me_faculty`` and ``ucb_bioe_faculty``) lists ONE personal
    address across two directory profiles under slightly different names ("Tony
    Keaveny" vs "Tony M. Keaveny"). The merge-time
    ``drop_joint_appointment_duplicates`` and the threshold-2
    ``_null_shared_contact_emails`` both run DURING each collector's own merge;
    when a department site is rate-limited (429) its profile emails are absent at
    merge time and are re-added only afterward — by the corpus-wide pi_enricher
    pass and by ``_carry_forward_enrichment`` from the committed corpus. The
    collision therefore reappears *after* every merge-time pass has run, and the
    corpus-wide ``_null_shared_admin_emails`` pass (threshold 3) does not catch a
    2-way share. This FINAL pass runs post-enrichment over the whole corpus and
    is order-independent.

    Two same-person groupings, both conservative — this DROPS the duplicate
    (keeping the real contact) rather than nulling a real address:

    * **Same normalized name** (order-insensitive; middle initials + credential
      suffixes dropped, so "Tony Keaveny" == "Tony M. Keaveny") under two
      different ucb sources — one person cross-listed. Keep the keyword-richer
      record, merge the loser's email/profile link into it, drop the loser.
      (``ucb_bioe_faculty`` merges before ``ucb_me_faculty`` and is the richer
      home record, so Keaveny's bioe row is kept — matching the merge order.)
    * **Same non-null contact_email** under two different ucb sources — collapse
      ONLY when the records are the same person: their profile-URL slugs match
      (their normalized names matching is already handled by the pass above).
      When names differ AND slugs differ they are two DIFFERENT people sharing a
      scraped department mailbox; dropping one would delete a real professor, so
      leave them for ``_null_shared_contact_emails`` to null instead.

    Distinct from ``_null_shared_contact_emails`` (different people on one
    mailbox -> null) — this handles same-person joint appointments (-> drop).
    Mutates ``opps`` (merges survivor fields) and returns
    ``{"kept": [...], "removed": int}``; reassign the caller's list to ``kept``.
    """
    from .faculty_graph import (
        _join_slug,
        _merge_faculty_fields,
        _norm_person_name,
        _pick_richer,
    )

    fac = [o for o in opps if _is_ucb_faculty(o)]
    remove: set[int] = set()

    def _collapse(group: list[dict]) -> None:
        group = [o for o in group if id(o) not in remove]
        # Require >= 2 records from DIFFERENT sources: a same-source duplicate is
        # a within-directory listing dup handled at scrape time (dedup_by_profile_url).
        if len(group) < 2 or len({o.get("source") for o in group}) < 2:
            return
        survivor = _pick_richer(group, frozenset())
        for o in group:
            if o is survivor:
                continue
            _merge_faculty_fields(survivor, o)  # carry email/profile link forward
            remove.add(id(o))
            logger.info(
                f"  Collapsing ucb joint-appointment duplicate {o.get('pi_name')!r} "
                f"({o.get('source')}) into {survivor.get('source')} — same person"
            )

    # Pass 1: same normalized name across different ucb sources.
    by_name: dict[str, list[dict]] = {}
    for o in fac:
        nn = _norm_person_name(o.get("pi_name"))
        if nn:
            by_name.setdefault(nn, []).append(o)
    for group in by_name.values():
        _collapse(group)

    # Pass 2: same non-null email across different ucb sources — collapse only
    # when the profile-URL slugs match (same person under one profile). Different
    # slugs + different names = different people on a shared inbox: defer to
    # _null_shared_contact_emails rather than drop a real professor.
    by_email: dict[str, list[dict]] = {}
    for o in fac:
        if id(o) in remove:
            continue
        if em := _dedup_email(o):
            by_email.setdefault(em, []).append(o)
    for group in by_email.values():
        group = [o for o in group if id(o) not in remove]
        if len(group) < 2 or len({o.get("source") for o in group}) < 2:
            continue
        slugs = {_join_slug(o.get("url") or o.get("source_url") or "") for o in group}
        slugs.discard("")
        if len(slugs) == 1:
            _collapse(group)

    kept = [o for o in opps if id(o) not in remove]
    return {"kept": kept, "removed": len(remove)}


_SHARED_PHRASE_NAV_THRESHOLD = 3


def _derive_keywords_from_raw(opps: list[dict]) -> int:
    """Enrich broad-field-only ucb_* faculty with real keywords parsed from the
    research-interest text the profile-enrichment already stored in
    ``research_areas_raw`` — Berkeley's substitute for UIUC's Illinois Experts
    enrichment (Berkeley runs no Elsevier-Pure portal, so there is no per-faculty
    publication-concept feed; the dept-profile research text is the next-best
    signal, and it is already scraped). Reuses UIUC's shared phrase splitter +
    cleaner so the junk/furniture/fragment filtering matches across schools.

    For each record stuck on the broad dept field (<=1 keyword), parse its raw
    text into clean topical phrases, skipping phrases shared by >3 dept peers (a
    nav-block, not personal) and self-name tokens, keep up to 4, and rebuild the
    title parenthetical so it stays a subset of the keywords (the DQ gate checks
    that). Mutates in place; returns the count enriched."""
    from collections import Counter

    from .uiuc_faculty import _clean_research_phrase, _split_research_phrases

    fac = [o for o in opps if _is_ucb_faculty(o)]
    dept_counts: dict[str, Counter] = {}
    for o in fac:
        raw = (o.get("metadata") or {}).get("research_areas_raw") or ""
        c = dept_counts.setdefault(o.get("department", ""), Counter())
        for p in _split_research_phrases(raw):
            c[p.lower()] += 1

    enriched = 0
    for o in fac:
        if len(o.get("keywords") or []) > 1:
            continue  # already carries specific keywords
        broad = (o.get("keywords") or [""])[0].lower()
        raw = (o.get("metadata") or {}).get("research_areas_raw") or ""
        if not raw.strip():
            continue
        parts = _split_research_phrases(raw)
        if len(raw) >= 295 and parts:
            parts = parts[:-1]  # the 300-char cap usually truncates the last phrase
        name_tokens = {t.lower() for t in re.split(r"\W+", o.get("pi_name") or "") if t}
        counts = dept_counts[o.get("department", "")]
        derived: list[str] = []
        for p in parts:
            if counts[p.lower()] > _SHARED_PHRASE_NAV_THRESHOLD:
                continue
            cleaned = _clean_research_phrase(p)
            if not cleaned or cleaned == broad or cleaned in derived or cleaned in name_tokens:
                continue
            derived.append(cleaned)
            if len(derived) >= 4:
                break
        if derived:
            o["keywords"] = derived
            # Rebuild the title parenthetical from the new keywords so the DQ
            # "title areas subset of keywords" invariant holds.
            base = re.sub(r"\s*\([^()]*\)\s*$", "", o.get("title", ""))
            o["title"] = f"{base} ({', '.join(derived[:3])})"
            enriched += 1
    return enriched


def merge_into_processed(new_opps: list[dict]) -> tuple[int, int]:
    """Upsert faculty records into processed/opportunities.json by id."""
    if not PROCESSED_FILE.exists():
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    new_opps, dropped = drop_joint_appointment_duplicates(new_opps, existing)
    if dropped:
        logger.info(f"Dropped {dropped} joint-appointment duplicate(s) before merge")
    from .uiuc_faculty import _carry_forward_enrichment

    index = {opp.get("id"): opp for opp in existing if opp.get("id")}
    added = updated = 0
    for opp in new_opps:
        if opp["id"] in index:
            cur = index[opp["id"]]
            opp["metadata"]["first_seen_at"] = cur.get(
                "metadata", {}).get("first_seen_at", opp["metadata"]["first_seen_at"])
            # Carry richer prior enrichment (keywords/title/description) forward
            # before the wholesale .update(), or a fresh broad re-scrape silently
            # clobbers it — the same guard the UIUC/faculty_graph merge paths use.
            # UCB isn't OpenAlex-enriched today, so this is latent, but it closes
            # the trap before Berkeley enrichment or a manual keyword edit lands.
            _carry_forward_enrichment(cur, opp)
            cur.update(opp)
            updated += 1
        else:
            existing.append(opp)
            index[opp["id"]] = opp
            added += 1
    # Faculty DQ pass over the full corpus (UIUC-aligned): a dept/coordinator
    # mailbox scraped onto 2+ professors, or a generic unit inbox, is nulled so
    # a re-scrape can't reintroduce a shared-email DQ failure or a misfiring
    # cold-email target — without hand-maintaining NOISE_EMAILS for each one.
    shared_nulled = _null_shared_contact_emails(existing)
    unit_nulled = _null_unit_mailbox_emails(existing)
    if shared_nulled or unit_nulled:
        logger.info(
            f"Nulled {shared_nulled} shared-mailbox + {unit_nulled} unit-mailbox "
            f"faculty contact email(s)"
        )
    derived = _derive_keywords_from_raw(existing)
    if derived:
        logger.info(f"Derived specific keywords for {derived} broad-only faculty from research_areas_raw")
    atomic_write_json(PROCESSED_FILE, existing)
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
