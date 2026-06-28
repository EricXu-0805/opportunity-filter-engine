"""UIUC faculty from three HTML directories the campus JSON APIs don't cover:
Carle Illinois College of Medicine, the College of Law, and the School of Labor
& Employment Relations.

- **Carle** (`/about/directory/faculty/bio-translational-sciences`): `div.item.person`
  cards carry name + title + netid + email (mailto) **on the listing**, but each
  profile page lists the person's own Research Interests, so a per-profile fetch
  enriches the otherwise broad-field-only record. Only the bio-translational-
  sciences research faculty are taken — clinical-sciences (`cicom-clsci`,
  practicing physicians) are excluded on purpose, this being a research index.
- **Law** (`/faculty-research/faculty-profiles/`): `article.faculty-member`
  (rendered twice for the responsive grid/list, deduped by profile URL); the
  email **and** an "Areas of Expertise" disclosure live on each profile page, so
  faculty are enriched one profile at a time.
- **LER** (`/people/faculty/`): "Last, First" directory links; email **and**
  Research Interests live on each profile page.

Listings expose only a name + a department broad field, so a faculty member's own
research areas come from the profile page (see :func:`_labeled_phrases`); a
profile that has no such section (or describes its work in prose) honestly falls
back to the department broad field rather than inventing keywords.

All reuse :func:`uiuc_faculty.normalize_faculty` (identical schema,
``source="uiuc_faculty"``) and merge through
:func:`uiuc_faculty.merge_into_processed`, so cross-college email dedup, the
faculty DQ sequence, and source-keyed school/audience tagging apply unchanged.
"""

from __future__ import annotations

import logging
import re
import time

from .uiuc_faculty import (
    DELAY,
    _clean_name,
    _fetch_soup,
    normalize_faculty,
)

logger = logging.getLogger(__name__)

CARLE_URL = (
    "https://medicine.illinois.edu/about/directory/faculty/bio-translational-sciences"
)
CARLE_PROFILE = "https://medicine.illinois.edu/about/directory/faculty/profile/{netid}"
LAW_URL = "https://law.illinois.edu/faculty-research/faculty-profiles/"
LER_URL = "https://ler.illinois.edu/people/faculty/"

CARLE_CFG = {
    "short": "Carle Medicine",
    "name": "Carle Illinois College of Medicine",
    "majors": ["Bioengineering", "Neuroscience", "Biology",
               "Molecular & Cellular Biology", "Biochemistry", "Public Health"],
    "keywords": ["biomedical sciences"],
}
LAW_CFG = {
    "short": "Law",
    "name": "College of Law",
    "majors": ["Law", "Pre-Law", "Political Science"],
    "keywords": ["law"],
}
LER_CFG = {
    "short": "LER",
    "name": "School of Labor and Employment Relations",
    "majors": ["Labor and Employment Relations", "Human Resource Management",
               "Industrial Relations"],
    "keywords": ["labor and employment relations"],
}


def _first_illinois_email(soup) -> str:
    """First ``@illinois.edu`` mailto on a profile page. Shared-assistant/unit
    inboxes that slip through are nulled later by the faculty DQ."""
    for a in soup.select('a[href^="mailto:"]'):
        addr = a.get("href", "")[7:].split("?")[0].strip().lower()
        if addr.endswith("@illinois.edu"):
            return addr
    return ""


# Headings (or `<summary>` disclosures) under which a UIUC profile lists the
# person's own research areas. Colleges label the same thing differently —
# "Research Interests" (LER, Carle), "Areas of Expertise" (Law) — so one label
# set covers them and every profile collector reuses _labeled_phrases.
_RESEARCH_LABEL_RE = re.compile(
    r"research interest|research area|research focus"
    r"|areas? of expertise|areas? of research|area of (study|interest)",
    re.I,
)

# When comma-splitting a block (Gies), a profile that wrote prose rather than a
# list shatters into sentence fragments. A real research area is a short noun
# phrase; the tell-tale junk is a clause that opens with a connective/preposition
# or runs long. (Only applied with split_commas — Law's <br>-separated areas can
# legitimately be a 7-word phrase that opens with a content word.)
_FRAGMENT_PREFIX = re.compile(
    r"^(and|or|but|to|the|an?|of|in|on|for|with|by|as|at|is|are|was|were|this|that|these|those"
    r"|currently|including|such|etc|particularly|also|which|where|when|while|his|her|their|its)\b",
    re.I,
)
# Some profiles list publication venues under "Research Interests"; a journal
# title is not a topic. No business research area contains these whole words.
_VENUE_RE = re.compile(r"\b(journal|proceedings)\b", re.I)


