"""
Handshake opportunity collector (school-parameterized).

Scrapes research/internship postings from a school's Handshake instance using
cookie-based authentication. Handshake is login-gated PER SCHOOL: each school
has its own `<subdomain>.joinhandshake.com` and only shows postings to a
logged-in account at that school. So this collector targets one school at a
time, driven by a `--school` slug, and reads that school's session cookies from
`data/handshake_cookies_<slug>.json`. It is a MANUAL collector (cookies expire
in days and there is no headless login) — it is deliberately NOT wired into
refresh_all.

Add a school by adding an entry to HANDSHAKE_SCHOOLS (subdomain + source +
campus-city tokens) and a matching SOURCE_DEFAULTS entry. The school must have a
real logged-in session for any data to come back.

Auth flow (per school):
  1. Log into <subdomain>.joinhandshake.com in Chrome
  2. python -m src.collectors.handshake --school <slug> --export-cookies
  3. python -m src.collectors.handshake --school <slug> --save

Usage:
    python -m src.collectors.handshake --school uiuc --export-cookies
    python -m src.collectors.handshake --school ucb                 # preview
    python -m src.collectors.handshake --school ucb --save           # merge
"""

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Per-school Handshake config. `source` MUST have a matching SOURCE_DEFAULTS
# entry (UIUC keeps the legacy "handshake" source for backward compatibility;
# new schools use "handshake_<slug>"). `campus_cities` lowercase tokens decide
# the on_campus flag from a posting's location.
HANDSHAKE_SCHOOLS: dict[str, dict] = {
    "uiuc":  {"subdomain": "illinois", "source": "handshake",       "campus_cities": ("champaign", "urbana")},
    "ucb":   {"subdomain": "berkeley", "source": "handshake_ucb",   "campus_cities": ("berkeley",)},
    "umich": {"subdomain": "umich",    "source": "handshake_umich", "campus_cities": ("ann arbor",)},
}

SEARCH_PARAMS = {
    "category": "Posting",
    "ajax": "true",
    "including_all_facets_in_searches": "true",
    "page": 1,
    "per_page": 25,
    "sort_direction": "desc",
    "sort_column": "default",
}

RESEARCH_KEYWORDS = [
    "research assistant",
    "undergraduate research",
    "research intern",
    "lab assistant",
    "research associate",
    "data science research",
    "machine learning research",
]

CHROME_COOKIE_PATHS = {
    "darwin": Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies",
    "linux": Path.home() / ".config/google-chrome/Default/Cookies",
    "win32": Path.home() / "AppData/Local/Google/Chrome/User Data/Default/Network/Cookies",
}


def _resolve_school(slug: str) -> dict:
    """Resolve a school slug into a runtime config (base URL, cookie path, headers)."""
    if slug not in HANDSHAKE_SCHOOLS:
        raise ValueError(
            f"Unknown Handshake school {slug!r}. Known: {sorted(HANDSHAKE_SCHOOLS)}. "
            "Add it to HANDSHAKE_SCHOOLS (+ a SOURCE_DEFAULTS entry)."
        )
    cfg = HANDSHAKE_SCHOOLS[slug]
    base = f"https://{cfg['subdomain']}.joinhandshake.com"
    cookie = PROJECT_ROOT / "data" / f"handshake_cookies_{slug}.json"
    # Backward-compat: UIUC's pre-existing cookie file had no slug suffix.
    legacy = PROJECT_ROOT / "data" / "handshake_cookies.json"
    if slug == "uiuc" and not cookie.exists() and legacy.exists():
        cookie = legacy
    return {
        "slug": slug,
        "source": cfg["source"],
        "base_url": base,
        "search_url": f"{base}/stu/postings",
        "cookie_file": cookie,
        "campus_cities": tuple(c.lower() for c in cfg["campus_cities"]),
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{base}/stu/postings",
            "Origin": base,
        },
    }


