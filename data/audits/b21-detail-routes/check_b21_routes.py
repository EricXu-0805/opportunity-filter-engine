"""Release-built Chromium and same-origin public API. No request interception or sending."""
import argparse
import json
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "b21-cases.json").read_text())
KATE = "faculty-pitt-phil-2930bf5f"
KATE_ARCHIVE = "faculty-pitt-ling-e0bda033"
ROBIN_LINK = "https://chass.ncsu.edu/people/jrclayt2/"
WRITING = re.compile(r"(?:cold-email|/api/tailor|/api/renovate|/api/applications|/api/email)")
PROFILE = {"name": "Release QA Student", "institution": "UIUC", "college": "Liberal Arts and Sciences",
           "major": "Philosophy", "grade": "Sophomore", "is_international": False,
           "research_interests": "Philosophy", "skills": [], "coursework": []}


def verify(condition, message):
    if not condition:
        raise AssertionError(message)


def get(url, **kwargs):
    for attempt in range(4):
        response = requests.get(url, timeout=50, **kwargs)
        if response.status_code != 429 or attempt == 3:
            response.raise_for_status()
            return response
        retry = response.headers.get("Retry-After", "60")
        time.sleep((int(retry) if retry.isdigit() else 60) + 1)


def anchors(main, href):
    return main.locator("a[href]").evaluate_all("(links, h) => links.filter(l => l.getAttribute('href') === h).map(l => l.innerText.trim())", href)


def page_ready(page, sha):
    page.get_by_role("link", name="Back to matches", exact=True).wait_for(timeout=60000)
    verify(page.locator("html").get_attribute("data-release-sha") == sha, "frontend release SHA")
    return page.get_by_role("main")


def check_case(c, args, page, out):
    oid, name = c["id"], c["name"]
    address = args.site + "/opportunities/" + oid
    api = get(args.site + "/api/opportunities/" + oid, params={"_release_scope": args.scope})
    a = api.json()
    out.update(api_status=api.status_code, api_id=a.get("id"), pi_name=a.get("pi_name"),
               role=(a.get("metadata") or {}).get("faculty_title"), actionable=a["target_truth"]["actionable"],
               contact_status=a.get("contact_email_status"), api_url=a.get("url"), api_source=a.get("source_url"))
    verify(a["id"] == oid and a["pi_name"] == name, "public API original identity")
    verify(a["target_truth"]["actionable"] is c["active"], "public API actionability")
    verify(not a.get("contact_email"), "anonymous official contact protection")
    if c.get("kind") == "archived_directory":
        verify(not a.get("url") and not a.get("source_url") and a.get("archived_faculty_directory_url") == c["url"], "Jacob archival reading link")
        verify(ROBIN_LINK not in json.dumps(a), "Robin's link leaked into Jacob's public detail")
    else:
        verify(c["url"] == a.get("source_url") == a.get("url"), "published source and personal address")

    response = page.goto(address, wait_until="domcontentloaded", timeout=90000)
    verify(response and response.status == 200 and page.url == address, "HTML HTTP or original path")
    main = page_ready(page, args.sha)
    heading = main.get_by_role("heading", level=1).inner_text()
    verify(heading == name, "screen heading: " + heading)
    text = main.inner_text()
    archived = "This record is no longer active." in text
    verify(archived == (not c["active"]), "archive banner visibility")
    label = "View source" if c.get("kind") == "archived_directory" else "View faculty profile"
    proof = anchors(main,c["url"])
    verify(label in proof, f"{label} expected for {c['url']}, found {proof}")
    out.update(heading=heading, html_status=response.status, page_url=page.url, reading_label=label,
               reading_href=c["url"], archive_banner=archived)
    if c.get("role"):
        verify(c["role"] == out["role"] and c["role"] in text, "visible faculty role: " + str(out.get("role")))
    if c.get("kind") == "archived_directory":
        verify(not main.get_by_role("link", name="View faculty profile", exact=True).count(), "Jacob's personal profile button")
        verify(not anchors(main,ROBIN_LINK), "Robin URL on Jacob's screen")
    draft = main.get_by_role("button", name="Draft email", exact=True)
    if c["active"] and (oid in {KATE,"faculty-ncsu-chass-8026d528","faculty-fsu-comm-e3519c6b"}):
        draft.wait_for(state="visible", timeout=25000)
    if archived:
        verify(not draft.is_visible(), "archived draft control")
        verify(not main.get_by_role("link", name="Apply now", exact=True).is_visible(), "archived application control")
        verify(not main.locator('a[href^="mailto:"]').count(), "archived mailto link")
    out["draft_button_visible_with_device_profile"] = draft.is_visible()
    if c.get("kind") == "kate":
        verify(c["department"] == a["department"] and c["department"] in text, "department")
        verify(out["contact_status"] == "unavailable", "do not borrow a department email")
        if oid == KATE_ARCHIVE:
            link = main.get_by_role("link", name="View current faculty record", exact=True)
            verify(a.get("current_faculty_id") == KATE and a.get("verified_secondary_appointment") == c["role"], "archive pointer or retained secondary appointment")
            verify(link.get_attribute("href") == "/opportunities/" + KATE, "current faculty record link")
            link.click()
            page.wait_for_url(args.site + "/opportunities/" + KATE, timeout=45000)
            next_main = page_ready(page,args.sha)
            next_main.get_by_role("button", name="Draft email", exact=True).wait_for(timeout=25000)
            verify(next_main.get_by_role("heading", level=1).inner_text() == name and "Department of Philosophy" in next_main.inner_text(), "current faculty record handoff")
            out["archive_to_current_clicked"] = page.url
        else:
            verify(not a.get("current_faculty_id"), "primary record should not point to another")
            verify(main.get_by_test_id("contact-unavailable").is_visible(), "unavailable official email notice")
    if oid == "faculty-fsu-comm-e3519c6b":
        verify("Associate Professor" in text and not re.search(r"\bAssociate Profess\b",text), "clipped FSU rank")
        verify(out["contact_status"] == "sign_in_required", "FSU anonymous email policy")


