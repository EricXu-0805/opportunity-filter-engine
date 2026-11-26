"""Read the original detail routes in Chromium and through the same site's public API."""
import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from playwright.sync_api import sync_playwright

ARCHIVES = {
    "faculty-ucsd-nano-25a6d469": ("Sadik Esener", "https://jacobsschool.ucsd.edu/faculty/profile?id=31"),
    "faculty-ucsd-nano-dc9e3de3": ("Michael Heller", "https://jacobsschool.ucsd.edu/faculty/profile?id=1"),
    "faculty-ucsd-nano-2aa92754": ("Darren Lipomi", "https://jacobsschool.ucsd.edu/faculty/profile?id=345"),
    "faculty-ucsd-nano-04ac1d79": ("Ying Shirley Meng", "https://jacobsschool.ucsd.edu/faculty/profile?id=284"),
    "faculty-ucsd-nano-27240933": ("Sheng Xu", "https://jacobsschool.ucsd.edu/faculty/profile?id=387"),
    "faculty-ncsu-chass-089a76c8": ("Jeffery Braden", None),
    "faculty-umd-phys-5e8e0edd": ("Elizabeth Beise", None),
}
CONTROL = ["faculty-ucsd-nano-e94320ae", "faculty-ucsd-che-8330aad7", "faculty-ucsd-nano-d24bdcfa"]
WISCONSIN = ["wisc-86cba49b83d7", "sro-595e912d", "sro-3c378261"]
SMU = ["nsf-reu-2447670", "sro-44f176cd"]
CRISP = "sro-3ec4ea4e"
CUI = "faculty-utexas-mpdd-5850399f"
OUTREACH = "Contact this faculty member to ask whether undergraduate research opportunities are currently available."
TITLES = [
    "Drum Filling of Thin-Film Freeze-Dried Monoclonal Antibody Powder in UniDose Powder Nasal Spray System",
    "IgM has a better relative distribution in inflammation sites and tumor tissues than IgG",
]


def check(page, site, oid, sha, scope):
    url = site + "/opportunities/" + oid
    for attempt in range(3):
        public = requests.get(site + "/api/opportunities/" + oid, params={"_release_scope": scope}, timeout=30)
        if public.status_code != 429 or attempt == 2:
            break
        wait = public.headers.get("Retry-After", "60")
        time.sleep(max(1, int(wait) if wait.isdigit() else 60) + 1)
    public.raise_for_status()
    api = public.json()
    assert api["id"] == oid
    response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    assert response is not None and response.status == 200
    page.get_by_role("heading", level=1).last.wait_for(state="visible", timeout=45000)
    # Hydration may first leave a "Loading opportunity..." shell with a title.
    page.get_by_role("link", name="Back to matches", exact=True).wait_for(state="visible", timeout=45000)
    main = page.get_by_role("main")
    text = main.inner_text()
    assert page.locator("html").get_attribute("data-release-sha") == sha
    result = {"id": oid, "url": url, "api_status": public.status_code, "browser_status": response.status,
              "heading": main.get_by_role("heading", level=1).inner_text(),
              "actionable": api["target_truth"]["actionable"]}
    if oid in ARCHIVES:
        official_name, individual = ARCHIVES[oid]
        assert result["heading"] == api["pi_name"] == official_name
        assert result["actionable"] is False and api["target_truth"]["reason_code"] == "inactive"
        assert "This record is no longer active." in text
        for label in ("Apply now", "Draft email"):
            assert not main.get_by_role("button", name=label, exact=True).is_visible()
            assert not main.get_by_role("link", name=label, exact=True).is_visible()
        if individual:
            assert main.get_by_role("link", name="View faculty profile", exact=True).get_attribute("href") == individual
        assert not api["description_clean"].endswith(OUTREACH)
        result.update(inactive_banner=True, source=individual or api["source_url"], generated_outreach=False,
                      external_apply_or_draft_control=False)
    elif oid in CONTROL:
        assert result["actionable"] and "This record is no longer active." not in text
        assert main.get_by_role("link", name="View faculty profile", exact=True).is_visible()
        result["view_faculty_profile"] = True
    elif oid == CUI:
        assert result["actionable"] and api["pi_name"] == "Zhengrong Cui"
        papers = main.get_by_role("heading", name="Recent publications", exact=True)
        assert papers.is_visible()
        result["paper_links"] = []
        for title in TITLES:
            link = main.get_by_role("link", name=title, exact=True)
            assert link.is_visible(), title
            result["paper_links"].append({"title": title, "visible_href": link.get_attribute("href")})
    elif oid in WISCONSIN:
        assert result["actionable"] and api["paid"] == "yes"
        assert "7,000" in text and "UW–Madison students may apply" in text
        assert not re.search(r"(?:current )?UW[–-]Madison students (?:are excluded|are not eligible)", text, re.I)
        result["published_stipend_visible"] = True
        result["home_student_may_apply_visible"] = True
        result["published_eligibility_source"] = api["detail_fields"]["fields"]["funding"]["quotes"]["compensation"]["source_url"]
    else:
        assert result["actionable"]
        wanted = ["Biomedical science", "Behavioral science"] if oid == CRISP else ["Mathematics", "Statistics", "Computer Science", "Social science"]
        reported = api["detail_fields"]["fields"]["eligibility"]
        assert set(reported["explicit"]["majors"]) == set(wanted)
        for major in wanted:
            assert major.lower() in text.lower(), major
        result["host_majors_visible"] = wanted
        result["published_eligibility_source"] = reported["quotes"]["majors"]["source_url"]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    site = args.site.rstrip("/")
    assert urlsplit(site).hostname in {"127.0.0.1", "localhost", "joinalab.com"}
    health = requests.get(site + "/api/health", timeout=40)
    health.raise_for_status()
    assert health.json()["release_sha"] == args.sha
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="en-US", viewport={"width": 1400, "height": 960})
        for oid in [*ARCHIVES, *CONTROL, CUI, *WISCONSIN, *SMU, CRISP]:
            if rows:
                time.sleep(18)
            page = context.new_page()
            try:
                rows.append({"ok": True, **check(page, site, oid, args.sha, args.scope)})
            except Exception as exc:
                rows.append({"ok": False, "id": oid, "failure": f"{type(exc).__name__}: {str(exc)[:240]}",
                             "visible_headings": page.get_by_role("main").get_by_role("heading").all_text_contents()[:24]})
            print(oid, "PASS" if rows[-1]["ok"] else rows[-1], flush=True)
            page.close()
        browser.close()
    report = {"time_utc": datetime.now(UTC).isoformat(timespec="seconds"), "site": site,
              "scope": "Read-only Chrome navigation and public GETs; no application, account, subscription or email actions.",
              "verified_frontend_and_backend_sha": args.sha, "rows": rows}
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    for row in rows:
        print(row["id"], "PASS" if row["ok"] else row, flush=True)
    assert all(r["ok"] for r in rows), "See the per-original-ID receipt"


if __name__ == "__main__":
    main()
