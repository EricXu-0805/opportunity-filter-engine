"""Verify the host and directory results a Boston undergraduate can see on the official site."""
import json,re
from pathlib import Path
from urllib.parse import quote,urlsplit
from playwright.sync_api import expect,sync_playwright
from verify_m25_results_20261126 import capture,is_view,receipt
site="https://joinalab.com"
out=Path("evidence");out.mkdir(exist_ok=True)

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
    college = {"ucb":"College of Letters and Science", "uiuc":"Grainger College of Engineering",
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
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox","--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page();page.on("response",capture)
    page.set_default_timeout(90000)
    page.on("pageerror",lambda exc: print("Browser error:",str(exc)[:400],flush=True))
    try:
        release=ctx.request.get(site+"/api/health").json()["release_sha"]
        assert release == "bdb523bec33c71f682e0d895f06a8bad859863b6"
        assert f'data-release-sha="{release}"' in ctx.request.get(site).text()
        receipt["frontend_release"]=receipt["backend_release"]=release
        enter_results(page,"ucb",major="Integrative Biology",interests="biomedical research, medicine, biology and health")
        receipt["student"] = {"school":"UC Berkeley","major":"Integrative Biology","year":"Junior"}
        q="Summer Training as Research Scholars"
        receipt["views"]={}
        for source in ("","bu_research_programs","uiuc_sro"):
            with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")==q and ((r.request.post_data_json or {}).get("view",{}).get("source") or "")==source,timeout=90000) as obs:
                if source:page.get_by_role("combobox",name="Source",exact=True).select_option(source)
                else:page.goto(site+"/results?tab=all&ai=0&q="+quote(q),wait_until="domcontentloaded")
            assert obs.value.ok
            if not source:
                live_query = obs.value.request.post_data_json
                view_url = obs.value.url
            d=obs.value.json();assert not d["has_more"] and d["filtered_total"]==len(d["results"])
            info=receipt["views"][source or "all"]={}
            for result in d["results"]:
                oid=result["opportunity_id"]
                card=page.locator("#match-card-"+oid)
                expect(card).to_be_visible(timeout=50000)
                card.get_by_role("button",name="Show details",exact=True).click()
                info[oid]={"card_text":card.inner_text(),"rank_gaps":result.get("reasons_gap",[]),"score":result.get("final_score")}
            receipt["views"][source or "all"]["total"]=d["filtered_total"]
            ids = [x["opportunity_id"] for x in d["results"]]
            expected = ["sro-60f60fbd","sro-bc33bc08"] if source=="uiuc_sro" else ["bu-bbc659c6ac92"]
            assert len(ids)==len(expected) and set(ids)==set(expected), (source,ids,expected)
            assert all("Targets graduate / PhD students" not in (v.get("card_text") or "") for v in info.values() if isinstance(v,dict))
            page.screenshot(path=out/("stars-"+(source or "all")+".png"))
        originals = ["bu-bbc659c6ac92", "sro-60f60fbd", "sro-bc33bc08"]
        response = ctx.request.post(site+"/api/opportunities/batch", data={"ids": originals})
        assert response.ok and response.json()["found"] == len(originals)
        records = {row["id"]:row for row in response.json()["opportunities"]}
        assert set(records) == set(originals)
        links = receipt["original_links"] = {}
        for oid in originals:
            original = page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
            assert original and original.ok
            expect(page.get_by_role("heading",level=1)).to_have_text(records[oid]["title"],timeout=70000)
            button = page.get_by_role("link",name=re.compile(r"^Apply\b",re.I)).first
            expect(button).to_have_attribute("href", "https://www.bumc.bu.edu/gms/students/summer-training-as-research-scholars-program/")
            links[oid] = {"status":original.status, "page":page.url, "student_deadline":records[oid]["deadline"], "host":button.get_attribute("href")}
            assert links[oid]["student_deadline"] == "2027-01-15"
            facts = page.get_by_test_id("fact-application_method-requirements")
            expect(facts).to_contain_text("Three recommendation letters")
            faculty_deadline = page.get_by_test_id("fact-application_method-recommendation_deadline")
            expect(faculty_deadline).to_contain_text("February 1")
            expect(faculty_deadline.get_by_role("link")).to_have_attribute("href",links[oid]["host"]+"frequently-asked-questions/")
            links[oid]["recommendations"] = facts.inner_text()
            links[oid]["recommender_deadline"] = faculty_deadline.inner_text()
        prior_id = "sro-51c40e5b"
        # Historical detail requests from the released web client declare compatibility.
        prior = ctx.request.get(site+"/api/opportunities/"+prior_id, params={
            "_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2",
        })
        assert prior.ok and prior.json()["id"]==prior_id
        old = prior.json()
        assert old["deadline"] != "2027-01-15" and "degree_path" not in old["detail_fields"]["fields"]["eligibility"]["explicit"]
        receipt["historic_control"] = {"id":prior_id,"status":prior.status,"deadline":old["deadline"]}
        # Replay the normal page's read-only query, restoring requested historical
        # favorites in the view. This does not write any favorites or reminders.
        restored = receipt["restore_favorite_ids_in_view"] = {}
        for label, favorites, tab in (("first_directory",[originals[1]],"all"),
                                      ("second_directory",[originals[2]],"all"),
                                      ("all_three",originals,"starred")):
            query = {**live_query,"view":{**live_query["view"],"favorite_ids":favorites,"tab":tab},"page_size":1}
            query.pop("cursor",None)
            ids = []
            while True:
                response = ctx.request.post(view_url,data=query,timeout=90000)
                assert response.ok, (label,response.status)
                d = response.json()
                ids.extend(row["opportunity_id"] for row in d["results"])
                if not d["has_more"]: break
                assert d["next_cursor"] and len(ids)<4
                query["cursor"] = d["next_cursor"]
            restored[label] = {"requested":favorites, "returned":ids,"total":d["filtered_total"]}
            assert len(ids)==len(set(ids))==d["filtered_total"]==len(favorites) and set(ids)==set(favorites),(label,ids)
        # The ordinary browser takes a real cursor through an untruncated
        # multi-page search; the focused program search fits on one page.
        with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")=="research" and not (r.request.post_data_json or {}).get("cursor"),timeout=90000) as first:
            page.goto(site+"/results?tab=all&ai=0&q=research",wait_until="domcontentloaded")
        a=first.value.json()
        assert a["has_more"] and a["next_cursor"] and len(a["results"])==50
        with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("cursor")==a["next_cursor"],timeout=90000) as second:
            page.get_by_role("button",name="Next",exact=True).click()
        b=second.value.json()
        i=[x["opportunity_id"] for x in a["results"]];j=[x["opportunity_id"] for x in b["results"]]
        assert len(set(i+j))==len(i+j) and a["filtered_total"]==b["filtered_total"]
        expect(page.locator("#match-card-"+j[0])).to_be_visible(timeout=45000)
        receipt["browser_pages"]={"total":a["filtered_total"],"page_one":i,"page_two":j}
    finally:
        (out/"stars-source-matches.json").write_text(json.dumps(receipt,indent=2)+"\n")
        print(json.dumps(receipt))
        browser.close()
