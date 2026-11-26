"""Compare three M65 public details and a real signed-in guest view with the named cohort pages."""
import json
import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright, expect
from verify_m25_results_20261126 import capture, enter_results, is_view, out, receipt, site

cases = {
    "sro-3c378261": ("Cellular and Molecular Biology of Stress", "2027-02-15", "2027-02-10",
                      "https://wiscience.wisc.edu/research/summer_research_program/", "Apply by February 10, 2027"),
    "nsf-reu-2447669": ("Genes & the Environment", "2026-02-15", "2026-03-15",
                       "https://med.und.edu/education-training/biomedical-sciences/reu/index.html", "through March 15, 2026"),
}
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = browser.new_context(locale="en-US", service_workers="block", viewport={"width": 1250, "height": 950})
    page = ctx.new_page()
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page.on("response", capture)
    try:
        enter_results(page)
        for oid, (query, old, new, host, excerpt) in cases.items():
            source = ctx.new_page()
            assert source.goto(host, wait_until="domcontentloaded").ok
            expect(source.get_by_text(excerpt, exact=False).first).to_be_visible(timeout=30000)
            source.close()
            url = site + "/opportunities/" + oid
            page.goto(url, wait_until="domcontentloaded")
            expect(page.get_by_role("heading", level=1)).to_be_visible()
            body = page.locator("main").inner_text()
            api = page.request.get(site + "/api/opportunities/" + oid, params={"_release_scope": "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
            assert api.ok
            value = api.json()
            assert value["id"] == oid and value["deadline"] in (old,new)
            assert value["deadline"] in body
            fixed = value["deadline"] == new
            assert value["deadline_is_estimate"] is (not fixed)
            if fixed:
                assert value["target_truth"]["actionable"] is (oid != "nsf-reu-2447669")
            elif "Estimated by us" not in body:
                raise AssertionError("Estimate has no visible qualification")
            receipt[oid] = {"detail": url, "source": host, "official_excerpt": excerpt, "date": value["deadline"],
                            "estimated": value["deadline_is_estimate"], "truth": value["target_truth"], "corrected": fixed}
            page.screenshot(path=out/(oid+"-date.png"))
            with page.expect_response(lambda r: is_view(r) and (r.request.post_data_json or {}).get("view", {}).get("search_query") == query, timeout=90000) as response:
                page.goto(site + "/results?tab=all&ai=0&q="+quote(query),wait_until="domcontentloaded")
            wire = response.value.json()
            assert response.value.ok and not wire["has_more"]
            ids = [r["opportunity_id"] for r in wire["results"]]
            receipt[oid]["result_ids"] = ids
            if oid in ids:
                expect(page.locator("#match-card-"+oid)).to_be_visible(timeout=45000)
            if fixed and oid=="nsf-reu-2447669": assert oid not in ids
        chen="caltech-a7fedb84058b"
        url=site+"/opportunities/"+chen
        page.goto(url,wait_until="domcontentloaded"); expect(page.get_by_role("heading",level=1)).to_be_visible()
        body=page.locator("main").inner_text()
        api=page.request.get(site+"/api/opportunities/"+chen,params={"_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
        assert api.ok; value=api.json(); fixed=value["target_truth"]["reference_only"]
        assert value["is_rolling"] is (not fixed) and value["target_truth"]["actionable"] is (not fixed)
        assert ("Applications reviewed on a rolling basis" in body) is (not fixed)
        if fixed:
            assert not page.get_by_role("link",name="Apply now",exact=True).count()
            assert not page.get_by_role("button",name="Draft email",exact=True).count()
        receipt[chen]={"detail":url,"truth":value["target_truth"],"rolling":value["is_rolling"],"corrected":fixed}
        page.screenshot(path=out/(chen+"-detail.png"))
        assert len({receipt[i]["corrected"] for i in [*cases,chen]})==1, "Mixed deployment"
    finally:
        (out/"m23.json").write_text(json.dumps(receipt,indent=2)+"\n")
        print(json.dumps(receipt),flush=True)
        browser.close()
