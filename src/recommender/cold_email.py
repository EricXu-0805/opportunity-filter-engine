import re

from src.evidence import faculty_contact_claims_unverified, is_professor_rank
from src.matcher.ranker import _BAD_PI_NAMES, _BROAD_FIELDS, _tokenize
from src.publication_trust import verified_recent_works

# Tokenizer for skill matching: a letter followed by letters/digits/+/#/. so
# "c++", "c#", "node.js" stay whole. Used to match a skill as a WHOLE token in a
# posting, not a raw substring — substring matching let single-letter skills
# ("R", "C") and short ones ("AI") match inside unrelated words ("Research").
_SKILL_TOKEN_RE = re.compile(r"[a-z][a-z0-9+#.]*")

# A stored coursework entry of the shape WORD + calendar-year is a venue or a
# date ("CVPR 2026", "NeurIPS 2025", "May 2027"), not a catalog number — the
# résumé parser's ACRONYM+NUMBER heuristic can't tell them apart, and citing
# one as "relevant coursework" is a false claim in the student's own voice.
# Genuine catalog numbers in the 1950–2049 band ("CS 2050") are sacrificed:
# losing one course from a sentence is cheap, a fabricated claim is not.
_DATELIKE_COURSE_RE = re.compile(r"^\S{2,12}\.?\s+(19[5-9]\d|20[0-4]\d)$")


def filter_course_entries(courses: list) -> list[str]:
    """Coursework entries safe to cite as courses — venue/date shapes dropped."""
    return [
        c for c in (str(x).strip() for x in courses or [])
        if c and not _DATELIKE_COURSE_RE.match(c)
    ]


def _extract_skill_names(raw_skills: list) -> list[str]:
    result = []
    for s in raw_skills:
        if isinstance(s, dict):
            result.append(s.get("name", ""))
        elif isinstance(s, str):
            result.append(s)
        else:
            result.append(getattr(s, "name", str(s)))
    return [n for n in result if n]


def _extract_skill_levels(raw_skills: list) -> dict[str, str]:
    result = {}
    for s in raw_skills:
        if isinstance(s, dict):
            result[s.get("name", "")] = s.get("level", "beginner")
        elif isinstance(s, str):
            result[s] = "beginner"
        else:
            result[getattr(s, "name", str(s))] = getattr(s, "level", "beginner")
    return result


_EMAIL_GENERIC_KW = frozenset({
    "undergraduate", "research", "summer", "program", "internship",
    "opportunity", "assistant", "student", "uiuc", "illinois",
    "computer science", "artificial intelligence", "machine learning", "ai", "ml",
    "engineering", "science", "technology", "science & technology",
    "natural sciences", "social sciences & behavior", "department",
    # Current directory imports also use these bare taxonomy buckets as the
    # only keyword for some faculty rows.  They identify a school/discipline,
    # not the person's research, so they cannot authorize paid personalized
    # prose such as "your research on law".  Keep exact matching: short but
    # meaningful source terms such as HPC, CFD, AMO, HEP, CMT, tax, and Tap
    # remain valid evidence.
    "law", "art", "lit", "inc",
})


# Lab-type taxonomy. Cold-email tone, structure, and the skills a student
# should foreground all shift by lab type — wet labs care about bench
# technique + hours, dry labs care about a working GitHub link, humanities
# labs care about writing samples and IRB familiarity. Three buckets are
# what AcadeLink's contact-tips pages converge on, which matches what
# UIUC undergrads actually face. Default is "dry" because our user base
# skews STEM/Grainger, and a dry-lab template degrades the most gracefully
# when applied to an ambiguous CS-adjacent posting.
LabType = str  # "wet" | "dry" | "humanities"

_WET_LAB_KEYWORDS = frozenset({
    # disciplines
    "biology", "biological", "bio", "chemistry", "chemical", "biochem",
    "biochemistry", "microbiology", "molecular biology", "cell biology",
    "genetics", "neuroscience", "physiology", "pharmacology", "pharmacy",
    "biomedical", "biotechnology", "immunology", "virology", "ecology",
    "evolutionary biology", "medicine", "medical", "clinical", "nutrition",
    "food science", "plant biology", "animal science", "veterinary",
    # techniques
    "pcr", "rt-pcr", "western blot", "elisa", "cell culture", "microscopy",
    "fluorescence", "flow cytometry", "crispr", "sequencing", "rna-seq",
    "wet lab", "wet bench", "assay", "bench work", "protein purification",
    "gel electrophoresis", "pipetting", "sterile technique",
})

_DRY_LAB_KEYWORDS = frozenset({
    # disciplines
    "computer science", "computing", "data science", "software",
    "machine learning", "deep learning", "artificial intelligence",
    "computer vision", "natural language processing", "nlp", "robotics",
    # "computer engineering" carries the ampersand department form
    # ("Electrical & Computer Engineering"), which contains neither
    # "electrical engineering" nor "ece" as a substring — without it the
    # highest-weight dry signal is mute and one application-domain word
    # ("medical technologies") can flip a chip lab to wet.
    "electrical engineering", "computer engineering", "ece",
    "mechanical engineering",
    "civil engineering", "aerospace", "materials science", "physics",
    "applied math", "statistics", "operations research", "bioinformatics",
    "computational biology", "computational neuroscience",
    "human-computer interaction", "hci",
    # techniques / tools
    "python", "pytorch", "tensorflow", "jax", "scikit-learn", "pandas",
    "numpy", "kubernetes", "docker", "aws", "gcp", "azure",
    "javascript", "typescript", "react", "node", "rust", "golang",
    "c++", "cuda", "github", "git", "linux", "command-line", "shell",
    "algorithm", "data structure", "simulation", "modeling",
})

