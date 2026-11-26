"""Run after deployment with one fresh real visitor, using the already audited B21 original URL checks."""
import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import requests
from playwright.sync_api import expect, sync_playwright

SITE = "https://joinalab.com"
DB = "mjpirkyduibkakvlbdko.supabase.co"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"


def prepare_visitor(context, page, report):
    current_user, revisions, confirmed_fields, persisted_reads = [], [], {}, []
    signup_sent, confirmed_signup_failure = [], []
    def observe(response):
        url = urlsplit(response.url)
        if url.hostname != DB:
            return
        if url.path == "/auth/v1/signup":
            if response.ok:
                data = response.json()
                assert data["user"]["is_anonymous"] and not current_user
                current_user.append(data["user"]["id"])
            else:
                confirmed_signup_failure.append(response.status)
            return
        if not response.ok or not current_user:
            return
        if url.path.endswith("/rpc/commit_profile_patch_cas"):
            saved = response.json()
            if saved.get("status") == "applied":
                revisions.append(saved["revision"])
                patch = (response.request.post_data_json or {}).get("p_patch") or {}
                confirmed_fields.update({k:v for k,v in patch.items() if k in {"name","research_interests"}})
        elif url.path == "/rest/v1/profiles" and parse_qs(url.query).get("id") == ["eq."+current_user[0]]:
            saved = response.json()
            for row in saved if isinstance(saved,list) else [saved]:
                fields = (row or {}).get("profile_data") or {}
                if fields.get("name") == "Faculty Directory QA" and fields.get("research_interests") == "Comparative faculty research":
                    persisted_reads.append(row.get("revision"))

    def own_calls(route):
        request = route.request
        url = urlsplit(request.url)
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return route.continue_()
        if request.method == "POST" and url.hostname == DB:
            data = request.post_data_json or {}
            if (url.path == "/auth/v1/signup" and not current_user and not data.get("email")
                    and (not signup_sent or (len(signup_sent) == 1 and confirmed_signup_failure))):
                signup_sent.append(True)
                return route.continue_()
            if url.path == "/auth/v1/token" and current_user:
                return route.continue_()
            if url.path.endswith("/rpc/commit_profile_patch_cas") and current_user and data.get("p_expected_device_id") == current_user[0]:
                return route.continue_()
        return route.abort()

    context.route("**/*", own_calls)
    context.on("response", observe)
    page.goto(SITE, wait_until="domcontentloaded", timeout=90000)
    name = page.locator("#student_name")
    expect(name).to_be_visible(timeout=60000)
    tried_retry = False
    for _ in range(150):
        if current_user and not page.get_by_test_id("hydration-note").is_visible():
            break
        retry = page.get_by_role("button",name=re.compile(r"^(Retry|Retry loading profile|Retry sync)$")).first
        if not tried_retry and retry.is_visible():
            tried_retry = True
            retry.click()
        page.wait_for_timeout(200)
    assert len(current_user) == 1, "A real anonymous visitor is required"
    skip = page.get_by_role("button",name="Skip tour",exact=True)
    if skip.is_visible():
        skip.click()
        page.get_by_role("button",name="Try it",exact=True).click()
    campus = page.get_by_test_id("university-card-uiuc")
    if campus.is_visible():
        campus.click()
        page.get_by_test_id("switcher-confirm").click()
    name.fill("Faculty Directory QA")
    page.locator("#college").select_option(label="Liberal Arts & Sciences (LAS)")
    page.locator("#major").select_option(label="Integrative Biology")
    page.locator("#grade").select_option(label="Junior")
    interests=page.locator("#research_interests")
    interests.fill("Comparative faculty research")
    for _ in range(150):
        if confirmed_fields.get("research_interests") == "Comparative faculty research":
            break
        page.wait_for_timeout(200)
    assert revisions and confirmed_fields.get("research_interests") == "Comparative faculty research", "Final input was not committed"
    persisted_reads.clear()
    page.reload(wait_until="domcontentloaded")
    expect(name).to_have_value("Faculty Directory QA",timeout=60000)
    expect(interests).to_have_value("Comparative faculty research",timeout=60000)
    for _ in range(150):
        if persisted_reads:
            break
        page.wait_for_timeout(200)
    assert persisted_reads, "The stored values were not read back through this visitor's own production profile"
    report["normal_visitor"] = {"anonymous_signup": True, "profile_saved_by_site_ui": True,
                                "saved_revision_count": len(revisions), "home_form_restored_after_reload": True,
                                "profile_revisions_read_back": persisted_reads.copy(), "product_retry_used": tried_retry}
    page.close()


def run(args, cases):
    site_release = lambda: cases.get(SITE + "/api/health").json()["release_sha"]
    assert site_release() == args.sha
    report = {"started": datetime.now(UTC).isoformat(), "expected_release":args.sha, "site":SITE,
              "rows": [],"scope":"Normal public detail routes, one fresh student profile. No draft, contact, favorite, or application action."}
    def save():
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(locale="en-US", viewport={"width":1400,"height":960})
        context.add_cookies([{"name":"ofe_lang","value":"en","url":SITE}])
        report["browser"] = browser.version
        try:
            prepare_visitor(context,context.new_page(),report)
            save()
            for case in cases.CASES:
                page = context.new_page()
                result = {"id":case["id"],"original_pr":case["pr"],"ok":False}
                try:
                    cases.check_case(case,SimpleNamespace(site=SITE,scope=SCOPE,sha=args.sha,out=str(args.out)),page,result)
                    result["ok"] = True
                except Exception as exc:
                    result["failure"] = str(exc)[:500]
                finally:
                    page.close()
                report["rows"].append(result)
                save()
                print(case["id"], result["ok"],flush=True)
                time.sleep(18)
        finally:
            report["backend_after"] = site_release()
            report["finished"] = datetime.now(UTC).isoformat()
            save()
            browser.close()
    assert len(report["rows"]) == len(cases.CASES) and all(r["ok"] for r in report["rows"])
    assert report["backend_after"] == args.sha


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha",required=True)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--audited-checkout",type=Path,required=True)
    args = parser.parse_args()
    assert re.fullmatch("[0-9a-f]{40}",args.sha)
    sys.path.insert(0,str(args.audited_checkout/"data/audits/b21-detail-routes"))
    import check_b21_routes
    run(args,check_b21_routes)
