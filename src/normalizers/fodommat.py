"""The requirements shared by the host and directory records for summer 2027."""

from src.program_windows import ProgramWindow, reviewed_window

_IDS = ("ext-uiuc-ncsa-reu", "sro-1532726e")
_HOST = "https://reu.ncsa.illinois.edu/"
_YEARS = ("freshman", "sophomore", "junior", "senior")
_FACTS = {
    "majors": (("all",), "any major and in any year of undergraduate studies"),
    "preferred_year": (_YEARS, "any major and in any year of undergraduate studies"),
    "skills_required": (
        ("Python", "machine learning"),
        "experience with Python is required as well as some exposure to machine learning",
    ),
}


def _cohort(record: dict) -> ProgramWindow | None:
    if record.get("id") not in _IDS or record.get("deadline") != "2027-02-15":
        return None
    window = reviewed_window(record)
    return window if window and window.page == _HOST else None


def apply_requirements(record: dict) -> None:
    if _cohort(record) is None:
        return
    eligibility = record.get("eligibility")
    if not isinstance(eligibility, dict):
        return
    inferred = record["metadata"].get("inferred_fields")
    for field, (values, _) in _FACTS.items():
        eligibility[field] = list(values)
        if isinstance(inferred, dict):
            inferred.pop("eligibility." + field, None)


def host_quote(record: dict, field: str) -> dict | None:
    """Attribute only the particular field values checked against this cohort."""
    if record.get("id") not in _IDS or field not in _FACTS:
        return None
    values, quote = _FACTS[field]
    eligibility = record.get("eligibility")
    if not isinstance(eligibility, dict) or eligibility.get(field) != list(values):
        return None
    window = _cohort(record)
    if window is None:
        return None
    return {"text": quote, "source_url": window.page, "observed_at": window.reviewed_on.isoformat()}
