"""Carnegie Mellon's undergraduate research project list, from a dated snapshot.

CMU's undergraduate research office publishes a list of projects faculty are
recruiting undergraduates for — a Google Sheet linked from
https://www.cmu.edu/uro/getting-started-in-research/index.html. The sheet
opens only for a CMU Andrew login, so no collector can fetch it. Someone with
a CMU account exports it by hand, and ``import_export`` below turns the export
into ``data/snapshots/cmu_uro_projects.json``. This module turns that file
into listings on every CMU refresh.

The site shows what the owner approved and nothing more: per project a short
title, the person who listed it (name, position, department), the date it was
listed, how to reach that person, and the source. So that is all the snapshot
keeps. The sheet's synopses, skills, keywords, end dates and inquiry
instructions stay on CMU's list, and so does any address a listing gives for
someone other than the person shown. The repository is public, so the file is
held to the same scope as the site: ``validate_snapshot`` refuses any other
field and any address that is not a row's contact.

Nothing here is ever refreshed silently. ``last_verified`` is the snapshot
date, not the run date, and the description says the list may not be updated
as positions are filled (CMU's own caveat). The snapshot carries three dates:

  * ``snapshot_date`` — when the sheet was exported;
  * ``refresh_due``   — when a new export is needed (start of next semester);
    from then on ops-scan files a manual_review incident and the weekly
    ``snapshot-reminder`` workflow emails the operator (``refresh_status`` /
    ``reminder`` / ``email_due`` below are the one definition both use);
  * ``valid_until``   — the end of the academic year the list covers. After
    it every row is emitted inactive with ``deactivation_reason: expired``,
    and ``metadata.expires_at`` lets ``deactivate_past`` retire the rows in
    the committed shard even on a day CMU is not refreshed. With the rows
    retired nothing on the site is stale, so the reminder stops asking: the
    incident is filed once and the email repeats at most monthly.

Rows are retired, never deleted: a row a newer snapshot no longer lists is
kept inactive with ``deactivation_reason: absent_from_snapshot``.

Refreshing (the reminder repeats this):
  1. Open the sheet with an @andrew.cmu.edu Google account (link above) and
     download the Projects List tab as CSV (File > Download > Comma-separated
     values). Not PDF: the PDF export cuts long cells at the page edge. Keep
     the CSV outside the repository; the importer refuses one inside it.
  2. ``python -m src.collectors.cmu_uro_projects --import-csv EXPORT.csv
     --snapshot-date ... --refresh-due ... --valid-until ... --contributor ...``
     rewrites the snapshot. A response already in it keeps its reviewed
     title, name and contact, provided the export still shows that contact;
     every other decision is printed for a person: a title for each new
     listing and, where the inquiry answer is not plainly one address, form
     or page, the contact route. The file does not validate until they are
     made.
  3. Update the values tests/test_cmu_uro_projects.py and
     tests/test_snapshot_reminder.py pin to this snapshot (dates, counts,
     ids) to the new export; ``pytest`` on both validates the file, and the
     next CMU refresh publishes it.

Ids are ``cmu-uro-`` + md5(source :: submitted_at | respondent address),
computed from the export: a response keeps its id across exports, and two
responses never share one (two rows in the 2026-27 sheet carry the same
timestamp). The snapshot stores the id, not the respondent address.

Imports stay standard-library at module level so the reminder checker
(``scripts/snapshot_reminder.py``) runs without installing requirements.

Usage:
    python -m src.collectors.cmu_uro_projects            # preview
    python -m src.collectors.cmu_uro_projects --save     # merge into processed data
    python -m src.collectors.cmu_uro_projects --import-csv EXPORT.csv ...
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .atomic_json import atomic_write_json

logger = logging.getLogger(__name__)

SOURCE = "cmu_uro_projects"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_FILE = PROJECT_ROOT / "data" / "snapshots" / "cmu_uro_projects.json"
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
SNAPSHOT_PATH_IN_REPO = "data/snapshots/cmu_uro_projects.json"
SCHEMA_VERSION = 2

ORGANIZATION = "Carnegie Mellon University"
LOCATION = "Pittsburgh, PA"
REMINDER_DEDUP_KEY = "manual_review:snapshot_refresh:cmu_uro_projects"
EXPIRY_WARNING_DAYS = 30
# Past the end date the weekly email goes out on the first run and then once
# every this many days: five weekly runs, so never more than once a month.
EXPIRED_NOTICE_EVERY_DAYS = 35
TITLE_CAP = 160

# Everything a snapshot may hold. Anything else from the sheet is out of the
# approved scope, so validate_snapshot refuses an unknown key.
ROW_FIELDS = ("id", "listed_on", "name", "position", "department", "title",
              "contact_email", "contact_basis", "application_url")
META_FIELDS = frozenset({
    "name", "publisher", "public_listing_url", "source_sheet_url", "access", "publisher_note",
    "kept_from_the_sheet", "snapshot_date", "valid_until", "refresh_due", "contributor",
    "contributor_github", "captured_from", "excluded_responses",
})
# How the listing asks to be contacted, and so what the row may carry:
#   listed_address     — contact_email is an address written in the answer;
#   respondent_address — the lister is the person to write to: the answer asks
#                        for email without writing an address, or names the
#                        lister as the recipient and only copies someone in;
#                        contact_email is the address the listing came from,
#                        and anyone copied in is not published;
#   form / web_page    — no address; application_url is the form or page;
#   listed_contacts    — the answer sends students to someone else (their
#                        addresses are not published, and neither is the
#                        lister's when the answer only copies them in);
#                        CMU's list is the route.
EMAIL_BASES = frozenset({"listed_address", "respondent_address"})
LINK_BASES = frozenset({"form", "web_page"})
CONTACT_BASES = EMAIL_BASES | LINK_BASES | {"listed_contacts"}

_ID = re.compile(r"cmu-uro-[0-9a-f]{12}")
_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# What #963 shipped where a value was missing ("Not specified in extracted
# row", "None stated"); an export can carry the same in any cell.
_PLACEHOLDER = re.compile(
    r"^(?:n/?a|none(?: stated)?|not (?:specified|stated|applicable)\b.*|tbd|unknown|-+)$", re.I)
_LINK = re.compile(r"https://[^\s<>()\"']+")
_ASKS_FOR_EMAIL = re.compile(r"\b(?:e-?mail|contact me|reach out)\b", re.I)
_HONORIFIC = re.compile(r"^(?:prof(?:essor)?|dr)\.?\s+", re.I)

# The only sentences the description adds to the approved fields. They name
# no subject area, so the enricher cannot read a keyword, major or skill into
# a listing from them (tests pin that).
_ROUTE_NOTE = {
    "form": "The listing asks students to apply through a form.",
    "web_page": "The listing sends students to the lab's own web page.",
    "listed_contacts": ("The listing asks students to contact someone other than the person "
                        "shown here; how to reach them is on CMU's list."),
}


class SnapshotError(ValueError):
    """The snapshot file cannot be published as it stands."""


def _iso_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _https(value: object) -> bool:
    return isinstance(value, str) and value.startswith("https://") and " " not in value


def _text(row: dict, key: str) -> str | None:
    value = row.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _row_problems(row: dict, where: str) -> list[str]:
    problems = [f"{where}.{key} is not a published field"
                for key in row if key not in ROW_FIELDS]
    problems += [f"{where}.{key} missing" for key in ROW_FIELDS if key not in row]
    if "id" in row and not _ID.fullmatch(str(row["id"])):
        problems.append(f"{where}.id is not a cmu-uro- id")
    if "listed_on" in row and _iso_date(row["listed_on"]) is None:
        problems.append(f"{where}.listed_on is not an ISO date")
    for key in ("name", "position", "department", "title"):
        if key not in row:
            continue
        text = _text(row, key)
        if text is None:
            problems.append(f"{where}.{key} is empty")
        elif _PLACEHOLDER.match(text):
            problems.append(f"{where}.{key} is a placeholder: {text!r}")
        elif _ADDRESS.search(text):
            problems.append(f"{where}.{key} shows an email address")
    if len(_text(row, "title") or "") > TITLE_CAP:
        problems.append(f"{where}.title is over {TITLE_CAP} characters")

    basis, email, link = row.get("contact_basis"), row.get("contact_email"), row.get("application_url")
    if basis not in CONTACT_BASES:
        problems.append(f"{where}.contact_basis must be one of {sorted(CONTACT_BASES)}")
    elif basis in EMAIL_BASES:
        if not isinstance(email, str) or not _ADDRESS.fullmatch(email):
            problems.append(f"{where}.contact_email must be an address when contact_basis is {basis}")
        if link is not None:
            problems.append(f"{where}.application_url must be null for an email contact")
    else:
        if email is not None:
            problems.append(f"{where}.contact_email must be null when contact_basis is {basis}")
        if basis in LINK_BASES and not _https(link):
            problems.append(f"{where}.application_url must be an https link when contact_basis is {basis}")
        if basis == "listed_contacts" and link is not None:
            problems.append(f"{where}.application_url must be null when contact_basis is {basis}")
    return problems


def validate_snapshot(data: object) -> list[str]:
    """Every reason this snapshot must not be published; [] when it may be."""
    if not isinstance(data, dict):
        return ["snapshot is not an object"]
    problems = [f"{key} is not a known field" for key in data
                if key not in ("schema_version", "snapshot", "projects")]
    if data.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    meta = data.get("snapshot")
    if not isinstance(meta, dict):
        return problems + ["snapshot metadata missing"]
    problems += [f"snapshot.{key} is not a known field" for key in meta if key not in META_FIELDS]
    dates ={key: _iso_date(meta.get(key)) for key in ("snapshot_date", "refresh_due", "valid_until")}
    for key, value in dates.items():
        if value is None:
            problems.append(f"{key} is not an ISO date")
    if None not in dates.values() and not (
            dates["snapshot_date"] <= dates["refresh_due"] <= dates["valid_until"]):
        problems.append("dates must satisfy snapshot_date <= refresh_due <= valid_until")
    for key in ("name", "contributor"):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            problems.append(f"{key} missing")
    for key in ("public_listing_url", "source_sheet_url"):
        if not _https(meta.get(key)):
            problems.append(f"{key} must be an https URL")
    excluded = meta.get("excluded_responses") or []
    if not isinstance(excluded, list) or not all(
            isinstance(e, dict) and _ID.fullmatch(str(e.get("id"))) for e in excluded):
        problems.append("excluded_responses must be a list of {id, reason}")
        excluded = []
    excluded_ids = {e["id"] for e in excluded}

    projects = data.get("projects")
    if not isinstance(projects, list) or not projects:
        return problems + ["projects must be a non-empty list"]
    seen: set[str] = set()
    for index, row in enumerate(projects):
        where = f"projects[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{where} is not an object")
            continue
        problems += _row_problems(row, where)
        opp_id = row.get("id")
        if opp_id in seen:
            problems.append(f"{where} duplicates the id of an earlier response")
        if opp_id in excluded_ids:
            problems.append(f"{where} is listed in excluded_responses")
        seen.add(opp_id)

    # The file is published as it is, so no address may ride along in any
    # field — metadata and titles included — except a row's own contact.
    contacts = {row["contact_email"].casefold() for row in projects
                if isinstance(row, dict) and isinstance(row.get("contact_email"), str)}
    stray = {a for a in _ADDRESS.findall(json.dumps(data, ensure_ascii=False))
             if a.casefold() not in contacts}
    if stray:
        problems.append(f"{len(stray)} address(es) appear that are no row's contact_email")
    return problems


def load_snapshot(path: Path | None = None) -> dict:
    """Read and validate the snapshot; raises SnapshotError on any problem."""
    path = path or SNAPSHOT_FILE
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    problems = validate_snapshot(data)
    if problems:
        raise SnapshotError(f"{path.name}: " + "; ".join(problems[:10]))
    return data


def project_id(submitted_at: str, respondent_email: str) -> str:
    """The id of one sheet response: ISO submission time and the address it came from."""
    key = f"{submitted_at}|{respondent_email.strip().casefold()}"
    return "cmu-uro-" + hashlib.md5(f"{SOURCE}::{key}".encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Refresh reminder (ops-scan detector and scripts/snapshot_reminder.py)
# ---------------------------------------------------------------------------

def refresh_status(snapshot: dict, today: date) -> dict:
    """Whether the snapshot needs a new export, as of ``today``.

    ``expired`` outranks ``expiring`` outranks ``refresh_due``; ``current``
    is the only state that asks nothing of anyone.
    """
    meta = snapshot["snapshot"]
    refresh_due = date.fromisoformat(meta["refresh_due"])
    valid_until = date.fromisoformat(meta["valid_until"])
    days_left = (valid_until - today).days
    if today > valid_until:
        state = "expired"
    elif days_left <= EXPIRY_WARNING_DAYS:
        state = "expiring"
    elif today >= refresh_due:
        state = "refresh_due"
    else:
        state = "current"
    return {
        "state": state,
        "due": state != "current",
        "checked_on": today.isoformat(),
        "snapshot_date": meta["snapshot_date"],
        "refresh_due": meta["refresh_due"],
        "valid_until": meta["valid_until"],
        "days_until_expiry": days_left,
        "projects": len(snapshot["projects"]),
        "contributor": meta["contributor"],
    }


def email_due(status: dict) -> bool:
    """Whether this week's run of the snapshot-reminder workflow emails the operator.

    Every week while a refresh is due or the end date is near. Past the end
    date the rows are retired, so the email says so on the first weekly run
    after it and then on every fifth run: a 7-day window in each
    ``EXPIRED_NOTICE_EVERY_DAYS`` cycle holds exactly one weekly run.
    """
    if status["state"] != "expired":
        return status["due"]
    days_past_end = -status["days_until_expiry"]  # 1 on the day after valid_until
    return (days_past_end - 1) % EXPIRED_NOTICE_EVERY_DAYS < 7


def reminder(snapshot: dict, status: dict) -> dict:
    """Subject, one-paragraph summary, full text and incident detail.

    Normal priority in every state: 031's record_ops_incident keeps the
    priority an incident was first filed with, so a reminder first filed high
    near the end date would still be high after it, when there is nothing
    left to rush.
    """
    meta = snapshot["snapshot"]
    state = status["state"]
    taken, count = meta["snapshot_date"], status["projects"]
    retired_on = (date.fromisoformat(meta["valid_until"]) + timedelta(days=1)).isoformat()
    if state == "expired":
        subject = (f"JoinALab: the CMU research project list expired on {meta['valid_until']} "
                   f"- its {count} listings are retired from {retired_on}")
        summary = (f"The CMU undergraduate research project list on the site, a hand-exported "
                   f"snapshot taken {taken} by {meta['contributor']} ({count} projects), passed "
                   f"its end date {meta['valid_until']}: its listings are retired from "
                   f"{retired_on} by the daily refresh and stay retired until someone with a CMU Andrew login "
                   "exports the sheet again.")
    else:
        if state == "expiring":
            subject = (f"JoinALab: the CMU research project list expires on {meta['valid_until']} "
                       f"({status['days_until_expiry']} days) - refresh it")
        else:
            subject = (f"JoinALab: time to refresh the CMU research project list "
                       f"(snapshot from {taken}, due {meta['refresh_due']})")
        summary = (f"The CMU undergraduate research project list on the site is a hand-exported "
                   f"snapshot taken {taken} by {meta['contributor']} ({count} projects); refresh "
                   f"due {meta['refresh_due']}, shown until {meta['valid_until']}. Only someone "
                   "with a CMU Andrew login can export the sheet.")
    steps = [
        f"Open the sheet with an @andrew.cmu.edu Google account: {meta['source_sheet_url']} "
        f"(linked from {meta['public_listing_url']}).",
        "Download the Projects List tab as CSV (File > Download > Comma-separated values), "
        "not PDF: the PDF export cuts long cells at the page edge. Save it outside the "
        "repository: it holds the whole sheet, while only each project's title, the person "
        "who listed it and how to reach them are published.",
        "Run python -m src.collectors.cmu_uro_projects --import-csv <the CSV> --snapshot-date "
        "<export date> --refresh-due <when the next export is due, no later than the end "
        "date> --valid-until <last day of the academic year the list covers> --contributor "
        f"\"<your name>\". It rewrites {SNAPSHOT_PATH_IN_REPO}, "
        "keeps each listing already reviewed, and prints what needs a person: a short title "
        "for each new listing, and the contact route where the listing's answer is not plainly "
        "one address, form or page.",
        "Update the values tests/test_cmu_uro_projects.py and tests/test_snapshot_reminder.py "
        "pin to this snapshot (dates, counts, ids) to the new export, run both, and open a PR; "
        "the next CMU refresh publishes it and retires rows the new list dropped.",
    ]
    text = "\n".join([
        f"The CMU undergraduate research project list on JoinALab is a snapshot, and it "
        f"is {'past its end date' if state == 'expired' else 'due for a refresh'}.",
        "",
        f"Snapshot: {meta['name']}",
        f"Taken {taken} by {meta['contributor']}; {count} projects.",
        f"Refresh due {meta['refresh_due']}; shown on the site until {meta['valid_until']}, "
        + (f"{status['days_until_expiry']} days from {status['checked_on']}. After that date its "
           "listings are retired automatically."
           if state != "expired" else
           f"and its listings are retired from {retired_on} by the daily refresh: the site shows none of its listings until a new "
           "export lands. The weekly check sends this notice on its first run after the end "
           "date and then every fifth week until a new export lands."),
        "",
        "The list is a Google Sheet that only a CMU Andrew account can open, so no collector "
        "can fetch it: someone with a CMU login has to export it.",
        *[f"{n}. {step}" for n, step in enumerate(steps, 1)],
    ])
    detail = {
        "snapshot": meta["name"],
        "state": state,
        "snapshot_date": taken,
        "refresh_due": meta["refresh_due"],
        "valid_until": meta["valid_until"],
        "days_until_expiry": status["days_until_expiry"],
        "projects": count,
        "contributor": meta["contributor"],
        "source_sheet_url": meta["source_sheet_url"],
        "public_listing_url": meta["public_listing_url"],
        "snapshot_file": SNAPSHOT_PATH_IN_REPO,
        "how_to_refresh": steps,
    }
    if state == "expired":
        detail["retired_on"] = retired_on
    # The queue keeps an incident's first title, so it names the snapshot, not
    # its state; the summary and detail carry the state.
    title = f"CMU research project list snapshot taken {taken}"
    return {"subject": subject, "title": title, "summary": summary, "text": text,
            "priority": "normal", "detail": detail}


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def compose_description(row: dict, meta: dict) -> str:
    """The snapshot caveat and where the full listing is — our words only.

    None of the sheet's prose is published, so the description cannot quote
    it; it says the listing is a dated copy and that the synopsis, skills and
    inquiry instructions are on CMU's list.
    """
    return " ".join(part for part in (
        f"Listed on Carnegie Mellon's research project list for undergraduates; this copy "
        f"was taken {meta['snapshot_date']}.",
        "CMU notes that the list may not be updated as positions are filled, so this position "
        "may already be taken.",
        _ROUTE_NOTE.get(row["contact_basis"], ""),
        "The full listing, with the project synopsis, preferred skills and how to inquire, is "
        "on CMU's list, which opens only with a CMU Andrew login; CMU links it from its "
        "Getting Started in Research page.",
    ) if part)


def normalize_project(row: dict, meta: dict, *, today: date, now: str) -> dict:
    """One sheet response as a listing, built through the shared normalizer."""
    from src.normalizers.normalizer import normalize

    valid_until = date.fromisoformat(meta["valid_until"])
    expired = today > valid_until
    # The normalizer's rule reads (keywords, majors, skills, class years) see
    # the listing's own title and department, never the description below,
    # which is our caveat and not the listing's words.
    opp = normalize({
        "id": row["id"],
        "source": SOURCE,
        "source_type": "campus_program",
        "source_url": meta["source_sheet_url"],
        "title": row["title"],
        "organization": ORGANIZATION,
        "department": row["department"],
        "pi_name": row["name"],
        "url": meta["public_listing_url"],
        "location": LOCATION,
        "on_campus": True,
        "posted_date": row["listed_on"],
        "description_raw": "",
    })
    description = compose_description(row, meta)
    opp["description_raw"] = opp["description_clean"] = description
    opp["campus_source_type"] = "program"
    opp["opportunity_type"] = "research"
    opp["contact_email"] = row["contact_email"]
    opp["deadline"] = None
    opp["is_rolling"] = True
    opp["school"], opp["audience"] = "cmu", "campus"

    application = opp["application"]
    application["application_url"] = row["application_url"]
    application["contact_method"] = (
        "website" if row["application_url"] else "email" if row["contact_email"] else "unknown")

    metadata = opp["metadata"]
    metadata.update({
        "confidence_score": 0.7,
        # The sheet was read on the snapshot date and never since; a refresh
        # run re-emits the snapshot, it does not re-check the source.
        "last_verified": meta["snapshot_date"],
        "first_seen_at": now,
        "last_seen_at": now,
        "is_active": not expired,
        "expires_at": meta["valid_until"],
        "manually_reviewed": True,
        "notes": (f"Hand-exported snapshot of a CMU-login sheet: {meta['name']}, taken "
                  f"{meta['snapshot_date']} by {meta['contributor']}. The list may not be "
                  "updated as positions are filled."),
        "faculty_title": row["position"],
        "contact_basis": row["contact_basis"],
        "source_snapshot": {
            "name": meta["name"],
            "taken_on": meta["snapshot_date"],
            "valid_until": meta["valid_until"],
            "contributed_by": meta["contributor"],
        },
    })
    if expired:
        metadata["deactivated_at"] = (valid_until + timedelta(days=1)).isoformat()
        metadata["deactivation_reason"] = "expired"
    return opp


def fetch_and_normalize(today: date | None = None, *, path: Path | None = None) -> list[dict]:
    """Every response in the snapshot as a record; raises if the file is unfit."""
    snapshot = load_snapshot(path)
    today = today or datetime.now(UTC).date()
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    meta = snapshot["snapshot"]
    return [normalize_project(row, meta, today=today, now=now) for row in snapshot["projects"]]


def merge_into_processed(new_opps: list[dict]) -> tuple[int, int]:
    """Upsert the snapshot's rows; retire this source's rows it no longer lists.

    The snapshot is the whole list by construction, so absence is a verdict,
    not a flaky fetch. An empty batch changes nothing: ``fetch_and_normalize``
    raises on an empty snapshot, so empty only means nothing was collected.
    """
    if not new_opps or not PROCESSED_FILE.exists():
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    index = {opp.get("id"): opp for opp in existing if opp.get("id")}
    added = updated = 0
    for opp in new_opps:
        stored = index.get(opp["id"])
        if stored is None:
            existing.append(opp)
            index[opp["id"]] = opp
            added += 1
            continue
        stored_meta = stored.get("metadata") or {}
        metadata = opp["metadata"]
        metadata["first_seen_at"] = stored_meta.get("first_seen_at") or metadata["first_seen_at"]
        if metadata.get("is_active") is False and stored_meta.get("is_active") is False:
            metadata["deactivated_at"] = stored_meta.get("deactivated_at") or metadata.get("deactivated_at")
        stored.clear()
        stored.update(opp)
        updated += 1
    listed = {opp["id"] for opp in new_opps}
    retired_on = datetime.now(UTC).date().isoformat()
    retired = 0
    for opp in existing:
        metadata = opp.get("metadata")
        if (opp.get("source") != SOURCE or opp.get("id") in listed
                or not isinstance(metadata, dict) or metadata.get("is_active") is False):
            continue
        metadata["is_active"] = False
        metadata["deactivated_at"] = retired_on
        metadata["deactivation_reason"] = "absent_from_snapshot"
        retired += 1
    if retired:
        logger.info("%s: retired %d row(s) the current snapshot no longer lists", SOURCE, retired)
    atomic_write_json(PROCESSED_FILE, existing)
    return (added, updated)


# ---------------------------------------------------------------------------
# Importer: a CSV export of the sheet -> the snapshot
# ---------------------------------------------------------------------------

# The Google Form's questions, as the sheet's header row words them; a column
# is found by the start of its header. Only these are read: the synopsis to
# show a person who writes the title, the inquiry answer to pick the contact.
# Nothing read here is written to the snapshot except the published fields.
EXPORT_COLUMNS = {
    "submitted_at": "timestamp",
    "respondent_email": "email address",
    "last_name": "last name",
    "first_name": "first name",
    "department": "department affiliation",
    "position": "your title",
    "synopsis": "please enter a short synopsis",
    "inquiry": "how should students inquire",
}


def _export_timestamp(value: str) -> str:
    """The sheet shows 8/5/2026 7:31:11; the id is built from 2026-08-05T07:31:11."""
    value = value.strip()
    try:
        return datetime.strptime(value, "%m/%d/%Y %H:%M:%S").isoformat()
    except ValueError:
        return datetime.fromisoformat(value).isoformat()


def _canonical_link(url: str) -> str:
    """A link from an answer, without trailing punctuation or a Google Form's share query.

    ``?usp=sharing&ouid=...`` names the account that copied the link and does
    not change which form opens.
    """
    url = url.rstrip(".,;:!?")
    parts = urlsplit(url)
    if parts.netloc == "docs.google.com" and parts.path.startswith("/forms/"):
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return url


def _is_form(url: str) -> bool:
    parts = urlsplit(url)
    return parts.netloc == "forms.gle" or (
        parts.netloc == "docs.google.com" and parts.path.startswith("/forms/"))


def propose_contact(inquiry: str, respondent_email: str) -> dict | None:
    """The contact route when the inquiry answer leaves no doubt; None otherwise.

    Clear cases only: one link and no address, the respondent's own address
    and nothing else, or a request to email with no address or link at all.
    An address that is not the respondent's may be a student or lab manager
    the listing names, so it is always left to a person.
    """
    addresses = {a.casefold() for a in _ADDRESS.findall(inquiry)}
    links = [_canonical_link(url) for url in _LINK.findall(inquiry)]
    respondent = respondent_email.strip()
    if not addresses and len(links) == 1:
        return {"contact_email": None,
                "contact_basis": "form" if _is_form(links[0]) else "web_page",
                "application_url": links[0]}
    if links:
        return None
    if addresses == {respondent.casefold()}:
        return {"contact_email": respondent, "contact_basis": "listed_address", "application_url": None}
    if not addresses and _ASKS_FOR_EMAIL.search(inquiry):
        return {"contact_email": respondent, "contact_basis": "respondent_address",
                "application_url": None}
    return None


def _still_shown(entry: dict, inquiry: str, respondent_email: str) -> bool:
    """Whether a reviewed contact still matches what the new export says."""
    basis = entry.get("contact_basis")
    email = (entry.get("contact_email") or "").casefold()
    if basis == "listed_address":
        return email in {a.casefold() for a in _ADDRESS.findall(inquiry)}
    if basis == "respondent_address":
        return email == respondent_email.strip().casefold()
    if basis in LINK_BASES:
        return entry.get("application_url") in {_canonical_link(u) for u in _LINK.findall(inquiry)}
    return basis == "listed_contacts"


def read_export(csv_path: Path) -> list[dict]:
    """The export's responses, keyed by EXPORT_COLUMNS; raises on an unknown layout."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    header_at = next((i for i, row in enumerate(rows)
                      if row and row[0].strip().casefold() == "timestamp"), None)
    if header_at is None:
        raise SnapshotError(f"{csv_path.name}: no header row starting with 'Timestamp'")
    header = [" ".join(cell.split()).casefold() for cell in rows[header_at]]
    columns: dict[str, int] = {}
    for key, prefix in EXPORT_COLUMNS.items():
        found = [i for i, cell in enumerate(header) if cell.startswith(prefix)]
        if len(found) != 1:
            raise SnapshotError(f"{csv_path.name}: expected one column starting "
                                f"{prefix!r}, found {len(found)}")
        columns[key] = found[0]
    responses = []
    for row in rows[header_at + 1:]:
        if not any(cell.strip() for cell in row):
            continue
        row = row + [""] * (len(header) - len(row))
        responses.append({key: row[i].strip() for key, i in columns.items()})
    return responses


