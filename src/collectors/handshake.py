"""
Handshake opportunity collector.

Scrapes research opportunities and internships from Handshake
using cookie-based authentication. Requires a valid Handshake session.

Auth flow:
  1. Log into app.joinhandshake.com in Chrome
  2. Run: python -m src.collectors.handshake --export-cookies
     (copies cookies from Chrome → data/handshake_cookies.json)
  3. Run: python -m src.collectors.handshake --save

Usage:
    python -m src.collectors.handshake --export-cookies   # extract cookies from Chrome
    python -m src.collectors.handshake                    # preview results
    python -m src.collectors.handshake --save             # merge into opportunities.json
"""

import hashlib
import json
import logging
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
COOKIE_FILE = PROJECT_ROOT / "data" / "handshake_cookies.json"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://illinois.joinhandshake.com"
SEARCH_URL = f"{BASE_URL}/stu/postings"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_URL}/stu/postings",
    "Origin": BASE_URL,
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


def export_cookies_from_chrome() -> bool:
    """Extract Handshake session cookies from Chrome's cookie database."""
    cookie_db = CHROME_COOKIE_PATHS.get(sys.platform)
    if not cookie_db or not cookie_db.exists():
        logger.error(
            f"Chrome cookie database not found at {cookie_db}. "
            "Make sure Chrome is installed and you've logged into Handshake."
        )
        print("\nAlternative: manually export cookies using a browser extension:")
        print("  1. Install 'Cookie-Editor' extension in Chrome")
        print("  2. Go to app.joinhandshake.com (make sure you're logged in)")
        print("  3. Click Cookie-Editor → Export → JSON")
        print(f"  4. Save to: {COOKIE_FILE}")
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

        cookies = []
        for name, value, domain, path, secure, expires in rows:
            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "secure": bool(secure),
            })

        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f, indent=2)

        logger.info(f"Exported {len(cookies)} Handshake cookies to {COOKIE_FILE}")
        return True

    except Exception as e:
        logger.error(f"Failed to export cookies: {e}")
        print("\nChrome may have the cookie DB locked. Try closing Chrome first.")
        print("Or use the manual cookie export method (Cookie-Editor extension).")
        return False
    finally:
        tmp_db.unlink(missing_ok=True)


def _load_session() -> Optional[requests.Session]:
    """Create a requests session with Handshake cookies."""
    if not COOKIE_FILE.exists():
        logger.error(
            f"No cookie file at {COOKIE_FILE}. "
            "Run with --export-cookies first, or manually export cookies."
        )
        return None

    with open(COOKIE_FILE) as f:
        cookies = json.load(f)

    session = requests.Session()
    session.headers.update(HEADERS)

    for c in cookies:
        session.cookies.set(
            c["name"], c.get("value", ""),
            domain=c.get("domain", ".joinhandshake.com"),
            path=c.get("path", "/"),
        )

    return session


def _verify_session(session: requests.Session) -> bool:
    """Check if the Handshake session is still valid."""
    try:
        resp = session.get(f"{BASE_URL}/stu/postings", params={
            "ajax": "true", "per_page": 1, "page": 1,
            "category": "Posting",
        }, timeout=10)
        if resp.status_code == 200:
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
            if data and "results" in data:
                logger.info("Handshake session is valid")
                return True
        if resp.status_code in (401, 403, 302):
            logger.error("Handshake session expired. Re-login and re-export cookies.")
            return False
        logger.warning(f"Unexpected response: {resp.status_code}")
        return False
    except Exception as e:
        logger.error(f"Session check failed: {e}")
        return False


