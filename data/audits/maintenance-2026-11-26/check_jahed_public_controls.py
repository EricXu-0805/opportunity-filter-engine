"""Read actual UCSD details in Chromium and get the exact match and saved-detail card inputs."""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from playwright.sync_api import sync_playwright

JAHED = "faculty-ucsd-nano-8a42e65d"
KEN = "faculty-ucsd-nano-467aa36b"
PERSON = "https://jacobsschool.ucsd.edu/faculty/profile?id=527"
CONTROL = "http://jacobsschool.ucsd.edu/faculty/faculty_bios/index.sfe?fmp_recid=156"
ROSTER = "https://www.nanoengineering.ucsd.edu/index.php/fac"


def read_detail(page, site, oid, label, url, sha, scope):
    detail = requests.get(f"{site}/api/opportunities/{oid}", params={"_release_scope": scope}, timeout=90)
    detail.raise_for_status()
    row = detail.json()
    assert row["id"] == oid and row["pi_name"] == label
    assert row["target_truth"]["actionable"] and row["url"] == row["source_url"] == url
    response = page.goto(f"{site}/opportunities/{oid}", wait_until="domcontentloaded", timeout=90000)
    assert response and response.status == 200
    assert page.locator("html").get_attribute("data-release-sha") == sha
    main = page.get_by_role("main")
    main.get_by_role("heading", name=label, level=1, exact=True).wait_for(timeout=60000)
    link = main.get_by_role("link", name="View faculty profile", exact=True)
    link.wait_for(timeout=60000)
    assert link.get_attribute("href") == url
    receipt = {"id": oid, "pi_name": label, "api_http": detail.status_code, "page_http": response.status,
               "button_label": link.inner_text(), "rendered_href": url, "source_url": row["source_url"],
               "active": True, "frontend_sha": sha}
    if oid == JAHED:
        named_rank = row["detail_fields"]["fields"]["professor_or_lab"]["quotes"]["faculty_rank"]
        assert named_rank["text"] == "Associate Professor" and named_rank["source_url"] == PERSON
        receipt["rank_source"] = named_rank
    return row, receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    args = parser.parse_args()
    site = args.site.rstrip("/")
    assert urlsplit(site).hostname in {"127.0.0.1", "localhost"}, "Candidate services only"

    def current_sha():
        result = requests.get(site + "/api/health", timeout=60)
        result.raise_for_status()
        return result.json()["release_sha"]

    assert current_sha() == args.sha
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(locale="en-US")
        jahed, receipt = read_detail(page, site, JAHED, "Zeinab Jahed", PERSON, args.sha, args.scope)
        _, control = read_detail(page, site, KEN, "Ken Vecchio", CONTROL, args.sha, args.scope)
        browser.close()
    query = {"profile": {"name": "Test Student", "home_school": "ucsd", "school": "University of California San Diego",
                         "year": "sophomore", "major": "NanoEngineering", "gpa": 3.5,
                         "research_interests_text": "NanoEngineering materials", "seeking_type": ["research"],
                         "preferences": {"min_match_threshold": 0}},
             "view": {"tab": "all", "today": "2026-11-26", "search_query": "Zeinab Jahed", "source": "ucsd_faculty"},
             "page_size": 10}
    matched = requests.post(site + "/api/matches/view?llm=false", json=query, timeout=180)
    matched.raise_for_status()
    view = matched.json()
    (match,) = (result for result in view["results"] if result["opportunity_id"] == JAHED)
    compact = match["opportunity"]
    assert (compact.get("source_url") or compact["url"]) == PERSON
    args.inputs.mkdir(exist_ok=True)
    (args.inputs / "match.json").write_text(json.dumps(match))
    (args.inputs / "detail.json").write_text(json.dumps(jahed))
    assert current_sha() == args.sha
    report = {"checked_at": datetime.now(UTC).isoformat(timespec="seconds"), "same_frontend_backend_sha": args.sha,
              "target": receipt, "legacy_control": control, "matching_view_http": matched.status_code,
              "matching_query": query["view"], "matching_ids": [r["opportunity_id"] for r in view["results"]],
              "actual_card_url": compact["url"], "actual_card_source_url": compact.get("source_url"),
              "matched_count": view["filtered_total"], "scope": "Loopback public Chromium details and full-corpus matching. No account or saved-state write."}
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