_HUMANITIES_KEYWORDS = frozenset({
    # disciplines
    "psychology", "behavioral", "cognitive science", "sociology",
    "anthropology", "economics", "political science", "public policy",
    "history", "english", "literature", "linguistics", "philosophy",
    "religion", "communication", "media", "journalism", "education",
    "social work", "labor", "industrial relations", "law", "legal",
    "art history", "music", "theater", "performing arts", "design",
    "urban planning", "geography", "gender studies", "ethnic studies",
    # methods
    "qualitative", "ethnography", "ethnographic", "interview",
    "focus group", "survey design", "archival", "content analysis",
    "discourse analysis", "literature review", "irb", "human subjects",
    "nvivo", "atlas.ti", "spss", "stata", "qualtrics",
    "transcription", "coding qualitative", "case study",
})


_SHORT_ENTRY_PATTERNS: dict[str, re.Pattern[str]] = {}


def _entry_pattern(kw: str) -> re.Pattern[str]:
    if kw not in _SHORT_ENTRY_PATTERNS:
        if kw == "bio":
            _SHORT_ENTRY_PATTERNS[kw] = re.compile(r"(?<!\w)bio")
        else:
            _SHORT_ENTRY_PATTERNS[kw] = re.compile(
                r"(?<!\w)" + re.escape(kw) + r"(?!\w)"
            )
    return _SHORT_ENTRY_PATTERNS[kw]


def _detect_lab_type(opportunity: dict) -> LabType:
    """Classify an opportunity as wet / dry / humanities lab.

    Signal weighting:
      department > title > keywords > description excerpt > required skills.

    Returns "dry" as the default for two reasons:
      1. Our user base skews STEM/Grainger so dry is the modal case.
      2. The dry-lab template's emphasis (skills + projects + GitHub
         link) degrades most gracefully for ambiguous postings — the
         worst case is a humanities student sees a slightly tech-forward
         draft, which is still recoverable. The reverse (a CS student
         getting a "highlight your IRB training" template) would feel
         badly off-target.
    """
    def _score(text: str, vocab: frozenset[str]) -> int:
        if not text:
            return 0
        lower = text.lower()
        # Longest entry first, blanking each match: nested entries must not
        # stack on one span — "mathematical biology" is ONE wet signal, not
        # two ("biology" + "bio"), and "microbiology" is one, not three.
        # The stacking systematically inflated wet scores (that vocabulary
        # is nesting-heavy) and routed theory groups to bench-technique
        # guidance (faculty-ece-817eb026, observed live 2026-08-07).
        hits = 0
        for kw in sorted(vocab, key=lambda k: (-len(k), k)):
            if len(kw) <= 4:
                # Short entries only count as standalone words: bare
                # substrings turn person/school names into phantom signals —
                # "law" and "aws" both live inside "Lawson", "irb" inside
                # "Anirban", and every University of Delaware record carried
                # a humanities point. "bio" alone keeps prefix rights
                # ("biophysics", "bioengineering" are real wet signals not in
                # the vocabulary as words) but must not fire mid-word
                # ("autobiographical").
                pattern = _entry_pattern(kw)
                if pattern.search(lower):
                    hits += 1
                    lower = pattern.sub("\x00", lower)
            elif kw in lower:
                hits += 1
                lower = lower.replace(kw, "\x00")
        return hits

    # Compose signal corpora with descending weight.
    department = (opportunity.get("department") or "").lower()
    title = (opportunity.get("title") or "").lower()
    lab = (opportunity.get("lab_or_program") or "").lower()
    keywords_text = " ".join(opportunity.get("keywords", []) or []).lower()
    is_faculty = faculty_contact_claims_unverified(opportunity)
    desc = (
        _source_backed_faculty_research_text(opportunity)
        if is_faculty
        else (
            opportunity.get("description_clean")
            or opportunity.get("description_raw")
            or ""
        )
    ).lower()[:1500]
    required_text = "" if is_faculty else " ".join(
        opportunity.get("eligibility", {}).get("skills_required", []) or []
    ).lower()

    # Weighted scores. Department signal is worth 3x a description hit
    # because UIUC department names are the cleanest classifier we have
    # (e.g. "Molecular and Cellular Biology" is unambiguously wet).
    wet = (
        3 * _score(department, _WET_LAB_KEYWORDS)
        + 2 * _score(title, _WET_LAB_KEYWORDS)
        + 2 * _score(lab, _WET_LAB_KEYWORDS)
        + 1 * _score(keywords_text, _WET_LAB_KEYWORDS)
        + 1 * _score(desc, _WET_LAB_KEYWORDS)
    )
    dry = (
        3 * _score(department, _DRY_LAB_KEYWORDS)
        + 2 * _score(title, _DRY_LAB_KEYWORDS)
        + 2 * _score(lab, _DRY_LAB_KEYWORDS)
        + 1 * _score(keywords_text, _DRY_LAB_KEYWORDS)
        + 1 * _score(desc, _DRY_LAB_KEYWORDS)
        + 2 * _score(required_text, _DRY_LAB_KEYWORDS)
    )
    hum = (
        3 * _score(department, _HUMANITIES_KEYWORDS)
        + 2 * _score(title, _HUMANITIES_KEYWORDS)
        + 2 * _score(lab, _HUMANITIES_KEYWORDS)
        + 1 * _score(keywords_text, _HUMANITIES_KEYWORDS)
        + 1 * _score(desc, _HUMANITIES_KEYWORDS)
    )

    # All-zero (no signal) -> default to dry.
    if wet == 0 and dry == 0 and hum == 0:
        return "dry"

    # Pick the leader. Ties resolve in order: wet > humanities > dry,
    # which prevents a wet-lab posting with one "machine learning"
    # buzzword from being misrouted to the dry-lab tone.
    best = max(wet, dry, hum)
    if wet == best:
        return "wet"
    if hum == best:
        return "humanities"
    return "dry"


