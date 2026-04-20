"""
Post-normalization enricher for majors + keywords.

Backfills eligibility.majors and keywords fields when upstream sources
don't provide them. Used by both new-collection pipelines (RSS/Handshake/
manual) and the retroactive cleanup script over processed/opportunities.json.

Rules are keyword-based and conservative: only tag when the signal is
strong (subject word in title OR dedicated phrase in description).
Never overwrites real upstream data — only fills gaps or replaces the
"Unsorted" sentinel.
"""

from __future__ import annotations

import re
from typing import Iterable

# Canonical major name -> list of regex patterns (lowercase, word-boundary-aware).
# Title-prefix patterns (ending in ":" or appearing at start) get stronger weight.
MAJOR_PATTERNS: dict[str, list[str]] = {
    # STEM
    "CS": [r"\bcomputer science\b", r"\bcs\b(?!\s*[+/])", r"\bsoftware engineering\b"],
    "ECE": [r"\belectrical engineering\b", r"\bcomputer engineering\b", r"\bece\b"],
    "Statistics": [r"\bstatistics\b", r"\bbiostatistics\b", r"\bstatistical\b"],
    "Data Science": [r"\bdata science\b", r"\bdata scientist\b"],
    "Mathematics": [r"\bmathematics\b", r"\bapplied math\b", r"\bcombinatorics\b", r"\bnumber theory\b"],
    "Physics": [r"\bphysics\b", r"\bastrophysics\b", r"\bquantum\b", r"\bcondensed matter\b"],
    "Chemistry": [r"\bchemistry\b", r"\bchemical\b", r"\borganic synthesis\b"],
    "Biology": [r"\bbiology\b", r"\bbiological\b", r"\bgenetics\b", r"\bneuroscience\b", r"\bmicrobiology\b", r"\becology\b"],
    "Chemical Engineering": [r"\bchemical engineering\b"],
    "Bioengineering": [r"\bbioengineering\b", r"\bbiomedical engineering\b"],
    "Mechanical Engineering": [r"\bmechanical engineering\b", r"\bmechse\b"],
    "Civil Engineering": [r"\bcivil engineering\b", r"\benvironmental engineering\b"],
    "Materials Science": [r"\bmaterials science\b", r"\bmatse\b"],
    "Aerospace Engineering": [r"\baerospace\b"],
    "Industrial Engineering": [r"\bindustrial engineering\b", r"\bindustrial & enterprise\b"],
    "Nuclear Engineering": [r"\bnuclear engineering\b", r"\bnpre\b"],
    "Atmospheric Sciences": [r"\batmospheric\b", r"\bclimate science\b"],
    "IS": [r"\binformation sciences?\b", r"\bischool\b"],
    # Social Sciences
    "Psychology": [r"\bpsychology\b", r"\bpsycholog\b", r"\bcognitive\b", r"\bpsycholinguist"],
    "Sociology": [r"\bsociology\b", r"\bsocial work\b"],
    "Anthropology": [r"\banthropology\b", r"\bethnograph"],
    "Political Science": [r"\bpolitical science\b", r"\bgovernment\b"],
    "Economics": [r"\beconomics\b", r"\beconometric"],
    "Geography": [r"\bgeography\b", r"\bgis\b"],
    # Humanities
    "Linguistics": [
        r"\blinguistics?\b", r"\bpsycholinguist", r"\btesol\b",
        r"\blanguage acquisition\b", r"\bsecond language\b",
        r"\bbilingualism\b", r"\bmultilingual",
        r"\blanguage teaching\b", r"\bapplied linguistics\b",
    ],
    "Spanish": [r"\bspanish\b", r"\bhispanic\b", r"\blatin american studies\b"],
    "French": [r"\bfrench\b", r"\bfrancophone\b"],
    "German": [r"\bgerman\b", r"\bgermanic\b"],
    "East Asian Languages & Cultures": [r"\beast asian\b", r"\bjapanese\b", r"\bchinese\b", r"\bkorean\b"],
    "Slavic": [r"\bslavic\b", r"\brussian\b"],
    "Comparative Literature": [r"\bcomparative literature\b", r"\bworld literature\b"],
    "English": [r"\bcreative writing\b", r"\brhetoric\b", r"\benglish literature\b"],
    "History": [r"\bhistory\b", r"\bhistorical\b", r"\bmedieval\b"],
    "Philosophy": [r"\bphilosophy\b", r"\bethics\b"],
    "Religion": [r"\breligious studies\b", r"\btheology\b"],
    "Classics": [r"\bclassics\b", r"\bclassical civilization\b", r"\blatin\b(?!\s+american)"],
    # Arts / Media
    "Art History": [r"\bart history\b", r"\barth\b"],
    "Art": [r"\bstudio art\b", r"\bfine arts\b"],
    "Music": [r"\bmusic\b", r"\bmusicology\b", r"\bcomposition\b"],
    "Journalism": [r"\bjournalism\b"],
    "Advertising": [r"\badvertising\b"],
    "Communication": [r"\bcommunication studies?\b", r"\bmedia studies\b"],
    # Identity / Interdisciplinary
    "Gender & Women's Studies": [r"\bgender studies\b", r"\bwomen'?s studies\b"],
    "African American Studies": [r"\bafrican american studies\b"],
    "Asian American Studies": [r"\basian american studies\b"],
    "Latina/Latino Studies": [r"\blatin[ao] studies\b", r"\blatinx\b"],
    "Urban Planning": [r"\burban planning\b", r"\bregional planning\b"],
    "Business": [r"\bbusiness\b", r"\bmanagement\b", r"\bmarketing\b", r"\bfinance\b"],
    "Accountancy": [r"\baccountancy\b", r"\baccounting\b"],
    "Education": [r"\beducation research\b", r"\bpedagogy\b", r"\bcurriculum\b"],
}

