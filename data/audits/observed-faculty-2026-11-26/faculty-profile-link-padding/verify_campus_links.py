"""Navigate to saved teacher IDs and examine their published university links."""
import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    for opt in ("site", "scope", "sha", "out"):
        parser.add_argument("--" + opt, required=True)
    args = parser.parse_args()
    assert urlsplit(args.site).hostname in {"localhost", "127.0.0.1", "joinalab.com"}
    cases = json.loads(Path(__file__).with_name("candidate-browser-expected.json").read_text())
    assert requests.get(args.site + "/api/health", timeout=35).json()["release_sha"] == args.sha
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="en-US", viewport={"width": 1400, "height": 960})
        for oid, expected in cases.items():
            row = {"id": oid, "expected": expected}
            page = context.new_page()
            try:
                api = requests.get(args.site + "/api/opportunities/" + oid, params={"_release_scope": args.scope}, timeout=35)
                api.raise_for_status()
                data = api.json()
                assert data["id"] == oid and data.get("url") == data.get("source_url") == expected
                response = page.goto(args.site + "/opportunities/" + oid, wait_until="domcontentloaded", timeout=65000)
                assert response and response.status == 200
                page.get_by_role("link", name="Back to matches", exact=True).wait_for(state="visible", timeout=45000)
                main = page.get_by_role("main")
                assert main.get_by_role("heading", level=1).inner_text() == data["pi_name"]
                assert page.locator("html").get_attribute("data-release-sha") == args.sha
                action = main.get_by_role("link", name="View faculty profile", exact=True)
                if expected:
                    assert action.is_visible() and action.get_attribute("href") == expected
                else:
                    assert not action.count()
                row.update(passed=True, page_name=data["pi_name"], visible_person_link=action.get_attribute("href") if expected else None)
            except Exception as exc:
                row.update(passed=False,error=f"{type(exc).__name__}: {str(exc)[:300]}")
            results.append(row)
            print(oid, row, flush=True)
            page.close()
            time.sleep(18)
        browser.close()
    assert requests.get(args.site + "/api/health", timeout=35).json()["release_sha"] == args.sha
    report = {"revision": args.sha, "checked_at": datetime.now(UTC).isoformat(), "site": args.site, "rows": results}
    Path(args.out).write_text(json.dumps(report, indent=2)+"\n")
    assert all(row["passed"] for row in results)


if __name__ == "__main__":
    main()
