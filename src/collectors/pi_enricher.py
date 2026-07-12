"""
PI / Contact Email enricher.

Revisits SRO detail pages and UIUC department directories to fill in
pi_name and contact_email for existing opportunities.

Usage:
    python -m src.collectors.pi_enricher              # dry run
    python -m src.collectors.pi_enricher --save       # write to opportunities.json
"""

import json
import logging
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from src.normalizers.school_audience import SOURCE_DEFAULTS

from .ucb_common import _is_person_name

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"

HEADERS = {"User-Agent": "OpportunityFilterEngine/1.0 (educational project)"}
DELAY = 2

# school slug -> its institutional email/URL domains. Email recovery only ever
# accepts an address on the record's OWN school's domain (wrong-person guard:
# a personal Gmail or another university's address on the page is never a safe
# "Dear Prof. X" target), and the scrape gate only follows URLs on those
# domains (+ nsf.gov). Schools slugs match schools.ts / school_audience.
SCHOOL_EMAIL_DOMAINS: dict[str, tuple[str, ...]] = {
    "uiuc": ("illinois.edu",),
    "ucb": ("berkeley.edu",),
    "uw": ("washington.edu", "uw.edu"),
    "ucla": ("ucla.edu",),
    "utexas": ("utexas.edu",),
    "stanford": ("stanford.edu",),
    "gatech": ("gatech.edu",),
    "wisc": ("wisc.edu",),
    "umich": ("umich.edu",),
    "princeton": ("princeton.edu",),
    "ucsd": ("ucsd.edu",),
    "uchicago": ("uchicago.edu",),
    "uci": ("uci.edu",),
    "ucsb": ("ucsb.edu",),
    "boulder": ("colorado.edu",),
    "purdue": ("purdue.edu",),
    "duke": ("duke.edu",),
    "jhu": ("jhu.edu", "jh.edu", "jhmi.edu"),
    "northwestern": ("northwestern.edu", "u.northwestern.edu"),
    "upenn": ("upenn.edu",),
    "caltech": ("caltech.edu",),
    "cornell": ("cornell.edu",),
    "rice": ("rice.edu",),
    "vanderbilt": ("vanderbilt.edu",),
    "brown": ("brown.edu",),
    "dartmouth": ("dartmouth.edu",),
    "columbia": ("columbia.edu", "cumc.columbia.edu"),
}
# National records (school=None: SRO catalog, NSF REU, …) keep the historical
# UIUC-only recovery scope.
_DEFAULT_DOMAINS = ("illinois.edu",)


def _school_domains(opp: dict) -> tuple[str, ...]:
    """The record's own school's email/URL domains. Falls back from the stamped
    ``school`` field to the source registry (fresh records are stamped by
    apply_school_audience only AFTER this enricher runs in refresh_all)."""
    school = opp.get("school") or SOURCE_DEFAULTS.get(opp.get("source") or "", (None, ""))[0]
    return SCHOOL_EMAIL_DOMAINS.get(school, _DEFAULT_DOMAINS)


def _email_re(domains: tuple[str, ...]) -> re.Pattern:
    """Matches an address on one of ``domains`` incl. subdomains
    (jdoe@austin.utexas.edu), never a lookalike (myillinois.edu)."""
    alts = "|".join(re.escape(d) for d in domains)
    return re.compile(rf"[a-zA-Z0-9_.+-]+@(?:[a-zA-Z0-9-]+\.)*(?:{alts})\b")

# R70-B: emails extracted from BeautifulSoup whose local-part is the result
# of adjacent HTML-element concatenation (e.g. "265-4317nslack@illinois.edu"
# from `<strong>265-4317</strong><a>nslack@..</a>`) are garbage. Reject them
# so the regex extractor doesn't pollute contact_email.
#
# Two patterns observed across the 9 polluted manual records:
#   * Phone number prefix in local part: ``\d{3,4}-\d{3,4}`` anywhere.
#   * Capitalized label mashed into a lowercase address with no underscore
#     or further capital separator (e.g.
#     "Communicationsgrainger-marcom@illinois.edu"). The "no further capital"
#     constraint preserves legitimate CamelCase like
#     ``OluwatosinPopoola@uni.com`` and underscore-separated
#     ``Firstname_Lastname@uni.edu``.
_PHONE_IN_LOCAL = re.compile(r"^[^@]*\d{3,4}-\d{3,4}")
_CAPS_MASHED_LOCAL = re.compile(r"^[A-Z][a-z]+[^A-Z_@]{12,}@")


def _is_likely_real_email(email: str) -> bool:
    """Return True if the address doesn't look like a get_text() concat artifact.

    Conservative: only rejects clear corruption patterns we observed.
    Legitimate academic formats like ``Firstname_Lastname@uni.edu`` are kept.
    """
    if not email or "@" not in email:
        return False
    if _PHONE_IN_LOCAL.match(email):
        return False
    if _CAPS_MASHED_LOCAL.match(email):
        return False
    return True


