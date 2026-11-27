"""Read the NanoEngineering original IDs and their campus primary records after a real scheduled publication."""

import argparse
import json
import re
import time
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

import check_ucsd_nano_scheduled_original_ids as scheduled
import requests
from bs4 import BeautifulSoup

SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
ONG = "faculty-ucsd-nano-e94320ae"
PAGES = (scheduled.JAHED, scheduled.KEN, ONG, *scheduled.ARCHIVES)


def read(url, *, ids=None):
    """Use the normal public API, including its saved-items batch reader."""
    for attempt in range(3):
        response = (
            requests.get(url, timeout=(10, 60))
            if ids is None
            else requests.post(url, json={"ids": ids}, timeout=(10, 60))
        )
        if response.status_code == 429 and attempt < 2:
            wait = response.headers.get("Retry-After", "")
            time.sleep((int(wait) if wait.isdigit() else 60) + 1)
            continue
        response.raise_for_status()
        return response


def visible_main(document):
    main = document.select_one("main")
    assert main is not None
    # Next may append hidden fragments outside <main> and connect them via these stream commands.
    moves = re.compile(r'\$(RS|RC)\("([BPS]:[0-9a-f]+)","([BPS]:[0-9a-f]+)"\)')
    for script in document.find_all("script"):
        for mode, first, second in moves.findall(script.string or ""):
            marker_id, segment_id = (second, first) if mode == "RS" else (first, second)
            marker = document.find("template", id=marker_id)
            segment = document.find("div", id=segment_id, hidden=True)
            if marker is not None and segment is not None:
                marker.replace_with(*list(segment.contents))
    for hidden in main.select("[hidden], [aria-hidden=true], script, template"):
        hidden.decompose()
    return main