def export_cookies_from_chrome(sch: dict) -> bool:
    """Extract this school's Handshake session cookies from Chrome's cookie DB."""
    cookie_db = CHROME_COOKIE_PATHS.get(sys.platform)
    if not cookie_db or not cookie_db.exists():
        logger.error(
            f"Chrome cookie database not found at {cookie_db}. "
            "Make sure Chrome is installed and you've logged into Handshake."
        )
        print("\nAlternative: manually export cookies using a browser extension:")
        print("  1. Install 'Cookie-Editor' extension in Chrome")
        print(f"  2. Go to {sch['base_url']} (make sure you're logged in)")
        print("  3. Click Cookie-Editor → Export → JSON")
        print(f"  4. Save to: {sch['cookie_file']}")
        return False

    tmp_db = PROJECT_ROOT / "data" / "_chrome_cookies_tmp.db"
    try:
        shutil.copy2(cookie_db, tmp_db)
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, value, host_key, path, is_secure, expires_utc "
            "FROM cookies WHERE host_key LIKE '%joinhandshake.com%'"
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            logger.warning("No Handshake cookies found in Chrome. Log in first.")
            return False

        cookies = [
            {"name": name, "value": value, "domain": domain, "path": path, "secure": bool(secure)}
            for name, value, domain, path, secure, expires in rows
        ]
        with open(sch["cookie_file"], "w") as f:
            json.dump(cookies, f, indent=2)
        logger.info(f"Exported {len(cookies)} Handshake cookies to {sch['cookie_file']}")
        return True
    except Exception as e:
        logger.error(f"Failed to export cookies: {e}")
        print("\nChrome may have the cookie DB locked. Try closing Chrome first.")
        print("Or use the manual cookie export method (Cookie-Editor extension).")
        return False
    finally:
        tmp_db.unlink(missing_ok=True)


def _load_session(sch: dict) -> requests.Session | None:
    """Create a requests session with this school's Handshake cookies."""
    if not sch["cookie_file"].exists():
        logger.error(
            f"No cookie file at {sch['cookie_file']}. Run with "
            f"--school {sch['slug']} --export-cookies first, or export manually."
        )
        return None

    with open(sch["cookie_file"]) as f:
        cookies = json.load(f)

    session = requests.Session()
    session.headers.update(sch["headers"])
    for c in cookies:
        session.cookies.set(
            c["name"], c.get("value", ""),
            domain=c.get("domain", ".joinhandshake.com"),
            path=c.get("path", "/"),
        )
    return session


def _verify_session(session: requests.Session, sch: dict) -> bool:
    """Check if the Handshake session is still valid for this school."""
    try:
        resp = session.get(f"{sch['base_url']}/stu/postings", params={
            "ajax": "true", "per_page": 1, "page": 1, "category": "Posting",
        }, timeout=10)
        if resp.status_code == 200:
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
            if data and "results" in data:
                logger.info(f"Handshake session valid for {sch['slug']}")
                return True
        if resp.status_code in (401, 403, 302):
            logger.error(f"Handshake session expired for {sch['slug']}. Re-login and re-export cookies.")
            return False
        logger.warning(f"Unexpected response: {resp.status_code}")
        return False
    except Exception as e:
        logger.error(f"Session check failed: {e}")
        return False


