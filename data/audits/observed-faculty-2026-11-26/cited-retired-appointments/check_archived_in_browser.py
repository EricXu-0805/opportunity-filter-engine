"""Open four cited archived appointments and the department staff comparison in real Chromium."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from check_archived_appointment import FACULTY, LABELS, OUTREACH, STAFF_ID
from playwright.sync_api import sync_playwright

OLIVER_ID = "faculty-udel-geol-cc0d1c3c"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--oliver-url", required=True)
    args = parser.parse_args()
    site = args.site.rstrip("/")
    assert urlsplit(site).hostname in {"127.0.0.1", "localhost", "joinalab.com"}

    def release():
        response = requests.get(site + "/api/health", timeout=(15, 60))
        response.raise_for_status()
        assert response.json()["release_sha"] == args.sha

    report = {"site": site, "sha": args.sha, "started": datetime.now(UTC).isoformat(), "documents": []}

    def save():
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    release()
    with sync_playwright() as session:
        browser = session.chromium.launch()
        for language, (label, source_label, staff_job) in LABELS.items():
            context = browser.new_context(locale=language)
            context.add_cookies([{"name": "ofe_lang", "value": language, "url": site}])
            cases = [*FACULTY, STAFF_ID] + ([OLIVER_ID] if language == "en" else [])
            for oid in cases:
                name, title, source = FACULTY.get(
                    oid, ("Matthew Oliver" if oid == OLIVER_ID else "Debbie Walton", "", "")
                )
                page = context.new_page()
                url = site + "/opportunities/" + oid
                panel = page.get_by_role("main")
                heading = panel.get_by_role("heading", name=name, level=1, exact=True)
                temporary = panel.get_by_role(
                    "heading",
                    name="该机会暂时无法加载" if language == "zh" else "This opportunity is temporarily unavailable",
                    exact=True,
                )
                for attempt in range(3):
                    response = page.goto(url, wait_until="domcontentloaded", timeout=90000)
                    heading.or_(temporary).first.wait_for(timeout=60000)
                    if heading.is_visible():
                        break
                    if attempt < 2:
                        time.sleep(65)
                assert response and response.ok and page.url == url
                assert heading.is_visible() and page.locator("html").get_attribute("data-release-sha") == args.sha
                assert page.locator("html").get_attribute("lang") in {
                    language,
                    "zh-CN" if language == "zh" else "en-US",
                }
                result = {
                    "id": oid,
                    "heading": name,
                    "language": language,
                    "page_http": response.status,
                    "attempts": attempt + 1,
                }
                if oid == OLIVER_ID:
                    action = panel.get_by_role("link", name="View faculty profile", exact=True)
                    assert action.is_visible() and action.get_attribute("href") == args.oliver_url
                    result["faculty_profile"] = args.oliver_url
                else:
                    cited = panel.get_by_role("link", name=source_label, exact=True)
                    if oid == STAFF_ID:
                        assert panel.get_by_text(staff_job, exact=False).first.is_visible()
                        assert panel.get_by_text(label, exact=True).count() == 0 and cited.count() == 0
                        result["staff_role"] = staff_job
                    else:
                        assert (
                            panel.get_by_text(label, exact=True).is_visible()
                            and panel.get_by_text(title, exact=True).is_visible()
                        )
                        assert cited.is_visible() and cited.get_attribute("href") == source
                        result.update(visible_title=title, university_source=source)
                    for role in ("button", "link"):
                        for forbidden in OUTREACH:
                            assert panel.get_by_role(role, name=forbidden, exact=True).count() == 0
                    assert panel.locator('a[href^="mailto:"]:visible').count() == 0
                report["documents"].append(result)
                save()
                page.close()
                time.sleep(9)
            context.close()
        browser.close()
    release()
    assert len(report["documents"]) == 11
    report["finished"] = datetime.now(UTC).isoformat()
    save()


if __name__ == "__main__":
    main()