def _fetch_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, timeout=12, headers=HEADERS)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def _extract_contact_from_sro(soup: BeautifulSoup, domains: tuple[str, ...] = _DEFAULT_DOMAINS) -> dict:
    result = {}

    contact_div = soup.select_one("div.field--name-field-contact-email-s-")
    if not contact_div:
        for div in soup.select("div.field"):
            label = div.select_one(".field__label")
            if label and "contact" in label.get_text(strip=True).lower():
                contact_div = div
                break

    if contact_div:
        item = contact_div.select_one(".field__item")
        if item:
            email_text = item.get_text(strip=True)
            emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", email_text)
            if emails:
                result["contact_email"] = emails[0]

    mentor_div = None
    for div in soup.select("div.field"):
        label = div.select_one(".field__label")
        if label:
            lt = label.get_text(strip=True).lower()
            if any(kw in lt for kw in ["mentor", "faculty", "pi", "advisor",
                                        "supervisor", "professor", "director"]):
                mentor_div = div
                break

    if mentor_div:
        item = mentor_div.select_one(".field__item")
        if item:
            name = item.get_text(strip=True)
            name = re.sub(r"(?i)^(dr\.?|prof\.?|professor)\s*", "", name).strip()
            if name and len(name) < 60 and "@" not in name:
                result["pi_name"] = name

    if "contact_email" not in result:
        # R70-B: separator=" " prevents adjacent HTML elements from concatenating
        # into a single token. Without it, `<strong>265-4317</strong><a>nslack@..</a>`
        # collapses to "265-4317nslack@.." and the regex extracts a corrupted address.
        full_text = soup.get_text(separator=" ", strip=True)
        emails = _email_re(domains).findall(full_text)
        filtered = [e for e in emails if e != "ugresearch@illinois.edu" and _is_likely_real_email(e)]
        if filtered:
            result["contact_email"] = filtered[0]

    return result


def _infer_pi_from_lab(lab_name: str) -> str | None:
    patterns = [
        r"(?:Prof(?:essor)?\.?\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(?:Lab|Group|Research Group|Laboratory)",
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:Lab|Group|Research Group|Laboratory)\b",
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'s\s+(?:Lab|Group|Research)",
    ]
    generic = {"research", "computing", "computer", "advanced", "applied",
               "center", "institute", "systems", "data", "machine",
               "science", "undergraduate", "engineering", "physics",
               "chemistry", "biology", "summer", "program", "national",
               "photonic", "cognitive", "language", "quantum", "medical",
               "visual", "autonomous", "intelligent", "computational",
               "parallel", "distributed", "interactive", "information",
               "social", "natural", "human", "signal", "control", "power",
               "digital", "analog", "wireless", "optical", "network"}
    for p in patterns:
        m = re.search(p, lab_name)
        if m:
            candidate = m.group(1).strip()
            words = candidate.lower().split()
            if all(w not in generic for w in words) and len(candidate) > 2:
                return candidate
    return None


NOISE_EMAILS = {
    "ugresearch@illinois.edu", "webmaster@illinois.edu",
    "admissions@illinois.edu", "registrar@illinois.edu",
    "engineering@illinois.edu", "grainger@illinois.edu",
}


def _extract_contact_from_generic_page(soup: BeautifulSoup, domains: tuple[str, ...] = _DEFAULT_DOMAINS) -> dict:
    result = {}
    # R70-B: separator=" " prevents adjacent HTML elements from concatenating
    # into a single token. Without it the regex picks up phone+name+email
    # mashed together as one "email".
    text = soup.get_text(separator=" ", strip=True)

    school_emails = _email_re(domains).findall(text)
    personal = [
        e for e in school_emails
        if e not in NOISE_EMAILS and _is_likely_real_email(e)
    ]
    if personal:
        result["contact_email"] = personal[0]

    if "contact_email" not in result:
        for tag in soup.select("a[href^='mailto:']"):
            href = tag.get("href", "")
            email = href.replace("mailto:", "").split("?")[0].strip()
            if (
                email
                and "@" in email
                and email not in NOISE_EMAILS
                and _is_likely_real_email(email)
            ):
                result["contact_email"] = email
                break

    for el in soup.select("h2, h3, h4, .field__label, dt, strong, b"):
        label = el.get_text(strip=True).lower()
        if any(kw in label for kw in ["contact", "advisor", "mentor",
                                       "faculty", "pi", "director", "coordinator"]):
            sibling = el.find_next_sibling()
            if sibling:
                stext = sibling.get_text(strip=True)
                se = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", stext)
                if se:
                    result.setdefault("contact_email", se[0])
                name_part = re.sub(r"[^a-zA-Z\s.'-]", "", stext).strip()
                if (name_part and 3 < len(name_part) < 50
                        and "@" not in name_part and name_part[0].isupper()):
                    result.setdefault("pi_name", name_part.split("\n")[0].strip())

    return result


