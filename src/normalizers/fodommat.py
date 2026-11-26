"""The requirements shared by the host and directory records for summer 2027."""

from collections.abc import Collection, Iterable

from src.program_windows import NCSA_DIRECTORY, ProgramWindow, reviewed_window

HOST_ID = "ext-uiuc-ncsa-reu"
DIRECTORY_ID = "sro-1532726e"
IDS = (HOST_ID, DIRECTORY_ID)
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
    if record.get("id") not in IDS or record.get("deadline") != "2027-02-15":
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
    if record.get("id") not in IDS or field not in _FACTS:
        return None
    values, quote = _FACTS[field]
    eligibility = record.get("eligibility")
    if not isinstance(eligibility, dict) or eligibility.get(field) != list(values):
        return None
    window = _cohort(record)
    if window is None:
        return None
    return {"text": quote, "source_url": window.page, "observed_at": window.reviewed_on.isoformat()}


def same_offering(host: dict | None, directory: dict | None, *, projected: bool = False) -> bool:
    """Both original records still describe the checked host's summer 2027 cohort."""
    if not host or not directory:
        return False
    for record, oid, source, url in (
        (host, HOST_ID, "manual", _HOST), (directory, DIRECTORY_ID, "uiuc_sro", NCSA_DIRECTORY),
    ):
        if record.get("id") != oid or record.get("source") != source or record.get("url") != url:
            return False
        if _cohort(record) is not None:
            continue
        # A projected match card omits the raw source metadata. Its opening
        # was already bound to both the review and the source before projection.
        opening = record.get("application_opens")
        if not (projected and isinstance(opening, dict) and record.get("deadline") == "2027-02-15"
                and opening.get("source_url") == _HOST and opening.get("on") == "2026-12-15"):
            return False
    return True


def collapse_ids(ids: list[str], preferred: str = HOST_ID) -> list[str]:
    """Caller has checked the offering and applied the student's filters."""
    if HOST_ID not in ids or DIRECTORY_ID not in ids:
        return ids
    hide = HOST_ID if preferred == DIRECTORY_ID else DIRECTORY_ID
    return [oid for oid in ids if oid != hide]


def records_share_offering(records: Iterable[dict]) -> bool:
    members = {r["id"]: r for r in records if r.get("id") in IDS}
    return same_offering(members.get(HOST_ID), members.get(DIRECTORY_ID))


def preferred_source_id(source: str, previous: Collection[str] = ()) -> str:
    if source == "uiuc_sro" or (not source and DIRECTORY_ID in previous and HOST_ID not in previous):
        return DIRECTORY_ID
    return HOST_ID


def reconcile_pending(ids: list[str], source: str) -> list[str]:
    """Keep old pending links, removing only a verified duplicate or a differently scoped peer."""
    if source:
        wanted = {"manual": HOST_ID, "uiuc_sro": DIRECTORY_ID}.get(source)
        return [oid for oid in ids if oid not in IDS or oid == wanted]
    return collapse_ids(ids, preferred_source_id(source, ids))
