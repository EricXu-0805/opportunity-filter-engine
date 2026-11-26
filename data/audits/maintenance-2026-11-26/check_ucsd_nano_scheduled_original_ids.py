"""Check the published UCSD NanoEngineering records from one natural Friday refresh.

Example from the repository root:
    python data/audits/maintenance-2026-11-26/check_ucsd_nano_scheduled_original_ids.py \
        --date 2026-11-27 --jahed --out /tmp/ucsd-nano-20261127.json

--run and --data-pr can pin the publication. Exit 0 verifies the requested
observations, 1 reports a discrepancy, and 2 means the evidence is pending or
unavailable. This program reads public repository data and writes only --out.
"""

import argparse
import ast
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path

REPO = "EricXu-0805/opportunity-filter-engine"
API = f"repos/{REPO}/"
AUDIT = Path(__file__).resolve().parent
B19 = "13061d423178121463c101fd891e40b34d13ae77"
B20 = "dcad2b4e0b055844c9f6c61c73cb76a5e8cbdd9c"
ARCHIVES = {
    "faculty-ucsd-nano-25a6d469": "Sadik Esener",
    "faculty-ucsd-nano-dc9e3de3": "Michael Heller",
    "faculty-ucsd-nano-2aa92754": "Darren Lipomi",
    "faculty-ucsd-nano-04ac1d79": "Ying Shirley Meng",
    "faculty-ucsd-nano-27240933": "Sheng Xu",
}
KEN = "faculty-ucsd-nano-467aa36b"
JAHED = "faculty-ucsd-nano-8a42e65d"
CAMPUS = "data/processed/shards/ucsd.json"
LEDGER = "data/processed/collector_status.json"
CONFIG = "src/collectors/schools/ucsd_faculty.py"
GRAPH = "src/collectors/faculty_graph.py"
REVIEWS = "src/normalizers/reviewed_faculty_profiles.py"
UNIT = "Department of NanoEngineering"
ROSTER = "https://nanoengineering.ucsd.edu/fac/nanoe-faculty"
COMBINED = "https://www.nanoengineering.ucsd.edu/index.php/fac"
JACOBS = "https://jacobsschool.ucsd.edu/faculty/profile?id="
KEN_LINKS = {"http://jacobsschool.ucsd.edu/faculty/faculty_bios/index.sfe?fmp_recid=156", JACOBS + "156"}


def api(endpoint):
    return json.loads(subprocess.check_output(["gh", "api", API + endpoint], timeout=100))


