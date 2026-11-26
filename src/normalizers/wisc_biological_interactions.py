"""2027 WISCIENCE terms from the host overview and applicant FAQ."""
from src.program_windows import WINDOWS, ProgramWindow, reviewed_window

CAMPUS_ID = "wisc-86cba49b83d7"
IDS = (CAMPUS_ID, "sro-595e912d", "sro-3c378261")
WINDOW = WINDOWS[("wisc", "ibs_srp_cmbs_reu")]
SUMMARY = (
    "Undergraduates conduct mentored bioscience research at UW–Madison. "
    "UW–Madison students may apply. Funding for students from UW–Madison is limited. "
    "Applicants must have finished at least two undergraduate semesters by the start "
    "of the program and have at least one semester left afterward. WISCIENCE generally "
    "expects a 3.0 GPA and sometimes admits applicants with a lower GPA. "
    "The 2027 program runs from June 1 to August 7. All offers depend on funding."
)
SUPPORT = (
    "$7,000 stipend, housing, partial meal plan, health insurance if needed, and round-trip travel. "
    "All offers depend on funding."
)


def checked_window(record: dict) -> ProgramWindow | None:
    if record.get("id") not in IDS:
        return None
    if record.get("source") == "uiuc_sro" and record.get("organization") != "University of Wisconsin-Madison":
        return None
    window = reviewed_window(record)
    if window and window.page == WINDOW.page and window.closes_on == WINDOW.closes_on:
        return window
    return None


def apply_terms(record: dict) -> None:
    if not checked_window(record):
        return
    record.update(paid="yes", compensation_details=SUPPORT, duration="10 weeks")
    # This cohort uses completed and remaining semesters, not fixed class names.
    # The host permits individual GPA exceptions, so do not add a hard cutoff.
    inferred = record["metadata"].get("inferred_fields")
    if isinstance(inferred, dict):
        for key in ("paid", "eligibility.preferred_year", "eligibility.min_gpa"):
            inferred.pop(key, None)
    eligibility = record.get("eligibility")
    if isinstance(eligibility, dict):
        eligibility.update(preferred_year=[], min_gpa=None)
    if record["id"] == CAMPUS_ID:
        previous = record.get("description") or ""
        _, heading, from_page = previous.partition("\n\nFrom the program page: ")
        record["description"] = SUMMARY + heading + from_page
        record["description_clean"] = record["description"][:1500]
    else:
        clean = record.get("description_clean") or ""
        if not clean.startswith(SUMMARY):
            clean = (SUMMARY + "\n\n" + clean).rstrip()
        record["description_clean"] = clean[:1500]


def quote(record: dict, field: str) -> dict | None:
    window = checked_window(record)
    if not window:
        return None
    terms = {
        "paid": (record.get("paid") == "yes", "$7,000 stipend"),
        "compensation": (record.get("compensation_details") == SUPPORT, "$7,000 stipend"),
        "duration": (record.get("duration") == "10 weeks", "Length: 10 weeks"),
    }
    matches, excerpt = terms.get(field, (False, ""))
    if matches:
        return {"text": excerpt, "source_url": window.page, "observed_at": window.reviewed_on.isoformat()}
    return None
