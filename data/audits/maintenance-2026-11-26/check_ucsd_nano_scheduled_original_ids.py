"""Read the actual scheduled UCSD run, posted data PR and published original IDs."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

REPO = "EricXu-0805/opportunity-filter-engine"
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


def gh(*args):
    return json.loads(subprocess.check_output(["gh", *args]))


def read_published_blobs(revision):
    query = '''query($revision:String!, $ledger:String!, $campus:String!) {
      repository(owner:"EricXu-0805",name:"opportunity-filter-engine") {
        commit:object(expression:$revision) { oid }
        ledger:object(expression:$ledger) { oid }
        campus:object(expression:$campus) { oid }
      }
    }'''
    out = gh("api", "graphql", "-f", "query=" + query, "-f", "revision=" + revision,
             "-f", "ledger=" + revision + ":" + LEDGER, "-f", "campus=" + revision + ":" + CAMPUS)
    refs = out["data"]["repository"]
    assert refs["commit"]["oid"] == revision

    def read(oid):
        raw = subprocess.check_output([
            "gh", "api", "-H", "Accept: application/vnd.github.raw+json", f"repos/{REPO}/git/blobs/{oid}",
        ])
        assert hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == oid
        return json.loads(raw)

    return read(refs["ledger"]["oid"]), read(refs["campus"]["oid"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=int)
    parser.add_argument("--data-pr", required=True, type=int)
    parser.add_argument("--jahed", action="store_true", help="Also require the B20 Jahed collection and stable ID.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = gh("api", f"repos/{REPO}/actions/runs/{args.run}")
    pr = gh("api", f"repos/{REPO}/pulls/{args.data_pr}")
    assert run["event"] == "schedule" and run["path"] == ".github/workflows/refresh-data.yml"
    assert pr["head"]["ref"] == f"auto/refresh-data-{args.run}" and pr["base"]["ref"] == "main"
    # Track the collection change itself. Later tests and static-count commits do not change its behavior.
    expected = "dcad2b4e0b055844c9f6c61c73cb76a5e8cbdd9c" if args.jahed else "13061d423178121463c101fd891e40b34d13ae77"
    compare = gh("api", f"repos/{REPO}/compare/{expected}...{run['head_sha']}?per_page=1")
    contains = compare["status"] in {"ahead", "identical"}
    report = {"run": run["html_url"], "event": run["event"], "run_started_at": run["run_started_at"],
              "sha_actually_collected": run["head_sha"], "conclusion_for_all_schools": run["conclusion"],
              "data_pr": pr["html_url"], "data_pr_merged_at": pr["merged_at"], "scope_requires_jahed": args.jahed,
              "checked_source_head": expected, "includes_source_head": contains,
              "publication": "pending" if not pr["merged_at"] else "data_pr_merged_source_revision_unconfirmed"}
    if not contains:
        report["revision_note"] = "A run predating the change or a separately squashed fix needs its own source comparison."
    if contains and pr["merged_at"]:
        status, campus = read_published_blobs(pr["merge_commit_sha"])
        src = status["sources"].get("ucsd_faculty", {})
        unit = src.get("stale_unit_ledger", {}).get("nano", {})
        published = status["release"].get("by_unit", {}).get("ucsd", {}).get("ready") is True
        published = published and "ucsd" in status["release"].get("publishable", [])
        ids = unit.get("observed_entity_ids", [])
        lookup = {r["id"]: r for r in campus}
        wanted = {**ARCHIVES, KEN: "Ken Vecchio"}
        if args.jahed:
            wanted[JAHED] = "Zeinab Jahed"
        identities = {}
        for oid, name in wanted.items():
            row = lookup.get(oid, {})
            expected_active = oid not in ARCHIVES
            identities[oid] = {"expected_name": name, "published_name": row.get("pi_name"),
                               "stored_active": row.get("metadata", {}).get("is_active"),
                               "roster_observations": ids.count(oid), "citation": row.get("source_url"),
                               "profile": row.get("url")}
            identities[oid]["satisfies_identity_checks"] = (
                row.get("pi_name") == name and identities[oid]["stored_active"] is expected_active
                and ids.count(oid) == int(expected_active)
            )
            if oid == JAHED:
                receipt = row.get("metadata", {}).get("faculty_title_observation", {})
                biography = "https://jacobsschool.ucsd.edu/faculty/profile?id=527"
                roster = "https://www.nanoengineering.ucsd.edu/index.php/fac"
                identities[oid]["recorded_rank_observation"] = receipt
                identities[oid]["satisfies_identity_checks"] &= (
                    row.get("url") == row.get("source_url") == biography
                    and receipt.get("name") == name and receipt.get("source") == receipt.get("profile") == biography
                    and receipt.get("roster_url") == roster and bool(receipt.get("title"))
                )
        prior = json.loads(Path(__file__).with_name("ucsd-jahed-appointment-original-id-retry.json").read_bytes())
        expected_ids = set(prior["ordered_projected_ids"])
        if not args.jahed:
            expected_ids.discard(JAHED)
        report.update(
            publication="published" if published else "withheld", campus_merge_sha=pr["merge_commit_sha"],
            campus_count=len(campus), source_status=src.get("status"), department=unit.get("unit_name"),
            fetch_status=unit.get("fetch_status"), parse_status=unit.get("parse_status"),
            observed_rows=unit.get("observed_count"), distinct_observed_ids=len(set(ids)),
            unit_coverage=unit.get("coverage"), completeness=unit.get("completeness_status"),
            missed_present_identity_count=len(unit.get("missed_present_identities") or []),
            candidate_ids_missing_from_actual_roster=sorted(expected_ids - set(ids)),
            actual_ids_beyond_candidate=sorted(set(ids) - expected_ids),
            original_identity_comparison=identities,
        )
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(report["publication"], "includes source:", contains, "receipt:", args.out)
    if report["publication"] != "published":
        raise SystemExit(2)
    if (report["source_status"] != "ok" or report["fetch_status"] != "ok" or report["parse_status"] != "ok"
            or report["candidate_ids_missing_from_actual_roster"] or report["missed_present_identity_count"]
            or not all(r["satisfies_identity_checks"] for r in report["original_identity_comparison"].values())):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
