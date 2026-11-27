"""Follow the 11 saved Virginia Tech biographies on the actual deployment of the AOE fix."""
import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SITE = "https://joinalab.com"
SOURCE = "f6d6cfb9c37748319e1d4d0500d7156af39fc87b"
DIRECTORY = "https://www.aoe.vt.edu/people/faculty.html"
REPO = "EricXu-0805/opportunity-filter-engine"


def compare(base, head):
    return subprocess.check_output(
        ["gh", "api", f"repos/{REPO}/compare/{base}...{head}", "--jq", ".status"], text=True,
    ).strip()


def get(session, url, **kwargs):
    response = session.get(url, timeout=(15, 40), **kwargs)
    if response.status_code in {429, 502, 503, 504}:
        suggested = response.headers.get("Retry-After", "60")
        time.sleep(min(120, max(60, int(suggested) if suggested.isdigit() else 60)))
        response = session.get(url, timeout=(15, 40), **kwargs)
    response.raise_for_status()
    return response


def version(session):
    about = get(session, SITE + "/about").text
    front = re.search(r'data-release-sha="([a-f0-9]{40})"', about)
    return [front[1] if front else None, get(session, SITE + "/api/health").json()["release_sha"]]


def check(session, original, scope):
    pid = original["id"]
    row = get(session, f"{SITE}/api/opportunities/{pid}", params={"_release_scope": scope}).json()
    fact = {"title": "Emeritus faculty", "source_url": DIRECTORY}
    assert row["id"] == pid and row["pi_name"] == original["name"]
    assert row["historical_faculty_appointment"] == fact, (pid, row.get("historical_faculty_appointment"))
    assert row["target_truth"]["reason_code"] == "inactive" and not row["target_truth"]["actionable"]
    assert row["url"] == original["url"]
    detail = BeautifulSoup(get(session, f"{SITE}/opportunities/{pid}").content, "html.parser")
    assert original["name"] == detail.select_one("h1").get_text(" ", strip=True)
    assert "Emeritus faculty" in detail.get_text(" ", strip=True)
    content = detail.select_one("main") or detail
    actions = [(a.get_text(" ", strip=True), a["href"]) for a in content.select("a[href]")]
    assert ("View faculty profile", original["url"]) in actions and any(href == DIRECTORY for label, href in actions)
    assert not any(href.lower().startswith("mailto:") and "@vt.edu" in href.lower() for _, href in actions)
    assert not any(b.get_text(" ", strip=True).casefold() in {"draft email", "email professor", "apply now"}
                   for b in content.select("button,a"))
    university = get(session, original["url"])
    campus = BeautifulSoup(university.content, "html.parser")
    headings = [" ".join(h.stripped_strings) for h in campus.select("main h1,.vt-bio-name")]
    assert any(" ".join(h.split()) in {" ".join(t.split()) for t in original["heading"]} for h in headings)
    return {"id": pid, "name": row["pi_name"], "appointment": fact, "actionable": False,
            "individual_link": row["url"], "source_link": DIRECTORY, "campus_status": university.status_code,
            "campus_final": university.url, "campus_heading": headings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"[0-9a-f]{40}", args.sha)
    assert compare(SOURCE, args.sha) in {"ahead", "identical"} and compare(args.sha, "main") in {"ahead", "identical"}
    people = json.loads(Path(__file__).with_name("11-school-person-pages.json").read_text())["campus_people"]
    session = requests.Session()
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "start": version(session), "details": []}
    assert result["start"] == [args.sha, args.sha], result["start"]
    for person in people:
        try:
            row = check(session, person, args.scope)
        except (requests.RequestException, ValueError, KeyError, AssertionError) as exc:
            row = {"id": person["id"], "error": str(exc)}
        result["details"].append(row)
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        time.sleep(8)
    result["end"] = version(session)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    assert result["start"] == result["end"] and len(result["details"]) == 11
    assert not any("error" in row for row in result["details"])


if __name__ == "__main__":
    main()
