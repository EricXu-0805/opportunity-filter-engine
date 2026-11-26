"""Read the 28 Pitt Linguistics saved IDs and the two corrected appointments after B22."""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SITE = "https://joinalab.com"
CORRECTED = {"faculty-pitt-ling-84276229", "faculty-pitt-ling-0dbe04f3"}


def read(session, method, url, **kwargs):
    for attempt in range(2):
        try:
            response = session.request(method, url, timeout=(25, 55), **kwargs)
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.ConnectionError):
            if attempt:
                raise
            time.sleep(10)
        except requests.HTTPError as exc:
            if attempt or exc.response.status_code not in (429, 502, 503, 504):
                raise
            retry_after = exc.response.headers.get("Retry-After", "60")
            time.sleep(max(60, int(retry_after) if retry_after.isdigit() else 60))


def release(session):
    about = read(session, "GET", SITE + "/about").text
    version = re.search(r'data-release-sha="([a-f0-9]{40})"', about)
    return [version[1] if version else None, read(session, "GET", SITE + "/api/health").json()["release_sha"]]


def appointment(session, site, scope, expected):
    pid = expected["id"]
    data = read(session, "GET", site + "/api/opportunities/" + pid, params={"_release_scope": scope}).json()
    dom = BeautifulSoup(read(session, "GET", site + "/opportunities/" + pid).content, "html.parser")
    rank = data["metadata"]["faculty_title"]
    actionable = data["target_truth"]["actionable"]
    heading = [h.get_text(" ", strip=True) for h in dom.select("h1")]
    assert data["id"] == pid and heading == expected["heading"] and data["pi_name"] in heading, (pid, heading)
    assert rank == expected["api_rank"] and actionable == expected["actionable"], (pid, rank, actionable)
    assert data["contact_email_status"] == expected["contact_status"], pid
    links = [a["href"] for a in dom.select("a[href]") if a.get_text(" ", strip=True) == "View faculty profile"]
    source = expected["profile_and_current_links"][0]["destination"]
    assert links == [source] and data["url"] == source, (pid, links, data["url"])
    official = read(session, "GET", links[0])
    official_headings = [" ".join(h.stripped_strings) for h in BeautifulSoup(official.content, "html.parser").select("h1")]
    assert any(heading[0].casefold() in " ".join(x.split()).casefold() for x in official_headings), (pid, official_headings)
    rendered = rank in dom.get_text(" ", strip=True)
    if actionable:
        assert rendered, (pid, "current rank missing from the page")
    return {"id": pid, "heading": heading, "rank": rank, "rank_visible_on_page": rendered,
            "actionable": actionable, "contact_status": data["contact_email_status"], "profile_action": source,
            "school_status": official.status_code, "school_url": official.url, "school_heading": official_headings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    directory = Path(__file__).parent
    saved = json.loads((directory / "ling-monthly-baseline.json").read_text())["rows"]
    expected = json.loads((directory / "eight-candidate-details.json").read_text())["results"]
    ids = [r["id"] for r in saved]
    assert len(ids) == len(set(ids)) == 28
    session = requests.Session()
    start = release(session)
    assert start == [args.sha, args.sha], ("wait for the exact production release", start)
    batch = read(session, "POST", SITE + "/api/opportunities/batch", json={"ids": ids}).json()
    rows = {r["id"]: r for r in batch["opportunities"]}
    assert set(rows) == set(ids) and batch["found"] == 28, ("missing or unexpected original IDs", set(ids) ^ set(rows))
    receipt = {"start": start, "at": datetime.now(timezone.utc).isoformat(), "saved_ids": [], "appointments": [],
               "scope": "Published originals and two corrected public profiles. Scheduled list counts and per-ID observation timestamps require the subsequent natural collection and publication."}
    for r in saved:
        actual = rows[r["id"]]
        assert r["name"] == actual["pi_name"], (r["id"], r["name"], actual["pi_name"])
        receipt["saved_ids"].append({"id": r["id"], "published_name": actual["pi_name"]})
    for r in expected:
        if r["id"] in CORRECTED:
            try:
                result = appointment(session, SITE, args.scope, r)
            except (requests.RequestException, AssertionError, ValueError, KeyError) as exc:
                result = {"id": r["id"], "error": str(exc)}
            receipt["appointments"].append(result)
            time.sleep(8)
    receipt["end"] = release(session)
    args.out.write_text(json.dumps(receipt, indent=2) + "\n")
    assert receipt["end"] == start and len(receipt["appointments"]) == 2
    assert all("error" not in r for r in receipt["appointments"]), args.out


if __name__ == "__main__":
    main()
