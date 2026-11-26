"""Collector for the UC Santa Barbara URCA Undergraduate Research Directory.

UCSB's analog to Berkeley's URAP project database (``ucb_urap_projects``): the
URCA "Undergraduate Research Assistant Directory" is a board of individual
faculty-posted research projects open to undergraduates — the volume layer that
sits under the handful of curated program hubs in ``schools/ucsb.py``.

The public sitemap identifies records, including archived and test records. A
sitemap URL alone does not establish recruitment. The separate, public,
client-rendered Undergraduate Research Directory lists faculty projects seeking
undergraduate assistance. Only an unambiguous match on that list enables a
project's application action. Other entries retain their stable reference URLs.

The Salesforce object is Outbound-Funds ``Funding_Program__c``; the sitemap
mixes ~30 administrative entries (URCA grants, the Faculty Research Assistant
Program, per-course summer scholarships, the directory node itself) in with the
real per-project postings — those are filtered out by ``_ADMIN_SLUG_RE`` so only
individual research projects are emitted.

Seasonal like URAP: faculty post on a rolling basis, so the sitemap grows/shrinks
over time; ``merge_into_processed`` never wipes the corpus on an empty fetch.

The HTTP deps (``requests``) are imported lazily so importing this module (and
the normalization path) needs only the standard library.

Usage:
    python -m src.collectors.ucsb_urca_projects            # preview
    python -m src.collectors.ucsb_urca_projects --save     # merge into processed data
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from difflib import SequenceMatcher
from urllib.parse import unquote
from xml.etree import ElementTree

from .atomic_json import atomic_write_json
from .ucb_common import PROCESSED_FILE

logger = logging.getLogger(__name__)

SOURCE = "ucsb_urca_projects"
SITEMAP_INDEX = "https://ucsb.my.site.com/urca/s/sitemap.xml"
PORTAL = "https://ucsb.my.site.com/urca/s/urad"
_RECORD_URL_RE = re.compile(
    r"(https://ucsb\.my\.site\.com/urca/s/funding-program/"
    r"([A-Za-z0-9]+)/([^?#]+))(?:[?#].*)?"
)
_REQUIRED_FUNDING_SITEMAPS = frozenset(
    {
        (
            "https://ucsb.my.site.com/urca/s/"
            "sitemap-outfunds__funding_program__c-1.xml"
        ),
    }
)
# Salesforce lists the weekly delta only while it has recent changes to
# report; the ``-1`` enumeration above is always the full record set. Demand
# the delta and every quiet week reads as schema drift.
_OPTIONAL_FUNDING_SITEMAPS = frozenset(
    {
        (
            "https://ucsb.my.site.com/urca/s/"
            "sitemap-outfunds__funding_program__c-weekly.xml"
        ),
    }
)
_KNOWN_NON_TARGET_SITEMAPS = frozenset(
    {
        "https://ucsb.my.site.com/urca/s/sitemap-view-1.xml",
        "https://ucsb.my.site.com/urca/s/sitemap-listview-1.xml",
    }
)
# A single sitemap snapshot is not enough evidence to explain a sharp seasonal
# contraction.  Keep the threshold deliberately conservative until the refresh
# pipeline has a durable, consecutive-snapshot confirmation ledger.
_SHRINK_GUARD_MIN_BASELINE = 2
_MIN_SNAPSHOT_RETENTION_RATIO = 0.80
# Administrative / non-project entries that share the funding_program object.
_ADMIN_SLUG_RE = re.compile(
    r"course-scholarship|scholarship$|urca-grants|^urca-|faculty-research-assistant"
    r"|summer-sessions|^summer-\d{4}-|-grant$|research-assistant-directory",
    re.I,
)
_ACRONYM_RE = re.compile(r"\b(dna|rna|nmr|ai|ml|nlp|usa|uv|led|mri|ph|3d|2d|hiv|ucsb)\b", re.I)

KEYWORD_BANK = [
    "machine learning", "computer vision", "data science", "artificial intelligence",
    "robotics", "neuroscience", "genomics", "ecology", "evolution", "marine biology",
    "chemistry", "physics", "materials", "climate", "sustainability", "biochemistry",
    "molecular biology", "psychology", "economics", "engineering", "astrophysics",
]


class UnsafeUrcaSnapshotError(RuntimeError):
    """Raised before writing when one snapshot could retire trusted history."""


def _title_from_slug(slug: str) -> str:
    """De-slugify a URCA record slug into a readable project title."""
    title = slug.replace("-", " ").strip().title()
    # Re-uppercase common acronyms the title-case step lowercased.
    return _ACRONYM_RE.sub(lambda m: m.group(0).upper(), title)


def _fetch_text(url: str) -> str:
    try:
        import requests

        from .ucb_common import HEADERS
    except Exception:  # noqa: BLE001
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        return resp.text
    except Exception as e:  # noqa: BLE001
        logger.warning("URCA: fetch failed for %s: %s", url, e)
        return ""


def scrape_projects() -> list[dict]:
    """Enumerate individual URCA research projects from the public sitemap.

    Reads the sitemap index, follows every ``funding_program`` sub-sitemap, drops
    the administrative entries, and returns one raw dict per project (id, url,
    title). Degrades to ``[]`` on any fetch failure.
    """
    records, _evidence = scrape_projects_with_evidence()
    return records


def _parse_sitemap(text: str) -> tuple[str | None, list[str], bool]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None, [], False
    root_name = root.tag.rsplit("}", 1)[-1].casefold()
    expected_entry = {
        "urlset": "url",
        "sitemapindex": "sitemap",
    }.get(root_name)
    if expected_entry is None:
        return root_name, [], False

    locations: list[str] = []
    shape_valid = True
    for entry in list(root):
        if entry.tag.rsplit("}", 1)[-1].casefold() != expected_entry:
            shape_valid = False
            continue
        locs = [
            (child.text or "").strip()
            for child in list(entry)
            if child.tag.rsplit("}", 1)[-1].casefold() == "loc"
        ]
        if len(locs) != 1 or not locs[0]:
            shape_valid = False
            continue
        locations.append(locs[0])
    return root_name, locations, shape_valid


def scrape_projects_with_evidence() -> tuple[list[dict], dict]:
    """Return raw projects plus fail-closed sitemap evidence.

    A network failure, HTML error page, malformed XML, missing child sitemap,
    or unexpected sitemap-index shape is never a complete snapshot. A single
    structurally valid but empty response is also insufficient to confirm a
    legitimate empty season; that requires a future consecutive-snapshot
    evidence mechanism.
    """

    index = _fetch_text(SITEMAP_INDEX)
    index_root, index_locations, index_shape_valid = (
        _parse_sitemap(index) if index else (None, [], False)
    )
    if index_root not in {"urlset", "sitemapindex"} or not index_shape_valid:
        return [], {
            "sitemap_complete": False,
            "sitemap_structure_complete": False,
            "sitemaps_expected": 1,
            "sitemaps_loaded": 0,
            "empty_confirmed": False,
        }
    unexpected_locations: list[str] = []
    missing_locations: list[str] = []
    if index_root == "sitemapindex":
        subs = [
            location
            for location in index_locations
            if location in _REQUIRED_FUNDING_SITEMAPS
            or location in _OPTIONAL_FUNDING_SITEMAPS
        ]
        unexpected_locations.extend(
            location
            for location in index_locations
            if location not in subs
            and location not in _KNOWN_NON_TARGET_SITEMAPS
        )
        missing_locations = sorted(
            _REQUIRED_FUNDING_SITEMAPS - set(subs)
        )
    else:
        subs = []
    if index_root == "sitemapindex" and (
        missing_locations or unexpected_locations
    ):
        return [], {
            "sitemap_complete": False,
            "sitemap_structure_complete": False,
            "sitemaps_expected": len(_REQUIRED_FUNDING_SITEMAPS),
            "sitemaps_loaded": 0,
            "locations_seen": len(index_locations),
            "recognized_locations": 0,
            "unexpected_location_count": len(unexpected_locations),
            "unexpected_location_samples": unexpected_locations[:5],
            "missing_sitemap_count": len(missing_locations),
            "missing_sitemap_samples": missing_locations[:5],
            "empty_confirmed": False,
        }
    pages = subs or [SITEMAP_INDEX]
    raw: list[dict] = []
    seen: set[str] = set()
    loaded = 0
    complete = True
    locations_seen = 0
    recognized_locations = 0
    for sub in pages:
        xml = _fetch_text(sub) if sub != SITEMAP_INDEX else index
        root_name, locations, shape_valid = _parse_sitemap(xml)
        if root_name != "urlset" or not shape_valid:
            complete = False
            continue
        loaded += 1
        locations_seen += len(locations)
        for location in locations:
            match = _RECORD_URL_RE.fullmatch(location)
            if match is None:
                unexpected_locations.append(location)
                continue
            url, sid, encoded_slug = match.groups()
            slug = unquote(encoded_slug)
            recognized_locations += 1
            if sid in seen or _ADMIN_SLUG_RE.search(slug):
                continue
            seen.add(sid)
            raw.append({"id": sid, "url": url, "title": _title_from_slug(slug), "slug": slug})
    complete = (
        complete
        and loaded == len(pages)
        and not unexpected_locations
    )
    snapshot_complete = complete and bool(raw)
    return raw, {
        # Structural completeness is useful diagnostic evidence, but it does
        # not authorize publishing or retiring a zero-record snapshot.
        "sitemap_complete": snapshot_complete,
        "sitemap_structure_complete": complete,
        "sitemaps_expected": len(pages),
        "sitemaps_loaded": loaded,
        "locations_seen": locations_seen,
        "recognized_locations": recognized_locations,
        "unexpected_location_count": len(unexpected_locations),
        "unexpected_location_samples": unexpected_locations[:5],
        "empty_confirmed": False,
    }


def _keywords(text: str) -> list[str]:
    low = text.lower()
    return [k for k in KEYWORD_BANK if k in low][:6]


def _description_digest(value: str) -> str | None:
    text = " ".join(unicodedata.normalize("NFKC", value).split())
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def _read_directory(records: list[dict]) -> tuple[list[dict], dict[str, dict | None]]:
    """Read the public list and, only for unresolved titles, visible project details."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            response = page.goto(PORTAL, wait_until="domcontentloaded", timeout=40000)
            if not response or not response.ok or page.url != PORTAL:
                raise UnsafeUrcaSnapshotError("UCSB recruiting directory unavailable")
            page.get_by_text("faculty seeking research assistance", exact=False).wait_for(timeout=30000)
            table = page.get_by_role("table")
            rows = table.get_by_role("row")
            rows.nth(1).wait_for(timeout=30000)
            headers = table.get_by_role("columnheader").all_inner_texts()
            if [name.strip() for name in headers] != ["Project Title", "Description", "Program Tags"]:
                raise UnsafeUrcaSnapshotError("UCSB recruiting directory changed its columns")
            if page.get_by_role("button", name=re.compile(r"^(?:next(?: page)?|load more|show more)$", re.I)).count():
                raise UnsafeUrcaSnapshotError("UCSB recruiting directory is paginated")
            cells = rows.evaluate_all("""rows => rows.map(row => Array.from(row.querySelectorAll('td'),
                cell => cell.innerText.trim())).filter(cells => cells.length)""")
            if not cells or any(len(row) != 3 or not row[0] for row in cells):
                raise UnsafeUrcaSnapshotError("UCSB recruiting directory has incomplete project rows")
            directory = [{"title": row[0], "description_digest": _description_digest(row[1]),
                          "tags": row[2]} for row in cells]
            details = {}
            candidates = _detail_candidates(records, directory)
            if len(candidates) > 40:
                raise UnsafeUrcaSnapshotError("UCSB directory needs an unusually large number of detail checks")
            for row in candidates:
                # The live table has no link per row. The slug can be stale or
                # truncated. Similarity nominates a page to read; it never
                # authorizes a match or turns an unverified name into a fact.
                details[row["id"]] = _read_project_detail(page, row)
            return directory, details
        finally:
            browser.close()


