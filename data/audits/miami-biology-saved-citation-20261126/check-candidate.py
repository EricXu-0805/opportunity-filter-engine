"""Open the eight original Miami pages in an isolated, full-corpus build."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
import json
import re
import sys

import requests
from playwright.sync_api import expect, sync_playwright

base = Path(__file__).parent
evidence = json.loads((base / "formal-and-university.json").read_text())
replay = json.loads((base / "twelve-normal-replays.json").read_text())
expected = {r["id"]: r for r in [replay["initial"], *replay["initial_controls"]]}
site = "http://127.0.0.1:3000"
subject = "faculty-miami-bio-4dfe1b88"
scope = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
release = replay["source_sha"]
citation = "https://biology.as.miami.edu/people/index.html#:~:text=DeAngelis"
result = {"at": datetime.now(timezone.utc).isoformat(), "stage": "isolated complete candidate",
          "release": release, "rows": [], "passed": False}
assert len(expected) == 8 and requests.get(site + "/api/health", timeout=60).json()["release_sha"] == release
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(locale="en-US")
        for key, wanted in expected.items():
            row = {"id": key, "name": wanted["person"]}
            result["rows"].append(row)
            url = "/opportunities/" + key
            api = requests.get(site + "/api" + url, params={"_release_scope": scope}, timeout=55)
            api.raise_for_status()
            body = api.json()
            assert body["id"] == key and body["pi_name"] == wanted["person"]
            assert body["target_truth"]["actionable"] == wanted["actionable"]
            assert body.get("url") == wanted["url"] and body.get("source_url") == wanted["source_url"]
            assert not re.search(r"[\w.+-]+@[\w.-]+\.\w+", api.text)
            page = context.new_page()
            response = page.goto(site + url, wait_until="domcontentloaded", timeout=65000)
            assert response and response.status == 200
            assert page.locator("html").get_attribute("data-release-sha") == release
            main = page.get_by_role("main")
            heading = main.get_by_role("heading", level=1)
            expect(heading).to_have_text(body["title"], timeout=45000)
            text = main.inner_text()
            archived = "This record is no longer active." in text
            assert archived == (not wanted["actionable"])
            actions = []
            for label in ("View source", "View faculty profile"):
                for link in main.get_by_role("link", name=label, exact=True).all():
                    if link.is_visible():
                        actions.append({"label": label, "href": link.get_attribute("href")})
            if key == subject:
                assert heading.inner_text() == "Don DeAngelis" and "\u200c" not in heading.inner_text()
                assert body.get("url") is None and body["source_url"] == citation
                assert actions == [{"label": "View source", "href": citation}]
                assert body["metadata"]["faculty_title"] == "Research Professor"
                assert body["contact_email_status"] == "sign_in_required"
                assert body["last_seen_listed_at"] == "2026-11-20"
            row.update(html_status=response.status,api_http=api.status_code,heading=heading.inner_text(),
                       source_actions=actions,active=wanted["actionable"],archived_banner=archived,
                       contact_email_status=body["contact_email_status"],rank=body.get("metadata", {}).get("faculty_title"),
                       last_seen_listed_at=body.get("last_seen_listed_at"))
            page.close()
        browser.close()
    assert requests.get(site + "/api/health", timeout=60).json()["release_sha"] == release
    result["passed"] = True
finally:
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + "\n")
