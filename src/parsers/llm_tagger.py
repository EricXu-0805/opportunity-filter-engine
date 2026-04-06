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
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"

# Batch size for LLM calls
LLM_BATCH_SIZE = 10


def load_opportunities() -> list[dict]:
    """Load processed opportunities."""
    if not PROCESSED_FILE.exists():
        return []
    with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
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
}

YEAR_KEYWORDS = {
    "freshman": ["freshman", "first-year", "first year", "1st year"],
    "sophomore": ["sophomore", "second-year", "second year", "2nd year"],
    "junior": ["junior", "third-year", "third year", "3rd year"],
    "senior": ["senior", "fourth-year", "fourth year", "4th year"],
}


def rule_based_tag(opp: dict) -> dict:
    """Apply rule-based heuristics to extract structured fields."""
    desc = (opp.get("description_raw", "") or "") + " " + (opp.get("description_clean", "") or "")
    elig_text = opp.get("eligibility", {}).get("eligibility_text_raw", "")
    full_text = desc + " " + elig_text
    lower = full_text.lower()
    updates = {}

    # Skills extraction
    skills_found = []
    for skill, pattern in SKILL_PATTERNS.items():
        if re.search(pattern, full_text, re.IGNORECASE):
            skills_found.append(skill)

    if skills_found:
        existing_req = opp.get("eligibility", {}).get("skills_required", [])
        existing_pref = opp.get("eligibility", {}).get("skills_preferred", [])
        if not existing_req and not existing_pref:
            # Put first 2 as required, rest as preferred
            updates["skills_required"] = skills_found[:2] if len(skills_found) > 2 else skills_found
            updates["skills_preferred"] = skills_found[2:] if len(skills_found) > 2 else []

    # Year detection
    years_found = []
    for year, keywords in YEAR_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            years_found.append(year)

    # Also detect general patterns
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

    # International friendly detection
    if opp.get("eligibility", {}).get("international_friendly") == "unknown":
        intl = _detect_intl_from_text(full_text)
        if intl != "unknown":
            updates["international_friendly"] = intl
            updates["citizenship_required"] = intl == "no"

    # Paid status detection
    if opp.get("paid") == "unknown":
        paid = _detect_paid_from_text(full_text)
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
    ]
    yes_keywords = [
        "international students welcome", "open to all",
        "international students eligible", "all students",
        "no citizenship requirement", "international students are encouraged",
        "open to international", "regardless of citizenship",
        "all nationalities", "international applicants",
    ]
    if any(kw in lower for kw in no_keywords):
        return "no"
    if any(kw in lower for kw in yes_keywords):
        return "yes"
    return "unknown"


def _detect_paid_from_text(text: str) -> str:
    """Enhanced paid status detection."""
    lower = text.lower()
    if any(kw in lower for kw in ["stipend", "paid position", "salary",
                                    "compensation provided", "paid internship",
                                    "funded", "receive a stipend",
                                    "financial support", "weekly stipend"]):
        return "yes"
    if any(kw in lower for kw in ["unpaid", "unfunded", "volunteer",
                                    "no compensation", "not paid"]):
        return "no"
    return "unknown"


# ── LLM-Based Tagger ────────────────────────────

def llm_tag_batch(opps: list[dict]) -> list[dict]:
    """Use OpenAI gpt-4o-mini to tag a batch of opportunities."""
    try:
        import openai
    except ImportError:
        logger.warning("openai package not installed, falling back to rule-based tagging")
        return [rule_based_tag(o) for o in opps]

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set, falling back to rule-based tagging")
        return [rule_based_tag(o) for o in opps]

    client = openai.OpenAI(api_key=api_key)

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
            model="gpt-4o-mini",
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

    if use_llm and os.environ.get("OPENAI_API_KEY"):
        # Process in batches
        for batch_start in range(0, len(to_tag), LLM_BATCH_SIZE):
            batch = to_tag[batch_start:batch_start + LLM_BATCH_SIZE]
            batch_opps = [opp for _, opp in batch]

            logger.info(f"LLM tagging batch {batch_start // LLM_BATCH_SIZE + 1} ({len(batch)} items)...")
            updates_list = llm_tag_batch(batch_opps)

            for (idx, opp), updates in zip(batch, updates_list):
                if updates and not dry_run:
                    if apply_updates(opp, updates):
                        tagged_count += 1
                elif updates and dry_run:
                    tagged_count += 1
    else:
        # Rule-based fallback
        logger.info("Using rule-based tagging...")
        for idx, opp in to_tag:
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
        "mode": "llm" if (use_llm and os.environ.get("OPENAI_API_KEY")) else "rule-based",
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="LLM-Enhanced Auto-Tagger")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    parser.add_argument("--no-llm", action="store_true", help="Force rule-based tagging only")
    args = parser.parse_args()

    result = tag_all(use_llm=not args.no_llm, dry_run=args.dry_run)

    print(f"\n{'DRY RUN - ' if result['dry_run'] else ''}Auto-Tagging Results")
    print("=" * 40)
    print(f"Mode:           {result['mode']}")
    print(f"Total opps:     {result['total']}")
    print(f"Needs tagging:  {result['needs_tagging']}")
    print(f"Tagged:         {result['tagged']}")

    if result["dry_run"]:
        print("\n(No changes saved — remove --dry-run to apply)")