def _clean_research_interests(text: str) -> str:
    if not text:
        return ""
    text = re.sub(
        r"^(?:I am interested in|I'm interested in|my interest is in|interested in)\s*",
        "", text.strip(), flags=re.IGNORECASE,
    )
    return text.strip().rstrip(".")


def _short_interest(interests: str) -> str:
    """A clean, short rendering of the student's interests for an email hook:
    the first one or two comma-delimited phrases, never a mid-word character
    slice (CE: `interests[:80]` cut "...vision-language models, dee" mid-word)."""
    phrases = [p.strip() for p in (interests or "").split(",") if p.strip()]
    if not phrases:
        return ""
    out = phrases[0]
    if len(phrases) > 1 and len(out) < 40:
        out = f"{out}, {phrases[1]}"
    return out.rstrip(".")


def _topic_domains(text: str) -> set[str]:
    lower = text.lower()
    return {
        name
        for name, vocab in (
            ("wet", _WET_LAB_KEYWORDS),
            ("dry", _DRY_LAB_KEYWORDS),
            ("hum", _HUMANITIES_KEYWORDS),
        )
        if any(kw in lower for kw in vocab)
    }


def _alignment_plausible(interests: str, opp_topic_text: str) -> bool:
    """Whether claiming the student's interests align with the opportunity's
    topic is defensible. A cheap lexical check cannot see semantic kinship
    ("deep learning" ~ "computer vision"), so it vetoes only on provable
    mismatch: zero shared tokens AND provably different lab-type domains
    ("machine learning" vs "environmental economics"). No topic text, or no
    domain signal on either side, means there is nothing to disprove."""
    if not opp_topic_text.strip():
        return True
    if set(_tokenize(interests)) & set(_tokenize(opp_topic_text)):
        return True
    interest_domains = _topic_domains(interests)
    opp_domains = _topic_domains(opp_topic_text)
    return not interest_domains or not opp_domains or bool(interest_domains & opp_domains)


def _source_backed_faculty_research_text(opportunity: dict) -> str:
    """Research text a faculty-contact draft is allowed to treat as evidence.

    Faculty ``description_*`` is a product-generated display summary after the
    public projection.  Keep it out of every personalization consumer.  The
    only substantive target-side inputs here are source keywords, the scraped
    ``research_areas_raw`` field, and works whose attribution was independently
    verified.
    """
    parts = [
        str(keyword).strip()
        for keyword in (opportunity.get("keywords") or [])[:20]
        if str(keyword).strip()
    ]
    metadata = opportunity.get("metadata") or {}
    if isinstance(metadata, dict):
        research_areas = metadata.get("research_areas_raw")
        if isinstance(research_areas, str) and research_areas.strip():
            parts.append(research_areas.strip())
    for work in verified_recent_works(opportunity):
        title = str(work.get("title") or "").strip()
        if title:
            parts.append(title)
    return " ".join(parts)


def _infer_research_topic(opportunity: dict) -> str:
    keywords = opportunity.get("keywords") or []
    specific = [kw for kw in keywords if kw.lower() not in _EMAIL_GENERIC_KW]

    if specific:
        if len(specific) <= 2:
            return " and ".join(specific[:2])
        return ", ".join(specific[:2]) + f", and {specific[2]}"

    # A faculty row's description is OURS, not the source's:
    # neutralize_unverified_faculty_claims rewrites description_raw/clean from
    # identity fields on every faculty_research record the API serves. Mining
    # it would quote our own summary back to the professor as their research
    # AND satisfy the anchors/has_target_data/ungrounded-claim gates that exist
    # to catch that. The professor's own words are in research_areas_raw; with
    # neither that nor keywords there is no topic, and the caller degrades to a
    # neutral inquiry.
    if faculty_contact_claims_unverified(opportunity):
        metadata = opportunity.get("metadata") or {}
        areas = str(metadata.get("research_areas_raw") or "").strip()
        return areas[:80]

    desc = opportunity.get("description_raw") or opportunity.get("description_clean") or ""
    if desc:
        noise = {"seeking", "looking for", "we are", "this position", "the lab",
                 "research opportunity with", "contact the professor"}
        for sentence in desc.split("."):
            s = sentence.strip()
            if len(s) < 20:
                continue
            if any(n in s.lower() for n in noise):
                continue
            if "$" in s:
                continue
            return s[:80]
    return ""


