"""Read the three saved Ohio State pages once the correction reaches both services.

Run from an authenticated GitHub CLI environment with requests and beautifulsoup4.
Print the JSON evidence to stdout. An unmet version gate exits 2 before reading any detail.
"""
from pathlib import Path
from datetime import datetime, timezone
import json
import subprocess
import sys
import time

from bs4 import BeautifulSoup
import requests

INPUT = Path(__file__).with_name("five-roster-replays.json")
SOURCE = "80529cb9bb6201727ca3b1fb2e526a28d685a82f"
SAVED = "faculty-osu-bme-5874478d"
FORMAL = "https://joinalab.com"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
REPO = "EricXu-0805/opportunity-filter-engine"
rec = {"at": datetime.now(timezone.utc).isoformat(), "correction_sha": SOURCE,
       "outcome": "blocked", "detail_requests": 0, "requests": [], "originals": []}
session = requests.Session()
session.headers.update({"Accept-Language": "en-US,en;q=0.9"})
last_request = 0.0


def github(path, jq):
    return subprocess.check_output(["gh", "api", f"repos/{REPO}/{path}", "--jq", jq],
                                   text=True, timeout=45).strip()


def ancestor(older, newer):
    return github(f"compare/{older}...{newer}?per_page=1", ".status") in ("ahead", "identical")


def read(path, params=None, *, detail=False):
    global last_request
    time.sleep(max(0, 2 - (time.monotonic() - last_request)))
    last_request = time.monotonic()
    attempt = {"url": FORMAL + path, "at": datetime.now(timezone.utc).isoformat()}
    rec["requests"].append(attempt)
    if detail:
        rec["detail_requests"] += 1
    response = session.get(FORMAL + path, params=params, timeout=(8, 25), allow_redirects=False)
    attempt.update(url=response.url, http=response.status_code)
    if response.headers.get("Retry-After"):
        attempt["retry_after"] = response.headers["Retry-After"]
    response.raise_for_status()
    return response


def html_release(soup):
    marker = soup.select_one("[data-release-sha]")
    return marker["data-release-sha"] if marker else None


def versions():
    site = html_release(BeautifulSoup(read("/about").content, "html.parser"))
    api = read("/api/health").json().get("release_sha")
    if not site or not api:
        raise ValueError("Public version marker unavailable")
    return {"frontend": site, "backend": api}


def inspect(row, release):
    key = row["id"]
    path = "/opportunities/" + key
    page_response = read(path, detail=True)
    response = read("/api" + path, params={"_release_scope": SCOPE}, detail=True)
    page = BeautifulSoup(page_response.content, "html.parser")
    body = response.json()
    metadata = body.get("metadata") or {}
    truth = body.get("target_truth") or {}
    rank = body["detail_fields"]["fields"]["professor_or_lab"]["quotes"].get("faculty_rank")
    links = [(a.get_text(" ", strip=True), a["href"]) for a in page.select("a[href]")]
    source_links = [pair for pair in links if pair[1] == row["url"]]
    labels = {node.get_text(" ", strip=True) for node in page.select("button,a")}
    banners = [node.get_text(" ", strip=True) for node in page.select("[role=status]")]
    heading = page.h1.get_text(" ", strip=True) if page.h1 else None
    checks = {
        "original": body.get("id") == key,
        "version": html_release(page) == release,
        "page_heading": bool(heading) and heading == body["title"],
        "source": body["url"] == body["source_url"] == row["url"],
        "actionable": truth.get("actionable") == row["actionable"],
        "appointment": metadata.get("faculty_title") == row["title"],
        "visible_source": any(label in {"View faculty profile", "View source", "Source page"}
                              for label, _ in source_links),
    }
    if key == SAVED:
        checks.update(
            receipt=rank == row["rank_quote"],
            disclosure=body["contact_email_status"] == "unavailable" and "contact_email" not in body,
            archive=any("no longer active" in banner.lower() for banner in banners),
            no_outreach=labels.isdisjoint({"Draft email", "Draft an email", "Apply now", "Apply"}),
            last_listed=body.get("last_seen_listed_at") == row["last_seen_listed_at"],
            publications=len(metadata.get("recent_works") or []) == row["works"],
        )
    return {"id": key, "formal": FORMAL + path, "http": [page_response.status_code, response.status_code],
            "heading": heading, "provenance": rank, "banners": banners,
            "source_actions": source_links, "checks": checks}


def check():
    pair = versions()
    main = github("branches/main", ".commit.sha")
    rec.update(deployment_before=pair, main=main)
    if (pair["frontend"] != pair["backend"] or not ancestor(SOURCE, main)
            or not ancestor(SOURCE, pair["frontend"]) or not ancestor(pair["frontend"], main)):
        rec["blocker"] = "The merged source and the two public releases are not yet in the required ancestry."
        return
    expected = json.loads(INPUT.read_text())["candidate_initial"]
    for row in expected:
        rec["originals"].append(inspect(row, pair["frontend"]))
    rec["deployment_after"] = versions()
    if rec["deployment_after"] != pair:
        rec["blocker"] = "The release changed before the three originals completed."
        return
    rec["outcome"] = "passed" if all(all(row["checks"].values()) for row in rec["originals"]) else "failed"


if __name__ == "__main__":
    try:
        check()
    except (KeyError, ValueError, OSError, requests.RequestException, subprocess.SubprocessError) as error:
        rec["blocker"] = str(error)
    print(json.dumps(rec, indent=2))
    sys.exit(0 if rec["outcome"] == "passed" else 2)
