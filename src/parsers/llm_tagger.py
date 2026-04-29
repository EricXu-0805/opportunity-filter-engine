"""
LLM-Enhanced Auto-Tagger for opportunity data.
Uses OpenAI gpt-4o-mini to extract structured fields from descriptions,
with a rule-based fallback when no API key is available.

Usage:
    python -m src.parsers.llm_tagger              # tag unknowns (LLM if key available, else rules)
    python -m src.parsers.llm_tagger --dry-run    # preview changes without saving
    python -m src.parsers.llm_tagger --no-llm     # force rule-based only
"""

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"

# Batch size for LLM calls
LLM_BATCH_SIZE = 10


def load_opportunities() -> list[dict]:
    """Load processed opportunities."""
    if not PROCESSED_FILE.exists():
        return []
    with open(PROCESSED_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_opportunities(opps: list[dict]) -> None:
    """Save opportunities back to processed file."""
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(opps, f, indent=2, ensure_ascii=False, default=str)


def needs_tagging(opp: dict) -> bool:
    """Check if an opportunity has unknown fields that could be improved."""
    elig = opp.get("eligibility", {})
    if opp.get("paid") == "unknown":
        return True
    if elig.get("international_friendly") == "unknown":
        return True
    if not elig.get("skills_required") and not elig.get("skills_preferred"):
        return True
    if elig.get("preferred_year") == ["freshman", "sophomore", "junior", "senior"]:
        return True
    return False


# ── Rule-Based Heuristic Tagger ──────────────────

SKILL_PATTERNS = {
    "Python": r"\bpython\b",
    "R": r"\bR\b(?!\s*&|\s*D)",
    "MATLAB": r"\bmatlab\b",
    "Java": r"\bjava\b(?!script)",
    "C++": r"\bc\+\+\b",
    "C": r"(?<![a-zA-Z])\bC\b(?!\+|#|s|o)",
    "JavaScript": r"\bjavascript\b",
    "SQL": r"\bsql\b",
    "PyTorch": r"\bpytorch\b",
    "TensorFlow": r"\btensorflow\b",
    "pandas": r"\bpandas\b",
    "NumPy": r"\bnumpy\b",
    "scikit-learn": r"\bscikit.?learn\b|\bsklearn\b",
    "Git": r"\bgit\b(?!hub)",
    "Linux": r"\blinux\b",
    "Docker": r"\bdocker\b",
    "React": r"\breact\b",
    "OpenCV": r"\bopencv\b",
    "SPSS": r"\bspss\b",
    "SAS": r"\bsas\b",
    "Stata": r"\bstata\b",
    "Excel": r"\bexcel\b",
    "LaTeX": r"\blatex\b",
    "AWS": r"\baws\b",
    "GIS": r"\bgis\b",
    "CAD": r"\bcad\b",
    "Keras": r"\bkeras\b",
    "Flask": r"\bflask\b",
    "Django": r"\bdjango\b",
    "Node.js": r"\bnode\.?js\b",
    "TypeScript": r"\btypescript\b",
    "Rust": r"\brust\b(?!ic)",
    "Go": r"\bgo\b(?:lang)\b|\bgolang\b",
    "Scala": r"\bscala\b",
    "Julia": r"\bjulia\b(?!n)",
    "Perl": r"\bperl\b",
    "Ruby": r"\bruby\b(?! on)",
    "Spark": r"\bspark\b",
    "Hadoop": r"\bhadoop\b",
    "Tableau": r"\btableau\b",
    "CUDA": r"\bcuda\b",
    "HuggingFace": r"\bhugging.?face\b|\btransformers\b",
}

YEAR_KEYWORDS = {
    "freshman": ["freshman", "first-year", "first year", "1st year"],
    "sophomore": ["sophomore", "second-year", "second year", "2nd year"],
    "junior": ["junior", "third-year", "third year", "3rd year"],
    "senior": ["senior", "fourth-year", "fourth year", "4th year"],
}


def _build_full_text(opp: dict) -> str:
    """Build searchable text from all available fields, not just description."""
    parts = []
    # Core text fields
    parts.append(opp.get("description_raw", "") or "")
    parts.append(opp.get("description_clean", "") or "")
    parts.append(opp.get("eligibility", {}).get("eligibility_text_raw", "") or "")
    # Title and organizational fields
    parts.append(opp.get("title", "") or "")
    parts.append(opp.get("lab_or_program", "") or "")
    parts.append(opp.get("department", "") or "")
    parts.append(opp.get("organization", "") or "")
    # Extract meaningful words from URL path
    url = opp.get("url", "") or ""
    if url:
        from urllib.parse import urlparse
        path = urlparse(url).path
        # Convert '/opportunity/chemistry-reu-colorado-state' -> 'chemistry reu colorado state'
        path_words = path.replace("/", " ").replace("-", " ").replace("_", " ")
        parts.append(path_words)
    # Keywords list
    keywords = opp.get("keywords", [])
    if keywords:
        parts.append(" ".join(keywords))
    return " ".join(parts)


# Extended domain-to-skills mapping — used when no explicit skills found in text
DOMAIN_SKILLS = {
    # CS / Engineering
    r"\b(data science|data analysis|data mining|big data|data.?driven)\b": ["Python", "SQL", "pandas"],
    r"\b(machine learning|deep learning|artificial intelligence|neural network|AI\b)\b": ["Python", "PyTorch"],
    r"\b(computer vision|image processing|image analysis|object detection)\b": ["Python", "OpenCV"],
    r"\b(natural language processing|nlp|text mining|language model)\b": ["Python"],
    r"\b(web development|web app|full.?stack|front.?end|back.?end)\b": ["JavaScript", "Python"],
    r"\b(robotics|embedded|microcontroller|autonomous|ROS)\b": ["C++", "Python"],
    r"\b(database|sql server|relational|ETL|data warehouse)\b": ["SQL"],
    r"\b(engineering simulation|finite element|cfd|FEA)\b": ["MATLAB", "Python"],
    r"\b(signal processing|DSP|communications|wireless)\b": ["MATLAB", "Python"],
    r"\b(cybersecurity|information security|network security|cryptography)\b": ["Python", "Linux"],
    r"\b(cloud computing|distributed systems|kubernetes|microservices)\b": ["Python", "Docker"],
    r"\b(semiconductor|VLSI|chip design|digital design|FPGA)\b": ["MATLAB"],
    r"\b(quantum computing|quantum information)\b": ["Python"],
    r"\b(computer graphics|visualization|rendering|3D)\b": ["C++", "Python"],
    r"\b(software engineering|software development|programming)\b": ["Python", "Git"],

    # Natural Sciences
    r"\b(bioinformatics|computational biology|genomics|proteomics|sequencing)\b": ["Python", "R"],
    r"\b(statistics|statistical|biostatistics|econometrics)\b": ["R", "Python"],
    r"\b(chemistry|chemical|molecular|organic chemistry|inorganic)\b": ["Python", "MATLAB"],
    r"\b(physics|astrophysics|astronomy|particle physics|condensed matter)\b": ["Python", "MATLAB"],
    r"\b(biology|biological|ecology|evolution|microbiology|neuroscience)\b": ["R", "Python"],
    r"\b(materials science|nanotechnology|nanofabrication|polymers)\b": ["MATLAB", "Python"],
    r"\b(environmental science|climate|atmospheric|oceanography|sustainability)\b": ["Python", "R"],
    r"\b(gis|geospatial|geographic|remote sensing|mapping)\b": ["GIS", "Python"],
    r"\b(geology|earth science|seismology|hydrology)\b": ["Python", "MATLAB"],
    r"\b(agriculture|agronomy|crop|soil science|plant)\b": ["R", "Python"],

    # Health / Biomedical
    r"\b(biomedical engineering|bioengineering|tissue engineering)\b": ["MATLAB", "Python"],
    r"\b(epidemiology|public health|clinical research|health informatics)\b": ["R", "SPSS"],
    r"\b(medical imaging|radiology|pathology|diagnostics)\b": ["Python", "MATLAB"],
    r"\b(pharmaceutical|drug discovery|pharmacology)\b": ["Python", "R"],

    # Social Sciences
    r"\b(psychology|cognitive science|behavioral|experimental psychology)\b": ["R", "SPSS"],
    r"\b(economics|economic analysis|market research|econometric)\b": ["R", "Stata"],
    r"\b(political science|policy analysis|political|government)\b": ["R", "Stata"],
    r"\b(sociology|social research|survey|demographics)\b": ["R", "SPSS"],
    r"\b(linguistics|computational linguistics|corpus)\b": ["Python", "R"],
}

# Organization-based international-friendly inference
# Federal agencies / national labs almost always require US citizenship
FEDERAL_ORGS = [
    "nasa", "doe", "department of energy", "national science foundation", "nsf",
    "argonne", "brookhaven", "fermilab", "sandia", "los alamos", "oak ridge",
    "lawrence livermore", "pacific northwest", "ames laboratory",
    "national institutes of health", "nih", "cdc", "fda", "noaa",
    "army research", "naval research", "air force research",
    "department of defense", "dod", "department of homeland security", "dhs",
    "national security agency", "nsa", "national lab",
]

# Title patterns that signal paid/unpaid
PAID_TITLE_PATTERNS = [
    r"\bREU\b",          # NSF REUs are almost always funded
    r"\bSURF\b",         # Summer Undergraduate Research Fellowships
    r"\bfellowship\b",
    r"\bscholarship\b",
    r"\bpaid\b",
]


def rule_based_tag(opp: dict) -> dict:
    """Apply rule-based heuristics to extract structured fields."""
    full_text = _build_full_text(opp)
    lower = full_text.lower()
    updates = {}

    # ── Skills extraction ──
    skills_found = []
    for skill, pattern in SKILL_PATTERNS.items():
        if re.search(pattern, full_text, re.IGNORECASE):
            skills_found.append(skill)

    # Domain-based skill inference
    for pattern, domain_skills in DOMAIN_SKILLS.items():
        if re.search(pattern, lower):
            for s in domain_skills:
                if s not in skills_found:
                    skills_found.append(s)

    if skills_found:
        existing_req = opp.get("eligibility", {}).get("skills_required", [])
        existing_pref = opp.get("eligibility", {}).get("skills_preferred", [])
        if not existing_req and not existing_pref:
            updates["skills_required"] = skills_found[:2] if len(skills_found) > 2 else skills_found
            updates["skills_preferred"] = skills_found[2:] if len(skills_found) > 2 else []

    # ── Year detection ──
    years_found = []
    for year, keywords in YEAR_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            years_found.append(year)

    if "undergraduate" in lower or "undergrad" in lower:
        if not years_found:
            years_found = ["freshman", "sophomore", "junior", "senior"]
    if "rising junior" in lower or "rising senior" in lower:
        years_found = ["sophomore", "junior"]
    if "completed at least" in lower and ("two years" in lower or "2 years" in lower):
        years_found = ["junior", "senior"]

    current_years = opp.get("eligibility", {}).get("preferred_year", [])
    if years_found and current_years == ["freshman", "sophomore", "junior", "senior"]:
        updates["preferred_year"] = years_found

    # ── International friendly detection ──
    if opp.get("eligibility", {}).get("international_friendly") == "unknown":
        intl = _detect_intl_from_text(full_text)
        # Also try organization-based inference
        if intl == "unknown":
            intl = _detect_intl_from_org(opp)
        # Also try title-based inference (e.g., "NSF REU" → likely US only)
        if intl == "unknown":
            intl = _detect_intl_from_title(opp.get("title", ""))
        if intl != "unknown":
            updates["international_friendly"] = intl
            updates["citizenship_required"] = intl == "no"

    # ── Paid status detection ──
    if opp.get("paid") == "unknown":
        paid = _detect_paid_from_text(full_text)
        # Also try title-based inference
        if paid == "unknown":
            paid = _detect_paid_from_title(opp.get("title", ""))
        if paid != "unknown":
            updates["paid"] = paid

    return updates


def _detect_intl_from_text(text: str) -> str:
    """Enhanced international-friendly detection."""
    lower = text.lower()
    no_keywords = [
        "u.s. citizen", "us citizen", "citizenship required",
        "permanent resident only", "us only", "must be a u.s.",
        "u.s. citizenship", "authorized to work in the united states",
        "u.s. persons only", "u.s. national", "must be u.s.",
        "citizens or permanent residents", "citizen or permanent resident",
        "must be authorized to work in the u.s.",
        "u.s. citizens and permanent residents only",
        "u.s. citizenship is required",
        "eligibility is limited to u.s. citizens",
        "restricted to u.s. citizens",
        "green card holders",
    ]
    yes_keywords = [
        "international students welcome", "open to all",
        "international students eligible", "all students",
        "no citizenship requirement", "international students are encouraged",
        "open to international", "regardless of citizenship",
        "all nationalities", "international applicants",
        "international students are eligible",
        "open to students from any country",
        "no citizenship or residency requirement",
        "we welcome international",
        "students of all nationalities",
        "non-u.s. citizens are welcome",
        "non-us citizens",
    ]
    if any(kw in lower for kw in no_keywords):
        return "no"
    if any(kw in lower for kw in yes_keywords):
        return "yes"
    return "unknown"


def _detect_paid_from_text(text: str) -> str:
    """Enhanced paid status detection."""
    lower = text.lower()
    paid_keywords = [
        "stipend", "paid position", "salary", "compensation provided",
        "paid internship", "funded", "receive a stipend", "financial support",
        "weekly stipend", "hourly pay", "hourly rate", "per hour",
        "$",  # dollar amounts suggest paid
        "competitive salary", "monthly stipend", "living allowance",
        "housing provided", "travel reimbursement", "tuition waiver",
        "award amount", "grant amount", "funding provided", "fully funded",
    ]
    unpaid_keywords = [
        "unpaid", "unfunded", "volunteer", "no compensation", "not paid",
        "credit only", "for credit", "course credit only",
    ]
    if any(kw in lower for kw in paid_keywords):
        return "yes"
    if any(kw in lower for kw in unpaid_keywords):
        return "no"
    return "unknown"


def _detect_intl_from_org(opp: dict) -> str:
    """Infer international eligibility from organization name."""
    org = (opp.get("organization", "") or "").lower()
    title = (opp.get("title", "") or "").lower()
    source = (opp.get("source", "") or "").lower()
    combined = f"{org} {title} {source}"

    # Federal agencies / national labs → almost always US only
    for fed_org in FEDERAL_ORGS:
        if fed_org in combined:
            return "no"

    # University programs are generally open to international students
    uni_keywords = ["university", "college", "institute of technology", "polytechnic"]
    on_campus = opp.get("on_campus", False)
    if on_campus or any(kw in combined for kw in uni_keywords):
        # On-campus university programs are generally intl-friendly
        # but not confident enough to mark 'yes' — leave as unknown
        pass

    return "unknown"


def _detect_intl_from_title(title: str) -> str:
    """Infer international eligibility from title patterns."""
    lower = title.lower()
    # NSF REUs are federally funded → US citizens/PR only
    if re.search(r"\bnsf\b", lower) and re.search(r"\breu\b", lower):
        return "no"
    # Government-specific programs
    if any(kw in lower for kw in ["federal", "national lab", "defense", "homeland"]):
        return "no"
    return "unknown"


def _detect_paid_from_title(title: str) -> str:
    """Infer paid status from title patterns."""
    lower = title.lower()
    for pattern in PAID_TITLE_PATTERNS:
        if re.search(pattern, lower, re.IGNORECASE):
            return "yes"
    if any(kw in lower for kw in ["volunteer", "unpaid"]):
        return "no"
    return "unknown"


# ── LLM-Based Tagger ────────────────────────────

def llm_tag_batch(opps: list[dict]) -> list[dict]:
    """Use LLM to tag a batch of opportunities.
    Supports OpenAI directly or OpenRouter via OPENROUTER_API_KEY / OPENAI_BASE_URL.
    """
    try:
        import openai
    except ImportError:
        logger.warning("openai package not installed, falling back to rule-based tagging")
        return [rule_based_tag(o) for o in opps]

    # Determine API key and base URL
    # Priority: OPENROUTER_API_KEY > OPENAI_API_KEY
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("No API key set, falling back to rule-based tagging")
        return [rule_based_tag(o) for o in opps]

    base_url = os.environ.get("OPENAI_BASE_URL")
    if os.environ.get("OPENROUTER_API_KEY"):
        base_url = base_url or "https://openrouter.ai/api/v1"

    # Pick model: OpenRouter uses org/model format
    model = os.environ.get("LLM_MODEL", "")
    if not model:
        model = "openai/gpt-4o-mini" if base_url and "openrouter" in base_url else "gpt-4o-mini"

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = openai.OpenAI(**client_kwargs)

    # Build batch prompt
    opp_summaries = []
    for i, opp in enumerate(opps):
        desc = (opp.get("description_raw", "") or "")[:500]
        elig = opp.get("eligibility", {}).get("eligibility_text_raw", "")[:300]
        title = opp.get("title", "")
        opp_summaries.append(
            f"[{i}] Title: {title}\nDescription: {desc}\nEligibility: {elig}"
        )

    prompt = f"""Analyze these {len(opps)} research/internship opportunities and extract structured fields for each.

For each opportunity, return a JSON object with:
- "skills_required": list of technical skills explicitly required (e.g. ["Python", "R"])
- "skills_preferred": list of technical skills preferred but not required
- "preferred_year": list from ["freshman", "sophomore", "junior", "senior"] - who is eligible
- "international_friendly": "yes", "no", or "unknown" - can international students apply?
- "paid": "yes", "no", or "unknown" - is there a stipend/salary?

Return a JSON array of objects, one per opportunity, in the same order. Only include fields you can determine from the text.

Opportunities:
{chr(10).join(opp_summaries)}"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You extract structured data from academic opportunity descriptions. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        content = response.choices[0].message.content
        result = json.loads(content)

        # Handle both {"results": [...]} and [...] formats
        if isinstance(result, dict):
            results = result.get("results", result.get("opportunities", []))
        elif isinstance(result, list):
            results = result
        else:
            results = []

        # Pad or truncate to match input length
        while len(results) < len(opps):
            results.append({})

        return results[:len(opps)]

    except Exception as e:
        logger.error(f"LLM tagging failed: {e}")
        return [rule_based_tag(o) for o in opps]


def apply_updates(opp: dict, updates: dict) -> bool:
    """Apply extracted fields to an opportunity. Returns True if any changes made."""
    changed = False

    if "paid" in updates and opp.get("paid") == "unknown":
        opp["paid"] = updates["paid"]
        changed = True

    elig = opp.get("eligibility", {})

    if "international_friendly" in updates and elig.get("international_friendly") == "unknown":
        elig["international_friendly"] = updates["international_friendly"]
        elig["citizenship_required"] = updates.get("citizenship_required", updates["international_friendly"] == "no")
        changed = True

    if "skills_required" in updates and not elig.get("skills_required"):
        elig["skills_required"] = updates["skills_required"]
        changed = True

    if "skills_preferred" in updates and not elig.get("skills_preferred"):
        elig["skills_preferred"] = updates["skills_preferred"]
        changed = True

    if "preferred_year" in updates:
        current = elig.get("preferred_year", [])
        if current == ["freshman", "sophomore", "junior", "senior"] and updates["preferred_year"] != current:
            elig["preferred_year"] = updates["preferred_year"]
            changed = True

    return changed


def tag_all(use_llm: bool = True, dry_run: bool = False) -> dict:
    """Tag all opportunities that need it.

    Returns summary dict with counts.
    """
    opps = load_opportunities()
    if not opps:
        return {"total": 0, "needs_tagging": 0, "tagged": 0}

    to_tag = [(i, opp) for i, opp in enumerate(opps) if needs_tagging(opp)]
    logger.info(f"Found {len(to_tag)}/{len(opps)} opportunities needing tagging")

    tagged_count = 0

    has_llm_key = bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    if use_llm and has_llm_key:
        # Process in batches
        for batch_start in range(0, len(to_tag), LLM_BATCH_SIZE):
            batch = to_tag[batch_start:batch_start + LLM_BATCH_SIZE]
            batch_opps = [opp for _, opp in batch]

            logger.info(f"LLM tagging batch {batch_start // LLM_BATCH_SIZE + 1} ({len(batch)} items)...")
            updates_list = llm_tag_batch(batch_opps)

            for (_idx, opp), updates in zip(batch, updates_list, strict=False):
                if updates and not dry_run:
                    if apply_updates(opp, updates):
                        tagged_count += 1
                elif updates and dry_run:
                    tagged_count += 1
    else:
        logger.info("Using rule-based tagging...")
        for _idx, opp in to_tag:
            updates = rule_based_tag(opp)
            if updates and not dry_run:
                if apply_updates(opp, updates):
                    tagged_count += 1
            elif updates and dry_run:
                tagged_count += 1

    if not dry_run and tagged_count > 0:
        save_opportunities(opps)
        logger.info(f"Saved {tagged_count} tagged opportunities")

    return {
        "total": len(opps),
        "needs_tagging": len(to_tag),
        "tagged": tagged_count,
        "mode": "llm" if (use_llm and has_llm_key) else "rule-based",
        "dry_run": dry_run,
    }


def compute_confidence(opp: dict) -> float:
    """Calculate confidence score based on field completeness (0.0–1.0)."""
    score = 0.0
    max_score = 0.0

    # Title (required, always present) — 5 pts
    max_score += 5
    if opp.get("title"):
        score += 5

    # Description quality — 15 pts
    max_score += 15
    desc = opp.get("description_clean", "") or opp.get("description_raw", "") or ""
    if len(desc) > 200:
        score += 15
    elif len(desc) > 50:
        score += 10
    elif len(desc) > 10:
        score += 5

    # Organization — 10 pts
    max_score += 10
    if opp.get("organization"):
        score += 10

    # Skills data — 15 pts
    max_score += 15
    elig = opp.get("eligibility", {})
    skills_req = elig.get("skills_required", [])
    skills_pref = elig.get("skills_preferred", [])
    if skills_req:
        score += 10
    if skills_pref:
        score += 5

    # International friendly known — 15 pts
    max_score += 15
    intl = elig.get("international_friendly", "unknown")
    if intl in ("yes", "no"):
        score += 15

    # Paid status known — 10 pts
    max_score += 10
    if opp.get("paid") in ("yes", "no", "stipend"):
        score += 10

    # Year preference specificity — 10 pts
    max_score += 10
    years = elig.get("preferred_year", [])
    if years and years != ["freshman", "sophomore", "junior", "senior"] and years != ["unknown"]:
        score += 10
    elif years:
        score += 3

    # Deadline — 10 pts
    max_score += 10
    if opp.get("deadline"):
        score += 10

    # Application method known — 5 pts
    max_score += 5
    app = opp.get("application", {})
    if app.get("contact_method") and app["contact_method"] != "unknown":
        score += 5

    # Manually reviewed bonus — 5 pts
    max_score += 5
    if opp.get("metadata", {}).get("manually_reviewed"):
        score += 5

    return round(score / max_score, 2) if max_score > 0 else 0.0


def recompute_all_confidence() -> dict:
    """Recompute confidence scores for all records."""
    opps = load_opportunities()
    if not opps:
        return {"total": 0, "updated": 0}

    updated = 0
    for opp in opps:
        new_conf = compute_confidence(opp)
        old_conf = opp.get("metadata", {}).get("confidence_score", 0)
        if abs(new_conf - old_conf) > 0.01:
            opp.setdefault("metadata", {})["confidence_score"] = new_conf
            updated += 1

    save_opportunities(opps)
    logger.info(f"Recomputed confidence for {updated}/{len(opps)} opportunities")
    return {"total": len(opps), "updated": updated}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="LLM-Enhanced Auto-Tagger")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    parser.add_argument("--no-llm", action="store_true", help="Force rule-based tagging only")
    parser.add_argument("--recompute-confidence", action="store_true", help="Recompute confidence scores")
    args = parser.parse_args()

    if args.recompute_confidence:
        result = recompute_all_confidence()
        print("\nConfidence Recompute Results")
        print("=" * 40)
        print(f"Total opps:  {result['total']}")
        print(f"Updated:     {result['updated']}")
    else:
        result = tag_all(use_llm=not args.no_llm, dry_run=args.dry_run)

        print(f"\n{'DRY RUN - ' if result['dry_run'] else ''}Auto-Tagging Results")
        print("=" * 40)
        print(f"Mode:           {result['mode']}")
        print(f"Total opps:     {result['total']}")
        print(f"Needs tagging:  {result['needs_tagging']}")
        print(f"Tagged:         {result['tagged']}")

        if result["dry_run"]:
            print("\n(No changes saved — remove --dry-run to apply)")