def _infer_research_area(opportunity: dict) -> str:
    keywords = opportunity.get("keywords") or []
    if keywords:
        specific = [kw for kw in keywords if kw.lower() not in _EMAIL_GENERIC_KW]
        if specific:
            return specific[0]
    if faculty_contact_claims_unverified(opportunity):
        metadata = opportunity.get("metadata") or {}
        raw = str(metadata.get("research_areas_raw") or "").strip()
        if raw:
            return re.split(r"[,;|\n]", raw, maxsplit=1)[0].strip()[:80]
        # The faculty title and our display summary are identity/UI fields, not
        # evidence of a research area. Verified works remain available to the
        # AI brief as works rather than being relabelled as an area here.
        return ""
    # A department name ("Siebel School of Computing and Data Science") is not a
    # research area — claiming "your work in <department>, which aligns closely
    # with my interest" is the false-alignment outreach this email avoids (CE-2).
    # Fall through to a real topical area in the title, else return nothing so the
    # hook drops to a lab-only opener.
    title = opportunity.get("title", "")
    for area in ["machine learning", "data science", "computer vision",
                 "robotics", "biology", "chemistry", "physics",
                 "neuroscience", "ecology", "engineering"]:
        if area in title.lower():
            return area
    return ""


def _target_signal_is_specific(value: object) -> bool:
    """Whether a source research label says more than a generic field.

    This is an existence check, not a ranking threshold.  Short, meaningful
    source terms such as HPC, CFD, and AMO are valid evidence even though the
    scoring anchors intentionally prefer longer strings.  Conversely, a broad
    directory bucket such as ``Machine Learning`` or ``Computer Science`` is
    not enough to tell a provider that it knows this professor's actual work.
    """
    if not isinstance(value, str):
        return False
    normalized = re.sub(r"\s+", " ", value).strip().strip(".:- ").casefold()
    normalized = re.sub(r"^research (?:areas?|topics?)\s*:\s*", "", normalized)
    if not normalized:
        return False
    generic = _EMAIL_GENERIC_KW | _BROAD_FIELDS
    pieces = [
        piece.strip().strip(".:- ")
        for piece in re.split(r"\s*(?:[,;|/]|\band\b|&)\s*", normalized)
        if piece.strip().strip(".:- ")
    ]
    return any(piece not in generic for piece in pieces)


def has_source_backed_target_evidence(
    opportunity: dict,
    parts: dict | None = None,
) -> bool:
    """Single truth source for whether a cold-email brief may personalize.

    The provider may run only when at least one source-backed, non-generic
    target signal exists: a specific keyword/area/topic/raw research label or
    a work that passed attribution verification.  ``_professor_anchors`` is a
    separate scoring aid and may keep length thresholds; it must never decide
    whether evidence exists.
    """
    signals: list[object] = list((opportunity.get("keywords") or [])[:20])
    metadata = opportunity.get("metadata") or {}
    if isinstance(metadata, dict):
        signals.append(metadata.get("research_areas_raw"))
    for key in ("research_area", "research_topic", "research_areas_raw"):
        signals.append(opportunity.get(key))
        if parts is not None:
            signals.append(parts.get(key))
    if any(_target_signal_is_specific(signal) for signal in signals):
        return True
    if parts is not None and parts.get("recent_works"):
        # _common_parts populates this only through verified_recent_works.
        return True
    return bool(verified_recent_works(opportunity))


def _match_skills_to_tasks(skills: list[str], opp: dict) -> list[str]:
    is_faculty = faculty_contact_claims_unverified(opp)
    desc = (
        _source_backed_faculty_research_text(opp)
        if is_faculty
        else (opp.get("description_raw") or opp.get("description_clean") or "")
    ).lower()
    required = (
        []
        if is_faculty
        else [s.lower() for s in opp.get("eligibility", {}).get("skills_required", [])]
    )
    desc_tokens = set(_SKILL_TOKEN_RE.findall(desc))
    req_tokens = set()
    for r in required:
        req_tokens.update(_SKILL_TOKEN_RE.findall(r))
    matched = []
    for s in skills:
        sl = s.lower()
        # Multi-word skills ("machine learning") are specific enough to match as a
        # substring; single-token skills must match a WHOLE token so "R"/"C"/"AI"
        # don't match inside "Research"/"Algorithms". Exact required entries count.
        if (" " in sl and sl in desc) or sl in desc_tokens or sl in req_tokens or sl in required:
            matched.append(s)
    return matched