def _title_key(value: str) -> str:
    # Salesforce drops punctuation from slugs: e.g. "cost-effective" becomes
    # "costeffective". An ambiguous result on either side cannot identify an ID.
    return "".join(char for char in unicodedata.normalize("NFKD", value).casefold() if char.isalnum())


def _detail_candidates(records: list[dict], directory: list[dict]) -> list[dict]:
    keys = {row["id"]: _title_key(row["title"]) for row in records}
    sitemap_counts = Counter(keys.values())
    directory_counts = Counter(_title_key(entry["title"]) for entry in directory)
    unresolved = [key for key, count in directory_counts.items() if count != 1 or sitemap_counts[key] != 1]
    return [row for row in records if any(
        SequenceMatcher(None, key, keys[row["id"]]).ratio() >= 0.78 for key in unresolved
    )]


def _read_project_detail(page, row: dict) -> dict | None:
    from playwright.sync_api import Error

    try:
        response = page.goto(row["url"], wait_until="domcontentloaded", timeout=15000)
        location = _RECORD_URL_RE.fullmatch(page.url)
        if not response or not response.ok or not location or location[2] != row["id"]:
            return None
        main = page.get_by_role("main")
        title = main.get_by_role("heading", level=1).inner_text(timeout=15000).strip()
        main.get_by_text("Undergraduate Contribution", exact=True).first.wait_for(timeout=10000)
        body = main.inner_text()
        description = re.search(r"(?:^|\n)Description\s*\n(.*?)\nUndergraduate Contribution(?:\n|$)", body, re.S)
        project_title = re.search(r"(?:^|\n)Project Title\s*\n(.*?)\nFaculty Contact(?:\n|$)", body, re.S)
        tags = re.search(r"(?:^|\n)Program Tags\s*\n(.*?)\nWebsite(?:\n|$)", body, re.S)
        return {"title": project_title[1].strip().removeprefix("Help Project Title\n") if project_title else title,
                "description_digest": _description_digest(description[1]) if description else None,
                "tags": tags[1].strip() if tags else ""}
    except Error as exc:
        logger.info("UCSB detail %s unavailable: %s", row["id"], type(exc).__name__)
        return None