def check(args):
    site, api = args.site.rstrip("/"), args.api.rstrip("/")
    receipt = json.loads(args.scheduled.read_bytes()) if args.scheduled else None
    if receipt is not None:
        assert receipt["target_date"] == args.date.isoformat()
        assert receipt["requires_B20_Jahed"] and receipt["publication"] == "verified_scheduled_department_publication"
        for key in ("department_checks", "publication_checks"):
            assert receipt[key] and all(receipt[key].values())
        for row in receipt["original_identity_comparison"].values():
            assert row["checks"] and all(row["checks"].values())
        assert site == api == "https://joinalab.com"
    else:
        assert all(urlsplit(url).hostname in {"127.0.0.1", "localhost"} for url in (api, site))
    release = read(api + "/api/health").json()["release_sha"]
    about = BeautifulSoup(read(site + "/about").content, "html.parser")
    assert about.html["data-release-sha"] == release
    extras = set(receipt["other_observed_ids"]) if receipt is not None else set()
    if receipt is not None:
        release_head = receipt["revisions"]
        publication = release_head["publication"]
        run = scheduled.api(f"actions/runs/{receipt['run_id']}")
        assert (run["event"], run["path"], run["head_branch"], run["status"]) == (
            "schedule",
            ".github/workflows/refresh-data.yml",
            "main",
            "completed",
        )
        assert scheduled.stamp(run["created_at"]).date() == args.date
        assert (run["html_url"], run["head_sha"]) == (receipt["run"], receipt["sha_actually_collected"])
        pr = scheduled.get_pr(run["id"], int(receipt["data_pr"].rsplit("/", 1)[-1]))
        assert pr["base"]["ref"] == "main" and pr["head"]["repo"]["full_name"] == scheduled.REPO
        assert pr["head"]["ref"] in {f"auto/refresh-data-{run['id']}", f"auto/refresh-data-{run['id']}-r2"}
        assert pr["merged_at"] and pr["html_url"] == receipt["data_pr"]
        assert (pr["merge_commit_sha"], pr["head"]["sha"]) == (publication, release_head["data_head"])
        assert scheduled.api("compare/" + publication + "..." + release + "?per_page=1")["status"] in {
            "ahead",
            "identical",
        }
        upstream = {"run": receipt["run"], "data_pr": receipt["data_pr"], "published": publication}
        for path in (scheduled.CAMPUS, scheduled.LEDGER):
            assert scheduled.object_id(publication, path) == receipt["published_objects"]["publication"][path]
        active, _, ledger_only = scheduled.reviewed(True)
        ids = set(active) | scheduled.ARCHIVES.keys()
        assert set(receipt["original_identity_comparison"]) == ids
    else:
        assert release == args.local_candidate
        publication = release
        upstream = {"local_candidate": release}
        active, _, ledger_only = scheduled.reviewed(True)
        ids = set(active) | scheduled.ARCHIVES.keys()

    cross = json.loads(Path(__file__).with_name("ucsd-nano-cross-department-public-ids.json").read_bytes())["records"]
    assert len(cross) == 9 and set(cross) == ledger_only and len(ids) == 42
    unique = sorted(ids | extras | {r["preserved_id"] for r in cross.values()})
    campus = {r["id"]: r for r in json.loads(scheduled.contents(publication, scheduled.CAMPUS))}
    present = {}
    for index in range(0, len(unique), 100):
        batch = unique[index : index + 100]
        response = read(api + "/api/opportunities/batch", ids=batch).json()
        found = {r["id"]: r for r in response["opportunities"]}
        assert response["requested"] == len(batch) and len(found) == response["found"] == len(response["opportunities"])
        assert set(found) <= set(batch)
        present.update(found)
    result = {
        "observed_at": datetime.now(UTC).isoformat(),
        "ui": site,
        "api": api,
        "release_sha": release,
        "upstream": upstream,
        "same_campus_blob": scheduled.object_id(publication, scheduled.CAMPUS)
        == scheduled.object_id(release, scheduled.CAMPUS),
        "records": {},
        "cross_department": {},
        "new_roster_ids": sorted(extras),
        "pages": [],
    }
    for oid in unique:
        raw = campus.get(oid)
        if not raw:
            assert oid in cross and oid not in present, (oid, "observed identity has no verified published record")
            result["records"][oid] = {"stored_under_NANO": False, "public_batch_returned": False}
            continue
        row = present[oid]
        assert all(row.get(k) == raw.get(k) for k in ("pi_name", "department", "source", "url", "source_url")), oid
        meta, projected = raw.get("metadata") or {}, row.get("metadata") or {}
        assert all(projected.get(k) == meta.get(k) for k in ("faculty_title", "deactivation_reason")), oid
        # The public model represents inactivity through target_truth and omits the raw activity flag.
        assert (row["target_truth"]["reason_code"] == "inactive") == (meta.get("is_active") is False), oid
        if oid in scheduled.ARCHIVES:
            assert row["target_truth"]["reason_code"] == "inactive" and meta.get("is_active") is False
        result["records"][oid] = {
            "individual": row["pi_name"],
            "unit": row["department"],
            "faculty_title": meta.get("faculty_title"),
            "reading_url": row["url"],
            "source_url": row["source_url"],
            "active": meta.get("is_active"),
            "posture": row["target_truth"]["reason_code"],
            "public_batch_returned": True,
        }
    for probe, frozen in cross.items():
        pid = frozen["preserved_id"]
        person = present[pid]
        assert person["pi_name"] == frozen["individual_name"] and person["department"] == frozen["primary_unit"], (
            probe,
            pid,
        )
        assert result["records"][pid]["active"] is True and person["target_truth"]["reason_code"] != "inactive"
        assert probe not in present, (
            probe,
            pid,
            "both department and primary records are now visible; review identity",
        )
        result["cross_department"][probe] = {
            "primary_id": pid,
            "name": person["pi_name"],
            "department": person["department"],
        }

    for oid in PAGES:
        time.sleep(7)
        detail = read(api + "/api/opportunities/" + oid + "?_release_scope=" + SCOPE).json()
        raw = campus[oid]
        assert detail["id"] == oid and detail["pi_name"] == raw["pi_name"]
        if oid in scheduled.ARCHIVES:
            assert (
                detail["target_truth"]["reason_code"] == "inactive" and detail["contact_email_status"] == "unavailable"
            )
        if oid == scheduled.JAHED:
            rank = detail["detail_fields"]["fields"]["professor_or_lab"]["quotes"]["faculty_rank"]
            assert rank["text"] == raw["metadata"]["faculty_title"] and rank["source_url"] == scheduled.JACOBS + "527"
        for attempt in range(3):
            html = BeautifulSoup(read(site + "/opportunities/" + oid).content, "html.parser")
            assert html.html["data-release-sha"] == release
            panel = visible_main(html)
            h1 = panel.select_one("h1")
            if h1 is None or h1.get_text(" ", strip=True) != "This opportunity is temporarily unavailable":
                break
            if attempt < 2:
                time.sleep(65)
        assert h1 and h1.get_text(" ", strip=True) == raw["pi_name"], oid
        controls = {e.get_text(" ", strip=True) for e in panel.select("a, button")}
        hrefs = {a["href"] for a in panel.select("a[href]")}
        if oid == scheduled.JAHED:
            assert [
                a.get("href") for a in panel.select("a[href]") if a.get_text(" ", strip=True) == "View faculty profile"
            ] == [scheduled.JACOBS + "527"]
        if oid in scheduled.ARCHIVES:
            assert not {"Draft email", "Write an email", "Apply now"} & controls
            assert not any(url.startswith("mailto:") for url in hrefs)
        assert {raw["url"], raw["source_url"]} & hrefs, (oid, "missing school reading route")
        result["pages"].append(
            {
                "id": oid,
                "heading": raw["pi_name"],
                "reading_url": next(url for url in (raw["url"], raw["source_url"]) if url in hrefs),
                "archived": oid in scheduled.ARCHIVES,
                "render_attempts": attempt + 1,
            }
        )
    assert read(api + "/api/health").json()["release_sha"] == release
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        f"{len(unique)} referenced IDs, {len(present)} public records, {len(cross)} campus primaries, {len(PAGES)} pages"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--site", default="https://joinalab.com")
    p.add_argument("--api", default="https://joinalab.com")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--scheduled", type=Path)
    source.add_argument("--local-candidate")
    p.add_argument("--date", type=date.fromisoformat, default=date(2026, 11, 27))
    p.add_argument("--out", type=Path, required=True)
    check(p.parse_args())