def _common_parts(
    profile: dict, opportunity: dict, resume_bullets: list[str] | None = None
) -> dict:
    name = profile.get("name") or "Student"
    year = profile.get("year", "undergraduate")
    major = profile.get("major", "")
    school = profile.get("school", "UIUC")
    skills = _extract_skill_names(profile.get("hard_skills", []))
    skill_levels = _extract_skill_levels(profile.get("hard_skills", []))
    research_interests = _clean_research_interests(
        profile.get("research_interests_text", "")
    )
    linkedin_url = profile.get("linkedin_url", "")
    github_url = profile.get("github_url", "")
    scholar_url = profile.get("scholar_url", "")

    is_faculty = faculty_contact_claims_unverified(opportunity)
    pi_name = opportunity.get("pi_name") or ""
    lab = opportunity.get("lab_or_program", "")
    title = opportunity.get("title", "")
    opp_type = opportunity.get("opportunity_type", "")
    research_area = _infer_research_area(opportunity)
    research_topic = _infer_research_topic(opportunity)
    # Faculty descriptions are constructed display prose after projection, so
    # they must never enter the provider brief or anti-fabrication corpus as if
    # they were source research evidence. The real signals are carried in the
    # dedicated keyword/raw-area/verified-work fields below.
    opp_desc = "" if is_faculty else (
        opportunity.get("description_raw") or opportunity.get("description_clean") or ""
    )
    opp_skills_required = (
        []
        if is_faculty
        else opportunity.get("eligibility", {}).get("skills_required", [])
    )
    matching_skills = _match_skills_to_tasks(skills, opportunity)

    meta = opportunity.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    stated_rank = meta.get("faculty_title") or ""
    faculty_is_professor = is_faculty and is_professor_rank(stated_rank)

    # CE-6: reuse the matcher's junk-name set (adds "n/a" and "") as the single
    # source of truth, so a non-faculty source emitting "N/A" can't render
    # "Dear Professor N/A".
    #
    # Truthfulness W11: "Professor <name>" is a rank claim made on the
    # student's behalf — earned only by a stated professor rank (legacy
    # records whose rank was never scraped carry the historical "Professor"
    # stamp and keep the convention). A stated non-professor rank (Lecturer,
    # Research Scientist) or an explicitly-unknown rank ("") gets the neutral
    # full-name greeting — never a wrong honorific.
    if pi_name and pi_name.lower().strip() not in _BAD_PI_NAMES:
        if pi_name.lower().startswith(("prof", "dr")):
            recipient = pi_name
        elif is_professor_rank(stated_rank):
            recipient = f"Professor {pi_name}"
        else:
            recipient = pi_name
    elif opp_type == "summer_program":
        recipient = "Program Coordinator"
    else:
        # A generic listing with no trustworthy contact name does not prove
        # the recipient is a professor. The blank value intentionally routes
        # deterministic drafts to the neutral greeting in ``_greeting``.
        recipient = "Faculty member" if is_faculty else ""

    coursework = filter_course_entries(profile.get("coursework", []))
    lab_type = _detect_lab_type(opportunity)

    # The professor's own free-text research areas (the substantive signal) and
    # academic title — real data, surfaced for the multi-stage AI pipeline's
    # professor brief. Both may be empty; callers must tolerate that.
    faculty_title = stated_rank
    research_areas_raw = meta.get("research_areas_raw") or ""

    return dict(
        name=name, year=year, major=major, school=school,
        skills=skills, skill_levels=skill_levels,
        research_interests=research_interests,
        linkedin_url=linkedin_url, github_url=github_url,
        scholar_url=scholar_url,
        pi_name=pi_name, lab=lab, title=title,
        research_area=research_area, research_topic=research_topic,
        opp_desc=opp_desc, opp_skills_required=opp_skills_required,
        matching_skills=matching_skills, recipient=recipient,
        coursework=coursework, lab_type=lab_type,
        # Publication trust boundary: only works with explicitly verified
        # attribution may personalize output — name-matched/legacy/unknown
        # works never reach the template cite or the AI professor brief.
        recent_works=verified_recent_works(opportunity),
        faculty_title=faculty_title, research_areas_raw=research_areas_raw,
        is_faculty=is_faculty,
        faculty_is_professor=faculty_is_professor,
        # The student's real resume experience bullets (from /tailor/extract-
        # bullets, already grounded). Only the AI pipeline supplies these; the
        # deterministic template path leaves it empty.
        resume_bullets=[str(b) for b in (resume_bullets or []) if str(b).strip()],
    )


def generate_cold_email(profile: dict, opportunity: dict) -> str:
    p = _common_parts(profile, opportunity)
    return _build_balanced(p)


def generate_variants(profile: dict, opportunity: dict) -> list[dict]:
    p = _common_parts(profile, opportunity)
    lab_type = p["lab_type"]
    return [
        {"id": "balanced",  "label": "Balanced",       "text": _build_balanced(p),     "lab_type": lab_type},
        {"id": "skills",    "label": "Skills Focus",   "text": _build_skills_focus(p), "lab_type": lab_type},
        {"id": "concise",   "label": "Concise",        "text": _build_concise(p),      "lab_type": lab_type},
    ]


def _cap_subject(s: str, limit: int = 72) -> str:
    """Trim a subject line's visible text to a word boundary under `limit` so it
    isn't cut mid-word in inbox previews (the AI path enforces ~75)."""
    prefix = "Subject: "
    body = s[len(prefix):] if s.startswith(prefix) else s
    if len(body) <= limit:
        return s
    trimmed = body[:limit].rsplit(" ", 1)[0].rstrip(" ,—-")
    return prefix + trimmed


