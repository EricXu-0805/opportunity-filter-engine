"""Read-only Arizona Nursing release check. Run once per actual release, not as a scheduler."""

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=("snapshot", "natural"))
parser.add_argument("release_sha")
parser.add_argument("out", type=Path)
args = parser.parse_args()
if not re.fullmatch("[a-f0-9]{40}", args.release_sha):
    parser.error("expected full production commit")
receipt = json.loads((Path(__file__).resolve().parent.parent / "arizona-nursing-20261127.json").read_bytes())
before = {r["id"]: r for r in receipt["ids"]}
snapshot = "candidate_snapshot" if args.phase == "snapshot" else "candidate_full_replay"
rows = [
    {
        "id": r["id"],
        "status": r[snapshot]["http_api"],
        "actionable": r[snapshot]["actionable"],
        "url": r["university_url"],
        "last_seen": r[snapshot].get("last_seen_listed_at"),
    }
    for r in receipt["ids"]
]
session = requests.Session()
errors = []


def get(url):
    for attempt in range(1, 4):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code not in (429, 502, 503, 504):
                return resp
            errors.append({"url": url, "attempt": attempt, "status": resp.status_code})
            delay = resp.headers.get("Retry-After", "3")
            time.sleep(max(3, int(delay)) if delay.isdigit() else 5)
        except requests.RequestException as err:
            errors.append({"url": url, "attempt": attempt, "error": type(err).__name__})
            time.sleep(3)
    raise RuntimeError(f"source did not respond after 3 attempts: {url}")


def current():
    front = BeautifulSoup(get("https://joinalab.com/about").content, "html.parser").html.get("data-release-sha")
    back = get("https://joinalab.com/api/health").json()["release_sha"]
    return {"frontend": front, "backend": back}


def now():
    return datetime.now(UTC).isoformat()


result = {
    "phase": args.phase,
    "started": now(),
    "release": args.release_sha,
    "before": current(),
    "ids": [],
    "retry": errors,
}


def write():
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


def matching(pin):
    return set(pin.values()) == {args.release_sha}


if not matching(result["before"]):
    result["state"] = "pending_deployment"
    write()
    sys.exit(2)
for row in rows:
    id = row["id"]
    person = before[id]["name"]
    api = get("https://joinalab.com/api/opportunities/" + id)
    html = get("https://joinalab.com/opportunities/" + id)
    soup = BeautifulSoup(html.content, "html.parser")
    heading = soup.find("h1")
    dt = api.json()
    observation = {
        "id": id,
        "expected_person": person,
        "api": api.status_code,
        "html": html.status_code,
        "page_release": soup.html.get("data-release-sha"),
        "heading": heading.get_text(" ", strip=True) if heading else None,
        "public_name": dt.get("pi_name"),
        "last_seen_listed_at": dt.get("last_seen_listed_at"),
        "public_title": (dt.get("metadata") or {}).get("faculty_title"),
        "public_actionable": (dt.get("target_truth") or {}).get("actionable"),
        "school_url": dt.get("url"),
    }
    ok = api.status_code == row["status"] and observation["page_release"] == args.release_sha
    if row["status"] == 200:
        ok = (
            ok
            and html.status_code == 200
            and observation["public_name"] == person
            and person in (observation["heading"] or "")
            and observation["public_actionable"] is row["actionable"]
        )
        if row["last_seen"]:
            ok = ok and observation["last_seen_listed_at"] == row["last_seen"]
        observed = dt.get("url") or ""
        ok = ok and observed == row["url"]
        if observed and row["actionable"] and (urlsplit(observed).hostname or "").endswith("arizona.edu"):
            destination = get(observed)
            heading = BeautifulSoup(destination.content, "html.parser").select_one("h1")
            observation["university_page"] = {
                "status": destination.status_code,
                "final": destination.url,
                "h1": heading.get_text(" ", strip=True) if heading else None,
            }
            ok = (
                ok
                and destination.status_code == 200
                and observation["university_page"]["h1"] == before[id]["university_h1"]
            )
    else:
        ok = ok and not observation["public_name"]
    observation["matched"] = ok
    result["ids"].append(observation)
    time.sleep(0.45)
result.update(finished=now(), after=current())
result["matched"] = sum(r["matched"] for r in result["ids"])
result["state"] = "pass" if matching(result["after"]) and result["matched"] == len(rows) else "review"
write()
print(result["state"], result["matched"], "/", len(rows), args.out)
sys.exit(0 if result["state"] == "pass" else 1)
