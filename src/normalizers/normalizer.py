"""
Normalizer: converts RawOpportunity objects into the standardized schema.
V1 uses rule-based extraction. V2 will add LLM-powered extraction.
"""

import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Optional

from ..contact_instructions import CAPTURE_KEY, PAGES_KEY, SOURCE_KEY, retained_sources
from ..evidence import stamp_inferred
from ..opportunity_terms import extract_skill_requirements


def normalize(raw: dict, source_defaults: dict = None) -> dict:
    """Convert a raw opportunity dict into the standardized schema.

    Args:
        raw: Raw scraped data (flexible keys)
        source_defaults: Default tags from sources.yaml config

    Returns:
        Normalized opportunity dict matching opportunity_schema.md
    """
    defaults = source_defaults or {}
    desc = raw.get("description_raw", "")
    title = raw.get("title", "")
    extra = raw.get("extra_fields")
    contact_sources = retained_sources(extra.get(SOURCE_KEY)) if isinstance(extra, dict) else []

    title_inference = (extra.get("inferred_fields") or {}).get("title") if isinstance(extra, dict) and isinstance(extra.get("inferred_fields"), dict) else None
    source_title = "" if title_inference else title
    terms_text = "\n".join(value for value in (source_title, desc, raw.get("eligibility_text", "")) if isinstance(value, str))
    skills = extract_skill_requirements(terms_text)

    normalized = {
        "id": raw.get("id") or str(uuid.uuid4()),
        "source": raw.get("source", "unknown"),
        "source_url": raw.get("source_url", ""),
        "source_type": raw.get("source_type") or defaults.get("source_type", "unknown"),

        "title": title.strip(),
        "organization": raw.get("organization") or defaults.get("organization", ""),
        "department": raw.get("department", ""),
        "lab_or_program": raw.get("lab_or_program", ""),
        "pi_name": raw.get("pi_name"),
        "url": raw.get("url", ""),

        "location": raw.get("location") or defaults.get("location", ""),
        "on_campus": raw.get("on_campus") if raw.get("on_campus") is not None else defaults.get("on_campus", None),
        "remote_option": raw.get("remote_option", "unknown"),

        "opportunity_type": _infer_type(source_title, desc),
        "paid": raw.get("paid") or defaults.get("paid", "unknown"),
        "compensation_details": raw.get("compensation_details", ""),

        "deadline": raw.get("deadline"),
        "posted_date": raw.get("posted_date"),
        "start_date": raw.get("start_date"),
        "duration": raw.get("duration"),

        "eligibility": {
            "preferred_year": _extract_years(desc),
            "min_gpa": _extract_gpa(desc),
            "majors": _extract_majors(terms_text),
            "skills_required": skills["required"],
            "skills_preferred": skills["preferred"],
            "citizenship_required": _check_citizenship(desc),
            "international_friendly": raw.get("international_friendly") or defaults.get("international_friendly", "unknown"),
            "work_auth_notes": raw.get("work_auth_notes", ""),
            "eligibility_text_raw": raw.get("eligibility_text", ""),
        },

        "application": {
            "contact_method": _infer_contact_method(desc, raw.get("url", "")),
            "requires_resume": _check_keyword(desc, ["resume", "cv", "curriculum vitae"]),
            "requires_cover_letter": _check_keyword(desc, ["cover letter"]),
            "requires_transcript": _check_keyword(desc, ["transcript"]),
            "requires_recommendation": _check_keyword(desc, ["recommendation", "reference letter"]),
            "application_effort": "medium",
            "application_url": raw.get("application_url") or raw.get("url"),
        },

        "description_raw": desc,
        "description_clean": _clean_description(desc),
        "keywords": _extract_keywords(source_title, desc),

        "metadata": {
            "confidence_score": 0.6,  # Default; increase after manual review
            "last_verified": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "first_seen_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "last_seen_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "is_active": True,
            "manually_reviewed": False,
            "notes": "",
            "skill_mentions": skills["mentioned"],
            **({SOURCE_KEY: contact_sources} if isinstance(extra, dict) and SOURCE_KEY in extra else {}),
            **({PAGES_KEY: deepcopy(extra[PAGES_KEY])} if isinstance(extra, dict) and PAGES_KEY in extra else {}),
            **({CAPTURE_KEY: deepcopy(extra[CAPTURE_KEY])} if isinstance(extra, dict) and isinstance(extra.get(CAPTURE_KEY), dict) else {}),
        },
    }

    if title_inference:
        stamp_inferred(normalized["metadata"], "title", title_inference)
    for field in ("majors", "skills_required", "skills_preferred"):
        if normalized["eligibility"][field]:
            stamp_inferred(normalized["metadata"], f"eligibility.{field}", "rule:opportunity_terms")
    stamp_inferred(normalized["metadata"], "metadata.skill_mentions", "rule:opportunity_terms")
    if normalized["keywords"]:
        stamp_inferred(normalized["metadata"], "keywords", "rule:normalizer")

    # Compute application effort
    normalized["application"]["application_effort"] = _compute_effort(normalized["application"])

    if isinstance(extra, dict) and isinstance(extra.get(SOURCE_KEY), list) and len(extra[SOURCE_KEY]) > 8:
        metadata = normalized['metadata']
        metadata[SOURCE_KEY] = []
        metadata[PAGES_KEY] = {'version':1, 'pages':[], 'merge_issue':'source_limit'}
        receipt = metadata.get(CAPTURE_KEY)
        if isinstance(receipt, dict):
            metadata[CAPTURE_KEY] = {**receipt, 'status':'unsupported', 'reason':'source_limit'}
    return normalized