# Keywords to surface for search indexing. Separate from majors; more granular.
KEYWORD_PATTERNS: dict[str, list[str]] = {
    "machine learning": [r"\bmachine learning\b", r"\bml\b", r"\bdeep learning\b"],
    "artificial intelligence": [r"\bartificial intelligence\b", r"\bai\b"],
    "NLP": [r"\bnlp\b", r"\bnatural language processing\b", r"\blarge language model", r"\bllm\b"],
    "computer vision": [r"\bcomputer vision\b", r"\bimage recognition\b", r"\bobject detection\b"],
    "robotics": [r"\brobotics\b", r"\brobot\b", r"\bautonomous\b"],
    "data science": [r"\bdata science\b", r"\bdata analysis\b", r"\bdata analytics\b"],
    "bioinformatics": [r"\bbioinformatics\b", r"\bgenomics\b", r"\bcomputational biology\b"],
    "neuroscience": [r"\bneuroscience\b", r"\bbrain\b", r"\bcognitive\b"],
    "language": [r"\blanguage\b", r"\bbilingual", r"\blinguistic\b", r"\bmultilingual"],
    "language teaching": [r"\blanguage teaching\b", r"\btesol\b", r"\besl\b"],
    "psycholinguistics": [r"\bpsycholinguist", r"\blanguage acquisition\b"],
    "translation": [r"\btranslation\b", r"\binterpreting\b", r"\binterpretation\b"],
    "literature": [r"\bliterature\b", r"\bpoetics\b", r"\bcreative writing\b"],
    "history": [r"\bhistorical research\b", r"\barchival\b"],
    "humanities": [r"\bhumanities\b"],
    "social sciences": [r"\bsocial science", r"\bsocial research\b"],
    "public policy": [r"\bpublic policy\b", r"\bpolicy research\b"],
    "climate": [r"\bclimate change\b", r"\bsustainab", r"\benvironmental\b"],
    "health": [r"\bhealth\b", r"\bmedical\b", r"\bclinical\b"],
    "education": [r"\beducation\b", r"\blearning\b", r"\bstudent success\b"],
    "chemistry": [r"\bchemistry\b", r"\bchemical\b"],
    "materials": [r"\bmaterials\b", r"\bnanomaterials\b", r"\bpolymer"],
    "physics": [r"\bphysics\b", r"\bquantum\b"],
    "engineering": [r"\bengineering\b"],
    "research assistant": [r"\bresearch assistant\b"],
    "undergraduate research": [r"\bundergraduate research\b", r"\breu\b"],
    "paid": [r"\bpaid\b", r"\bstipend\b", r"\bhourly\b", r"\bcompensation\b"],
    "fellowship": [r"\bfellowship\b"],
    "internship": [r"\binternship\b", r"\bintern\b"],
}


def _combined_text(opp: dict) -> str:
    title = (opp.get("title") or "").lower()
    desc = (opp.get("description_clean") or opp.get("description_raw") or "").lower()
    desc = re.sub(r"<[^>]+>", " ", desc)
    lab = (opp.get("lab_or_program") or "").lower()
    dept = (opp.get("department") or "").lower()
    return f"{title} {dept} {lab} {desc}"


def infer_majors(opp: dict) -> list[str]:
    text = _combined_text(opp)
    if not text.strip():
        return []
    found: list[str] = []
    for major, patterns in MAJOR_PATTERNS.items():
        for p in patterns:
            if re.search(p, text):
                found.append(major)
                break
    return found


def infer_keywords(opp: dict) -> list[str]:
    text = _combined_text(opp)
    if not text.strip():
        return []
    found: list[str] = []
    for kw, patterns in KEYWORD_PATTERNS.items():
        for p in patterns:
            if re.search(p, text):
                found.append(kw)
                break
    return found


_UNSORTED_SENTINELS = frozenset({"unsorted", "uncategorized", "misc"})


def _is_unsorted(keywords: Iterable[str]) -> bool:
    """Treat ['Unsorted'] / ['uncategorized'] as effectively-empty."""
    if not keywords:
        return True
    cleaned = [k for k in keywords if k and k.strip()]
    if not cleaned:
        return True
    return all(k.strip().lower() in _UNSORTED_SENTINELS for k in cleaned)


def enrich_opportunity(opp: dict) -> dict:
    """Backfill majors + keywords in-place when upstream is empty.

    Returns the same dict (mutated). Safe to call multiple times —
    non-empty upstream fields are never overwritten.
    """
    elig = opp.setdefault("eligibility", {})
    if not elig.get("majors"):
        inferred = infer_majors(opp)
        if inferred:
            elig["majors"] = inferred

    kws = opp.get("keywords") or []
    if _is_unsorted(kws):
        inferred_kws = infer_keywords(opp)
        if inferred_kws:
            opp["keywords"] = inferred_kws

    return opp


def enrich_all(opps: list[dict]) -> tuple[int, int]:
    """Enrich a list of opportunities. Returns (majors_added, keywords_added)."""
    majors_added = 0
    keywords_added = 0
    for o in opps:
        before_majors = o.get("eligibility", {}).get("majors") or []
        before_kws = o.get("keywords") or []
        enrich_opportunity(o)
        after_majors = o.get("eligibility", {}).get("majors") or []
        after_kws = o.get("keywords") or []
        if not before_majors and after_majors:
            majors_added += 1
        if _is_unsorted(before_kws) and not _is_unsorted(after_kws):
            keywords_added += 1
    return majors_added, keywords_added
