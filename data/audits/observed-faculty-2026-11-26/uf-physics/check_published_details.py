"""Read all 52 original public UF Physics details and the six original HTML samples on one release."""

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SITE = "https://joinalab.com"
DIRECT = "https://opportunity-filter-engine-api.onrender.com/api/health"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
FACULTY = "https://phys.ufl.edu/people/faculty/"
SOURCE = Path(__file__).with_name("normal-public-details.json")


def get(url, **kwargs):
    for attempt in range(4):
        response = requests.get(url, timeout=(12, 65), **kwargs)
        if response.status_code == 429 and attempt < 3:
            value = response.headers.get("Retry-After", "60")
            time.sleep((int(value) if value.isdigit() else 60) + 1)
            continue
        if response.status_code in (502, 503, 504) and attempt < 3:
            time.sleep(6 * (attempt + 1))
            continue
        response.raise_for_status()
        return response


def release():
    url = SITE + "/about"
    page = BeautifulSoup(get(url).content, "html.parser")
    return {
        url: page.html["data-release-sha"],
        SITE + "/api/health": get(SITE + "/api/health").json()["release_sha"],
        DIRECT: get(DIRECT).json()["release_sha"],
    }


def detail(expected, data):
    oid = expected["id"]
    url = expected["personal_url"]
    name = expected["name"]
    assert data["id"] == oid, "The public ID changed"
    assert data["pi_name"] == data["title"] == name, "The current public name or heading changed"
    assert data["source_url"] == data["url"] == url, (
        "The source and main reading link must both point to the named campus profile"
    )
    assert data["target_truth"]["actionable"] is True, "The original should be active"
    facts = data["detail_fields"]["fields"]["professor_or_lab"]
    quote = facts["quotes"]["faculty_rank"]
    assert facts["explicit"]["faculty_rank"] == expected["rank_quote"]["text"] == quote["text"], "Wrong academic rank"
    assert quote["source_url"] == FACULTY == expected["rank_quote"]["source_url"], "Wrong source for the academic rank"
    assert quote["observed_at"] == expected["rank_quote"]["observed_at"], "The reviewed date changed on this release"
    return {
        "id": oid,
        "name": name,
        "active": True,
        "published_profile": url,
        "rank_quote": {key: quote[key] for key in ("text", "source_url", "observed_at")},
    }


def html_detail(expected, content, sha):
    document = BeautifulSoup(content, "html.parser")
    assert document.html and document.html.get("data-release-sha") == sha, "Different frontend release"
    main = document.select_one("main")
    assert main, "The rendered detail did not load"
    # A streamed Next.js response can put only the loading shell in <main>.
    # Follow its actual Suspense segment/placeholder pairs. An unrelated hidden
    # block or a heading copied only into a JSON script cannot fulfill a check.
    if not main.select_one("h1"):
        moves = re.compile(r'\$(RS|RC)\("([BPS]:[0-9a-f]+)","([BPS]:[0-9a-f]+)"\)')
        for script in document.find_all("script"):
            for mode, first, second in moves.findall(script.string or ""):
                marker_id, segment_id = (second, first) if mode == "RS" else (first, second)
                marker = document.find("template", id=marker_id)
                segment = document.find("div", id=segment_id, hidden=True)
                if marker is not None and segment is not None:
                    marker.replace_with(*list(segment.contents))
    headings = [h.get_text(" ", strip=True) for h in main.select("h1")]
    assert expected["name"] in headings, "Missing original name in the rendered HTML"
    links = [a.get("href") for a in main.select("a[href]") if a.get_text(" ", strip=True) == "View faculty profile"]
    assert links == [expected["personal_url"]], "The visible reading action has a different campus destination"
    return {
        "heading": expected["name"],
        "action_label": "View faculty profile",
        "href": links[0],
        "exact_rank_in_rendered_text": expected["rank_quote"]["text"] in main.get_text(" ", strip=True),
    }