# --- Extraction helpers ---

YEAR_KEYWORDS = {
    "freshman": ["freshman", "first-year", "first year", "1st year"],
    "sophomore": ["sophomore", "second-year", "second year", "2nd year"],
    "junior": ["junior", "third-year", "third year", "3rd year"],
    "senior": ["senior", "fourth-year", "fourth year", "4th year"],
}


def _extract_years(text: str) -> list[str]:
    text_lower = text.lower()
    # "advanced undergraduate" is an explicit no-freshman signal (the AAAS Mass
    # Media Fellowship said exactly this yet showed "Accepts freshman students").
    if "advanced undergraduate" in text_lower:
        return ["junior", "senior"]
    found = []
    for year, keywords in YEAR_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(year)
    if not found and "undergraduate" in text_lower:
        return ["freshman", "sophomore", "junior", "senior"]
    return found or ["unknown"]


def _extract_gpa(text: str) -> Optional[float]:
    match = re.search(r"(?:GPA|gpa|G\.P\.A\.)\s*(?:of\s+)?(\d\.\d+)", text)
    if match:
        return float(match.group(1))
    return None


MAJOR_KEYWORDS = {
    "CS": ["computer science"],
    "ECE": ["electrical engineering", "computer engineering"],
    "STAT": ["statistics"],
    "Data Science": ["data science"],
    "IS": ["information science", "information sciences", "information systems", "ischool"],
    "Math": ["mathematics", "math"],
    "Physics": ["physics"],
    "Biology": ["biology", "biological sciences"],
    "Chemistry": ["chemistry", "chemical engineering"],
    "Engineering": ["engineering"],
}
_MAJOR_ACRONYMS = {"CS": "CS", "ECE": "ECE", "STAT": "STAT", "IS": "IS"}
_MAJOR_LIST = r"(?:CS|ECE|STAT|IS)(?:\s*(?:[,/&]|and|or)\s*(?:or\s+)?(?:CS|ECE|STAT|IS))*"
_EDUCATION_PREFIX = re.compile(
    r"\b(?:[Mm]ajoring\s+in|[Mm]ajors?\s*(?:in|:)\s*|[Dd]egrees?\s+in|"
    r"[Ss]tudents?\s+(?:in|studying)|[Bb]ackground\s+in|[Dd]epartment\s+of)\s*(" + _MAJOR_LIST + r")(?!\w)")
_EDUCATION_SUFFIX = re.compile(r"(?<!\w)(" + _MAJOR_LIST + r")\s+(?:majors?|students?|degrees?|department|program)\b")