def reconcile_directory(records: list[dict], directory: list[dict], details: dict[str, dict | None]) -> tuple[list[dict], dict]:
    # A unique full title on both sides is sufficient. Duplicate/renamed
    # titles must also match the real project detail's description and be a
    # unique title/description pair on both sides. Preserve ambiguous IDs.
    by_key = {_title_key(entry["title"]): entry for entry in directory}
    directory_counts = Counter(_title_key(entry["title"]) for entry in directory)
    keys = {row["id"]: _title_key((details.get(row["id"]) or row)["title"]) for row in records}
    sitemap_counts = Counter(keys.values())
    fetched_counts = Counter(keys[sid] for sid, detail in details.items() if detail)
    unread_keys = {keys[sid] for sid, detail in details.items() if detail is None}

    def fingerprint(entry):
        return (_title_key(entry["title"]), entry["description_digest"],
                tuple(sorted(tag.strip().casefold() for tag in entry["tags"].split(";") if tag.strip())))

    directory_pairs = Counter(fingerprint(entry) for entry in directory)
    detail_pairs = Counter(fingerprint(detail) for detail in details.values() if detail)
    reconciled = []
    for row in records:
        key = keys[row["id"]]
        listed = directory_counts[key] == 1 and sitemap_counts[key] == 1
        detail = details.get(row["id"])
        if detail:
            key, digest, _ = pair = fingerprint(detail)
            # On a namesake group a failed read could hide another ID with
            # the same description. Its surviving sibling does not win by default.
            listed = bool(digest and directory_pairs[pair] == 1 and detail_pairs[pair] == 1
                          and (sitemap_counts[key] == 1 or fetched_counts[key] == sitemap_counts[key]))
        if key in unread_keys:
            row = {**row, "urca_directory": "unavailable"}
        elif listed:
            row = {**row, "title": by_key[key]["title"], "urca_directory": "listed"}
        else:
            row = {**row, "urca_directory": "ambiguous" if key in by_key else "not_matched"}
        reconciled.append(row)
    count = sum(row["urca_directory"] == "listed" for row in reconciled)
    if not count:
        raise UnsafeUrcaSnapshotError("no public recruiting titles could be matched to sitemap records")
    return reconciled, {"directory_rows": len(directory), "directory_distinct_titles": len(by_key),
                        "directory_matched_ids": count, "directory_detail_unavailable": sum(d is None for d in details.values())}