def _labeled_phrases(soup, label_re=_RESEARCH_LABEL_RE, split_commas=False) -> list[str]:
    """Atomized phrases from the block after the first heading/`<summary>` whose
    text matches ``label_re`` — list items if present, else the block text split
    on separators (';', line breaks from `<br>`, bullets). Prose sentences fall
    outside the length guard, so a profile that describes its research in
    paragraphs yields nothing and the caller falls back to the broad field rather
    than inventing keywords. ``split_commas`` also breaks on commas — opt-in for
    sources (Gies) that list several areas comma-joined on one line, where Law's
    multi-word single areas ("Civil Procedure, …" as one phrase) aren't a concern.
    Sub-labels like "Methods:" / "Applications:" are dropped. Capped; the faculty
    DQ does the final cleaning."""
    sep = r"[;,\n·•]|\s{2,}" if split_commas else r"[;\n·•]|\s{2,}"
    for tag in soup.find_all(["h2", "h3", "h4", "summary"]):
        if label_re.search(tag.get_text(strip=True)):
            block = tag.find_next(["ul", "p", "div"])
            if not block:
                return []
            items = [li.get_text(" ", strip=True) for li in block.select("li")]
            if not items:
                items = re.split(sep, block.get_text("\n", strip=True))
            out, seen = [], set()
            for it in items:
                it = it.strip(" .,;").strip()
                if not (3 <= len(it) <= 60) or it.lower() in seen:
                    continue
                if label_re.search(it) or it.endswith(":"):  # leaked section / sub-label
                    continue
                if split_commas and (
                    not it[:1].isalnum()             # leading », - etc.
                    or len(it.split()) > 6            # a prose clause, not an area
                    or _FRAGMENT_PREFIX.match(it)     # tail of a split sentence
                    or _VENUE_RE.search(it)           # a journal name, not a topic
                ):
                    continue
                seen.add(it.lower())
                out.append(it)
                if len(out) >= 8:
                    break
            return out
    return []


def _research_interests(soup) -> list[str]:
    """LER profiles label their block 'Research Interests'; alias kept for clarity
    at the call site."""
    return _labeled_phrases(soup)


def fetch_carle() -> list[dict]:
    """Carle bio-translational research faculty — name + email + netid on the
    listing; each profile page's Research Interests enrich the broad-field record
    (no section -> fall back to the broad field)."""
    soup = _fetch_soup(CARLE_URL)
    if soup is None:
        logger.error("Carle directory unreachable")
        return []
    cards = soup.select("div.item.person")
    out: list[dict] = []
    for i, card in enumerate(cards):
        name_el = card.select_one(".name")
        if not name_el:
            continue
        name = _clean_name(re.sub(r"\s+", " ", name_el.get_text(strip=True)))
        if not name:
            continue
        title_el = card.select_one(".title")
        mail = card.select_one('a[href^="mailto:"]')
        netid = card.get("data-netid") or ""
        email = (mail["href"][7:].split("?")[0].strip() if mail else "") or (
            f"{netid}@illinois.edu" if netid else ""
        )
        url = CARLE_PROFILE.format(netid=netid) if netid else CARLE_URL
        prof = _fetch_soup(url) if netid else None
        kws = (_labeled_phrases(prof) if prof else []) or list(CARLE_CFG["keywords"])
        rec = normalize_faculty(
            {
                "name": name,
                "email": email,
                "url": url,
                "title": title_el.get_text(strip=True) if title_el else "Professor",
                "research_areas": "; ".join(kws),
            },
            CARLE_CFG,
            keywords=kws,
        )
        if rec:
            out.append(rec)
        if netid and i < len(cards) - 1:
            time.sleep(DELAY)
    logger.info(f"Carle Medicine: {len(out)} bio-translational faculty")
    return out


def fetch_law() -> list[dict]:
    """College of Law faculty — name on the listing, email per profile page."""
    soup = _fetch_soup(LAW_URL)
    if soup is None:
        logger.error("Law directory unreachable")
        return []
    profiles: dict[str, str] = {}
    for art in soup.select("article.faculty-member"):
        h2 = art.select_one("h2")
        link = art.find("a", href=True)
        if h2 and link and "/faculty-profiles/" in link["href"]:
            profiles.setdefault(link["href"], h2.get_text(strip=True))
    out: list[dict] = []
    for i, (url, name) in enumerate(profiles.items()):
        name = _clean_name(name)
        if not name:
            continue
        prof = _fetch_soup(url)
        email = _first_illinois_email(prof) if prof else ""
        kws = (_labeled_phrases(prof) if prof else []) or list(LAW_CFG["keywords"])
        rec = normalize_faculty(
            {"name": name, "email": email, "url": url,
             "title": "Professor", "research_areas": "; ".join(kws)},
            LAW_CFG,
            keywords=kws,
        )
        if rec:
            out.append(rec)
        if i < len(profiles) - 1:
            time.sleep(DELAY)
    logger.info(f"College of Law: {len(out)} faculty")
    return out


