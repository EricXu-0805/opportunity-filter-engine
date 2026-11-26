"""Read the eight original Miami HTML and anonymous API responses once both releases contain #1498.

Run once at the production window. A release mismatch stops before the first detail request.
The published GitHub receipt and the output omit contact values.
"""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

from bs4 import BeautifulSoup

here = Path(__file__).resolve().parent
reader = here.parent / "osu-bme-appointment-20261126" / "check-after-release.py"
spec = importlib.util.spec_from_file_location("normal_school_reader", reader)
public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public)
reference = json.loads((here / "twelve-normal-replays.json").read_text())
source = reference["source_sha"]
subject = reference["initial"]["id"]
rows = [reference["initial"], *reference["initial_controls"]]
assert len({r["id"] for r in rows}) == 8
rec = public.rec
rec.update(correction_sha=source, observed_at=datetime.now(timezone.utc).isoformat())
source_labels = {"View faculty profile", "View source"}


def check_one(expected, release):
    key = expected["id"]
    route = "/opportunities/" + key
    response = public.read(route, detail=True)
    api = public.read("/api" + route, params={"_release_scope": public.SCOPE}, detail=True)
    body = api.json()
    page = BeautifulSoup(response.content, "html.parser")
    heading = page.h1.get_text(" ", strip=True) if page.h1 else ""
    links = [(a.get_text(" ", strip=True), a["href"]) for a in page.select("main a[href]")]
    actions = [(label, url) for label, url in links if label in source_labels]
    status = [e.get_text(" ", strip=True) for e in page.select("[role=status]")]
    protected = not re.search(r"[\w.+-]+@[\w.-]+\.\w+", unquote(api.text)) and not any(
        "@" in unquote(url) for _, url in actions)
    checks = {
        "release": public.html_release(page) == release,
        "original": body.get("id") == key and body.get("pi_name") == expected["person"],
        "heading": heading == body.get("title") and bool(heading),
        "actionable": body["target_truth"]["actionable"] == expected["actionable"],
        "historical_banner": any("no longer active" in s.lower() for s in status) == (not expected["actionable"]),
        "public_contact_protection": protected,
    }
    if key == subject:
        checks.update(
            faculty_profile=body.get("url") is None,
            citation=body.get("source_url") == expected["source_url"],
            named_source_action=actions == [("View source", expected["source_url"])],
            name_is_visible=heading == "Don DeAngelis",
            contact_status=body.get("contact_email_status") == expected["contact_email_status"],
            faculty_title=body.get("metadata", {}).get("faculty_title") == expected["appointment"],
            original_papers=all(title in {work.get("title") for work in body["metadata"].get("recent_works", [])}
                                for title in expected["papers"]),
        )
    return {"id": key, "formal": public.FORMAL + route, "http": [response.status_code, api.status_code],
            "heading": heading, "last_seen_listed_at": body.get("last_seen_listed_at"),
            "source_actions": actions if protected else [], "checks": checks}


def check():
    pair = public.versions()
    main = public.github("branches/main", ".commit.sha")
    rec.update(deployment_before=pair, main=main)
    current = pair["frontend"]
    if (current != pair["backend"] or not public.ancestor(source, main)
            or not public.ancestor(source, current) or not public.ancestor(current, main)):
        rec["blocker"] = "Waiting for merged source and matching public releases containing that source."
        return
    for row in rows:
        rec["originals"].append(check_one(row, current))
    rec["deployment_after"] = public.versions()
    if rec["deployment_after"] == pair:
        rec["outcome"] = "passed" if all(all(r["checks"].values()) for r in rec["originals"]) else "failed"
    else:
        rec["blocker"] = "The public release changed during the detail review."


try:
    check()
except (KeyError, ValueError, OSError, public.requests.RequestException, public.subprocess.SubprocessError) as exc:
    rec["blocker"] = type(exc).__name__
print(json.dumps(rec, indent=2))
sys.exit({"passed": 0, "failed": 1, "blocked": 2}[rec["outcome"]])
