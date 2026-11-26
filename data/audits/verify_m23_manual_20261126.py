"""Check two public opportunity details against public admissions pages."""
import json
import re
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

site = "https://joinalab.com"
cases = [
    ("ucsd-d93b49abd299", "https://ugresearch.ucsd.edu/programs/urh-summer/index.html",
     ("Each program has a cohort and a coordinator", "McNair Program", "Look through the programs")),

    ("ucsd-c6d547c9321a", "https://ucsd-research.academicworks.com/opportunities/2368",
     ("11/20/2026", "undergraduate students in all majors", "October 29, 2026")),
    ("ucsb-45d0bef1a207", "https://calbridge.org/undergraduate-program/",
     ("must be attending a California State University", "in April", "Graduate students are not eligible")),
]
out = Path("evidence")
out.mkdir(exist_ok=True)
public = {}
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    context = browser.new_context(locale="en-US", service_workers="block")
    page = context.new_page()
    try:
        release = context.request.get(site + "/api/health").json()["release_sha"]
        frontend = re.search(r'data-release-sha="([a-f0-9]{40})"', context.request.get(site).text())[1]
        public.update(frontend=frontend, backend=release, programs=[])
        assert frontend == release
        for oid, host, expected in cases:
            response = page.goto(host, wait_until="domcontentloaded")
            received = " ".join((page.locator("body").text_content() or "").split()).lower()
            missing = [s for s in expected if s.lower() not in received]
            assert response.status == 200 and not missing, (oid, response.status, missing)
            response = context.request.get(site + "/api/opportunities/" + oid, params={
                "_release_scope": "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2",
            })
            assert response.ok
            row = response.json()
            assert row["id"] == oid
            page.goto(site + "/opportunities/" + oid, wait_until="domcontentloaded")
            expect(page.get_by_role("heading", level=1)).to_have_text(row["title"], timeout=60000)
            timing = page.get_by_test_id("fact-field-timing")
            expect(timing).to_be_visible()
            # Record only public program fields needed for the regression.
            public["programs"].append(dict(id=oid, host=host, source_http=200, title=row["title"],
                                           deadline=row["deadline"], rolling=row["is_rolling"],
                                           actionable=row["target_truth"]["actionable"],
                                           application_url=row["application"]["application_url"],
                                           timing=timing.inner_text()))
            assert not row["deadline"] and row["is_rolling"] and row["target_truth"]["actionable"]
            if oid=="ucsd-d93b49abd299":
                assert row["application"]["application_url"]==host and row["eligibility"]["international_friendly"]=="yes"
                public["programs"][-1]["eligibility_label"]="international-friendly"

    finally:
        (out / "two-public-programs.json").write_text(json.dumps(public, indent=2) + "\n")
        browser.close()
