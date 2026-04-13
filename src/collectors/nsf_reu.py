import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

NSF_API = "https://api.nsf.gov/services/v1/awards.json"
FIELDS = (
    "id,title,piFirstName,piLastName,piEmail,"
    "abstractText,startDate,expDate,"
    "awardeeName,awardeeCity,awardeeStateCode,"
    "fundProgramName"
)
PAGE_SIZE = 25

STEM_KEYWORDS = {
    "computer": ["CS", "ECE"],
    "computing": ["CS", "ECE"],
    "data science": ["CS", "STAT", "IS"],
    "machine learning": ["CS", "ECE", "STAT"],
    "artificial intelligence": ["CS", "ECE"],
    "physics": ["Physics", "Engineering"],
    "chemistry": ["Chemistry"],
    "biology": ["Biology"],
    "biomedical": ["Bioengineering", "Biology"],
    "material": ["Materials Science", "Chemistry"],
    "engineering": ["Engineering"],
    "math": ["Mathematics", "STAT"],
    "statistics": ["STAT", "CS"],
    "environmental": ["Environmental Engineering", "Biology"],
    "astronomy": ["Astronomy", "Physics"],
    "neuroscience": ["Neuroscience", "Biology"],
    "robotics": ["ECE", "CS", "Mechanical Engineering"],
    "social": ["Sociology", "Psychology"],
    "psychology": ["Psychology"],
    "economics": ["Economics"],
    "ecology": ["Biology", "Natural Resources"],
    "ocean": ["Earth Sciences"],
    "geo": ["Geology", "Earth Sciences"],
    "nano": ["ECE", "Physics", "Materials Science"],
    "cyber": ["CS", "IS"],
    "network": ["CS", "ECE"],
}


def _extract_skills_from_abstract(abstract: str) -> list[str]:
    known = [
        "Python", "Java", "C++", "C", "R", "MATLAB", "SQL",
        "PyTorch", "TensorFlow", "machine learning", "deep learning",
        "data analysis", "Linux", "Git", "Docker",
        "JavaScript", "React", "GIS",
    ]
    lower = abstract.lower()
    return [s for s in known if s.lower() in lower]


def _infer_majors(title: str, abstract: str, program: str) -> list[str]:
    combined = (title + " " + abstract + " " + program).lower()
    majors = set()
    for keyword, mapped in STEM_KEYWORDS.items():
        if keyword in combined:
            majors.update(mapped)
    return sorted(majors) if majors else ["STEM"]


def _detect_international(abstract: str) -> str:
    lower = abstract.lower()
    if any(kw in lower for kw in [
        "international students welcome", "international students are eligible",
        "international students are encouraged", "open to international",
        "regardless of citizenship", "all students regardless",
    ]):
        return "yes"
    # NSF-funded REU programs typically require US citizenship/permanent residency
    return "no"


KEYWORD_BANK = [
    "machine learning", "deep learning", "computer vision", "robotics",
    "natural language processing", "data science", "cybersecurity",
    "quantum", "nanotechnology", "materials science", "renewable energy",
    "neuroscience", "genomics", "bioinformatics", "ecology",
    "climate", "sustainability", "astrophysics", "chemistry",
    "signal processing", "embedded systems", "networks",
    "artificial intelligence", "internet of things", "blockchain",
    "autonomous", "biomedical", "drug discovery", "proteomics",
    "remote sensing", "geophysics", "hydrology", "marine biology",
    "organic chemistry", "polymer", "semiconductor", "photonics",
    "fluid dynamics", "thermodynamics", "structural engineering",
    "epidemiology", "public health", "cognitive science",
    "human-computer interaction", "software engineering",
    "parallel computing", "high performance computing",
    "graph theory", "optimization", "stochastic",
]


def _extract_keywords(title: str, abstract: str) -> list[str]:
    combined = (title + " " + abstract).lower()
    return [kw for kw in KEYWORD_BANK if kw in combined][:8]