def fetch_ler() -> list[dict]:
    """LER faculty — 'Last, First' listing links; email + Research Interests per
    profile page."""
    soup = _fetch_soup(LER_URL)
    if soup is None:
        logger.error("LER directory unreachable")
        return []
    seen: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        if "/directory/" not in a["href"]:
            continue
        text = a.get_text(strip=True)
        if not text or "," not in text:
            continue
        last, first = (p.strip() for p in text.split(",", 1))
        href = a["href"]
        if href.startswith("/"):
            href = "https://ler.illinois.edu" + href
        seen.setdefault(href, f"{first} {last}")
    out: list[dict] = []
    for i, (url, name) in enumerate(seen.items()):
        name = _clean_name(name)
        if not name:
            continue
        prof = _fetch_soup(url)
        email = _first_illinois_email(prof) if prof else ""
        areas = _research_interests(prof) if prof else []
        kws = areas or list(LER_CFG["keywords"])
        rec = normalize_faculty(
            {"name": name, "email": email, "url": url, "title": "Professor",
             "research_areas": "; ".join(kws)},
            LER_CFG,
            keywords=kws,
        )
        if rec:
            out.append(rec)
        if i < len(seen) - 1:
            time.sleep(DELAY)
    logger.info(f"School of Labor & Employment Relations: {len(out)} faculty")
    return out


# ── Fine & Applied Arts (Music, Architecture, Art & Design) ──────────────────
# Uniform Drupal `article.person-card` listing, paginated `…/page/N/`, with name
# + title + email (mailto) on the card — no per-profile fetch.
FAA_UNITS = [
    {"short": "Music", "name": "School of Music", "base": "https://music.illinois.edu",
     "path": "/people/faculty/",
     "majors": ["Music", "Music Composition", "Musicology", "Music Education",
                "Music Performance"], "keywords": ["music"]},
    {"short": "Architecture", "name": "School of Architecture",
     "base": "https://arch.illinois.edu", "path": "/about/faculty-directory/",
     "majors": ["Architecture", "Sustainable Design", "Urban Design"],
     "keywords": ["architecture"]},
    {"short": "Art & Design", "name": "School of Art and Design",
     "base": "https://art.illinois.edu", "path": "/about/faculty-directory/",
     "majors": ["Art", "Graphic Design", "Industrial Design", "Studio Art",
                "Art History", "Art Education"], "keywords": ["art and design"]},
]


def _faa_card(card, unit: dict) -> dict | None:
    h2 = card.select_one("h2.linked-title") or card.select_one("h2")
    if not h2:
        return None
    name = _clean_name(h2.get_text(strip=True))
    if not name:
        return None
    link = card.select_one("a.linked-title__link") or h2.find("a")
    url = link["href"] if link and link.get("href") else unit["base"] + unit["path"]
    mail = card.select_one('a[href^="mailto:"]')
    email = mail["href"][7:].split("?")[0].strip() if mail else ""
    info = card.select_one(".person-card__info")
    title = "Professor"
    if info:
        t = info.get_text(" ", strip=True).replace(name, "", 1)
        t = re.split(r"\S+@\S+", t)[0].strip(" |·–-")
        title = t[:80] or "Professor"
    return normalize_faculty(
        {"name": name, "email": email, "url": url, "title": title,
         "research_areas": unit["keywords"][0]},
        {"short": unit["short"], "name": unit["name"],
         "majors": unit["majors"], "keywords": unit["keywords"]},
        keywords=list(unit["keywords"]),
    )


def fetch_faa() -> list[dict]:
    out: list[dict] = []
    for unit in FAA_UNITS:
        n0 = len(out)
        for page in range(1, 16):
            url = unit["base"] + unit["path"] + ("" if page == 1 else f"page/{page}/")
            soup = _fetch_soup(url)
            cards = soup.select("article.person-card") if soup else []
            if not cards:
                break
            for card in cards:
                rec = _faa_card(card, unit)
                if rec:
                    out.append(rec)
            time.sleep(DELAY)
        logger.info(f"{unit['short']}: {len(out) - n0} faculty")
    return out


# ── College of Media (Advertising, Journalism, Media & Cinema Studies) ───────
# WordPress Content-Views grid `div.pt-cv-content-item`; name + profile link on
# the listing, email per profile page. (ICR has no standalone faculty page — its
# faculty are cross-listed from other departments.)
MEDIA_UNITS = [
    {"slug": "advertising", "name": "Department of Advertising",
     "majors": ["Advertising", "Communication"], "keywords": ["advertising"]},
    {"slug": "journalism", "name": "Department of Journalism",
     "majors": ["Journalism", "Communication"], "keywords": ["journalism"]},
    {"slug": "media-and-cinema-studies", "name": "Department of Media and Cinema Studies",
     "majors": ["Media and Cinema Studies", "Communication"],
     "keywords": ["media and cinema studies"]},
]


