"""
Normalizer: converts RawOpportunity objects into the standardized schema.
V1 uses rule-based extraction. V2 will add LLM-powered extraction.
"""

import re
import uuid
from datetime import datetime
from typing import Optional


def normalize(raw: dict, source_defaults: dict = None) -> dict:
    """
    Convert a raw opportunity dict into the standardized schema.
    
    Args:
        raw: Raw scraped data (flexible keys)
        source_defaults: Default tags from sources.yaml config
    
    Returns:
        Normalized opportunity dict matching opportunity_schema.md
    """
    defaults = source_defaults or {}
    desc = raw.get("description_raw", "")
    title = raw.get("title", "")

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

        "opportunity_type": _infer_type(title, desc),
        "paid": raw.get("paid") or defaults.get("paid", "unknown"),
        "compensation_details": raw.get("compensation_details", ""),

        "deadline": raw.get("deadline"),
        "posted_date": raw.get("posted_date"),
        "start_date": raw.get("start_date"),
        "duration": raw.get("duration"),

        "eligibility": {
            "preferred_year": _extract_years(desc),
            "min_gpa": _extract_gpa(desc),
            "majors": _extract_majors(desc),
            "skills_required": _extract_skills(desc, required=True),
            "skills_preferred": _extract_skills(desc, required=False),
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
        "keywords": _extract_keywords(title, desc),

        "metadata": {
            "confidence_score": 0.6,  # Default; increase after manual review
            "last_verified": datetime.utcnow().isoformat(),
            "first_seen_at": datetime.utcnow().isoformat(),
            "last_seen_at": datetime.utcnow().isoformat(),
            "is_active": True,
            "manually_reviewed": False,
            "notes": "",
        },
    }

    # Compute application effort
    normalized["application"]["application_effort"] = _compute_effort(normalized["application"])

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
    "CS": ["computer science", " cs ", "cs,", "cs/"],
    "ECE": ["electrical", "computer engineering", " ece ", "ece,"],
    "STAT": ["statistics", " stat ", "stat,"],
    "Data Science": ["data science"],
    "IS": ["information science", "ischool", " is "],
    "Math": ["mathematics", " math "],
    "Physics": ["physics"],
    "Biology": ["biology", "biological"],
    "Chemistry": ["chemistry", "chemical"],
    "Engineering": ["engineering"],
}


def _extract_majors(text: str) -> list[str]:
    text_lower = text.lower()
    found = []
    for major, keywords in MAJOR_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(major)
    return found


SKILL_KEYWORDS = [
    "Python", "Java", "C++", "C#", "JavaScript", "TypeScript",
    "R", "MATLAB", "SQL", "Rust", "Go",
    "PyTorch", "TensorFlow", "scikit-learn", "pandas", "NumPy",
    "OpenCV", "HuggingFace", "transformers",
    "machine learning", "deep learning", "NLP",
    "data analysis", "data visualization",
    "Linux", "Git", "Docker",
    "React", "Flask", "FastAPI", "Django",
    "AWS", "GCP", "Azure",
]


def _extract_skills(text: str, required: bool = True) -> list[str]:
    found = []
    text_lower = text.lower()
    for skill in SKILL_KEYWORDS:
        if skill.lower() in text_lower:
            found.append(skill)
    return found


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
    """Remove HTML artifacts, normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:500]


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
