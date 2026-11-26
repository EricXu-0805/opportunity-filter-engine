"""Published student and recommender terms for Boston University's 2027 STaRS cohort."""

from src.program_windows import STARS_HOST, STARS_SRO_IDS, STARS_WINDOW, ProgramWindow, reviewed_window

CAMPUS_ID = "bu-bbc659c6ac92"
IDS = (CAMPUS_ID, *STARS_SRO_IDS)
FAQ = STARS_HOST + "frequently-asked-questions/"
CITIZENSHIP = "U.S. citizen or permanent resident"
YEARS = ("sophomore", "junior")  # The student's current year, before the summer.
_CITIZENSHIP_EXCERPT = "citizen or permanent resident"
_QUOTES = {
    "class_year": (STARS_HOST, "Rising 3rd or 4th year"),
    "min_gpa": (STARS_HOST, "at least 3.0"),
    "citizenship": (STARS_HOST, _CITIZENSHIP_EXCERPT),
    "international_students": (STARS_HOST, _CITIZENSHIP_EXCERPT),
    "work_authorization_notes": (STARS_HOST, _CITIZENSHIP_EXCERPT),
    "requirements": (STARS_HOST, "Three letters of recommendation"),
}
# Facet values summarize the applicable rule. Each short excerpt links straight
# to the page that establishes it, including the FAQ's distinct recommender date.
_EXTRA = {
    "eligibility": {
        "majors": ("STEM", STARS_HOST, "STEM"),
        "degree_path": ("Full-time or part-time STEM studies leading to a bachelor's degree. "
                        "Expected graduation in 2028 or later.", STARS_HOST, "2028 and beyond"),
        "transfer_students": ("Two-year college students may apply. In the statement of interest, "
                              "name the bachelor's programs you are applying to and say whether "
                              "you have been admitted.", FAQ, "two-year college"),
        "medical_students": ("Medical students may apply only in their first year at Boston University.",
                             FAQ, "first year Boston University medical students"),
        "gpa_context": ("The application lets you explain a GPA below 3.0 on a 4.0 scale.",
                        FAQ, "explain any issues with GPA"),
        "research_background": ("An interest in biological research is required. Previous research experience is optional.",
                                STARS_HOST, "prior research experience (optional)"),
    },
    "application_method": {
        "recommendation_deadline": ("BU must receive all three letters by February 1. The FAQ gives "
                                    "the month and day without specifying a year.", FAQ, "on or before February 1st"),
    },
}


def checked_window(record: dict) -> ProgramWindow | None:
    if record.get("id") not in IDS:
        return None
    window = reviewed_window(record)
    if not window or window.page != STARS_HOST or record["metadata"].get("is_active") is False:
        return None
    return window


def apply_terms(record: dict) -> None:
    if not checked_window(record):
        return
    eligibility, application = record.get("eligibility"), record.get("application")
    if not isinstance(eligibility, dict) or not isinstance(application, dict):
        return
    record["opportunity_type"] = "summer_program"
    # SRO assigns differing major tags from the directory text. BU welcomes
    # STEM applicants generally and gives examples rather than a fixed list.
    eligibility.update(majors=[], preferred_year=list(YEARS), min_gpa=3.0, citizenship_required=True,
                       international_friendly="no", work_auth_notes=CITIZENSHIP)
    application["requires_recommendation"] = "yes"
    stamps = record["metadata"].get("inferred_fields")
    if isinstance(stamps, dict):
        for field in ("majors", "preferred_year", "min_gpa", "citizenship_required", "international_friendly"):
            stamps.pop("eligibility." + field, None)


def _citation(page: str, excerpt: str) -> dict:
    return {"text": excerpt, "source_url": page, "observed_at": STARS_WINDOW.reviewed_on.isoformat()}


def quote(record: dict, facet: str) -> dict | None:
    evidence = _QUOTES.get(facet)
    if not evidence or not checked_window(record):
        return None
    eligibility = record.get("eligibility")
    application = record.get("application")
    if not isinstance(eligibility, dict) or not isinstance(application, dict):
        return None
    matches = {
        "class_year": eligibility.get("preferred_year") == list(YEARS),
        "min_gpa": eligibility.get("min_gpa") == 3.0,
        "citizenship": eligibility.get("citizenship_required") is True,
        "international_students": eligibility.get("international_friendly") == "no",
        "work_authorization_notes": eligibility.get("work_auth_notes") == CITIZENSHIP,
        "requirements": application.get("requires_recommendation") == "yes",
    }
    return _citation(*evidence) if matches[facet] else None


def detail_facts(record: dict, group: str):
    if checked_window(record):
        for facet, (value, page, excerpt) in _EXTRA[group].items():
            yield facet, value, _citation(page, excerpt)
