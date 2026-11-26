"""Student-facing terms checked on the same host pages as these two 2027 cohorts."""

from src.program_windows import SMU_WINDOW, ProgramWindow, reviewed_window

CRISP_ID = "sro-3ec4ea4e"
SMU_IDS = ("nsf-reu-2447670", "sro-44f176cd")
IDS = (CRISP_ID, *SMU_IDS)
_CRISP_PAGE = "https://cancer.iu.edu/education/summer/acs-cancer-research-internship.html"
_SMU_PAGE = (
    "https://www.smu.edu/provost/saes/academic-enrichment/engaged-learning/"
    "research/research-experiences-undergraduates/data-science-reu"
)
_SMU_STIPEND = "$5,600 stipend"
_SMU_YEARS = ("sophomore", "junior")
# The application portal and the campus program page describe the same award.
_SMU_QUOTES = {
    "paid": (_SMU_PAGE, "$5600 stipend"),
    "compensation": (_SMU_PAGE, "$5600 stipend"),
    "duration": (SMU_WINDOW.page, "The REU runs each summer for eight weeks"),
    "class_year": (_SMU_PAGE, "Completed second or third year of college or university with a strong academic record"),
}
_CRISP_QUOTES = {
    "paid": (_CRISP_PAGE, "Receive a stipend (payment)"),
    "min_gpa": (_CRISP_PAGE, "Have a cumulative GPA of 3.2 or higher"),
}


def checked_window(record: dict) -> ProgramWindow | None:
    oid = record.get("id")
    if oid not in IDS:
        return None
    window = reviewed_window(record)
    expected = _CRISP_PAGE if oid == CRISP_ID else SMU_WINDOW.page
    return window if window and window.page == expected else None


def apply_terms(record: dict) -> None:
    if checked_window(record) is None:
        return
    eligibility = record.get("eligibility")
    if not isinstance(eligibility, dict):
        return
    inferred = record["metadata"].get("inferred_fields")
    record["paid"] = "yes"
    if isinstance(inferred, dict):
        inferred.pop("paid", None)
    if record["id"] == CRISP_ID:
        eligibility["min_gpa"] = 3.2
        return
    record["compensation_details"] = _SMU_STIPEND
    record["duration"] = "8 weeks"
    eligibility["preferred_year"] = list(_SMU_YEARS)
    if isinstance(inferred, dict):
        inferred.pop("eligibility.preferred_year", None)
    if record["source"] == "nsf_reu":
        # This collector extracts skills from the grant abstract, which lists
        # what the bootcamp teaches. The application does not require them.
        eligibility["skills_required"] = []


def quote(record: dict, field: str) -> dict | None:
    window = checked_window(record)
    if window is None:
        return None
    quotes = _CRISP_QUOTES if record["id"] == CRISP_ID else _SMU_QUOTES
    evidence = quotes.get(field)
    if evidence is None:
        return None
    eligibility = record.get("eligibility")
    if not isinstance(eligibility, dict):
        eligibility = {}
    observed = {
        "paid": (record.get("paid"), "yes"),
        "compensation": (record.get("compensation_details"), _SMU_STIPEND),
        "duration": (record.get("duration"), "8 weeks"),
        "class_year": (eligibility.get("preferred_year"), list(_SMU_YEARS)),
        "min_gpa": (eligibility.get("min_gpa"), 3.2),
    }
    actual, expected = observed[field]
    if actual != expected:
        return None
    page, text = evidence
    return {"text": text, "source_url": page, "observed_at": window.reviewed_on.isoformat()}