def fetch_media() -> list[dict]:
    out: list[dict] = []
    for unit in MEDIA_UNITS:
        soup = _fetch_soup(f"https://media.illinois.edu/{unit['slug']}-faculty/")
        items = soup.select("div.pt-cv-content-item") if soup else []
        n0 = len(out)
        for i, item in enumerate(items):
            a = item.select_one("h4.pt-cv-title a")
            if not a:
                continue
            name = _clean_name(a.get_text(strip=True))
            if not name:
                continue
            url = a.get("href", "")
            prof = _fetch_soup(url) if url else None
            email = _first_illinois_email(prof) if prof else ""
            rec = normalize_faculty(
                {"name": name, "email": email, "url": url, "title": "Professor",
                 "research_areas": unit["keywords"][0]},
                {"short": "Media", "name": unit["name"],
                 "majors": unit["majors"], "keywords": unit["keywords"]},
                keywords=list(unit["keywords"]),
            )
            if rec:
                out.append(rec)
            if i < len(items) - 1:
                time.sleep(DELAY)
        logger.info(f"Media/{unit['slug']}: {len(out) - n0} faculty")
    return out


# ── College of Veterinary Medicine ───────────────────────────────────────────
# `div.person-teaser` with the email obfuscated in an `img[data-src]` attribute
# (no mailto); name + title in the heading text, joined by an en dash.
VETMED_UNITS = [
    {"path": "veterinary-clinical-medicine/faculty",
     "name": "Department of Veterinary Clinical Medicine",
     "majors": ["Veterinary Medicine", "Animal Sciences", "Biology"],
     "keywords": ["veterinary clinical medicine"]},
    {"path": "pathobiology/faculty7",
     "name": "Department of Pathobiology",
     "majors": ["Veterinary Medicine", "Pathobiology", "Microbiology", "Biology"],
     "keywords": ["pathobiology"]},
    {"path": "comparative-biosciences/faculty",
     "name": "Department of Comparative Biosciences",
     "majors": ["Veterinary Medicine", "Comparative Biosciences", "Neuroscience",
                "Biology"], "keywords": ["comparative biosciences"]},
]


def fetch_vetmed() -> list[dict]:
    out: list[dict] = []
    for unit in VETMED_UNITS:
        soup = _fetch_soup(f"https://vetmed.illinois.edu/about-the-college/{unit['path']}/")
        teasers = soup.select("div.person-teaser") if soup else []
        n0 = len(out)
        for t in teasers:
            heading = t.get_text(" ", strip=True)
            parts = re.split(r"[–—]|\s-\s", heading, maxsplit=1)
            name = _clean_name(parts[0])
            if not name:
                continue
            title = parts[1].strip()[:80] if len(parts) > 1 else "Professor"
            email = next((i.get("data-src") for i in t.select("img")
                          if i.get("data-src", "").endswith("@illinois.edu")), "")
            link = t.find("a", href=True)
            url = link["href"] if link else ""
            if url.startswith("/"):
                url = "https://vetmed.illinois.edu" + url
            rec = normalize_faculty(
                {"name": name, "email": email, "url": url,
                 "title": title or "Professor", "research_areas": unit["keywords"][0]},
                {"short": "VetMed", "name": unit["name"],
                 "majors": unit["majors"], "keywords": unit["keywords"]},
                keywords=list(unit["keywords"]),
            )
            if rec:
                out.append(rec)
        logger.info(f"VetMed/{unit['path'].split('/')[0]}: {len(out) - n0} faculty")
    return out


def fetch_and_normalize() -> list[dict]:
    """All HTML-directory colleges, normalized. A failure for one is logged and
    skipped so one dead site can't sink the rest."""
    out: list[dict] = []
    for label, fn in (
        ("Carle", fetch_carle), ("Law", fetch_law), ("LER", fetch_ler),
        ("FAA", fetch_faa), ("Media", fetch_media), ("VetMed", fetch_vetmed),
    ):
        try:
            out.extend(fn())
        except Exception as e:
            logger.error(f"HTML faculty fetch failed for {label}: {e}")
    logger.info(f"Total HTML-directory faculty: {len(out)}")
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    opps = fetch_and_normalize()
    print(f"\nFetched {len(opps)} HTML-directory faculty")
    for o in opps[:8]:
        print(f"  {o['title'][:66]}  [{o['department']}]  {o.get('contact_email')}")