def normalize_project(raw: dict) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    opp_id = "ucsb-urca-proj-" + hashlib.md5(raw["id"].encode()).hexdigest()[:12]
    directory = raw.get("urca_directory", "unverified")
    # This exact Salesforce record is a public test fixture ("Hi Anita!").
    # A renamed record or a genuine project with 'test' in its title is not
    # classified by this exception.
    test_record = raw["id"] == "a0WVt00000BbDUbMAN" and raw.get("slug") == "test-from-aj"
    recruiting = directory == "listed" and not test_record
    if test_record:
        description = "UCSB URCA test record. This page is retained for reference."
    elif directory == "ambiguous":
        description = "UCSB lists a project with this title, but this individual record could not be confirmed in the recruiting directory."
    elif recruiting:
        description = "UCSB lists this project in its Undergraduate Research Directory for faculty seeking undergraduate research assistants."
    else:
        description = "This UCSB URCA project has a public record. Current recruitment has not been confirmed for this project."
    return {
        "id": opp_id,
        "source": SOURCE,
        "source_type": "campus_program",
        "campus_source_type": "program",
        "source_url": raw["url"],
        "title": raw["title"][:200],
        "organization": "University of California, Santa Barbara",
        "department": "",
        # The directory the project is listed in is not its lab or program.
        "lab_or_program": "",
        # No pi_name: the mentor isn't reliably on the sitemap, and a shared/blank
        # name across 240+ project records would trip the shared-name DQ gate.
        "pi_name": None,
        "contact_email": None,
        "url": raw["url"],
        "location": "Santa Barbara, CA",
        # A URCA project runs in a UCSB lab; school (ucsb) carries whose campus
        # it is, and the ranker compares that to profile.home_school.
        "on_campus": True,
        "remote_option": "unknown",
        "opportunity_type": "research",
        "paid": "unknown",
        "compensation_details": "",
        "deadline": None,
        "is_rolling": None,
        "posted_date": None,
        "start_date": None,
        "duration": None,
        "eligibility": {
            "preferred_year": [],
            "min_gpa": None,
            "majors": [],
            "skills_required": [],
            "skills_preferred": [],
            # Unknown, not False: the page states no citizenship rule (M03).
            "citizenship_required": None,
            "international_friendly": "unknown",
            "work_auth_notes": "",
            "eligibility_text_raw": "",
        },
        "application": {
            "contact_method": "website",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": raw["url"] if recruiting else None,
        },
        "description": description,
        "description_raw": description,
        "description_clean": description[:1500],
        "keywords": _keywords(raw["title"]) + ["undergraduate research"],
        "school": "ucsb",
        "audience": "campus",
        "metadata": {
            "confidence_score": 0.5,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": not test_record,
            "reference_only": not recruiting,
            "listing_status": "open" if recruiting else "unknown",
            "status": "open" if recruiting else "unknown",
            "urca_directory": directory,
            "urca_directory_url": PORTAL,
            "manually_reviewed": False,
            "notes": "Auto-imported from the UCSB URCA Undergraduate Research Directory sitemap",
            "urca_record_id": raw["id"],
            "discovered": True,
        },
    }


