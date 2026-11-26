"""Verify the host and directory results a Boston undergraduate can see on the official site."""
import json,re
from pathlib import Path
from urllib.parse import quote,urlsplit
from playwright.sync_api import expect,sync_playwright
from verify_m25_results_20261126 import capture,is_view,out,receipt,site

def enter_results(page, school="ucb", *, major="Computer Science", interests=None):
    page.goto(site, wait_until="domcontentloaded")
    page.locator("#student_name").wait_for(timeout=60000)
    for _ in range(100):
        page.wait_for_timeout(250)
        if receipt["guest_signup"] == 200 and not page.get_by_test_id("hydration-note").is_visible() and not page.get_by_test_id("profile-refresh-status").is_visible():
            break
    assert receipt["guest_signup"] == 200
    campus = page.get_by_test_id("university-card-" + school)
    if not campus.is_visible():
        change = page.get_by_role("button", name="Change", exact=True)
        change.click()
        page.wait_for_timeout(500)
        if not campus.is_visible():
            change.click()
    campus.click()
    page.get_by_test_id("switcher-confirm").click()
    page.locator("#student_name").fill("Sample Student")
    college = {"ucb":"College of Computing, Data Science, and Society", "uiuc":"Grainger College of Engineering",
              "bu":"College of Arts & Sciences"}[school]
    for selector, value in (("#college", college), ("#major", major)):
        field = page.locator(selector)
        if field.evaluate("e=>e.tagName") == "SELECT":
            field.select_option(label=value)
        else:
            field.fill(value)
    page.locator("#grade").select_option(label="Junior")
    interests = interests or "biomedical research, medicine and health"
    page.locator("#research_interests").fill(interests)
    for label in ("Research", "Summer program", "Internship"):
        target = page.locator('fieldset[aria-describedby="seeking-types-help"]').get_by_role("button", name=label, exact=True)
        if target.get_attribute("aria-pressed") != "true":
            target.click()
    generate = page.get_by_test_id("generate-matches")
    expect(generate).to_be_enabled(timeout=45000)
    generate.click()
    for _ in range(25):
        page.wait_for_timeout(250)
        if urlsplit(page.url).path.startswith("/results"):
            break
    if urlsplit(page.url).path == "/" and generate.is_enabled():
        generate.click()
    page.wait_for_url(re.compile("/results"), timeout=55000)
    cards = page.locator("[id^=match-card-]")
    cards.first.wait_for(timeout=90000)
    assert receipt["profile_commit"] == 200
    if page.get_by_test_id("switcher-confirm").is_visible():
        page.keyboard.press("Escape")

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page();page.on("response",capture)
    try:
        release=ctx.request.get(site+"/api/health").json()["release_sha"]
        assert release in ctx.request.get(site).text()
        receipt["frontend_release"]=receipt["backend_release"]=release
        enter_results(page,"bu",major="Biology",interests="biomedical research, medicine, biology and health")
        q="Summer Training as Research Scholars"
        receipt["views"]={}
        for source in ("","bu_research_programs","uiuc_sro"):
            with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")==q and ((r.request.post_data_json or {}).get("view",{}).get("source") or "")==source,timeout=90000) as obs:
                if source:page.get_by_role("combobox",name="Source",exact=True).select_option(source)
                else:page.goto(site+"/results?tab=all&ai=0&q="+quote(q),wait_until="domcontentloaded")
            assert obs.value.ok
            d=obs.value.json();assert not d["has_more"] and d["filtered_total"]==len(d["results"])
            info=receipt["views"][source or "all"]={}
            for result in d["results"]:
                oid=result["opportunity_id"]
                card=page.locator("#match-card-"+oid)
                expect(card).to_be_visible(timeout=50000)
                card.get_by_role("button",name="Show details",exact=True).click()
                info[oid]={"card_text":card.inner_text(),"rank_gaps":result.get("reasons_gap",[]),"score":result.get("final_score")}
            receipt["views"][source or "all"]["total"]=d["filtered_total"]
            page.screenshot(path=out/("stars-"+(source or "all")+".png"))
    finally:
        (out/"stars-source-matches.json").write_text(json.dumps(receipt,indent=2)+"\n")
        print(json.dumps(receipt))
        browser.close()
