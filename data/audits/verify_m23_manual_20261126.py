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


cases = [
    ("sro-7b7d80d3","Computer Assisted Synthesis","https://ccas.nd.edu/outreach/surf-program/", ["undergraduate summer research", "immediate mentor"]),
    ("sro-5725bf41","Summer STAR", "https://www.augusta.edu/gradschool/star/admission-requirements.php", ["undergraduate Bachelor", "September 15, 2026"]),
    ("sro-e74d89e9","Michigan Humanities Emerging Research Scholars","https://rackham.umich.edu/prospective-students/michhers/", ["rising seniors","February 1, 2027","December 2, 2026"]),
    ("stanford-1a20b2e045cf","Stanford Summer Research Program","https://biosciences.stanford.edu/pathways/ssrp-amgen-scholars-program/the-ssrp-amgen-scholars-program-application/", ["November 1, 2026","February 1, 2027"]),
    ("sro-7f860ddc","Microbiology Summer Undergraduate Research", "https://med.uth.edu/mmg/summer-research-program/", ["December 1, 2026","February 1, 2027"]),
]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page();page.on("response",capture)
    try:
        for attempt in range(12):
            release=ctx.request.get(site+"/api/health",params={"probe":str(attempt)}).json()["release_sha"]
            front=re.search(r'data-release-sha="([a-f0-9]{40})"',ctx.request.get(site,params={"probe":str(attempt)}).text())[1]
            receipt["frontend_release"],receipt["backend_release"]=front,release
            if front==release:break
            page.wait_for_timeout(5000)
        assert front==release,(front,release)
        receipt["programs"]={}
        for oid,query,url,phrases in cases:
            entry=receipt["programs"][oid]={"program":query,"host":url}
            resp=page.goto(url,wait_until="domcontentloaded")
            entry["host_http"]=resp.status if resp else None
            text=" ".join((page.locator("body").text_content() or "").split()).lower()
            entry["read_on_host"]={t:t.lower() in text for t in phrases}
            if oid=="sro-e74d89e9" and entry["host_http"]==403:
                # The public application login corroborates the audience. Its
                # displayed 2026 date is historical and is not evidence for 2027.
                admission="https://secure.rackham.umich.edu/michhers/"
                alternate=page.goto(admission,wait_until="domcontentloaded")
                wording=" ".join((page.locator("body").text_content() or "").split()).lower()
                entry["secondary_host"]={"url":admission,"http":alternate.status,
                                         "rising_seniors":"rising seniors" in wording}
                entry["date_observation"]="The runner could not read this host page (403). Rackham's 2027 Important Dates and Apply Today sections were checked separately."

            api=ctx.request.get(site+"/api/opportunities/"+oid,params={"_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
            assert api.ok;data=api.json();assert data["id"]==oid
            entry.update({k:data.get(k) for k in ("id","title","deadline","is_rolling","application_opens","source","audience")})
            entry["eligibility"]=data["eligibility"];entry["target_truth"]=data["target_truth"]
            page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
            expect(page.get_by_role("heading",level=1)).to_have_text(data["title"],timeout=90000)
            entry["timing_display"]=page.get_by_test_id("fact-field-timing").inner_text()
            entry["eligibility_display"]=page.get_by_test_id("fact-field-eligibility").inner_text()
            page.get_by_test_id("fact-field-timing").screenshot(path=out/(oid+"-timing.png"))
        assert receipt["programs"]["sro-e74d89e9"]["deadline"]=="2027-02-10"
        assert not receipt["programs"]["stanford-1a20b2e045cf"]["deadline"]
        enter_results(page,"bu",major="Biology",interests="research, biological science, microbiology, medicine, history and linguistics")
        for oid,q,url,phrases in cases:
            with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")==q,timeout=90000) as read:
                page.goto(site+"/results?tab=all&ai=0&q="+quote(q),wait_until="domcontentloaded")
            response=read.value;assert response.ok
            d=response.json();assert not d["has_more"]
            entry=receipt["programs"][oid];entry["results_total"]=d["filtered_total"]
            entry["on_results"]=[r["opportunity_id"] for r in d["results"]]
            for r in d["results"]:
                if r["opportunity_id"]==oid:
                    card=page.locator("#match-card-"+oid);expect(card).to_be_visible(timeout=60000)
                    card.get_by_role("button",name="Show details",exact=True).click()
                    entry["card_text"]=card.inner_text()
                    entry["ranking_reason"]=r.get("reasons_gap")
        for oid,e in receipt["programs"].items():
            if oid=="sro-e74d89e9" and e["host_http"]==403:
                assert e["secondary_host"]["http"] in (200,403)
                if e["secondary_host"]["http"]==200:
                    assert e["secondary_host"]["rising_seniors"]
            else:
                assert e["host_http"]==200 and all(e["read_on_host"].values()),oid
            assert e["on_results"]==[] and e["results_total"]==0
    finally:
        (out/"five-undergraduate-programs.json").write_text(json.dumps(receipt,indent=2)+"\n")
        print(json.dumps(receipt))
        browser.close()