def fetch_and_normalize() -> list[dict]:
    rows, _ = fetch_and_normalize_with_evidence()
    return rows


def fetch_and_normalize_with_evidence() -> tuple[list[dict], dict]:
    raw, evidence = scrape_projects_with_evidence()
    if not evidence.get("sitemap_complete"):
        # A partial ID set can make two namesakes appear unique.
        return [], evidence
    directory, details = _read_directory(raw)
    raw, directory_evidence = reconcile_directory(raw, directory, details)
    return [normalize_project(record) for record in raw], {**evidence, **directory_evidence}


def merge_snapshot_into_processed(
    new_opps: list[dict],
    *,
    snapshot_complete: bool,
) -> tuple[int, int, int]:
    """Upsert a safe URCA snapshot and retire rows absent from it.

    Empty snapshots and sharp one-run contractions fail before any mutation.
    They may become publishable only after a durable consecutive-snapshot
    confirmation mechanism exists.
    """
    if not new_opps:
        if snapshot_complete:
            raise UnsafeUrcaSnapshotError(
                "refusing complete zero-record URCA snapshot without "
                "consecutive-snapshot evidence"
            )
        logger.info("URCA projects: 0 scraped — leaving corpus untouched")
        return (0, 0, 0)
    if not PROCESSED_FILE.exists():
        return (0, 0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    index = {o.get("id"): o for o in existing if o.get("id")}
    # A failed detail read does not withdraw a previously confirmed project or
    # give the old observation a fresh timestamp. New unresolved IDs remain
    # read-only. A complete recruiting directory may still update other rows.
    retained = {o["id"] for o in new_opps if (o.get("metadata") or {}).get("urca_directory") == "unavailable"
                and (index.get(o["id"], {}).get("metadata") or {}).get("urca_directory") == "listed"}
    if snapshot_complete:
        existing_active_ids = {
            opp.get("id")
            for opp in existing
            if (
                opp.get("source") == SOURCE
                and opp.get("id")
                and (opp.get("metadata") or {}).get("is_active") is not False
            )
        }
        incoming_active_ids = {
            opp.get("id")
            for opp in new_opps
            if (
                opp.get("source") == SOURCE
                and opp.get("id")
                and (opp.get("metadata") or {}).get("is_active") is not False
            )
        }
        previous_listed = {opp["id"] for opp in existing if opp.get("source") == SOURCE
                           and (opp.get("metadata") or {}).get("urca_directory") == "listed"
                           and (opp.get("metadata") or {}).get("is_active") is True}
        current_listed = {opp["id"] for opp in new_opps
                          if (opp.get("metadata") or {}).get("urca_directory") == "listed"}
        current_listed.update(retained)
        if (len(previous_listed) >= _SHRINK_GUARD_MIN_BASELINE and
                len(current_listed & previous_listed) / len(previous_listed) < _MIN_SNAPSHOT_RETENTION_RATIO):
            raise UnsafeUrcaSnapshotError("refusing sharp loss of previously matched recruiting projects")
        retained_active_ids = existing_active_ids & incoming_active_ids
        if (
            len(existing_active_ids) >= _SHRINK_GUARD_MIN_BASELINE
            and len(retained_active_ids) / len(existing_active_ids)
            < _MIN_SNAPSHOT_RETENTION_RATIO
        ):
            raise UnsafeUrcaSnapshotError(
                "refusing sharp URCA identity churn without "
                "consecutive-snapshot evidence: "
                f"{len(retained_active_ids)}/{len(existing_active_ids)} "
                f"previous active IDs remain, below "
                f"{_MIN_SNAPSHOT_RETENTION_RATIO:.0%}"
            )
    added = updated = 0
    for opp in new_opps:
        if opp["id"] in retained:
            continue
        if opp["id"] in index:
            opp["metadata"]["first_seen_at"] = index[opp["id"]].get(
                "metadata", {}).get("first_seen_at", opp["metadata"]["first_seen_at"])
            index[opp["id"]].update(opp)
            updated += 1
        else:
            existing.append(opp)
            index[opp["id"]] = opp
            added += 1
    deactivated = 0
    if snapshot_complete:
        active_ids = {opp["id"] for opp in new_opps}
        deactivated_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
        for opp in existing:
            if (
                opp.get("source") != SOURCE
                or opp.get("id") in active_ids
                or (opp.get("metadata") or {}).get("is_active") is False
            ):
                continue
            metadata = opp.setdefault("metadata", {})
            metadata["is_active"] = False
            metadata["deactivated_at"] = deactivated_at
            metadata["deactivation_reason"] = (
                "absent_from_complete_urca_sitemap"
            )
            deactivated += 1
    atomic_write_json(PROCESSED_FILE, existing)
    return (added, updated, deactivated)


def merge_into_processed(new_opps: list[dict]) -> tuple[int, int]:
    """Compatibility upsert; without evidence, never retire absent records."""
    added, updated, _deactivated = merge_snapshot_into_processed(
        new_opps,
        snapshot_complete=False,
    )
    return added, updated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help="Merge into processed/opportunities.json")
    args = parser.parse_args()
    opps = fetch_and_normalize()
    print(f"Fetched {len(opps)} URCA projects")
    for o in opps[:8]:
        print(" ", o["title"])
    if args.save:
        print("merged:", merge_into_processed(opps))