def _subject(p: dict, style: str = "") -> str:
    lab = p["lab"]
    area = p["research_area"]
    lab_type = p.get("lab_type", "dry")

    # AcadeLink's contact-tips pages use distinct subject conventions per
    # lab type — wet labs say "Inquiry", dry labs say "Interest" (skills
    # framing), humanities say "Assistant Interest" (the role is RA, not
    # a lab seat). Mirroring that vocabulary signals lab literacy.
    intent = {
        "wet": "Research Inquiry",
        "dry": "Undergraduate Research Interest",
        "humanities": "Research Assistant Interest",
    }.get(lab_type, "Research Inquiry")

    # Lead with the differentiator (research area > lab > title) and drop the
    # verbose "<Year> <Major> student" clause — the body already says who they
    # are, and that clause pushed every subject past the 75-char inbox-preview
    # cap the AI path enforces. _cap_subject guards a long area/title.
    if style == "concise":
        ctx = area or lab or p["title"] or "research"
        return _cap_subject(f"Subject: Research Interest — {ctx}")
    if area:
        return _cap_subject(f"Subject: {intent} — {area}")
    if lab and "Prof" in lab:
        return _cap_subject(f"Subject: {intent} — joining your lab")
    ctx = lab or p["title"] or "your research"
    return _cap_subject(f"Subject: {intent} — {ctx}")


def _closing(p: dict) -> str:
    lines = [f"\n\nBest regards,\n{p['name']}"]
    if p.get("linkedin_url"):
        lines.append(f"LinkedIn: {p['linkedin_url']}")
    if p.get("github_url"):
        lines.append(f"GitHub: {p['github_url']}")
    if p.get("scholar_url"):
        lines.append(f"Google Scholar: {p['scholar_url']}")
    return "\n".join(lines)


def _greeting(p: dict) -> str:
    """Render a named/role recipient, or fail closed to a neutral greeting."""
    recipient = str(p.get("recipient") or "").strip()
    return f"Dear {recipient}," if recipient else "Hello,"


def _ask_for_lab_type(lab_type: LabType, is_faculty: bool = False) -> str:
    if is_faculty:
        return (
            "\n\nWould you be open to letting me know whether you have any"
            " current or upcoming research openings for a student? If so, I"
            " would appreciate a brief conversation about how I might support"
            " your research."
        )
    if lab_type == "wet":
        return (
            "\n\nI am eager to develop my wet-lab skills further and"
            " can commit to in-person hours each week. I am happy to"
            " complete any required safety training and to start under"
            " a graduate mentor."
            "\n\nWould you be open to a brief meeting to discuss"
            " how I might contribute?"
        )
    if lab_type == "humanities":
        return (
            "\n\nI would welcome the chance to assist with literature"
            " reviews, qualitative coding, or any other tasks that"
            " would be helpful to your research."
            "\n\nWould you have 15 minutes to discuss how I might"
            " support your work?"
        )
    return (
        "\n\nI would love the chance to contribute to your lab"
        " and to learn more about your research."
        "\n\nWould you be open to a short meeting?"
        " I am happy to work around your availability."
    )


def _at_school(p: dict) -> str:
    school = (p.get("school") or "").strip()
    return f" at {school}" if school else ""


def _student_self(p: dict, connector: str) -> str:
    """Grammatical self-description that omits any missing year/major/school
    without leaving double spaces or dangling words (CE-3). ``connector`` picks
    the voice: 'studying' -> 'a sophomore studying CS', 'major' -> 'a sophomore
    CS major', 'student' -> 'a sophomore CS student'."""
    year = (p.get("year") or "").strip()
    major = (p.get("major") or "").strip()
    at = _at_school(p)
    if not major:
        return (f"a {year} student" if year else "a student") + at
    if connector == "studying":
        return (f"a {year} studying {major}" if year else f"a student studying {major}") + at
    if connector == "major":
        return f"a {' '.join(filter(None, [year, major]))} major{at}"
    return f"a {' '.join(filter(None, [year, major]))} student{at}"


def _build_balanced(p: dict) -> str:
    subject = _subject(p)
    greeting = _greeting(p)

    intro = f"My name is {p['name']}, and I am {_student_self(p, 'studying')}."
    intro += _p1_research_hook(p)
    intro += _recent_work_cite(p)

    skills_para = _p2_skills_applied(p)
    ask = _ask_for_lab_type(
        p.get("lab_type", "dry"), is_faculty=bool(p.get("is_faculty"))
    )
    closing = _closing(p)
    body = f"{greeting}\n\n{intro}{skills_para}{ask}{closing}"
    return f"{subject}\n\n{body}"