def expectations_from_publication(rows, receipt):
    assert receipt["result"] in {
        "verified_scheduled_publication",
        "physics_publication_verified_workflow_ended_with_an_issue",
    }, "The real Physics publication and campus source checks must finish first"
    assert receipt["unit_checks"] and all(receipt["unit_checks"].values())
    originals = {r["id"]: r for r in receipt["originals"]}
    assert len(receipt["originals"]) == len(originals) == 52
    assert set(originals) == {r["id"] for r in rows}
    current = []
    for original in rows:
        row = originals[original["id"]]
        assert row["checks"] and all(row["checks"].values())
        assert row["campus_name_url_rank_match"] and row["campus_profile"]["matches"]
        assert row["published_name"] == original["name"] and row["published_profile"] == original["personal_url"]
        assert row["observations"] == 1 and row["published_rank"]
        observed_date = datetime.fromisoformat(row["published_last_seen_at"].replace("Z", "+00:00")).date().isoformat()
        current.append({
            **original,
            "rank_quote": {"source_url": FACULTY, "text": row["published_rank"], "observed_at": observed_date},
        })
    return current


def main(sha, out, scheduled_file=None):
    source = json.loads(SOURCE.read_bytes())
    rows = source["rows"]
    assert source["head"] == "6d67369a1e40847db3f3c8beda3ef668e85eec40"
    assert len(rows) == len({row["id"] for row in rows}) == 52
    assert sum(bool(row.get("rendered_page")) for row in rows) == 6
    upstream = None
    if scheduled_file:
        receipt = json.loads(scheduled_file.read_bytes())
        rows = expectations_from_publication(rows, receipt)
        import check_scheduled_publication as scheduled

        merged = receipt["data_merge"]
        assert scheduled.api(f"compare/{merged}...{sha}", per_page=1)["status"] in {"identical", "ahead"}
        blob_id, _ = scheduled.blob(merged, scheduled.SHARD)
        assert blob_id == receipt["published_blobs"][scheduled.SHARD]
        upstream = {key: receipt[key] for key in ("run", "data_pr", "data_merge", "result", "workflow_conclusion")}
        upstream["uf_blob"] = blob_id
    before = release()
    assert set(before.values()) == {sha}, "The release has not reached all three production endpoints"
    report = {
        "source_commit": source["head"],
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": sha,
        "scheduled_publication": upstream,
        "production_before": before,
        "rows": [],
    }

    def save():
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    save()
    for expected in rows:
        case = {"id": expected["id"], "ok": False}
        try:
            oid = expected["id"]
            api = get(SITE + "/api/opportunities/" + oid, params={"_release_scope": SCOPE})
            case.update(detail(expected, api.json()))
            case["api_status"] = api.status_code
            if expected.get("rendered_page"):
                time.sleep(5)
                address = SITE + "/opportunities/" + oid
                for attempt in range(3):
                    page = get(address)
                    assert page.url == address, "The original path redirected"
                    try:
                        visible = html_detail(expected, page.content, sha)
                        break
                    except AssertionError:
                        if attempt == 2 or b"temporarily unavailable" not in page.content.lower():
                            raise
                        time.sleep(65)
                case["official_html"] = {"url": address, "status": page.status_code, **visible}
            case["ok"] = True
        except (AssertionError, KeyError, requests.RequestException) as exc:
            case["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
        report["rows"].append(case)
        save()
        print(case["id"], case["ok"], flush=True)
        time.sleep(6)
    report["production_after"] = release()
    report["finished"] = datetime.now(UTC).isoformat(timespec="seconds")
    report["passed_originals"] = sum(r["ok"] for r in report["rows"])
    report["passed_html"] = sum(bool(r.get("official_html")) for r in report["rows"])
    save()
    assert (
        set(report["production_after"].values()) == {sha}
        and report["passed_originals"] == 52
        and report["passed_html"] == 6
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--scheduled", type=Path, help="Verified natural publication receipt for these 52 original IDs")
    args = parser.parse_args()
    main(args.sha, args.out, args.scheduled)