def main():
    p = argparse.ArgumentParser()
    for key in ("site","sha","tree","scope","out"):
        p.add_argument("--"+key, required=True)
    args = p.parse_args()
    verify(urlsplit(args.site).hostname in ("127.0.0.1","localhost"), "isolated candidate required")
    verify(subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip() == args.sha, "checkout SHA")
    verify(subprocess.check_output(["git","rev-parse","HEAD^{tree}"],text=True).strip() == args.tree, "candidate tree")
    first_health = get(args.site+"/api/health").json()
    verify(first_health["release_sha"] == args.sha, "backend SHA")
    pitt = {r["id"]:r for r in json.loads(Path("data/processed/shards/pitt.json").read_text())}
    hist = {}
    for c in CASES:
        if c.get("kind") == "kate":
            md=pitt[c["id"]]["metadata"]
            verify(md["first_seen_at"] == c["first_seen_at"] and md["is_active"] is c["active"], "Kate original ID history")
            hist[c["id"]] = {"first_seen_at":md["first_seen_at"],"active":md["is_active"]}
    verify(pitt[KATE_ARCHIVE]["metadata"]["duplicate_of"] == KATE, "stored archive pointer")
    out = {"candidate":args.sha, "tree":args.tree, "started_at":datetime.now(UTC).isoformat(),
           "endpoint":args.site, "backend_first":first_health, "kate_history":hist, "rows":[],
           "profile":"Synthetic saved device-only profile in a fresh Chromium context. No account or authentication token.",
           "writing_requests":[]}
    def save():
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n")
    save()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        out["chromium_version"]=browser.version
        # A pre-existing local student profile exercises the actual CTA condition on both Kate IDs.
        # No mocked route, replayed API, auth/session token, auth-state injection or app-code override.
        state={"cookies":[],"origins":[{"origin":args.site,"localStorage":[{"name":"ofe_profile","value":json.dumps(PROFILE)}]}]}
        context=browser.new_context(locale="en-US",viewport={"width":1400,"height":960},storage_state=state)
        context.on("request",lambda r: out["writing_requests"].append([r.method,urlsplit(r.url).path]) if WRITING.search(urlsplit(r.url).path) and r.method not in {"GET","HEAD","OPTIONS"} else None)
        for c in CASES:
            row = {"id":c["id"],"pr":c["pr"],"ok":False}
            page=context.new_page()
            try:
                check_case(c,args,page,row)
                row["ok"]=True
            except Exception as exc:
                row["error"]=str(exc)[:950]
                row["page"]=page.url
                try: row["visible_actions"]=page.get_by_role("main").get_by_role("button").all_text_contents()[:22]
                except Exception: pass
            finally:
                page.close()
            out["rows"].append(row)
            save()
            print(c["id"],"PASS" if row["ok"] else row,flush=True)
            time.sleep(8)
        browser.close()
    out["backend_final"]=get(args.site+"/api/health").json()
    out["finished_at"]=datetime.now(UTC).isoformat()
    out["passed"]=sum(r["ok"] for r in out["rows"])
    save()
    verify(out["backend_final"]["release_sha"] == args.sha, "release changed")
    verify(not out["writing_requests"],"unexpected writing request")
    verify(out["passed"] == len(CASES),f"{out['passed']}/{len(CASES)} passed")

if __name__ == "__main__":
    main()
