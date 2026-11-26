"""Read academic ranks from the named profile header of Delaware materials faculty."""

import re
from datetime import UTC, date, datetime

from src.collectors import faculty_graph, ucb_common
from src.collectors.import_document import ImportDocumentError
from src.contact_instructions import same_source_page
from src.evidence import RETIRED_TITLE_REASON, is_retired_title

_PROFILE = re.compile(r"https://mseg\.udel\.edu/people/(?!faculty/?$)[a-z0-9-]+/?\Z")
_ID_PREFIX = "faculty-udel-mseg-"
_ACADEMIC_RANK = re.compile(r"\b(?:professor|instructor|lecturer)\b", re.IGNORECASE)
_AWARD = re.compile(r"\b(?:awards?|medals?|prizes?|winner|recipient|of the year)\b", re.IGNORECASE)


def _read(row: dict) -> str:
    url = row["url"]
    if faculty_graph._source_budget_spent():
        return "unavailable"
    try:
        page = ucb_common.fetch_soup(url, bounded=True, timeout=8, max_retries=1)
    except ImportDocumentError:
        return "unavailable"
    if page is None or ucb_common.profile_page_is_denial(page):
        return "unavailable"
    if (getattr(page, "_ofe_requested_url", None) == url and getattr(page, "_ofe_final_url", None)
            and not same_source_page(url, page._ofe_final_url)):
        return "changed_target"
    observation = ucb_common._fetch_profile_contact_observation(page, requested_url=url, record_profile_url=url)
    if not observation:
        return "unavailable"
    final, stamp = observation
    try:
        checked = datetime.fromisoformat(stamp)
    except ValueError:
        return "unavailable"
    if checked.tzinfo is None or checked > datetime.now(UTC):
        return "unavailable"
    names = page.select("#main-content .et_pb_post_title .et_pb_title_container > h1.entry-title")
    if len(names) != 1:
        return "unavailable"
    shown = names[0].get_text(" ", strip=True)
    column = names[0].find_parent(class_="et_pb_column")
    # This module immediately follows the named profile in the same column.
    # A later h5 lists institute duties and subsequent modules contain awards.
    modules = column.select(":scope > .et_pb_post_title + .et_pb_text > .et_pb_text_inner") if column else []
    if len(modules) != 1:
        return "unavailable"
    headings = modules[0].select(":scope > :is(h2,h4)")
    rank = " ".join(headings[0].stripped_strings) if len(headings) == 1 else ""
    retired = is_retired_title(rank)
    valid_rank = bool((_ACADEMIC_RANK.search(rank) or retired) and not _AWARD.search(rank))
    metadata = row["metadata"]
    checked_on = checked.astimezone(UTC).date().isoformat()
    if not ucb_common._strict_profile_name_matches(shown, row["pi_name"]):
        if not valid_rank or not faculty_graph._is_person_name(shown):
            return "unavailable"
        metadata.update(is_active=False, deactivation_reason="profile_identity_mismatch", deactivated_at=checked_on)
        return "identity_mismatch"
    if not valid_rank or (retired and len(_ACADEMIC_RANK.findall(rank)) > 1):
        return "no_rank"
    metadata["faculty_title"] = rank
    metadata["faculty_title_observation"] = {
        "name": row["pi_name"], "title": rank, "profile": url, "source": final, "checked_on": checked_on,
    }
    if retired:
        metadata.update(is_active=False, deactivation_reason=RETIRED_TITLE_REASON, deactivated_at=checked_on)
    return "observed"


def observe_materials_ranks(rows: list[dict]) -> None:
    for row in rows:
        if row["id"].startswith(_ID_PREFIX) and _PROFILE.fullmatch(row.get("url") or ""):
            row["metadata"]["faculty_title_read_status"] = _read(row)


def preserve_unread_rank(previous: dict, incoming: dict) -> None:
    """Only a newly confirmed active rank can reopen an archived materials profile."""
    if (not incoming["id"].startswith(_ID_PREFIX) or previous.get("id") != incoming["id"]
            or previous.get("pi_name") != incoming.get("pi_name")):
        return
    new, old = incoming["metadata"], previous["metadata"]
    status = new.get("faculty_title_read_status")
    if (old.get("is_active") is False and new.get("is_active") is False
            and old.get("deactivation_reason") == new.get("deactivation_reason") and old.get("deactivated_at")):
        new["deactivated_at"] = old["deactivated_at"]
    if status == "observed":
        return
    if (old.get("is_active") is False and old.get("deactivation_reason")
            in (RETIRED_TITLE_REASON, "profile_identity_mismatch") and new.get("is_active") is not False):
        new.update(is_active=False, deactivation_reason=old["deactivation_reason"], deactivated_at=old.get("deactivated_at"))
    receipt = old.get("faculty_title_observation")
    if status != "unavailable" or not isinstance(receipt, dict):
        return
    try:
        checked_on = date.fromisoformat(receipt["checked_on"])
    except (KeyError, TypeError, ValueError):
        return
    if (checked_on <= datetime.now(UTC).date() and receipt.get("name") == incoming["pi_name"]
            and receipt.get("title") and receipt["title"] == old.get("faculty_title")
            and receipt.get("profile") == previous.get("url") == incoming.get("url")
            and same_source_page(incoming["url"], receipt.get("source"))):
        new["faculty_title"] = receipt["title"]
        new["faculty_title_observation"] = receipt.copy()