def _build_skills_focus(p: dict) -> str:
    subject = _subject(p)
    greeting = _greeting(p)

    intro = f"My name is {p['name']}, and I am {_student_self(p, 'major')}."
    intro += _p1_research_hook(p)
    intro += _recent_work_cite(p)

    skills_para = ""
    skills = p["skills"]
    matching = p["matching_skills"]
    levels = p["skill_levels"]

    if skills:
        expert_skills = [s for s in skills if levels.get(s) == "expert"]
        experienced_skills = [s for s in skills if levels.get(s) == "experienced"]

        if expert_skills:
            skills_para += f"\n\nI have strong proficiency in {', '.join(expert_skills[:3])}"
            if experienced_skills:
                skills_para += f" and working experience with {', '.join(experienced_skills[:3])}"
            skills_para += "."
        elif experienced_skills:
            skills_para += f"\n\nI have hands-on experience with {', '.join(experienced_skills[:4])}."
        else:
            # Beginner-only: the same standard the AI prompt's hard rules
            # impose — never presented as experience, at most exposure.
            skills_para += f"\n\nI have foundational exposure to {', '.join(skills[:4])}."

        seasoned = {
            s.lower() for s in skills
            if levels.get(s) in ("expert", "experienced")
        }
        if matching:
            seasoned_matching = [s for s in matching if s.lower() in seasoned]
            if seasoned_matching:
                if p.get("is_faculty"):
                    skills_para += (
                        f" In particular, my background in {', '.join(seasoned_matching)}"
                        f" is relevant to your research and current projects."
                    )
                else:
                    skills_para += (
                        f" In particular, my background in {', '.join(seasoned_matching)}"
                        f" is directly applicable to this position."
                    )
            else:
                # A beginner-level overlap is a reason to be interested, not a
                # background to claim.
                if p.get("is_faculty"):
                    skills_para += (
                        f" I am actively building on {', '.join(matching)},"
                        f" which is relevant to your research areas."
                    )
                else:
                    skills_para += (
                        f" I am actively building on {', '.join(matching)},"
                        f" which this position uses directly."
                    )

        required = p["opp_skills_required"]
        if required:
            have = [s for s in required if s.lower() in seasoned]
            if have:
                if p.get("is_faculty"):
                    skills_para += (
                        f" I already work with {', '.join(have)}, which could"
                        " support your research and current projects."
                    )
                else:
                    skills_para += f" I already work with {', '.join(have)} which this role requires."

    coursework = p.get("coursework", [])
    if coursework:
        skills_para += f" Relevant coursework includes {', '.join(coursework[:3])}."

    lab_type = p.get("lab_type", "dry")
    if lab_type == "dry" and p.get("github_url"):
        skills_para += f" My recent work is on GitHub at {p['github_url']}."

    if p.get("is_faculty"):
        ask = (
            "\n\nCould I ask whether you have any current or upcoming research"
            " openings for a student? If so, I would welcome a brief conversation"
            " about how my skills could support your research."
        )
    else:
        ask = (
            "\n\nI would welcome the opportunity to discuss how my skills"
            " could support your current projects."
            "\n\nWould you have 15 minutes for a brief conversation?"
        )
    closing = _closing(p)
    body = f"{greeting}\n\n{intro}{skills_para}{ask}{closing}"
    return f"{subject}\n\n{body}"


def _build_concise(p: dict) -> str:
    subject = _subject(p, style="concise")
    greeting = _greeting(p)

    core = f"I am {_student_self(p, 'student')}"
    if p["research_area"]:
        core += (
            f", interested in your research in {p['research_area']}"
            if p.get("is_faculty")
            else f", interested in {p['research_area']}"
        )
    core += "."

    skills = p["skills"]
    matching = p["matching_skills"]
    levels = p["skill_levels"]

    def _claim(names: list[str]) -> str:
        # Same beginner rule as every other builder: exposure, not experience.
        if all(levels.get(s, "beginner") == "beginner" for s in names):
            return f" I have foundational exposure to {', '.join(names)}."
        return f" I have experience with {', '.join(names)}."

    if matching:
        chosen = matching[:3]
        verb = "is" if len(chosen) == 1 else "are"
        target = "your research" if p.get("is_faculty") else "your work"
        core += _claim(chosen)[:-1] + f", which {verb} relevant to {target}."
    elif skills:
        core += _claim(skills[:3])

    if p.get("is_faculty"):
        ask = (
            " Could I ask whether you have any current or upcoming research"
            " openings for a student?"
        )
    else:
        ask = " Would you be open to a brief conversation about potential opportunities in your lab?"

    closing = _closing(p)
    body = f"{greeting}\n\n{core}{ask}{closing}"
    return f"{subject}\n\n{body}"


