"""Verify 23 saved Pitt philosophy IDs on the same release of both public services."""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SITE = "https://joinalab.com"
SHARED_BROWSER = {"faculty-pitt-phil-2930bf5f", "faculty-pitt-phil-4e0c21eb"}


def now():
    return datetime.now(timezone.utc).isoformat()


def get(session, url, **kwargs):
    for attempt in range(2):
        try:
            response = session.get(url, timeout=(25, 50), **kwargs)
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.ConnectionError):
            if attempt:
                raise
            time.sleep(12)
        except requests.HTTPError as exc:
            if attempt or exc.response.status_code not in (429, 502, 503, 504):
                raise
            retry_after = exc.response.headers.get("Retry-After", "60")
            time.sleep(max(60, int(retry_after) if retry_after.isdigit() else 60))


def releases(session):
    html = get(session, SITE + "/about").text
    page_build = re.search(r'data-release-sha="([a-f0-9]{40})"', html)
    return [page_build[1] if page_build else None, get(session, SITE + "/api/health").json()["release_sha"]]


def check_one(session, record, candidate, scope):
    pid = record["original_id"]
    api = get(session, SITE + "/api/opportunities/" + pid, params={"_release_scope": scope}).json()
    rank = api["metadata"]["faculty_title"]
    assert (api["id"], api["pi_name"], rank) == (pid, record["name"], candidate["displayed_rank"]), (pid, rank)
    assert api["target_truth"]["actionable"] and api["url"] == record["official_profile"], (pid, api.get("url"))
    result = {"id": pid, "name": api["pi_name"], "published_url": api["url"], "faculty_title": rank}
    if pid in SHARED_BROWSER:
        result["shared_browser"] = "The B21 Chromium release probe covers this person's normal UI and two saved cross-unit records."
        return result

    detail = BeautifulSoup(get(session, SITE + "/opportunities/" + pid).content, "html.parser")
    names = [h.get_text(" ", strip=True) for h in detail.select("h1")]
    links = [a["href"] for a in detail.select("a[href]") if a.get_text(" ", strip=True) == "View faculty profile"]
    assert record["name"] in names and rank in detail.get_text(" ", strip=True), (pid, "rendered name or rank", names)
    assert links == [record["official_profile"]], (pid, "visible faculty profile action", links)
    official = get(session, links[0])
    headings = [h.get_text(" ", strip=True) for h in BeautifulSoup(official.content, "html.parser").select("h1")]
    assert set(record["school_heading"]).intersection(headings), (pid, "university name", headings)
    result.update({"detail_heading": names, "profile_action": links[0], "official_final_url": official.url,
                   "university_status": official.status_code, "university_name": headings})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    parent = Path(__file__).parent
    records = json.loads((parent / "official-and-before.json").read_text())["records"]
    rows = json.loads((parent / "candidate-details.json").read_text())["results"]
    candidates = {row["id"]: row for row in rows}
    assert len(records) == len({record["original_id"] for record in records}) == 23
    session = requests.Session()
    start = releases(session)
    assert start == [args.sha, args.sha], ("wait for the reviewed release", start)
    result = {"started_at": now(), "expected": args.sha, "start": start, "details": []}
    for record in records:
        try:
            row = check_one(session, record, candidates[record["original_id"]], args.scope)
        except (requests.RequestException, AssertionError, ValueError, KeyError) as exc:
            row = {"id": record["original_id"], "error": str(exc)}
        result["details"].append(row)
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        time.sleep(13)
    result.update({"end": releases(session), "completed_at": now()})
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    assert result["end"] == start and not any("error" in r for r in result["details"])


if __name__ == "__main__":
    main()
