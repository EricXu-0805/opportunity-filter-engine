"""Read a natural UF rotation, its merged data PR, Physics ledger and named faculty pages.

From this directory, run:
    python check_scheduled_publication.py --date 2026-11-27 --out /tmp/uf-physics-20261127.json

For the historical zero-row control, pass --date 2026-11-20 --run 44761914990 --data-pr 1211.
Exit 0 means all tracked originals passed. Exit 1 means a published discrepancy.
Exit 2 means publication, source provenance or access to the university is pending.
All remote requests are GETs. The only file written is --out.
"""

import argparse
import ast
import hashlib
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REPO = "EricXu-0805/opportunity-filter-engine"
API = f"https://api.github.com/repos/{REPO}"
SOURCE = "6d67369a1e40847db3f3c8beda3ef668e85eec40"
DIRECTORY = "https://phys.ufl.edu/people/faculty/"
SHARD = "data/processed/shards/uf.json"
LEDGER = "data/processed/collector_status.json"
UF_CODE = "src/collectors/schools/uf_faculty.py"
GRAPH_CODE = "src/collectors/faculty_graph.py"
EXPECTED = Path(__file__).with_name("normal-refresh-failure-and-recovery.json")
HEADERS = {"User-Agent": "OFE-UF-Physics-publication-check/1.0"}
GITHUB = requests.Session()
GITHUB.headers.update(HEADERS)
GITHUB.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=2,
            backoff_factor=1,
            allowed_methods={"GET"},
            status_forcelist=(502, 503, 504),
        )
    ),
)
# Campus reads use the same ordinary HTTP headers that the school collector uses.
try:
    from src.collectors.ucb_common import HEADERS as CAMPUS_HEADERS
except ImportError:
    CAMPUS_HEADERS = HEADERS


def api(path, **params):
    response = GITHUB.get(f"{API}/{path}", params=params, timeout=(12, 45))
    response.raise_for_status()
    return response.json()


def blob(revision, path):
    metadata = api("contents/" + path, ref=revision)
    raw = GITHUB.get(f"https://raw.githubusercontent.com/{REPO}/{revision}/{path}", timeout=(12, 60))
    raw.raise_for_status()
    content = raw.content
    oid = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    if oid != metadata["sha"]:
        raise ValueError(f"Downloaded blob differs from GitHub's identifier for {path}")
    return oid, content


def source_parts(content, path):
    """Recognize a squash with the same adapter and directory-rank handling."""
    module = ast.parse(content)
    if path == UF_CODE:
        signed = [
            n
            for n in module.body
            if isinstance(n, ast.FunctionDef)
            and n.name == "_physics_rank"
            or isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id.startswith("_PHY_") for t in n.targets)
        ]
        for d in (n for n in ast.walk(module) if isinstance(n, ast.Dict)):
            if any(
                isinstance(k, ast.Constant) and k.value == "short" and isinstance(v, ast.Constant) and v.value == "PHY"
                for k, v in zip(d.keys, d.values, strict=True)
            ):
                signed.append(d)
        return [ast.dump(n) for n in signed]
    parser = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "_parse_cards")
    return [
        ast.dump(n)
        for n in ast.walk(parser)
        if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "directory_rank"
    ]


def lineage(revision):
    comparison = api(f"compare/{SOURCE}...{revision}", per_page=1)
    if comparison["status"] in {"ahead", "identical"}:
        return "ancestor"
    for path in (UF_CODE, GRAPH_CODE):
        expected = source_parts(blob(SOURCE, path)[1], path)
        if not expected or source_parts(blob(revision, path)[1], path) != expected:
            return "unconfirmed"
    return "same_reviewed_code_after_squash"


def when(text):
    if not isinstance(text, str):
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    except ValueError:
        return None


