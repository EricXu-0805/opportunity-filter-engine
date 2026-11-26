"""Observe the public research-topic labels on five archives and one active faculty page."""
import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from playwright.sync_api import sync_playwright

ARCHIVED = [
    "faculty-pitt-ling-14fc90c7",
    "faculty-duke-nurs-36cb4f9e",
    "faculty-pitt-frit-4c67c442",
    "faculty-duke-econ-cbbe8690",
    "faculty-wisc-me-24b38826",
]
LIVE = "faculty-pitt-cs-2ba882dd"
LABELS = {
    "en": {
        "archive": "Topics inferred by our system",
        "active": "Topics inferred from a matched OpenAlex record",
        "back": "Back to matches",
        "temporary": "This opportunity is temporarily unavailable",
    },
    "zh": {
        "archive": "系统推断的研究方向",
        "active": "根据匹配到的 OpenAlex 记录推断的研究方向",
        "back": "返回匹配列表",
        "temporary": "该机会暂时无法加载",
    },
}


def check_page(page, site, sha, lang, row):
    oid = row["id"]
    labels = LABELS[lang]
    url = f"{site}/opportunities/{oid}"
    back = page.get_by_role("link", name=labels["back"], exact=True)
    temporary = page.get_by_role("heading", name=labels["temporary"], exact=True)
    for attempt in range(3):
        response = page.goto(url, wait_until="domcontentloaded", timeout=90000)
        back.or_(temporary).first.wait_for(timeout=60000)
        if not temporary.is_visible():
            break
        print("Temporary detail read", lang, oid, attempt + 1, flush=True)
        if attempt < 2:
            time.sleep(65)
    assert back.is_visible() and page.url == url, (oid, lang, "detail unavailable")
    assert response and response.status == 200
    release = page.locator("html").get_attribute("data-release-sha")
    assert release == sha
    assert page.locator("html").get_attribute("lang") in {lang, "zh-CN" if lang == "zh" else "en-US"}
    assert page.get_by_role("main").get_by_role("heading", level=1).inner_text() == row["pi_name"]
    if oid == LIVE:
        field = page.get_by_test_id("fact-research_content-research_areas").first
        assert field.get_attribute("data-state") == "inferred"
        block = field.inner_text()
        assert all(term in block for term in row["keywords"])
        note = field.get_by_test_id("fact-research_content-research_areas-basis")
        assert note.inner_text() == labels["active"], (lang, note.inner_text())
    else:
        note = page.get_by_test_id("keywords-inferred-note")
        assert note.inner_text(timeout=15000) == labels["archive"], (lang, oid)
        section = note.locator("xpath=ancestor::section[1]")
        for term in row["keywords"]:
            assert section.get_by_text(term, exact=True).first.is_visible(), (oid, term)
    assert note.is_visible()
    return {
        "id": oid, "locale": lang, "page_release": release, "api_actionable": row["target_truth"]["actionable"],
        "visible_topic_count": len(row["keywords"]), "visible_note": note.inner_text(), "page_http": response.status,
        "detail_read_attempts": attempt + 1,
    }


def run(args):
    site = args.site.rstrip("/")
    report = {"as_of": datetime.now(UTC).isoformat(timespec="seconds"), "site": site,
              "expected_sha": args.sha, "cases": [], "scope": "Public detail reads only."}
    try:
        health = requests.get(site + "/api/health", timeout=50)
        health.raise_for_status()
        report["backend_before"] = health.json()["release_sha"]
        assert report["backend_before"] == args.sha
        public = {}
        for oid in [*ARCHIVED, LIVE]:
            response = requests.get(site + "/api/opportunities/" + oid, params={"_release_scope": args.scope}, timeout=80)
            response.raise_for_status()
            row = response.json()
            assert row["id"] == oid and row["target_truth"]["actionable"] == (oid == LIVE)
            assert row["keywords"] and row["keywords_attribution"] == "inferred"
            public[oid] = row
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for lang in LABELS:
                context = browser.new_context(locale=lang)
                context.add_cookies([{"name": "ofe_lang", "value": lang, "url": site}])
                for oid, row in public.items():
                    print("Reading", lang, oid, flush=True)
                    report["current_case"] = {"locale": lang, "id": oid}
                    page = context.new_page()
                    try:
                        report["cases"].append(check_page(page, site, args.sha, lang, row))
                    except Exception:
                        report["current_case"]["headings"] = page.locator("main h1, main h2").all_text_contents()
                        raise
                    finally:
                        page.close()
                    time.sleep(10)
                context.close()
            browser.close()
        final = requests.get(site + "/api/health", timeout=50)
        final.raise_for_status()
        report["backend_after"] = final.json()["release_sha"]
        assert report["backend_after"] == args.sha
        report.pop("current_case")
    finally:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(len(report["cases"]), "normal Chromium detail-route observations passed.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parsed = parser.parse_args()
    assert urlsplit(parsed.site).hostname in {"localhost", "127.0.0.1", "joinalab.com"}
    run(parsed)