def _is_ucb_program_record(opp: dict) -> bool:
    """True for a UC Berkeley program/project/lab posting — a ``ucb_*`` record
    that is NOT an individual faculty directory profile (``source_type`` other
    than ``faculty_research``): URAP projects (``ucb_urap_projects``), research
    programs, external-research links, lab-recruiting pages (``ucb_campus``).

    These apply through a website portal (``contact_method="website"``,
    ``application_url`` = the portal) and deliberately carry ``pi_name=None`` /
    ``contact_email=None``: there is no single "Dear Prof. X" cold-email target.
    Scraping their berkeley.edu page grabs whatever address is on it — the
    supervising professor's PERSONAL email (which then collides with that same
    professor's own faculty record) or a shared department admin inbox (surf@,
    cdssinfo@, mcbuao@, ccinternships@) reused across many postings. Either way
    it trips the ucb_* no-shared-email data-quality gate
    (test_no_ucb_joint_appointment_duplicates) and is the wrong contact for a
    portal application, so the enricher must leave these records untouched."""
    return (opp.get("source") or "").startswith("ucb_") \
        and opp.get("source_type") != "faculty_research"


def enrich_opportunities(opps: list[dict], save: bool = False,
                         max_scrapes: int | None = None) -> dict:
    stats = {"total": len(opps), "already_has_email": 0, "enriched": 0,
             "scraped": 0, "inferred_pi": 0, "failed": 0, "skipped_budget": 0,
             "skipped_program": 0}

    for i, opp in enumerate(opps):
        if opp.get("contact_email"):
            stats["already_has_email"] += 1
            continue
        # UC Berkeley program/project/lab postings have no per-person cold-email
        # target (see _is_ucb_program_record). Leave contact_email/pi_name as the
        # collector set them (None) instead of scraping an arbitrary berkeley.edu
        # address off their page — that address collides with the supervising
        # professor's faculty record / other postings and fails the ucb_* dedup
        # gate, and is the wrong contact for a portal application anyway.
        if _is_ucb_program_record(opp):
            stats["skipped_program"] += 1
            continue

        enriched = False
        url = opp.get("url", "")
        domains = _school_domains(opp)
        if opp.get("source") == "uiuc_sro" and url.startswith("https://researchops"):
            scrapeable, extract = True, _extract_contact_from_sro
        else:
            scrapeable = bool(url) and (any(d in url for d in domains) or "nsf.gov" in url)
            extract = _extract_contact_from_generic_page

        if scrapeable and max_scrapes is not None and stats["scraped"] >= max_scrapes:
            stats["skipped_budget"] += 1
        elif scrapeable:
            soup = _fetch_soup(url)
            stats["scraped"] += 1
            if soup:
                info = extract(soup, domains)
                if info.get("contact_email"):
                    opp["contact_email"] = info["contact_email"]
                    enriched = True
                # Guard with _is_person_name: a scraped/derived "name" that is
                # really an institution/place ("Berkeley", "UC Berkeley") must
                # never become a pi_name — two such records collide on the
                # ucb_* joint-appointment data-quality gate and block the refresh.
                if info.get("pi_name") and not opp.get("pi_name") and _is_person_name(info["pi_name"]):
                    opp["pi_name"] = info["pi_name"]
            time.sleep(DELAY)

        if not opp.get("pi_name"):
            lab = opp.get("lab_or_program", "")
            pi = _infer_pi_from_lab(lab)
            # e.g. "Berkeley Lab SULI" -> "Berkeley"; reject institution/place names.
            if pi and _is_person_name(pi):
                opp["pi_name"] = pi
                stats["inferred_pi"] += 1

        if enriched:
            stats["enriched"] += 1
        elif not opp.get("contact_email"):
            stats["failed"] += 1

        if (i + 1) % 20 == 0:
            logger.info(f"Progress: {i+1}/{len(opps)} processed, {stats['enriched']} enriched")

    if save:
        with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
            json.dump(opps, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved {len(opps)} opportunities to {PROCESSED_FILE}")

    return stats


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Enrich opportunities with PI/contact info")
    parser.add_argument("--save", action="store_true", help="Write enriched data back to file")
    parser.add_argument("--limit", type=int, default=None, help="Max opportunities to process")
    args = parser.parse_args()

    with open(PROCESSED_FILE, encoding="utf-8") as f:
        opps = json.load(f)

    if args.limit:
        opps_to_process = opps[:args.limit]
    else:
        opps_to_process = opps

    stats = enrich_opportunities(opps_to_process, save=args.save)

    print(f"\n{'='*50}")
    print("PI ENRICHER RESULTS")
    print(f"{'='*50}")
    print(f"Total opportunities:   {stats['total']}")
    print(f"Already had email:     {stats['already_has_email']}")
    print(f"Pages scraped:         {stats['scraped']}")
    print(f"Successfully enriched: {stats['enriched']}")
    print(f"PI inferred from lab:  {stats['inferred_pi']}")
    print(f"No contact found:      {stats['failed']}")
    if not args.save:
        print("\n(Use --save to write enriched data back to file)")