def search_postings(session: requests.Session, sch: dict,
                    query: str = "", job_type: str = "",
                    page: int = 1, per_page: int = 25) -> dict:
    """Search this school's Handshake postings with given filters."""
    params = {**SEARCH_PARAMS, "page": page, "per_page": per_page}
    if query:
        params["search"] = query
    if job_type:
        params["job_type_names[]"] = job_type
    try:
        resp = session.get(sch["search_url"], params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Search failed for query='{query}': {e}")
        return {}


def _parse_posting(result: dict, sch: dict) -> dict | None:
    """Parse a Handshake search result (result.job nested structure)."""
    job = result.get("job", {}) or {}
    title = job.get("title", "").strip()
    if not title:
        return None

    posting_id = str(result.get("id", ""))
    employer_name = job.get("employer_name", "Unknown")

    cities = job.get("location_cities", [])
    states = job.get("location_states", [])
    location = f"{cities[0]}, {states[0]}" if cities and states else "Unknown"

    job_type = job.get("job_type_name", "")
    is_internship = "intern" in job_type.lower() if job_type else False

    salary_info = ""
    sal_min = job.get("salary_min_raw", "")
    sal_max = job.get("salary_max_raw", "")
    pay_schedule = (job.get("pay_schedule") or {}).get("friendly_name", "")
    if sal_min or sal_max:
        if sal_min and sal_max:
            amount = f"${sal_min}" if sal_min == sal_max else f"${sal_min}-${sal_max}"
        else:
            amount = f"${sal_min or sal_max}"
        salary_info = _normalize_compensation(f"{amount} {pay_schedule}".strip())

    paid = job.get("salary_type_behavior_identifier", "")

    return {
        "handshake_id": posting_id,
        "title": title,
        "employer": employer_name,
        "location": location,
        "job_type": job_type,
        "deadline": result.get("expiration_date"),
        "start_date": job.get("start_date"),
        "posted_date": result.get("created_at"),
        "description": "",
        "salary": salary_info,
        "is_internship": is_internship,
        "paid": "yes" if paid == "Paid" else "unknown",
        "international_friendly": "unknown",
        "url": f"{sch['base_url']}/stu/postings/{posting_id}",
        "apply_url": "",
        "remote": job.get("remote", False),
        "on_site": job.get("on_site", False),
        "employer_id": job.get("employer_id"),
    }


def normalize_posting(raw: dict, sch: dict) -> dict:
    """Normalize a parsed Handshake posting to the opportunity schema."""
    from src.normalizers.enricher import enrich_opportunity

    pid = raw["handshake_id"]
    opp_id = f"{sch['source']}-{hashlib.md5(pid.encode()).hexdigest()[:8]}"
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()

    desc = raw.get("description", "")
    keywords = _extract_keywords(desc)
    loc = (raw.get("location") or "").lower()
    on_campus = any(city in loc for city in sch["campus_cities"])

    opp = {
        "id": opp_id,
        "source": sch["source"],
        "source_url": raw["url"],
        "source_type": "internship" if raw.get("is_internship") else "job",
        "title": raw["title"],
        "organization": raw["employer"],
        "department": "",
        "lab_or_program": raw["employer"],
        "pi_name": None,
        "contact_email": None,
        "url": raw["url"],
        "location": raw["location"],
        "on_campus": on_campus,
        "remote_option": "unknown",
        "opportunity_type": "internship" if raw.get("is_internship") else "research",
        "paid": raw.get("paid", "unknown"),
        "compensation_details": raw.get("salary", ""),
        "deadline": raw.get("deadline"),
        "posted_date": raw.get("posted_date"),
        "start_date": raw.get("start_date"),
        "duration": "",
        "eligibility": {
            "preferred_year": ["sophomore", "junior", "senior"],
            "min_gpa": None,
            "majors": [],
            "skills_required": [],
            "skills_preferred": [],
            # External postings carry no citizenship evidence here — None is
            # the explicit unknown, never an optimistic False (truthfulness W11).
            "citizenship_required": None,
            "international_friendly": raw.get("international_friendly", "unknown"),
            "work_auth_notes": "",
            "eligibility_text_raw": desc[:500],
        },
        "application": {
            "contact_method": "online",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": raw.get("apply_url") or raw["url"],
        },
        "description_raw": desc,
        "description_clean": desc[:1500],
        "keywords": keywords,
        "metadata": {
            "confidence_score": 0.8,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": f"Imported from {sch['slug']} Handshake (posting {pid})",
            "handshake_id": pid,
        },
    }
    return enrich_opportunity(opp)


def _normalize_compensation(raw: str) -> str:
    """Normalize a Handshake salary string for display. Handshake mislabels
    monthly research/internship stipends as "Per hour" (e.g. "$2250-$2250 Per
    hour" — $2250/hr is not a real undergrad wage) and emits redundant equal
    ranges. Collapse "$X-$X" to "$X" and drop an implausible "Per hour" label
    (amount >= $200/hr) so we never assert a wrong pay period. A plausible hourly
    rate ("$25 Per hour") and any other period (Per year/month) are left intact;
    returns "" for an empty value so the caller can fall back to the paid flag."""
    s = (raw or "").strip()
    if not s:
        return ""
    s = re.sub(r"\$(\d[\d,]*)-\$\1\b", r"$\1", s)  # "$2250-$2250" -> "$2250"
    m = re.search(r"\$(\d[\d,]*)", s)
    if m and int(m.group(1).replace(",", "")) >= 200 and re.search(r"\bper hour\b", s, re.I):
        s = re.sub(r"\s*\bper hour\b", "", s, flags=re.I).strip()
    return s


def _extract_keywords(text: str) -> list[str]:
    text_lower = text.lower()
    KEYWORD_BANK = [
        "machine learning", "deep learning", "computer vision", "data science",
        "artificial intelligence", "natural language processing", "robotics",
        "cybersecurity", "software engineering", "web development",
        "mobile development", "cloud computing", "database",
        "data analysis", "statistics", "bioinformatics",
        "embedded systems", "signal processing", "quantum computing",
    ]
    return [kw for kw in KEYWORD_BANK if kw in text_lower][:6]


def fetch_and_normalize(session: requests.Session, sch: dict,
                        queries: list[str] = None,
                        max_pages: int = 3) -> list[dict]:
    """Fetch research-related postings from a school's Handshake and normalize."""
    if queries is None:
        queries = RESEARCH_KEYWORDS

    all_opps = []
    seen_ids = set()

    for query in queries:
        for page in range(1, max_pages + 1):
            data = search_postings(session, sch, query=query, page=page, per_page=25)
            results = data.get("results", [])
            if not results:
                break
            for posting in results:
                raw = _parse_posting(posting, sch)
                if not raw or raw["handshake_id"] in seen_ids:
                    continue
                seen_ids.add(raw["handshake_id"])
                all_opps.append(normalize_posting(raw, sch))
            time.sleep(1.5)
        logger.info(f"  Query '{query}': {len(seen_ids)} unique so far")

    logger.info(f"Total {sch['slug']} Handshake opportunities: {len(all_opps)}")
    return all_opps


def merge_into_processed(new_opps: list[dict], filepath: str = None) -> tuple[int, int]:
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

    parser = argparse.ArgumentParser(description="Handshake Opportunity Collector")
    parser.add_argument("--school", default="uiuc",
                        help=f"School slug (default: uiuc). Known: {sorted(HANDSHAKE_SCHOOLS)}")
    parser.add_argument("--export-cookies", action="store_true",
                        help="Export this school's Handshake cookies from Chrome")
    parser.add_argument("--save", action="store_true",
                        help="Merge into processed/opportunities.json")
    parser.add_argument("--max-pages", type=int, default=3,
                        help="Max pages per search query (default: 3)")
    parser.add_argument("--query", type=str, default=None,
                        help="Custom search query (overrides defaults)")
    args = parser.parse_args()

    try:
        sch = _resolve_school(args.school)
    except ValueError as e:
        print(e)
        exit(1)

    if args.export_cookies:
        ok = export_cookies_from_chrome(sch)
        if ok:
            print(f"\nCookies exported to {sch['cookie_file']}")
            print(f"Now run: python -m src.collectors.handshake --school {sch['slug']}")
        else:
            print("\nCookie export failed. See instructions above.")
        exit(0 if ok else 1)

    session = _load_session(sch)
    if not session:
        print("\nNo cookies found. Run one of:")
        print(f"  python -m src.collectors.handshake --school {sch['slug']} --export-cookies")
        print(f"  Or manually save cookies to {sch['cookie_file']}")
        exit(1)

    if not _verify_session(session, sch):
        print(f"\nSession expired. Log into {sch['base_url']} in Chrome and re-export:")
        print(f"  python -m src.collectors.handshake --school {sch['slug']} --export-cookies")
        exit(1)

    queries = [args.query] if args.query else None
    opps = fetch_and_normalize(session, sch, queries=queries, max_pages=args.max_pages)

    print(f"\nFetched {len(opps)} opportunities from {sch['slug']} Handshake")
    for o in opps[:5]:
        print(f"\n  {o['title'][:65]}")
        print(f"    Employer: {o['organization']}")
        print(f"    Location: {o['location']}")
        print(f"    Keywords: {', '.join(o.get('keywords', []))}")

    if args.save and opps:
        added, updated = merge_into_processed(opps)
        print(f"\nSaved: {added} new, {updated} updated")
    elif not args.save:
        print("\n(Use --save to merge into processed/opportunities.json)")