def get_run(args):
    if args.run:
        return api(f"actions/runs/{args.run}")
    runs = api(
        "actions/workflows/refresh-data.yml/runs",
        event="schedule",
        branch="main",
        created=args.date.isoformat(),
        per_page=100,
    )["workflow_runs"]
    if len(runs) > 1:
        raise ValueError("Multiple scheduled runs on this date. Select the UF run with --run.")
    return runs[0] if runs else None


def get_pr(run_id, requested):
    if requested:
        return api(f"pulls/{requested}")
    found = []
    for branch in (f"auto/refresh-data-{run_id}", f"auto/refresh-data-{run_id}-r2"):
        found.extend(api("pulls", state="all", base="main", head=f"EricXu-0805:{branch}", per_page=10))
    merged = [p for p in found if p.get("merged_at")]
    if len(merged) > 1:
        raise ValueError("Multiple merged data PRs. Select the publication with --data-pr.")
    return merged[0] if merged else next(iter(found), None)


def check_campus(row):
    url = row["expected_profile"]
    try:
        r = requests.get(url, headers=CAMPUS_HEADERS, timeout=25)
        soup = BeautifulSoup(r.content, "html.parser")
        headings = [h.get_text(" ", strip=True) for h in soup.select("main h1, article h1")]
        named = row["expected_name"] in headings
        roles = soup.select("main [class*='position'], main [class*='job-title'], main [class*='faculty-title']")
        rank_matches = any(n.get_text(" ", strip=True) == row["published_rank"] for n in roles)
        confirmed = r.status_code == 200 and r.url == url and named and rank_matches
        result = {
            "http": r.status_code,
            "landing_url": r.url,
            "named_heading": named,
            "rank_matches": rank_matches,
            "matches": confirmed,
            "blocked": r.status_code in (401, 403, 429) or r.status_code >= 500,
        }
    except requests.RequestException as exc:
        result = {"matches": False, "blocked": True, "error": type(exc).__name__}
    time.sleep(0.35)
    return result


def campus_checks(rows):
    response = requests.get(DIRECTORY, headers=CAMPUS_HEADERS, timeout=25)
    if response.status_code != 200 or response.url != DIRECTORY:
        return {"status": response.status_code, "landed": response.url, "blocked": True}, False
    soup = BeautifulSoup(response.content, "html.parser")
    cards = {}
    for card in soup.select("main article.ufclas-team-grid__item"):
        section = card.find_previous("h2")
        if not section or section.get_text(" ", strip=True) != "Faculty":
            continue
        person = card.select_one("h3.ufclas-team-grid__name")
        role = card.select_one(".ufclas-team-grid__position")
        bio = card.select_one(".ufclas-team-grid__bio a[href]")
        if person and role and bio:
            key = (person.get_text(" ", strip=True), urljoin(DIRECTORY, bio["href"]))
            cards.setdefault(key, []).append(role.get_text(" ", strip=True))
    if not cards:
        return {"status": 200, "blocked": True, "reason": "no_readable_faculty_cards"}, False
    with ThreadPoolExecutor(max_workers=3) as pool:
        for row, person_page in zip(rows, pool.map(check_campus, rows), strict=True):
            row["campus_profile"] = person_page
            row["campus_name_url_rank_match"] = cards.get((row["expected_name"], row["expected_profile"])) == [
                row["published_rank"]
            ]
    return {
        "status": 200,
        "landed": response.url,
        "named_faculty_cards": len(cards),
        "blocked": any(r["campus_profile"]["blocked"] for r in rows),
    }, True