def import_export(csv_path: Path, current: dict, *, snapshot_date: str, refresh_due: str,
                  valid_until: str, contributor: str, contributor_github: str | None = None,
                  sheet_url: str | None = None, list_name: str | None = None
                  ) -> tuple[dict, list[str]]:
    """A new snapshot from a CSV export, and what a person must still decide.

    A response already in ``current`` keeps its reviewed entry (title, name,
    position, department, contact) unless the export no longer shows its
    contact. A new one gets its id, date, name, position and department from
    the export, a proposed contact when ``propose_contact`` is sure, and an
    empty title — ``validate_snapshot`` fails until a person writes one.
    """
    previous = {entry["id"]: entry for entry in current.get("projects") or ()}
    excluded = {e["id"] for e in current["snapshot"].get("excluded_responses") or ()}
    projects: list[dict] = []
    review: list[str] = []
    responses = read_export(csv_path)
    for response in responses:
        submitted = _export_timestamp(response["submitted_at"])
        respondent = response["respondent_email"]
        opp_id = project_id(submitted, respondent)
        if opp_id in excluded:
            review.append(f"{opp_id}: skipped, it is in excluded_responses")
            continue
        undecided = {"contact_email": None, "contact_basis": None, "application_url": None}
        entry = dict(previous[opp_id]) if opp_id in previous else None
        if entry is not None:
            if not _still_shown(entry, response["inquiry"], respondent):
                entry.update(undecided)
                review.append(f"{opp_id} ({entry['name']}): its answer changed; choose the "
                              f"contact again from: {response['inquiry']!r}")
        else:
            name = " ".join(filter(None, (_HONORIFIC.sub("", response["first_name"]),
                                          response["last_name"])))
            proposal = propose_contact(response["inquiry"], respondent)
            entry = {"id": opp_id, "listed_on": submitted[:10], "name": name,
                     "position": response["position"], "department": response["department"],
                     "title": "", **(proposal or undecided)}
            review.append(f"{opp_id} ({name}): new; check the name, position and department, "
                          f"and write a short title (at most {TITLE_CAP} characters) from its "
                          f"synopsis: {response['synopsis'][:400]!r}")
            if proposal is None:
                review.append(f"{opp_id} ({name}): choose the contact route from: "
                              f"{response['inquiry']!r} (never an address the answer gives "
                              "for someone else)")
        projects.append(entry)
    kept = {entry["id"] for entry in projects}
    review += [f"{entry['id']} ({entry['name']}): no longer on the list; the next refresh "
               "retires it" for entry in previous.values() if entry["id"] not in kept]

    meta = dict(current["snapshot"])
    meta.update({
        "snapshot_date": snapshot_date,
        "refresh_due": refresh_due,
        "valid_until": valid_until,
        "contributor": contributor,
        "captured_from": (f"CSV export of the sheet's Projects List tab ({len(responses)} "
                          "responses); the export is not committed."),
    })
    if contributor_github is not None:
        meta["contributor_github"] = contributor_github
    if sheet_url is not None:
        meta["source_sheet_url"] = sheet_url
    if list_name is not None:
        meta["name"] = list_name
    return {"schema_version": SCHEMA_VERSION, "snapshot": meta, "projects": projects}, review