def _extract_majors(text: str) -> list[str]:
    # Field names describe research relevance, not verified admission rules.
    # Ambiguous acronyms must occupy an education phrase, not just appear near
    # the word 'students' (e.g. 'This IS a notice for students').
    text = re.sub(r"(?:https?://|www\.)[^\s<>]+|<[^>]+>", " ", text)
    positive_clauses = [clause for clause in re.split(r"[.!?;\n]", text)
                        if not re.search(r"\b(?:no|not|without|neither)\b", clause, re.I)]
    found = []
    for major, keywords in MAJOR_KEYWORDS.items():
        if any(re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", clause, re.I)
               for clause in positive_clauses for kw in keywords):
            found.append(major)
            continue
        acronym = _MAJOR_ACRONYMS.get(major)
        if acronym and any(re.search(r"\b" + acronym + r"\b", match.group(1))
                           for clause in positive_clauses
                           for pattern in (_EDUCATION_PREFIX, _EDUCATION_SUFFIX)
                           for match in pattern.finditer(clause)):
            found.append(major)
    return found


def _extract_skills(text: str, required: bool = True) -> list[str]:
    """Compatibility helper; bare mentions are metadata, not requirements."""
    return extract_skill_requirements(text)["required" if required else "preferred"]


def _check_citizenship(text: str) -> bool:
    citizenship_phrases = [
        "u.s. citizen", "us citizen", "united states citizen",
        "permanent resident", "authorized to work in the u.s.",
        "must be a citizen", "citizenship required",
    ]
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in citizenship_phrases)


def _check_keyword(text: str, keywords: list[str]) -> str:
    text_lower = text.lower()
    if any(kw in text_lower for kw in keywords):
        return "yes"
    return "unknown"


def _infer_type(title: str, desc: str) -> str:
    combined = (title + " " + desc).lower()
    if any(kw in combined for kw in ["summer program", "reu", "surf", "fellowship"]):
        return "summer_program"
    if any(kw in combined for kw in ["internship", "intern "]):
        return "internship"
    if any(kw in combined for kw in ["research assistant", "research position", "lab"]):
        return "research"
    return "research"


def _infer_contact_method(text: str, url: str) -> str:
    text_lower = text.lower()
    if "apply online" in text_lower or "application form" in text_lower:
        return "portal"
    if any(kw in text_lower for kw in ["email", "send to", "contact"]):
        return "email"
    if "handshake" in url.lower():
        return "portal"
    return "unknown"


def _clean_description(text: str) -> str:
    """Remove HTML artifacts, normalize whitespace, cap at 1500 chars.

    Cap raised from 500 → 1500 in R70-A to stop truncating descriptions
    mid-sentence (NSF REU 554/554 records were affected). Backend route
    already serves [:1500] so this aligns the storage with the wire format.
    """
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:1500]


def _extract_keywords(title: str, desc: str) -> list[str]:
    """Extract relevant keywords for search indexing."""
    combined = (title + " " + desc).lower()
    keywords = []
    keyword_bank = [
        "undergraduate", "research assistant", "machine learning",
        "deep learning", "data science", "NLP", "computer vision",
        "robotics", "systems", "networks", "security",
        "summer research", "REU", "fellowship", "paid",
    ]
    for kw in keyword_bank:
        if kw.lower() in combined:
            keywords.append(kw)
    return keywords


def _compute_effort(application: dict) -> str:
    """Estimate application effort based on requirements."""
    requirement_fields = (
        "requires_resume",
        "requires_cover_letter",
        "requires_transcript",
        "requires_recommendation",
    )
    # Unknown material requirements are not the same thing as "none". Until
    # every input is known, a reassuring low-effort claim has no evidence.
    if any(application.get(field) not in {"yes", "no"} for field in requirement_fields):
        return "unknown"
    effort_points = 0
    if application.get("requires_resume") == "yes":
        effort_points += 1
    if application.get("requires_cover_letter") == "yes":
        effort_points += 2
    if application.get("requires_transcript") == "yes":
        effort_points += 1
    if application.get("requires_recommendation") == "yes":
        effort_points += 3

    if effort_points >= 4:
        return "high"
    elif effort_points >= 2:
        return "medium"
    return "low"