def examine(args, report):
    run = get_run(args)
    if not run:
        return "awaiting_scheduled_run", 2
    if (
        run["event"] != "schedule"
        or run["path"] != ".github/workflows/refresh-data.yml"
        or run["head_branch"] != "main"
        or when(run["created_at"]).date() != args.date
    ):
        raise ValueError("The supplied run is not this date's scheduled main refresh.")
    report.update(
        run=run["html_url"],
        run_id=run["id"],
        run_head=run["head_sha"],
        workflow_state=run["status"],
        workflow_conclusion=run.get("conclusion"),
    )
    pr = get_pr(run["id"], args.data_pr)
    if not pr:
        if run["status"] == "completed" and run.get("conclusion") != "success":
            return "scheduled_workflow_ended_without_publishing", 1
        return "awaiting_data_pr", 2
    if (
        pr["base"]["ref"] != "main"
        or pr["head"]["repo"]["full_name"] != REPO
        or not re.fullmatch(rf"auto/refresh-data-{run['id']}(?:-r2)?", pr["head"]["ref"])
    ):
        raise ValueError("The data PR was not produced by this scheduled run.")
    report.update(data_pr=pr["html_url"], merged_at=pr.get("merged_at"))
    if not pr.get("merged_at") or run["status"] != "completed":
        return "awaiting_completed_run_and_merged_pr", 2

    ref = pr["merge_commit_sha"]
    source_status = lineage(run["head_sha"])
    canonical = {r["id"]: r for r in json.loads(EXPECTED.read_text())["reviewed_fields"]}
    initial = {r["id"]: r for r in json.loads(blob(SOURCE, SHARD)[1]) if r["id"] in canonical}
    if len(initial) != len(canonical) or len(initial) != 52:
        raise ValueError("The source baseline does not contain 52 unique original identities.")
    ledger_oid, ledger_bytes = blob(ref, LEDGER)
    campus_oid, campus_bytes = blob(ref, SHARD)
    head = pr["head"]["sha"]
    head_match = all(
        api("contents/" + path, ref=head)["sha"] == oid for path, oid in ((SHARD, campus_oid), (LEDGER, ledger_oid))
    )
    previous = api("git/commits/" + ref)["parents"][0]["sha"]
    previous_oids = {p: api("contents/" + p, ref=previous)["sha"] for p in (SHARD, LEDGER)}
    ledger = json.loads(ledger_bytes)
    campus = json.loads(campus_bytes)
    count = Counter(r["id"] for r in campus)
    lookup = {r["id"]: r for r in campus}
    source = ledger.get("sources", {}).get("uf_faculty", {})
    unit = source.get("stale_unit_ledger", {}).get("phy", {})
    listed = Counter(unit.get("observed_entity_ids") or [])
    start, end = when(run["run_started_at"]), when(run["updated_at"])
    stamp = when(ledger.get("timestamp"))
    release = ledger.get("release", {})
    ready = release.get("by_unit", {}).get("uf", {}).get("ready") is True and "uf" in release.get("publishable", [])
    unit_start, unit_end = when(unit.get("started_at")), when(unit.get("completed_at"))
    unit_checks = {
        "merged_pr_contains_published_uf_and_ledger_blobs": head_match,
        "merged_uf_and_ledger_advanced_since_first_parent": (
            previous_oids[SHARD] != campus_oid and previous_oids[LEDGER] != ledger_oid
        ),
        "uf_authorized_and_published": ready and "uf" in (ledger.get("request", {}).get("schools") or []),
        "ledger_written_during_run": bool(stamp and start <= stamp <= end),
        "physics_unit": unit.get("unit_name") == "Department of Physics" and unit.get("school") == "uf",
        "physics_unit_ran_during_the_workflow": bool(
            unit_start and unit_end and start <= unit_start <= unit_end <= end
        ),
        "physics_fetch_parse_complete": (
            unit.get("fetch_status"),
            unit.get("parse_status"),
            unit.get("completeness_status"),
        )
        == ("ok", "ok", "complete"),
        "observed_ids_count_agrees": unit.get("observed_count")
        == unit.get("coverage", {}).get("parsed_faculty_rows")
        == len(listed)
        and all(v == 1 and i.startswith("faculty-uf-phy-") for i, v in listed.items()),
        "no_missed_identities_or_partial_rows": not unit.get("missed_present_identities")
        and all(
            unit.get("coverage", {}).get(key) == 0
            for key in (
                "duplicate_rows",
                "partial_render_rows",
                "unparsed_rows",
                "ambiguous_rows",
                "identity_match_failures",
                "parser_errors",
            )
        ),
    }
    report.update(
        source_provenance=source_status,
        data_merge=ref,
        data_head=head,
        merge_first_parent=previous,
        prior_blobs=previous_oids,
        published_blobs={SHARD: campus_oid, LEDGER: ledger_oid},
        school_corpus_rows=len(campus),
        duplicate_uf_ids=sorted(i for i, n in count.items() if n != 1),
        uf_source_status=source.get("status"),
        physics={
            k: unit.get(k)
            for k in (
                "unit_name",
                "fetch_status",
                "parse_status",
                "completeness_status",
                "observed_count",
                "coverage",
                "started_at",
                "completed_at",
            )
        },
        unit_checks=unit_checks,
        expected_ids_missing_from_observations=sorted(canonical.keys() - listed.keys()),
        other_observed_physics_ids=sorted(listed.keys() - canonical.keys()),
    )
    rows = []
    for oid, expected in sorted(canonical.items()):
        row = lookup.get(oid, {})
        meta = row.get("metadata") or {}
        quote = meta.get("faculty_title_observation") or {}
        last = when(meta.get("last_seen_at"))
        checks = {
            "one_published_original": count[oid] == 1,
            "one_observation": listed[oid] == 1,
            "still_active": meta.get("is_active") is True,
            "name": row.get("pi_name") == expected["pi_name"],
            "named_profile": row.get("url") == row.get("source_url") == expected["url"],
            "first_seen_preserved": meta.get("first_seen_at") == initial[oid]["metadata"]["first_seen_at"],
            "seen_during_run": bool(last and start <= last <= end),
            "rank_bound_to_directory_and_person": (
                bool(meta.get("faculty_title"))
                and quote.get("name") == row.get("pi_name")
                and quote.get("title") == meta.get("faculty_title")
                and quote.get("source") == DIRECTORY
                and quote.get("profile") == expected["url"]
                and bool(last)
                and quote.get("checked_on") == last.date().isoformat()
            ),
        }
        rows.append(
            {
                "id": oid,
                "expected_name": expected["pi_name"],
                "expected_profile": expected["url"],
                "published_name": row.get("pi_name"),
                "published_rank": meta.get("faculty_title"),
                "published_profile": row.get("url"),
                "published_last_seen_at": meta.get("last_seen_at"),
                "observations": listed[oid],
                "checks": checks,
            }
        )
    report["originals"] = rows
    if report["duplicate_uf_ids"] or not all(unit_checks.values()) or not all(all(r["checks"].values()) for r in rows):
        return "published_originals_or_physics_ledger_need_review", 1
    if source_status == "unconfirmed":
        return "checked_release_did_not_establish_collection_from_the_fix", 2
    official, available = campus_checks(rows)
    report["live_official_directory"] = official
    if official.get("blocked") or not available:
        return "published_originals_passed_current_campus_verification_pending", 2
    if not all(r["campus_name_url_rank_match"] and r["campus_profile"]["matches"] for r in rows):
        return "published_and_current_campus_evidence_differ", 1
    if run.get("conclusion") != "success":
        return "physics_publication_verified_workflow_ended_with_an_issue", 1
    return "verified_scheduled_publication", 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date(2026, 11, 27))
    parser.add_argument("--run", type=int)
    parser.add_argument("--data-pr", type=int)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "target_utc_date": args.date.isoformat(),
        "reviewed_source": SOURCE,
    }
    try:
        state, code = examine(args, report)
    except (requests.RequestException, ValueError, KeyError) as exc:
        state, code = "evidence_unavailable_or_mismatched", 2
        report["error"] = str(exc)[:400]
    report["result"] = state
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(state, args.out)
    return code


if __name__ == "__main__":
    sys.exit(main())