def search_postings(session: requests.Session,
                    query: str = "",
                    job_type: str = "",
                    page: int = 1,
                    per_page: int = 25) -> dict:
    """Search Handshake postings with given filters."""
    params = {
        **SEARCH_PARAMS,
        "page": page,
        "per_page": per_page,
    }
    if query:
        params["search"] = query
    if job_type:
        params["job_type_names[]"] = job_type

    try:
        resp = session.get(SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Search failed for query='{query}': {e}")
        return {}


def _parse_posting(result: dict) -> Optional[dict]:
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

    deadline = result.get("expiration_date")
    start_date = job.get("start_date")
    posted = result.get("created_at")

    job_type = job.get("job_type_name", "")
    is_internship = "intern" in job_type.lower() if job_type else False

    salary_info = ""
    sal_min = job.get("salary_min_raw", "")
    sal_max = job.get("salary_max_raw", "")
    pay_schedule = (job.get("pay_schedule") or {}).get("friendly_name", "")
    if sal_min or sal_max:
        salary_info = f"${sal_min}-${sal_max} {pay_schedule}".strip()

    paid = job.get("salary_type_behavior_identifier", "")

    return {
        "handshake_id": posting_id,
        "title": title,
        "employer": employer_name,
        "location": location,
        "job_type": job_type,
        "deadline": deadline,
        "start_date": start_date,
        "posted_date": posted,
        "description": "",
        "salary": salary_info,
        "is_internship": is_internship,
        "paid": "yes" if paid == "Paid" else "unknown",
        "international_friendly": "unknown",
        "url": f"{BASE_URL}/stu/postings/{posting_id}",
        "apply_url": "",
        "remote": job.get("remote", False),
        "on_site": job.get("on_site", False),
        "employer_id": job.get("employer_id"),
    }


def normalize_posting(raw: dict) -> dict:
    """Normalize a parsed Handshake posting to the opportunity schema."""
    from src.normalizers.enricher import enrich_opportunity

    pid = raw["handshake_id"]
    opp_id = f"handshake-{hashlib.md5(pid.encode()).hexdigest()[:8]}"
    now = datetime.utcnow().isoformat()

    desc = raw.get("description", "")
    keywords = _extract_keywords(desc)

    paid = raw.get("paid", "unknown")

    opp = {
        "id": opp_id,
        "source": "handshake",
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
        "on_campus": "champaign" in raw["location"].lower() or "urbana" in raw["location"].lower(),
        "remote_option": "unknown",
        "opportunity_type": "internship" if raw.get("is_internship") else "research",
        "paid": paid,
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
            "citizenship_required": False,
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
        "description_clean": desc[:500],
        "keywords": keywords,
        "metadata": {
            "confidence_score": 0.8,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": f"Imported from Handshake (posting {pid})",
            "handshake_id": pid,
        },
    }
    return enrich_opportunity(opp)


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


def fetch_and_normalize(session: requests.Session,
                        queries: list[str] = None,
                        max_pages: int = 3) -> list[dict]:
    """Fetch research-related postings from Handshake and normalize them."""
    if queries is None:
        queries = RESEARCH_KEYWORDS

    all_opps = []
    seen_ids = set()

    for query in queries:
        for page in range(1, max_pages + 1):
            data = search_postings(session, query=query, page=page, per_page=25)
            results = data.get("results", [])
            if not results:
                break

            for posting in results:
                raw = _parse_posting(posting)
                if not raw or raw["handshake_id"] in seen_ids:
                    continue
                seen_ids.add(raw["handshake_id"])
                opp = normalize_posting(raw)
                all_opps.append(opp)

            time.sleep(1.5)

        logger.info(f"  Query '{query}': {len(seen_ids)} unique so far")

    logger.info(f"Total Handshake opportunities: {len(all_opps)}")
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
    parser.add_argument("--export-cookies", action="store_true",
                        help="Export Handshake cookies from Chrome")
    parser.add_argument("--save", action="store_true",
                        help="Merge into processed/opportunities.json")
    parser.add_argument("--max-pages", type=int, default=3,
                        help="Max pages per search query (default: 3)")
    parser.add_argument("--query", type=str, default=None,
                        help="Custom search query (overrides defaults)")
    args = parser.parse_args()

    if args.export_cookies:
        ok = export_cookies_from_chrome()
        if ok:
            print(f"\nCookies exported to {COOKIE_FILE}")
            print("Now run: python -m src.collectors.handshake")
        else:
            print("\nCookie export failed. See instructions above.")
        exit(0 if ok else 1)

    session = _load_session()
    if not session:
        print("\nNo cookies found. Run one of:")
        print("  python -m src.collectors.handshake --export-cookies")
        print(f"  Or manually save cookies to {COOKIE_FILE}")
        exit(1)

    if not _verify_session(session):
        print("\nSession expired. Log into Handshake in Chrome and re-export cookies:")
        print("  python -m src.collectors.handshake --export-cookies")
        exit(1)

    queries = [args.query] if args.query else None
    opps = fetch_and_normalize(session, queries=queries, max_pages=args.max_pages)

    print(f"\nFetched {len(opps)} opportunities from Handshake")
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
