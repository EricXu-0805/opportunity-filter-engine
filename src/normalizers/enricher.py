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
    "Education": [r"\beducation research\b", r"\bpedagogy\b", r"\bcurriculum\b", r"\bteacher\b", r"\btutor\b",
                  r"\binstructional design", r"\bclassroom assistant"],
    "Natural Resources & Environmental Sciences": [
        r"\bsustainab", r"\benvironmental\b", r"\bconservation\b", r"\bwildlife\b",
        r"\becology\b", r"\bnatural resources\b", r"\bpark ranger\b", r"\bparks intern\b",
        r"\bforestry\b", r"\bclimate (change|action)\b",
    ],
    "Food Science": [r"\bfood science\b", r"\bfood safety\b", r"\bfood systems\b",
                     r"\bnutrition(al)? science", r"\bdietetics?\b"],
    "Crop Sciences": [r"\bcrop sciences?\b", r"\bagronomy\b", r"\bsustainable agriculture\b",
                      r"\bplant protection\b", r"\bplant biotech"],
    "Agricultural & Biological Engineering": [
        r"\bagricultural (engineer|engineering|intern)\b", r"\bfarm\b", r"\bagricultural sciences\b",
    ],
    "Geology": [r"\bgeology\b", r"\bgeologic", r"\bfossil", r"\bpaleontolog"],
    "Marine Science": [r"\bmarine (science|biolog|research|intern)\b", r"\bocean(ograph)?\b", r"\baquatic\b"],
    "Hospitality": [r"\bhospitality\b", r"\brestaurant management\b", r"\bculinary\b",
                    r"\bfood (and|&) beverage\b", r"\btourism\b", r"\bhotel management\b"],
    "Human Resources": [r"\bhuman resources\b", r"\bhr intern\b", r"\btalent acquisition\b", r"\brecruitment\b"],
    "Library & Information Science": [r"\blibrary (intern|page|worker|assistant)\b", r"\barchival\b", r"\bdigitization\b"],
}