def _p1_research_hook(p: dict) -> str:
    research_topic = p["research_topic"]
    research_area = p["research_area"]
    lab = p["lab"]
    interests = p["research_interests"]

    # CE-1: a bare broad department field ("physics", "molecular biology") is not
    # a specific topic — claiming a student's interest "aligns closely" with it is
    # exactly the lazy, unsupported outreach this email is meant to avoid. Drop a
    # broad field so the hook falls back to a lab-only opener that makes no
    # false-alignment claim.
    if research_area and research_area.lower() in _BROAD_FIELDS:
        research_area = ""
    if research_topic and research_topic.lower() in _BROAD_FIELDS:
        research_topic = ""

    # CE-7: every interest-bearing branch below asserts alignment ("aligns
    # closely", "strongly resonates", "closely related") but nothing ever
    # compared the opportunity's topic to the student's interests. On a
    # provable mismatch, drop the interests so the claim-free openers below
    # ("I came across ... and would like to learn more") take over.
    if interests and not _alignment_plausible(interests, f"{research_topic} {research_area}"):
        interests = ""

    # CE-2: compute the lab reference once so every branch drops the article
    # before a possessive proper-noun lab ("Prof. X's Research Group") — one
    # branch used to hardcode the ungrammatical "in the {lab}".
    if lab and lab[0].isupper() and ("Prof" in lab or "'s" in lab):
        lab_ref = lab
    elif lab:
        lab_ref = f"the {lab}"
    else:
        lab_ref = ""

    is_short_topic = bool(research_topic and len(research_topic) < 50 and " " in research_topic)
    short_interest = _short_interest(interests)

    if interests and is_short_topic and lab_ref:
        return (
            f" I am writing because your work on {research_topic}"
            f" in {lab_ref} strongly resonates with my interest in {short_interest}."
        )
    if interests and is_short_topic:
        return (
            f" I am writing because your research on {research_topic}"
            f" closely aligns with my interest in {short_interest}."
        )
    if interests and research_area and lab_ref:
        return (
            f" I came across {lab_ref} and your work in {research_area},"
            f" which aligns closely with my interest in {short_interest}."
        )
    if interests and research_area:
        return (
            f" I am reaching out because your work in {research_area}"
            f" aligns with my interest in {short_interest}."
        )
    if interests and lab_ref:
        return (
            f" I came across {lab_ref} and would like to ask whether there are"
            f" ways for a student interested in {short_interest} to contribute."
        )
    if is_short_topic and lab_ref:
        return (
            f" I came across {lab_ref} and your work on {research_topic},"
            f" and would like to learn more about opportunities to contribute."
        )
    if is_short_topic:
        return (
            f" I came across your research on {research_topic}"
            f" and would like to learn more about opportunities"
            f" to contribute."
        )
    if lab_ref:
        return (
            f" I came across {lab_ref} and am very interested"
            f" in contributing to your research."
        )
    return ""


def _recent_work_cite(p: dict) -> str:
    """One sentence citing the professor's newest usable paper — the template
    path's counterpart to the AI prompt's recent-works block, so the free tier
    also shows the student did their homework. ``p["recent_works"]`` comes
    through the publication trust gate (``_common_parts`` →
    ``verified_recent_works``), so "Your recent paper" is only ever said of a
    work with explicitly verified attribution; name-matched/legacy candidates
    never reach this sentence. "Caught my attention" claims only that they saw
    the title (they did — it is on the profile they are emailing from), never
    that they read the paper. OpenAlex
    titles can carry markup (``[<sup>18</sup>F]FDG``) and can run to hundreds
    of characters, so tags are stripped and only a 10-110 char title is cited;
    none qualifying → no sentence."""
    for w in p.get("recent_works", [])[:3]:
        title = re.sub(r"<[^>]+>", "", str(w.get("title") or ""))
        title = re.sub(r"\s+", " ", title).strip()
        if not 10 <= len(title) <= 110:
            continue
        year = w.get("year")
        yr = f" ({year})" if year else ""
        return f' Your recent paper "{title}"{yr} caught my attention.'
    return ""


def _p2_skills_applied(p: dict) -> str:
    skills = p["skills"]
    if not skills:
        return ""

    matching = p["matching_skills"]

    task_keywords = {
        "Python":     "data processing, analysis, and scripting",
        "MATLAB":     "data cleaning, visualization, and numerical computation",
        "R":          "statistical analysis and data visualization",
        "PyTorch":    "building and training deep learning models",
        "TensorFlow": "building and training deep learning models",
        "Java":       "software development and object-oriented design",
        "C++":        "systems programming and performance-critical applications",
        "C":          "low-level systems programming",
        "JavaScript": "web development and interactive applications",
        "SQL":        "database querying and data management",
        "React":      "building interactive user interfaces",
        "OpenCV":     "image processing and computer vision tasks",
        "pandas":     "data wrangling and analysis",
        "Git":        "version control and collaborative development",
        "Linux":      "system administration and command-line tooling",
        "Docker":     "containerization and reproducible environments",
        "LaTeX":      "technical writing and documentation",
    }

    top = (matching or skills)[:3]
    applications = []
    for s in top:
        app = task_keywords.get(s)
        if app:
            applications.append(f"{s} for {app}")
        else:
            applications.append(s)

    if len(applications) == 1:
        skill_str = applications[0]
    elif len(applications) == 2:
        skill_str = f"{applications[0]} and {applications[1]}"
    else:
        skill_str = f"{', '.join(applications[:-1])}, and {applications[-1]}"

    # The same standard the AI prompt's hard rules impose: a skill the student
    # marked BEGINNER is never presented as experience — at most foundational
    # exposure. This template is the fallback the fabrication gate degrades
    # to, so it cannot itself overstate.
    levels = p["skill_levels"]
    all_beginner = all(levels.get(s, "beginner") == "beginner" for s in top)
    verb = (
        "I have foundational exposure to"
        if all_beginner
        else "I have experience with"
    )
    para = f"\n\n{verb} {skill_str}."

    # When `top` is already the matching skills (matching is non-empty), naming
    # them again here just repeats the same list. Keep the relevance emphasis
    # without re-listing the identical skills.
    if matching and len(matching) >= 2:
        if p.get("is_faculty"):
            para += " These are relevant to your research and current projects."
        else:
            para += " These directly apply to the work described in your posting."

    coursework = p.get("coursework", [])
    if coursework:
        para += f" Relevant coursework includes {', '.join(coursework[:3])}."

    return para
