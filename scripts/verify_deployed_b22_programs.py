"""Read the existing Berkeley/Simplify bookmarks and compare their released public fields."""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from verify_deployed_b15_keyboard import SITE, check_deployment
from verify_deployed_b15_research import read_public


def fingerprint(fields):
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def main():
    expected = json.loads(Path("data/audits/release-probes/b22-program-expected.json").read_text())
    release = os.environ["OFE_EXPECTED_SITE_SHA"]
    mode = os.environ["OFE_PROGRAM_CHECK_MODE"]
    path = Path(os.environ["RUNNER_TEMP"]) / "public-b22-programs.json"
    assert mode in ("before", "after")
    selected = {"19631-1", "18918-2", "20078-1", "20432-1", "19936-3",
                "01c4d1da-b058-4813-b47e-7f8e4dba1bd1"}
    original = {r["source_id"]: r for r in expected["rows"]}
    report = {"release": release, "mode": mode, "site": SITE, "started_at": datetime.now(timezone.utc).isoformat(),
              "projections": [], "pages": [], "retry_events": []}
    check_deployment(release)
    docs = {}
    try:
        for row in expected["rows"]:
            if mode == "before" and row["source_id"] not in selected:
                continue
            doc = read_public(row, report["retry_events"])
            assert doc["id"] == row["id"]
            fields = {k: doc.get(k) for k in expected["fields"]}
            current = fingerprint(fields)
            if mode == "after":
                assert current == row["fingerprint"], (row["id"], current, row["fingerprint"])
                if row["historical_not_listed"]:
                    assert doc["target_truth"]["reference_only"] and not doc["application"].get("application_url")
            report["projections"].append({"id": row["id"], "fingerprint": current})
            if row["source_id"] in selected:
                docs[row["source_id"]] = doc
            time.sleep(0.65)

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(locale="en-US", viewport={"width": 1360, "height": 920})
            for source_id in sorted(selected):
                row, doc = original[source_id], docs[source_id]
                url = f"{SITE}/opportunities/{row['id']}"
                response = page.goto(url, wait_until="domcontentloaded", timeout=65000)
                assert response and response.ok
                expect(page.locator("h1").first).to_have_text(doc["title"], timeout=30000)
                assert page.locator("html").get_attribute("data-release-sha") == release
                body = page.locator("main").inner_text(timeout=30000)
                if source_id == "20432-1":
                    assert ("Sponsored by UC Berkeley" in doc["title"]) == (mode == "before")
                if source_id.startswith("01c4d1da"):
                    employer = "General Intuition &amp; Medal" if mode == "before" else "General Intuition & Medal"
                    assert doc["organization"] == employer and employer in body
                report["pages"].append({"id": row["id"], "url": url, "status": response.status, "visible_h1": doc["title"],
                                        "api_mentor_or_employer": doc["lab_or_program"],
                                        "public_posture": (doc.get("target_truth") or {}).get("reason_code")})
            browser.close()
        check_deployment(release)
        assert len(report["pages"]) == len(selected)
        assert len(report["projections"]) == (len(selected) if mode == "before" else len(expected["rows"]))
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