# Job-title -> major inference. Applied in addition to MAJOR_PATTERNS when
# the opportunity comes from a job board (e.g. Handshake) that ships the
# title but little/no description. Titles like "Software Engineer Intern"
# strongly imply CS even when no keyword in desc matches. These are LESS
# precise than full-text patterns — so they only fire for role-word matches.
JOB_TITLE_MAJOR_PATTERNS: dict[str, list[str]] = {
    "CS": [
        r"\bsoftware engineer", r"\bswe\b", r"\bprogrammer\b",
        r"\bweb developer\b", r"\bfull stack\b", r"\bbackend\b", r"\bfrontend\b",
        r"\bmobile developer\b", r"\bios developer\b", r"\bandroid developer\b",
        r"\bdevops\b", r"\bsite reliability\b", r"\bsre\b",
        r"\bmachine learning engineer\b", r"\bml engineer\b",
        r"\bdata engineer\b", r"\bai engineer\b",
    ],
    "ECE": [
        r"\bhardware engineer\b", r"\belectrical engineer\b", r"\bfirmware\b",
        r"\bembedded\b", r"\bcircuit design\b", r"\bsignal processing engineer\b",
        r"\brf engineer\b",
    ],
    "Mechanical Engineering": [
        r"\bmechanical engineer", r"\bcad (engineer|designer)\b", r"\bmanufacturing engineer\b",
        r"\bprocess engineer\b", r"\btest engineer\b", r"\brobotics engineer\b",
    ],
    "Civil Engineering": [
        r"\bcivil engineer", r"\bstructural engineer\b", r"\btransportation engineer\b",
        r"\bgeotechnical\b", r"\burban planner\b", r"\bfield intern\b",
    ],
    "Chemical Engineering": [
        r"\bchemical engineer", r"\bprocess development\b", r"\brefinery\b",
    ],
    "Data Science": [
        r"\bdata scientist\b", r"\bdata analyst\b", r"\banalytics\b", r"\bquantitative analyst\b",
        r"\bquant\b", r"\bresearch analyst\b",
    ],
    "Statistics": [
        r"\bstatistician\b", r"\bbiostatistician\b", r"\bactuarial\b",
    ],
    "Business": [
        r"\bbusiness analyst\b", r"\bconsultant\b", r"\boperations\b",
        r"\bstrategy\b", r"\bproduct manager\b", r"\bpm intern\b",
        r"\bmarketing\b", r"\bsales\b", r"\bhuman resources\b", r"\bhr intern\b",
        r"\bsupply chain\b", r"\blogistics\b", r"\bprocurement\b",
    ],
    "Finance": [
        r"\bfinancial analyst\b", r"\bfinance intern\b", r"\binvestment\b",
        r"\bbanking\b", r"\bportfolio\b", r"\btrader\b", r"\brevenue\b",
    ],
    "Accountancy": [r"\baccountant\b", r"\baudit\b", r"\btax (intern|analyst)\b"],
    "Journalism": [r"\bjournalist\b", r"\breporter\b", r"\beditor(ial)?\b", r"\bcontent writer\b"],
    "Communication": [r"\bcommunications?\b", r"\bpr (intern|manager)\b", r"\bpublic relations\b"],
    "Advertising": [r"\bcopywriter\b", r"\bbrand manager\b", r"\bdigital marketing\b"],
    "Art": [r"\bgraphic designer\b", r"\billustrator\b", r"\bui designer\b", r"\bux designer\b"],
    "Psychology": [r"\bclinical (intern|assistant)\b", r"\bbehavioral (analyst|research)\b"],
    "Education": [r"\bteacher\b", r"\btutor\b", r"\binstructor\b", r"\bteaching assistant\b"],
    "Biology": [r"\blab technician\b", r"\bresearch technician\b", r"\bfield biologist\b"],
    "Political Science": [r"\bpolicy (analyst|intern)\b", r"\blegislative\b", r"\bgovernment (intern|affairs)\b"],
    "Atmospheric Sciences": [r"\benvironmental (analyst|scientist)\b", r"\batmospheric (scientist|analyst)\b"],
    "Natural Resources & Environmental Sciences": [
        r"\benvironmental intern\b", r"\bsustainability (intern|crew|coordinator|associate)\b",
        r"\bconservation (intern|coordinator)\b", r"\bparks? intern\b",
        r"\bwildlife (intern|biologist|technician)\b", r"\bnatural resources (intern|technician)\b",
        r"\bpark ranger\b", r"\bfield (intern|technician|biologist)\b",
        r"\becologist\b", r"\bseasonal (intern|technician|biologist)\b",
    ],
    "Marine Science": [r"\bmarine (intern|biologist|scientist|educator)\b"],
    "Geology": [r"\bgeology (intern|technician)\b", r"\bfossil (intern|technician)\b",
                r"\bdigitizer\b", r"\bpaleontology intern\b"],
    "Food Science": [r"\bfood (safety|quality|science) (intern|assistant|analyst)\b"],
    "Crop Sciences": [r"\bagricultur(e|al) (intern|agent|technician)\b", r"\bfarm\b"],
    "Hospitality": [r"\b(food|beverage|culinary|hotel) intern\b"],
    "Human Resources": [r"\bhr\b.*\b(intern|internship|analyst|coordinator)\b",
                        r"\b(intern|internship)\b.*\bhr\b",
                        r"\brecruitment (intern|coordinator)\b"],
    "Library & Information Science": [
        r"\blibrary (page|cafe worker|intern|assistant)\b", r"\barchives? (intern|technician)\b",
    ],
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


# Skill patterns with strict word boundaries. Used to backfill
# eligibility.skills_required when upstream didn't extract any.
# These intentionally require clear context (e.g. "R programming"
# not "R" because "R" alone collides with words like "Research").
SKILL_PATTERNS: dict[str, list[str]] = {
    "Python": [r"\bpython\b"],
    "PyTorch": [r"\bpytorch\b"],
    "TensorFlow": [r"\btensorflow\b|\btensor flow\b"],
    "scikit-learn": [r"\bscikit[- ]learn\b|\bsklearn\b"],
    "NumPy": [r"\bnumpy\b"],
    "pandas": [r"\bpandas\b"],
    "MATLAB": [r"\bmatlab\b"],
    "R": [r"\bR\s+programming\b", r"\bR\s+language\b", r"\bR\s+statistical\b",
          r"\bR\s+(?:package|library|script)\b"],
    "SAS": [r"\bSAS\s+(?:software|programming|analytics)\b"],
    "Stata": [r"\bStata\b"],
    "SPSS": [r"\bSPSS\b"],
    "SQL": [r"\bSQL\b"],
    "Java": [r"\bJava\s+programming\b", r"\bin\s+Java\b(?!script)"],
    "C++": [r"C\+\+"],
    "C": [r"\bC\s+programming\b"],
    "JavaScript": [r"\bjavascript\b"],
    "TypeScript": [r"\btypescript\b"],
    "HTML/CSS": [r"\bHTML(?:\s*/\s*CSS)?\b", r"\bCSS\b"],
    "Git": [r"\bgit\b|\bgithub\b|\bgitlab\b"],
    "Docker": [r"\bdocker\b|\bcontainer"],
    "Linux": [r"\blinux\b|\bunix\b|\bbash\s+scripting\b"],
    "AWS": [r"\bAWS\b|\bamazon web services\b"],
    "GCP": [r"\bGCP\b|\bgoogle cloud\b"],
    "Azure": [r"\bmicrosoft azure\b"],
    "LaTeX": [r"\bLaTeX\b"],
    # ECE / hardware
    "LabVIEW": [r"\blabview\b"],
    "Verilog": [r"\bverilog\b|\bsystemverilog\b"],
    "VHDL": [r"\bvhdl\b"],
    "FPGA": [r"\bfpga\b"],
    "PCB design": [r"\bpcb\s+design\b"],
    # Mechanical / materials
    "CAD": [r"\bCAD\b|\bAutoCAD\b|\bSolidWorks\b|\bFusion\s+360\b"],
    "FEA": [r"\bFEA\b|\bfinite element\b|\bANSYS\b|\bAbaqus\b"],
    "3D printing": [r"\b3D\s+printing\b|\badditive manufacturing\b"],
    # Chemistry / biology wet-lab
    "PCR": [r"\bPCR\b|\bqPCR\b"],
    "microscopy": [r"\b(confocal |fluorescence |electron )?microscopy\b"],
    "HPLC": [r"\bHPLC\b|\bLC[- ]MS\b|\bGC[- ]MS\b"],
    "cell culture": [r"\bcell culture\b|\btissue culture\b"],
    "spectroscopy": [r"\b(NMR|IR|UV[- ]Vis|Raman)\s+spectroscopy\b", r"\bmass spectrometry\b"],
    # Statistical / data science
    "machine learning": [r"\bmachine learning\b"],
    "deep learning": [r"\bdeep learning\b|\bneural networks?\b"],
    "statistical analysis": [r"\bstatistical analysis\b|\bregression analysis\b"],
    "data analysis": [r"\bdata analysis\b|\bdata analytics\b"],
}

# Non-substring contexts that block a skill match even when the pattern
# matches. Prevents e.g. "R" in "Research" from surfacing.
_SKILL_BLOCKLIST_CONTEXTS: dict[str, list[str]] = {
    "R": [r"\bresearch\b", r"\bReview\b", r"\bResume\b"],
}


def _extract_skills_from_text(text: str) -> list[str]:
    found = []
    for skill, patterns in SKILL_PATTERNS.items():
        matched = False
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                matched = True
                break
        if not matched:
            continue
        blocklist = _SKILL_BLOCKLIST_CONTEXTS.get(skill)
        if blocklist and any(re.search(b, text, re.IGNORECASE) for b in blocklist):
            continue
        found.append(skill)
    return found


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

    title_text = (opp.get("title") or "").lower()
    if title_text:
        for major, patterns in JOB_TITLE_MAJOR_PATTERNS.items():
            if major in found:
                continue
            for p in patterns:
                if re.search(p, title_text):
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


# Titles that look like announcements/events/newsletters rather than actual
# openings. These should not be matched against student profiles — they
# pollute the ranking and confuse users. Detected at enrichment time and
# flagged via metadata.is_active=False so the matcher silently skips them.
_NON_OPPORTUNITY_TITLE_PATTERNS: list[str] = [
    r"\bsymposium\b.*\b(winner|award|recap|showcase|invited|completed)\b",
    r"\b(winner|award|recap|showcase)s?\b.*\bsymposium\b",
    r"\bapply to.*\b(symposium|competition|showcase)\b",
    r"\bless than.*\bmonth left\b",
    r"\bcall for applications\b",
    r"\bnew office sticker\b",
    r"\bstay connected\b",
    r"\bnewsletter\b",
    r"\bundergraduate research week\b",
    r"\bfamilies, you'?re invited\b",
    r"\bis here!\b",
    r"\bworkshops?\b$",
    r"\bimage of research\b",
    r"\b(you'?re|you are) invited\b",
]

_NON_OPPORTUNITY_COMPILED = [re.compile(p, re.IGNORECASE) for p in _NON_OPPORTUNITY_TITLE_PATTERNS]


def is_likely_non_opportunity(opp: dict) -> bool:
    """Heuristic: does this record look like an event announcement,
    newsletter, or general PR post rather than a real research/intern
    opportunity someone can apply to?

    Returns True when the title matches known non-opportunity patterns.
    Conservative — prefers false negatives over dropping real openings.
    """
    title = (opp.get("title") or "").strip()
    if not title:
        return False
    for pattern in _NON_OPPORTUNITY_COMPILED:
        if pattern.search(title):
            return True
    return False


# Sources whose postings are, by default, year-round research positions
# without a fixed deadline. Displaying "missing deadline" for these is
# misleading — they accept students any time (rolling basis).
_ROLLING_BY_SOURCE: frozenset = frozenset({
    "uiuc_faculty",  # professor research pages — contact anytime
    "uiuc_sro",      # SRO lab index — most are rolling
})

_ROLLING_TEXT_PATTERNS: list[str] = [
    r"\brolling\s+(basis|admission|application)",
    r"\bopen\s+until\s+filled\b",
    r"\bapplications?\s+accepted\s+(on a |)rolling",
    r"\baccepted\s+year[- ]round\b",
    r"\bcontact\s+(the\s+)?(pi|professor|faculty)\s+(directly|anytime)",
    r"\bno\s+(fixed\s+)?deadline\b",
    r"\bongoing\s+recruitment\b",
]

_ROLLING_TEXT_COMPILED = [re.compile(p, re.IGNORECASE) for p in _ROLLING_TEXT_PATTERNS]


def is_rolling_deadline(opp: dict) -> bool:
    """Return True when the opportunity accepts applicants on a rolling
    basis (no fixed deadline). Uses source defaults plus explicit
    textual signals in title/description.

    Used by the matcher/UI to differentiate "truly missing data" from
    "legitimately has no deadline" — the latter should not appear as a
    data-quality issue.
    """
    if opp.get("deadline"):
        return False
    source = opp.get("source", "")
    if source in _ROLLING_BY_SOURCE:
        return True
    text = " ".join([
        (opp.get("title") or ""),
        (opp.get("description_clean") or opp.get("description_raw") or ""),
    ])
    for pattern in _ROLLING_TEXT_COMPILED:
        if pattern.search(text):
            return True
    return False


def enrich_opportunity(opp: dict) -> dict:
    """Backfill majors + keywords in-place when upstream is empty.
    Also flags non-opportunities (events, announcements) as inactive.

    Returns the same dict (mutated). Safe to call multiple times —
    non-empty upstream fields are never overwritten, except when the
    non-opportunity heuristic matches (then is_active is forced False).
    """
    elig = opp.setdefault("eligibility", {})
    if not elig.get("majors"):
        inferred = infer_majors(opp)
        if inferred:
            elig["majors"] = inferred

    if not elig.get("skills_required"):
        desc = opp.get("description_raw") or opp.get("description_clean") or ""
        if desc and len(desc) >= 80:
            inferred_skills = _extract_skills_from_text(desc)
            if inferred_skills:
                elig["skills_required"] = inferred_skills

    kws = opp.get("keywords") or []
    if _is_unsorted(kws):
        inferred_kws = infer_keywords(opp)
        if inferred_kws:
            opp["keywords"] = inferred_kws

    if is_likely_non_opportunity(opp):
        meta = opp.setdefault("metadata", {})
        meta["is_active"] = False
        meta_notes = meta.get("notes", "")
        marker = "[auto-flagged: non-opportunity]"
        if marker not in meta_notes:
            meta["notes"] = (meta_notes + " " + marker).strip()

    if "is_rolling" not in opp and is_rolling_deadline(opp):
        opp["is_rolling"] = True

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
