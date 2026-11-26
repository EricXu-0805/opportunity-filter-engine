"""Verify the Pitt CS saved-detail release from the public frontend and its own API.

Run once after release with the actual deployed SHA and the current public API
scope. Pass an output file outside the source tree for the read-only receipt.
"""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


def get(session, url, **kwargs):
    response = session.get(url, timeout=(12, 35), **kwargs)
    if response.status_code == 429:
        retry = response.headers.get("Retry-After", "60")
        time.sleep(max(60, int(retry) if retry.isdigit() else 60))
        response = session.get(url, timeout=(12, 35), **kwargs)
    response.raise_for_status()
    return response


def version(session, site):
    about = get(session, site + "/about")
    page_sha = re.search(r'data-release-sha="([a-f0-9]{40})"', about.text)
    return [page_sha[1] if page_sha else None, get(session, site + "/api/health").json()["release_sha"]]


def check(session, site, scope, pair, pid, after_refresh):
    current = pair["current_id"]
    api = get(session, site + "/api/opportunities/" + pid, params={"_release_scope": scope}).json()
    detail_url = site + "/opportunities/" + pid
    detail = BeautifulSoup(get(session, detail_url).content, "html.parser")
    links = [
        {"label": a.get_text(" ", strip=True), "destination": urljoin(detail_url, a["href"])}
        for a in detail.select("a[href]")
        if a.get_text(" ", strip=True) in ("View faculty profile", "View current faculty record")
    ]
    active = pid == current
    assert api["id"] == pid and bool(api["target_truth"]["actionable"]) == active, (pid, "actionability")
    campus = None
    if active:
        destinations = {pair["school_url"]: pair["school_name"]}
        if after_refresh:
            # The full department roster can recover and once again return its
            # own, independently identified person page instead of the college's.
            destinations[pair["department_url"]] = pair["department_name"]
        url = api.get("url")
        assert url in destinations, (pid, "unexpected source URL", url)
        assert any(link["destination"] == url for link in links), (pid, "profile link", links)
        official = get(session, url)
        person = BeautifulSoup(official.content, "html.parser")
        headings = [heading.get_text(" ", strip=True) for heading in person.select("h1")]
        assert destinations[url] in headings, (pid, "wrong campus identity", headings)
        campus = {"url": url, "final_url": official.url, "http": official.status_code, "name": destinations[url]}
        if pid == "faculty-pitt-cs-e47a8796":
            assert api.get("contact_email_status") == "unavailable", (pid, "office address shown")
    else:
        assert api.get("current_faculty_id") == current, (pid, "saved record successor")
        assert any(link["destination"] == site + "/opportunities/" + current for link in links), (pid, "successor link", links)
    return {"id": pid, "current_id": current, "actionable": active, "links": links, "campus_person": campus}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--refresh-run", help="Natural refresh run URL after it publishes the school data")
    args = parser.parse_args()
    if args.refresh_run:
        assert re.fullmatch(r"https://github\.com/EricXu-0805/opportunity-filter-engine/actions/runs/\d+", args.refresh_run)
    site = "https://joinalab.com"
    folder = Path(__file__).parent
    pairs = json.loads((folder / "directory-comparison-and-person-destinations.json").read_text())["identities"]
    replay = json.loads((folder / "source-retries-and-restoration.json").read_text())
    primary = {group["name"]: group["current_id"] for group in replay["runs"]["repaired"][-1]["contacts"]}
    session = requests.Session()
    initial = version(session, site)
    assert initial == [args.sha, args.sha], (initial, "wait for the same release at both services")
    result = {"expected": args.sha, "natural_refresh": args.refresh_run, "start": initial, "started_at": datetime.now(timezone.utc).isoformat(), "details": []}
    for pair in pairs:
        pair["current_id"] = primary[pair["school_name"]]
        for pid in pair["published_ids"]:
            try:
                record = check(session, site, args.scope, pair, pid, bool(args.refresh_run))
            except (AssertionError, ValueError, requests.RequestException) as exc:
                record = {"id": pid, "error": str(exc)}
            result["details"].append(record)
            args.out.write_text(json.dumps(result, indent=2) + "\n")
            # SSR also reads the detail and its similar list in the same public rate bucket.
            time.sleep(11)
    result["end"] = version(session, site)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    assert result["end"] == initial and len(result["details"]) == 59, result["end"]
    assert not any("error" in row for row in result["details"]), args.out


if __name__ == "__main__":
    main()