def fetch_reu_awards(max_results: int = 500) -> list[dict]:
    all_awards = []
    offset = 1

    while offset <= max_results:
        params = {
            "keyword": "REU Site",
            "printFields": FIELDS,
            "offset": offset,
            "rpp": PAGE_SIZE,
            "dateStart": "01/01/2024",
        }
        try:
            resp = requests.get(NSF_API, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            awards = data.get("response", {}).get("award", [])
            if not awards:
                break
            all_awards.extend(awards)
            total = data.get("response", {}).get("metadata", {}).get("totalCount", 0)
            logger.info(f"Fetched {len(all_awards)}/{min(total, max_results)} REU awards")
            offset += PAGE_SIZE
        except Exception as e:
            logger.error(f"NSF API error at offset {offset}: {e}")
            break

    return all_awards


def _is_reu_site(award: dict) -> bool:
    title = award.get("title", "").lower()
    return "reu site" in title or "reu supplement" not in title


def normalize_award(award: dict) -> dict:
    title = award.get("title", "").strip()
    pi_first = award.get("piFirstName", "")
    pi_last = award.get("piLastName", "")
    pi_name = f"{pi_first} {pi_last}".strip()
    pi_email = award.get("piEmail", "")
    abstract = award.get("abstractText", "")
    school = award.get("awardeeName", "")
    city = award.get("awardeeCity", "")
    state = award.get("awardeeStateCode", "")
    program = award.get("fundProgramName", "")
    start = award.get("startDate", "")
    end = award.get("expDate", "")
    nsf_id = award.get("id", "")

    location = f"{city}, {state}" if city and state else state or ""
    url = f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={nsf_id}" if nsf_id else ""

    opp_id = f"nsf-reu-{nsf_id}" if nsf_id else f"nsf-reu-{hashlib.md5(title.encode()).hexdigest()[:8]}"
    now = datetime.utcnow().isoformat()

    skills = _extract_skills_from_abstract(abstract)
    majors = _infer_majors(title, abstract, program)
    intl = _detect_international(abstract)
    keywords = _extract_keywords(title, abstract)

    clean_title = re.sub(r"^REU\s+Site:\s*", "", title, flags=re.IGNORECASE).strip()

    return {
        "id": opp_id,
        "source": "nsf_reu",
        "source_url": url,
        "source_type": "summer_program",
        "title": f"REU: {clean_title}",
        "organization": school,
        "department": program,
        "lab_or_program": clean_title,
        "pi_name": pi_name or None,
        "contact_email": pi_email or None,
        "url": url,
        "location": location,
        "on_campus": True,
        "remote_option": "no",
        "opportunity_type": "summer_program",
        "paid": "yes",
        "compensation_details": "NSF-funded stipend (typically $6,000-$7,000 for 10 weeks)",
        "deadline": None,
        "posted_date": start[:10] if start else None,
        "start_date": start[:10] if start else None,
        "duration": "Summer (8-10 weeks)",
        "eligibility": {
            "preferred_year": ["freshman", "sophomore", "junior"],
            "min_gpa": None,
            "majors": majors,
            "skills_required": skills[:3],
            "skills_preferred": skills[3:],
            "citizenship_required": intl == "no",
            "international_friendly": intl,
            "work_auth_notes": "",
            "eligibility_text_raw": abstract[:500],
        },
        "application": {
            "contact_method": "online",
            "requires_resume": "yes",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "yes",
            "application_effort": "medium",
            "application_url": url,
        },
        "description_raw": abstract,
        "description_clean": abstract[:500],
        "keywords": keywords,
        "metadata": {
            "confidence_score": 0.95,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": f"Auto-imported from NSF Awards API (Award #{nsf_id})",
            "nsf_award_id": nsf_id,
            "nsf_end_date": end,
        },
    }


def _dedup_collaborative(opps: list[dict]) -> list[dict]:
    seen_titles = {}
    result = []
    for o in opps:
        base = re.sub(r"^REU:\s*", "", o["title"])
        base = re.sub(r"Collaborative Research:\s*", "", base)
        base = base[:60].strip().lower()
        if base not in seen_titles:
            seen_titles[base] = o
            result.append(o)
        else:
            existing = seen_titles[base]
            if len(o.get("description_raw", "")) > len(existing.get("description_raw", "")):
                result.remove(existing)
                seen_titles[base] = o
                result.append(o)
    return result


def fetch_and_normalize(max_results: int = 500) -> list[dict]:
    raw = fetch_reu_awards(max_results=max_results)
    reu_only = [a for a in raw if _is_reu_site(a)]
    logger.info(f"Filtered to {len(reu_only)} REU Site awards (excluded supplements)")

    normalized = []
    for a in reu_only:
        try:
            normalized.append(normalize_award(a))
        except Exception as e:
            logger.error(f"Failed to normalize NSF award {a.get('id')}: {e}")

    before = len(normalized)
    normalized = _dedup_collaborative(normalized)
    if before != len(normalized):
        logger.info(f"Deduped collaborative entries: {before} → {len(normalized)}")

    return normalized


def merge_into_processed(new_opps: list[dict], filepath: str = None) -> tuple[int, int]:
    filepath = filepath or str(PROCESSED_DIR / "opportunities.json")

    existing = []
    if Path(filepath).exists():
        with open(filepath, "r", encoding="utf-8") as f:
            existing = json.load(f)

    index = {opp["id"]: opp for opp in existing}
    added, updated = 0, 0

    for opp in new_opps:
        if opp["id"] in index:
            opp["metadata"]["first_seen_at"] = index[opp["id"]].get("metadata", {}).get(
                "first_seen_at", opp["metadata"]["first_seen_at"]
            )
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

    parser = argparse.ArgumentParser(description="NSF REU Site Collector")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--max", type=int, default=500)
    args = parser.parse_args()

    opps = fetch_and_normalize(max_results=args.max)
    print(f"\nFetched {len(opps)} REU Site opportunities")

    for o in opps[:5]:
        print(f"\n  {o['title'][:65]}")
        print(f"    PI: {o.get('pi_name','')} ({o.get('contact_email','')})")
        print(f"    School: {o['organization']}")
        print(f"    Majors: {', '.join(o['eligibility']['majors'])}")
        print(f"    Skills: {', '.join(o['eligibility']['skills_required'])}")
        print(f"    Intl: {o['eligibility']['international_friendly']}")

    if args.save:
        added, updated = merge_into_processed(opps)
        print(f"\nSaved: {added} new, {updated} updated")
    else:
        print("\n(Use --save to merge into processed/opportunities.json)")
