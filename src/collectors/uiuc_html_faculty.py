"""UIUC faculty from three HTML directories the campus JSON APIs don't cover:
Carle Illinois College of Medicine, the College of Law, and the School of Labor
& Employment Relations.

- **Carle** (`/about/directory/faculty/bio-translational-sciences`): `div.item.person`
  cards carry name + title + netid + email (mailto) **on the listing**, so no
  per-profile fetch. Only the bio-translational-sciences research faculty are
  taken — clinical-sciences (`cicom-clsci`, practicing physicians) are excluded
  on purpose, this being a research-opportunity index.
- **Law** (`/faculty/faculty-profiles/`): `article.faculty-member` (rendered
  twice for the responsive grid/list, deduped by profile URL); the email lives on
  each profile page, so faculty are enriched one profile at a time.
- **LER** (`/people/faculty/`): "Last, First" directory links; email **and**
  Research Interests live on each profile page.

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
LAW_URL = "https://law.illinois.edu/faculty/faculty-profiles/"
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


def _research_interests(soup) -> list[str]:
    """Phrases under a 'Research Interests' heading (LER profiles), atomized and
    capped. The faculty DQ does the final junk/fragment cleaning."""
    for tag in soup.find_all(["h2", "h3", "h4"]):
        if "research interest" in tag.get_text(strip=True).lower():
            block = tag.find_next(["ul", "p", "div"])
            if not block:
                return []
            items = [li.get_text(" ", strip=True) for li in block.select("li")]
            if not items:
                items = re.split(r"[;\n·•]|\s{2,}", block.get_text("\n", strip=True))
            out, seen = [], set()
            for it in items:
                it = it.strip(" .,;").strip()
                if 3 <= len(it) <= 60 and it.lower() not in seen:
                    seen.add(it.lower())
                    out.append(it)
                if len(out) >= 8:
                    break
            return out
    return []


def fetch_carle() -> list[dict]:
    """Carle bio-translational research faculty — listing carries email + netid,
    so no per-profile fetch."""
    soup = _fetch_soup(CARLE_URL)
    if soup is None:
        logger.error("Carle directory unreachable")
        return []
    out: list[dict] = []
    for card in soup.select("div.item.person"):
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
        rec = normalize_faculty(
            {
                "name": name,
                "email": email,
                "url": f"https://medicine.illinois.edu/about/directory/faculty/profile/{netid}"
                if netid else CARLE_URL,
                "title": title_el.get_text(strip=True) if title_el else "Professor",
                "research_areas": "biomedical sciences",
            },
            CARLE_CFG,
            keywords=list(CARLE_CFG["keywords"]),
        )
        if rec:
            out.append(rec)
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
        rec = normalize_faculty(
            {"name": name, "email": email, "url": url,
             "title": "Professor", "research_areas": "law"},
            LAW_CFG,
            keywords=list(LAW_CFG["keywords"]),
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


def fetch_and_normalize() -> list[dict]:
    """All three HTML-directory colleges, normalized. A failure for one is
    logged and skipped so one dead site can't sink the rest."""
    out: list[dict] = []
    for label, fn in (("Carle", fetch_carle), ("Law", fetch_law), ("LER", fetch_ler)):
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
