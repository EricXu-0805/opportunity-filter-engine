"""Verify the seven reviewed original Delaware detail IDs at a single release."""
import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
PRIMARY = "faculty-udel-geol-cc0d1c3c"
SECONDARY = "faculty-udel-smsp-496e2b15"


def get(url, **kwargs):
    for attempt in range(3):
        result = requests.get(url, timeout=60, **kwargs)
        if result.status_code != 429 or attempt == 2:
            return result
        retry = result.headers.get("Retry-After", "")
        time.sleep((int(retry) if retry.isdigit() else 60) + 1)


def main():
    parser = argparse.ArgumentParser()
    for key in ("ui", "api", "sha", "out"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--campus", action="store_true", help="Follow the original public link to Delaware.")
    args = parser.parse_args()
    expected = json.loads(Path(__file__).with_name("delaware-original-candidate-expectations.json").read_bytes())
    rows, results = expected["candidate_detail"], {}
    assert len(rows) == 7 and expected["reviewed_commit"] == "7c91b024ca34b7d5ce8debca9fbc128e38b90671"
    health = args.api + "/api/health"
    for end in ("before", "after"):
        assert get(health).json()["release_sha"] == args.sha, end
        if end == "after":
            break
        for oid, prior in rows.items():
            response = get(args.api + "/api/opportunities/" + oid, params={"_release_scope": SCOPE})
            assert response.status_code == prior["http"], (oid, response.status_code)
            if oid == SECONDARY:
                assert response.status_code == 404
                results[oid] = {"status": 404}
                continue
            body = response.json()
            assert body["id"] == oid and body["url"] == prior["url"] and body["source_url"] == prior["source_url"]
            assert body["target_truth"]["actionable"] == prior["actionable"]
            assert body["contact_email_status"] == prior["contact_status"]
            record = {"status": response.status_code, "name": body.get("pi_name"), "source_url": body["source_url"],
                      "actionable": body["target_truth"]["actionable"], "contact_email_status": body["contact_email_status"]}
            if oid == PRIMARY:
                page = get(args.ui + "/opportunities/" + oid)
                page.raise_for_status()
                doc = BeautifulSoup(page.content, "html.parser")
                assert doc.html["data-release-sha"] == args.sha
                headings = [h for h in doc.select("h1") if h.get_text(" ", strip=True) == "Matthew Oliver"]
                assert len(headings) == 1
                panel = headings[0].find_parent(id=lambda v: v and v.startswith("S:")) or headings[0].find_parent("main")
                hrefs = [a["href"] for a in panel.select("a[href]") if a.get_text(" ", strip=True) == "View faculty profile"]
                assert hrefs == [prior["url"]]
                record["public_detail"] = {"status": 200, "heading": "Matthew Oliver", "faculty_action": hrefs[0]}
                if args.campus:
                    clicked = get(hrefs[0])
                    clicked.raise_for_status()
                    campus = BeautifulSoup(clicked.content, "html.parser")
                    assert [h.get_text(" ", strip=True) for h in campus.select("h1")] == ["Matthew Oliver"]
                    record["campus_destination"] = {"status": clicked.status_code, "url": clicked.url, "heading": "Matthew Oliver"}
            results[oid] = record
            time.sleep(7)
    receipt = {"observed_at": datetime.now(UTC).isoformat(), "release_sha": args.sha, "ui": args.ui, "api": args.api,
               "component": expected["reviewed_commit"], "results": results}
    Path(args.out).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print("Verified seven Delaware originals and the primary named reading action.")


if __name__ == "__main__":
    main()