def _import_main(args: argparse.Namespace) -> int:
    csv_path = Path(args.import_csv).expanduser().resolve()
    if csv_path.is_relative_to(PROJECT_ROOT):
        print(f"{csv_path} is inside the repository. Move it out first: the export holds the "
              "whole sheet, which is not published.", file=sys.stderr)
        return 2
    missing = [flag for flag in ("snapshot_date", "refresh_due", "valid_until", "contributor")
               if not getattr(args, flag)]
    if missing:
        print("--import-csv also needs " + ", ".join(f"--{m.replace('_', '-')}" for m in missing),
              file=sys.stderr)
        return 2
    with SNAPSHOT_FILE.open("r", encoding="utf-8") as f:
        current = json.load(f)
    snapshot, review = import_export(
        csv_path, current, snapshot_date=args.snapshot_date, refresh_due=args.refresh_due,
        valid_until=args.valid_until, contributor=args.contributor,
        contributor_github=args.contributor_github, sheet_url=args.sheet_url,
        list_name=args.list_name)
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    print(f"wrote {SNAPSHOT_PATH_IN_REPO}: {len(snapshot['projects'])} projects")
    for line in review:
        print(" -", line)
    problems = validate_snapshot(snapshot)
    if problems:
        print(f"{len(problems)} problem(s) left before it can be published; edit the file, then "
              "run pytest tests/test_cmu_uro_projects.py:")
        for problem in problems:
            print(" -", problem)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--save", action="store_true", help="Merge into processed/opportunities.json")
    parser.add_argument("--import-csv", help="Rewrite the snapshot from a CSV export of the sheet")
    parser.add_argument("--snapshot-date", help="with --import-csv: the export's date (ISO)")
    parser.add_argument("--refresh-due",
                        help="with --import-csv: when the next export is due, on or before --valid-until (ISO)")
    parser.add_argument("--valid-until",
                        help="with --import-csv: last day of the academic year the list covers (ISO)")
    parser.add_argument("--contributor", help="with --import-csv: who exported it")
    parser.add_argument("--contributor-github", help="with --import-csv: their GitHub handle")
    parser.add_argument("--sheet-url", help="with --import-csv: a new academic year's sheet")
    parser.add_argument("--list-name", help="with --import-csv: a new academic year's list name")
    args = parser.parse_args()
    if args.import_csv:
        raise SystemExit(_import_main(args))
    opps = fetch_and_normalize()
    print(f"{len(opps)} CMU URO projects ({sum(1 for o in opps if o['metadata']['is_active'])} active)")
    for o in opps[:8]:
        print(" ", o["id"], o["title"])
    if args.save:
        print("merged (added, updated):", merge_into_processed(opps))
