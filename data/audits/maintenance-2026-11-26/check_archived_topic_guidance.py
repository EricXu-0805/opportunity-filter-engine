"""Read the production-scale candidate's historical and active faculty topic notes in both site languages."""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from playwright.sync_api import sync_playwright

ARCHIVED = ["faculty-pitt-ling-14fc90c7","faculty-duke-nurs-36cb4f9e","faculty-pitt-frit-4c67c442",
            "faculty-duke-econ-cbbe8690","faculty-wisc-me-24b38826"]
LIVE = "faculty-pitt-cs-2ba882dd"
Q = {"en": ("Topics inferred by our system", "Topics inferred by our system. Check them before using them in your email."),
     "zh": ("系统推断的研究方向", "系统推断的研究方向，写信前请先核对。")}


def check(site, scope, sha):
    def health():
        res = requests.get(site + "/api/health", timeout=50)
        res.raise_for_status()
        return res.json()["release_sha"]
    assert health() == sha
    public = {}
    for oid in [*ARCHIVED, LIVE]:
        r = requests.get(site + "/api/opportunities/" + oid, params={"_release_scope":scope}, timeout=80)
        r.raise_for_status()
        row = r.json()
        assert row["id"] == oid and row["target_truth"]["actionable"] == (oid == LIVE)
        assert row["keywords"] and row["keywords_attribution"] == "inferred"
        public[oid] = row
    recorded = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for lang, (neutral, active) in Q.items():
            context = browser.new_context(locale=lang)
            context.add_cookies([{"name":"ofe_lang","value":lang,"url":site}])
            for oid, row in public.items():
                page = context.new_page()
                response = page.goto(f"{site}/opportunities/{oid}",wait_until="domcontentloaded",timeout=90000)
                assert response and response.status == 200
                note = page.get_by_test_id("keywords-inferred-note")
                note.wait_for(timeout=75000)
                assert page.locator("html").get_attribute("data-release-sha") == sha
                assert page.locator("html").get_attribute("lang") in (lang, "zh-CN" if lang=="zh" else "en-US")
                assert note.inner_text() == (active if oid == LIVE else neutral), (oid, lang, note.inner_text())
                section = note.locator("xpath=ancestor::section[1]")
                for term in row["keywords"]:
                    assert section.get_by_text(term,exact=True).first.is_visible(), (oid,term)
                recorded.append({"id":oid,"locale":lang,"visible_topic_count":len(row["keywords"]),
                                 "api_actionable":row["target_truth"]["actionable"],"visible_note":note.inner_text(),
                                 "page_http":response.status})
                page.close()
            context.close()
        browser.close()
    assert health() == sha
    return recorded


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--site",required=True)
    parser.add_argument("--scope",required=True)
    parser.add_argument("--sha",required=True)
    parser.add_argument("--out",required=True,type=Path)
    a=parser.parse_args()
    assert urlsplit(a.site).hostname in {"localhost","127.0.0.1","joinalab.com"}
    rows=check(a.site.rstrip("/"),a.scope,a.sha)
    a.out.write_text(json.dumps({"as_of":datetime.now(UTC).isoformat(timespec="seconds"),"site":a.site,
            "same_frontend_backend_sha":a.sha,"cases":rows,"scope":"Public page reads and attribution checks. No drafts, accounts or external actions."},ensure_ascii=False,indent=2)+"\n")
    print(len(rows),"normal Chromium detail-route observations passed.")