def stamp(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def inside(value, beginning, end):
    return bool(value and beginning and end and beginning <= value <= end)


def local(*args):
    return subprocess.run(["git", "-C", str(AUDIT), *args], capture_output=True)


@cache
def object_id(revision, path):
    # All caller-supplied revisions originate in GitHub's run/PR metadata or a pinned commit.
    local_oid = local("rev-parse", "--verify", revision + ":" + path)
    if local_oid.returncode == 0:
        return local_oid.stdout.decode().strip()
    return api("contents/" + path + "?ref=" + revision)["sha"]


@cache
def contents(revision, path):
    oid = object_id(revision, path)
    stored = local("cat-file", "blob", oid)
    raw = (
        stored.stdout
        if stored.returncode == 0
        else subprocess.check_output(
            ["gh", "api", "-H", "Accept: application/vnd.github.raw+json", API + "git/blobs/" + oid], timeout=120
        )
    )
    if hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != oid:
        raise ValueError("Object does not match its published Git identifier: " + path)
    return raw


def fingerprints(revision):
    config = ast.parse(contents(revision, CONFIG))
    if not any(isinstance(n, ast.FunctionDef) and n.name == "_nano_reviewed_rank" for n in config.body):
        return []
    graph = ast.parse(contents(revision, GRAPH))
    selected = [
        n
        for n in config.body
        if isinstance(n, ast.FunctionDef)
        and n.name.startswith("_nano_")
        or isinstance(n, ast.Assign)
        and any(
            isinstance(k, ast.Name)
            and (k.id.startswith("_NANO_") or k.id in {"_JACOBS_PROFILE", "_JACOBS_OLD_BIO", "_LADDER"})
            for k in n.targets
        )
    ]
    selected.extend(
        n
        for n in ast.walk(config)
        if isinstance(n, ast.Call) and any(isinstance(a, ast.Constant) and a.value == "NANO" for a in n.args)
    )
    # Bind the shared rank reader and its named citation as well as the department selectors.
    for n in ast.walk(graph):
        if isinstance(n, ast.If) and any(
            isinstance(c, ast.Constant) and c.value in {"review_profile_rank", "cite_profile_rank"}
            for c in ast.walk(n.test)
        ):
            selected.append(n)
    reviews = ast.parse(contents(revision, REVIEWS))
    selected.extend(
        n
        for n in reviews.body
        if isinstance(n, ast.FunctionDef)
        and (n.name.startswith("_ucsd_nano") or n.name == "carry_forward_reviewed_appointment")
    )
    for n in ast.walk(reviews):
        if isinstance(n, ast.Dict):
            selected.extend(
                ast.Tuple(elts=[key, val])
                for key, val in zip(n.keys, n.values, strict=True)
                if isinstance(key, ast.Constant) and key.value in ARCHIVES
            )
    return [ast.dump(n) for n in selected]


def provenance(revision, jahed):
    # A later combined B20 revision is also sufficient for B19-only checks.
    for known in [B20] if jahed else [B19, B20]:
        relation = api(f"compare/{known}...{revision}?per_page=1")["status"]
        signature = fingerprints(known)
        if signature and fingerprints(revision) == signature:
            return {
                "reviewed_revision": known,
                "comparison": relation,
                "method": "reviewed_collector_in_ancestry"
                if relation in {"ahead", "identical"}
                else "equivalent_reviewed_collector_after_integration",
            }
    return {"method": "unconfirmed"}


def get_run(args):
    if args.run:
        return api(f"actions/runs/{args.run}")
    runs = api(
        "actions/workflows/refresh-data.yml/runs?event=schedule&branch=main&per_page=100&created="
        + args.date.isoformat()
    )["workflow_runs"]
    if len(runs) > 1:
        raise ValueError("Multiple scheduled publications on this date; supply --run.")
    return next(iter(runs), None)


def get_pr(run, number):
    if number:
        return api(f"pulls/{number}")
    found = []
    for suffix in ("", "-r2"):
        found.extend(api(f"pulls?state=all&base=main&head=EricXu-0805:auto/refresh-data-{run}{suffix}"))
    merged = [p for p in found if p.get("merged_at")]
    if len(merged) > 1:
        raise ValueError("Multiple merged publications for the run; supply --data-pr.")
    return next(iter(merged or found), None)


def reviewed(jahed):
    prior = json.loads((AUDIT / "ucsd-jahed-appointment-original-id-retry.json").read_bytes())
    active = list(prior["ordered_projected_ids"])
    if not jahed:
        active.remove(JAHED)
    if len(active) != len(set(active)) or len(active) != (37 if jahed else 36):
        raise ValueError("Unexpected reviewed roster size")
    baseline = json.loads(contents(B20 if jahed else B19, CAMPUS))
    lookup = {r["id"]: r for r in baseline}
    ledger_only = set(
        json.loads((AUDIT / "ucsd-nano-two-emeritus-appointments.json").read_bytes())["department_reconciliation"][
            "projected_unit_ids_kept_elsewhere_in_campus_source"
        ]
    )
    if ledger_only != set(active) - lookup.keys() or len(ledger_only) != 9:
        raise ValueError("Published cross-department deduplication baseline differs from the review.")
    return active, lookup, ledger_only


def fields(row):
    m = row.get("metadata", {})
    result = {k: row.get(k) for k in ("pi_name", "url", "source_url", "department", "school", "source")}
    result.update(
        {
            k: m.get(k)
            for k in (
                "first_seen_at",
                "last_seen_at",
                "is_active",
                "faculty_title",
                "deactivation_reason",
                "deactivated_at",
            )
        }
    )
    result["faculty_profile_review"] = {
        k: v
        for k, v in (m.get("faculty_profile_review") or {}).items()
        if k in {"previous_url", "source_url", "reviewed_on", "previous_title"}
    }
    result["faculty_title_observation"] = {
        k: v
        for k, v in (m.get("faculty_title_observation") or {}).items()
        if k in {"source", "roster_url", "profile", "name", "title", "checked_on"}
    }
    return result


def department_report(status, campus, prior_rows, roster, baseline, ledger_only, run):
    source = status.get("sources", {}).get("ucsd_faculty", {})
    unit = source.get("stale_unit_ledger", {}).get("nano", {})
    release = status.get("release", {})
    start, end = stamp(run["run_started_at"]), stamp(run["updated_at"])
    unit_start, unit_end = stamp(unit.get("started_at")), stamp(unit.get("completed_at"))
    observed = Counter(unit.get("observed_entity_ids") or [])
    lookup = defaultdict(list)
    for row in campus:
        lookup[row["id"]].append(row)
    previous = {r["id"]: r for r in prior_rows}
    coverage = unit.get("coverage") or {}
    flags = {
        "UCSD_requested_and_publishable": (
            "ucsd" in (status.get("request", {}).get("schools") or [])
            and "ucsd" in (release.get("publishable") or [])
            and release.get("by_unit", {}).get("ucsd", {}).get("ready") is True
        ),
        "ledger_generated_within_run": inside(stamp(status.get("timestamp")), start, end),
        "department_identified": (
            unit.get("unit_id"),
            unit.get("school"),
            unit.get("source"),
            unit.get("unit_name"),
            unit.get("unit_url"),
            unit.get("roster_source_confirmed"),
        )
        == ("nano", "ucsd", "ucsd_faculty", UNIT, ROSTER, True),
        "department_read_within_run": inside(unit_start, start, end) and inside(unit_end, unit_start, end),
        "department_read_and_parsed": (
            unit.get("fetch_status"),
            unit.get("parse_status"),
            unit.get("validation_status"),
        )
        == ("ok", "ok", "ok")
        and not unit.get("failure_reason"),
        "no_unresolved_named_records": not unit.get("missed_present_identities")
        and all(
            coverage.get(k) == 0
            for k in ("ambiguous_rows", "identity_match_failures", "parser_errors", "partial_render_rows")
        ),
        "department_recorded_concrete_observations": bool(observed)
        and isinstance(unit.get("observed_count"), int)
        and 0 < unit["observed_count"] <= len(observed),
        "no_duplicate_ledger_ids": not any(n > 1 for n in observed.values()),
    }
    # observed_count measures rows emitted after campus dedup. observed_entity_ids also includes
    # people read here but emitted by a sibling. A partial unit may still publish its identified
    # people. Neither its coverage.duplicate_rows nor its retirement verdict is an ID count.
    original = {}
    expected_labels = {
        r["raw_projected_unit_id"]: r["displayed_name"]
        for r in json.loads((AUDIT / "ucsd-nano-two-emeritus-appointments.json").read_bytes())[
            "department_reconciliation"
        ]["each_source_row_before_and_after"]
        if r.get("raw_projected_unit_id")
    }
    sensitive = set(roster) | set(ARCHIVES)
    for oid in dict.fromkeys([*ARCHIVES, *roster]):
        n = len(lookup.get(oid, []))
        row = fields(lookup[oid][0]) if n else {}
        original_row = fields(baseline[oid]) if oid in baseline else {}
        previous_row = fields(previous[oid]) if oid in previous else {}
        exited = oid in ARCHIVES
        checks = {
            "department_observations": observed[oid] == int(not exited),
            "single_published_original": n <= 1 if oid in ledger_only else n == 1,
        }
        if oid in ledger_only and not n:
            checks["live_department_read_proven"] = (
                unit.get("retained_only_count") == 0
                and isinstance(unit.get("live_roster_count"), int)
                and unit["live_roster_count"] >= len(observed)
            )
        if n or oid not in ledger_only:
            last = stamp(row.get("last_seen_at"))
            checks.update(
                original_unit=(row.get("school"), row.get("source"), row.get("department"))
                == ("ucsd", "ucsd_faculty", UNIT),
                activity=row.get("is_active") is (not exited),
                first_seen_preserved=(
                    row.get("first_seen_at") == original_row.get("first_seen_at")
                    if original_row
                    else bool(row.get("first_seen_at"))
                ),
            )
            if exited:
                checks.update(
                    correct_named_archive=(
                        row.get("pi_name") == ARCHIVES[oid]
                        and all(
                            row.get(k) == original_row[k]
                            for k in (
                                "url",
                                "source_url",
                                "faculty_title",
                                "deactivation_reason",
                                "deactivated_at",
                                "faculty_profile_review",
                            )
                        )
                    ),
                    last_seen_preserved=bool(previous_row.get("last_seen_at"))
                    and row.get("last_seen_at") == previous_row["last_seen_at"]
                    and bool(last and unit_start and last < unit_start),
                )
            else:
                checks["observed_in_this_department_read"] = inside(last, unit_start, unit_end)
                if original_row:
                    checks["record_still_names_reviewed_person"] = row.get("pi_name") == original_row["pi_name"]
            if oid == KEN:
                checks["person_and_profile"] = (
                    row.get("pi_name") == "Ken Vecchio" and {row.get("url"), row.get("source_url")} <= KEN_LINKS
                )
            if oid == JAHED:
                q = row.get("faculty_title_observation") or {}
                checks["person_profile_two_sources_and_current_rank"] = (
                    row.get("pi_name") == q.get("name") == "Zeinab Jahed"
                    and row.get("url") == row.get("source_url") == q.get("profile") == q.get("source") == JACOBS + "527"
                    and q.get("roster_url") == COMBINED
                    and bool(row.get("faculty_title"))
                    and q.get("title") == row.get("faculty_title")
                    and bool(last)
                    and q.get("checked_on") == last.date().isoformat()
                )
        original[oid] = {
            "expected": "archived"
            if exited
            else "cross_department_roster_id"
            if oid in ledger_only
            else "active_original",
            "reviewed_directory_label": expected_labels.get(oid) or original_row.get("pi_name"),
            "expected_reviewed_fields": original_row,
            "source_differences_from_review": {
                k: {"reviewed": original_row.get(k), "published": row.get(k)}
                for k in ("pi_name", "url", "source_url", "faculty_title")
                if row and original_row and original_row.get(k) != row.get(k)
            },
            "previous_last_seen_at": previous_row.get("last_seen_at"),
            "published_rows": n,
            "roster_observations": observed[oid],
            "actual": row,
            "checks": checks,
        }
    known_profiles = {
        u: i
        for i in set(ARCHIVES) | {KEN, JAHED}
        if i in baseline
        for u in ({baseline[i].get("url")} | (KEN_LINKS if i == KEN else set()))
        if u
    }
    same_profile = [
        {"published_id": i, "original": known_profiles[r["url"]], "person_url": r["url"]}
        for i, rows in lookup.items()
        if i.startswith("faculty-ucsd-nano-") and i not in sensitive
        for r in rows
        if r.get("url") in known_profiles and i != known_profiles[r["url"]]
    ]
    flags["no_duplicate_reviewed_person_profile"] = not same_profile
    extra = sorted(observed.keys() - sensitive)
    return {
        "source_status": source.get("status"),
        "conclusion_for_all_schools": run.get("conclusion"),
        "release_for_UCSD": release.get("by_unit", {}).get("ucsd"),
        "ledger_timestamp": status.get("timestamp"),
        "department": {
            k: unit.get(k)
            for k in (
                "unit_id",
                "unit_name",
                "school",
                "source",
                "unit_url",
                "started_at",
                "completed_at",
                "fetch_status",
                "parse_status",
                "validation_status",
                "completeness_status",
                "retirement_authorized",
                "coverage",
                "observed_count",
                "live_roster_count",
                "retained_only_count",
                "listing_urls",
                "failure_reason",
            )
        },
        "missed_present_identity_count": len(unit.get("missed_present_identities") or []),
        "missed_identity_fingerprints": [
            hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
            for item in (unit.get("missed_present_identities") or [])
        ],
        "archive_evidence_scope": "A zero observation and an unchanged last-seen time establish that the named, previously reviewed archive was carried forward outside this roster. The department ledger supplies no fresh per-person rank citation for these excluded people.",
        "department_checks": flags,
        "original_identity_comparison": original,
        "expected_active_ids_missing": sorted(set(roster) - observed.keys()),
        "archived_ids_observed_again": sorted(observed.keys() & ARCHIVES.keys()),
        "other_observed_ids": extra,
        "duplicate_observed_ids": {i: n for i, n in observed.items() if n > 1},
        "duplicate_published_ids": {i: len(rows) for i, rows in lookup.items() if len(rows) > 1},
        "duplicate_reviewed_profiles": same_profile,
        "ordered_observed_department_ids": unit.get("observed_entity_ids") or [],
        "campus_rows": len(campus),
        "campus_ids_added_since_first_parent": sorted(lookup.keys() - previous.keys()),
        "campus_ids_removed_since_first_parent": sorted(previous.keys() - lookup.keys()),
    }


def examine(args, report):
    run = get_run(args)
    if not run:
        return "awaiting_scheduled_run", 2
    if (run["event"], run["head_branch"], run["path"], stamp(run["created_at"]).date()) != (
        "schedule",
        "main",
        ".github/workflows/refresh-data.yml",
        args.date,
    ):
        raise ValueError("The supplied run is not the target date's scheduled main refresh.")
    report.update(
        run=run["html_url"],
        run_id=run["id"],
        run_started_at=run["run_started_at"],
        run_updated_at=run["updated_at"],
        sha_actually_collected=run["head_sha"],
        workflow_status=run["status"],
        workflow_conclusion=run.get("conclusion"),
    )
    pr = get_pr(run["id"], args.data_pr)
    if not pr:
        return ("completed_without_data_publication", 1) if run["status"] == "completed" else ("awaiting_data_pr", 2)
    if (
        pr["base"]["ref"] != "main"
        or pr["head"]["repo"]["full_name"] != REPO
        or not re.fullmatch(rf"auto/refresh-data-{run['id']}(?:-r2)?", pr["head"]["ref"])
    ):
        raise ValueError("The data PR does not belong to this run.")
    report.update(data_pr=pr["html_url"], data_pr_merged_at=pr.get("merged_at"))
    if not pr.get("merged_at") or run["status"] != "completed":
        return "awaiting_completed_run_and_merged_data_pr", 2
    head, merge = pr["head"]["sha"], pr["merge_commit_sha"]
    parent = api(f"git/commits/{merge}")["parents"][0]["sha"]
    revisions = {"first_parent": parent, "data_head": head, "publication": merge}
    blobs = {k: {p: object_id(rev, p) for p in (CAMPUS, LEDGER)} for k, rev in revisions.items()}
    publication_checks = {
        p: blobs["data_head"][p] == blobs["publication"][p] != blobs["first_parent"][p] for p in (CAMPUS, LEDGER)
    }
    report.update(revisions=revisions, published_objects=blobs, publication_checks=publication_checks)
    status = json.loads(contents(merge, LEDGER))
    campus = json.loads(contents(merge, CAMPUS))
    prior_rows = json.loads(contents(parent, CAMPUS))
    roster, baseline, ledger_only = reviewed(args.jahed)
    report.update(department_report(status, campus, prior_rows, roster, baseline, ledger_only, run))
    created, merged = stamp(pr.get("created_at")), stamp(pr.get("merged_at"))
    begun, finished = stamp(run["run_started_at"]), stamp(run["updated_at"])
    read_completed = stamp(report["department"].get("completed_at"))
    publication_checks["data_PR_created_during_run_after_department_read"] = inside(created, begun, finished) and bool(
        read_completed and created >= read_completed
    )
    publication_checks["merged_after_data_PR_creation"] = bool(created and merged and created <= merged)
    report["data_pr_created_at"] = pr.get("created_at")
    report["data_pr_merged_during_run"] = inside(merged, begun, finished)
    report["published_ledger_url"] = f"https://github.com/{REPO}/blob/{merge}/{LEDGER}"
    report["published_campus_url"] = f"https://github.com/{REPO}/blob/{merge}/{CAMPUS}"
    source = provenance(run["head_sha"], args.jahed)
    report["source_provenance"] = source
    if (
        not all(publication_checks.values())
        or not all(report["department_checks"].values())
        or not all(all(p["checks"].values()) for p in report["original_identity_comparison"].values())
    ):
        return "published_originals_or_unit_evidence_need_review", 1
    if source["method"] == "unconfirmed":
        return "collector_revision_requires_independent_comparison", 2
    return "verified_scheduled_department_publication", 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", type=date.fromisoformat, default=date(2026, 11, 27))
    p.add_argument("--run", type=int)
    p.add_argument("--data-pr", type=int)
    p.add_argument(
        "--jahed", action="store_true", help="Require the B20 Jahed original and current two-source observation."
    )
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    report = {
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "target_date": a.date.isoformat(),
        "requires_B20_Jahed": a.jahed,
    }
    try:
        state, code = examine(a, report)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        state, code = "evidence_unavailable_or_mismatched", 2
        report["error"] = str(error)[:400]
    report["publication"] = state
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(state, a.out)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
