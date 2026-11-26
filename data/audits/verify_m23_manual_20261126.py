"""Compare the student application and separate recommender rules at three production STaRS links."""
import json,re
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

SITE = "https://joinalab.com"
HOST = "https://www.bumc.bu.edu/gms/students/summer-training-as-research-scholars-program/"
FAQ = HOST + "frequently-asked-questions/"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
PHASE = "after"
EXPECTED = "a6ce051e4b9b3d0932ce21bd7bd1409de65362e2"
out = Path("evidence"); out.mkdir(exist_ok=True)
receipt = {"phase": PHASE, "records": {}}
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = browser.new_context(locale="en-US", service_workers="block", viewport={"width": 1260, "height": 950})
    ctx.add_init_script("if(location.hostname==='joinalab.com')localStorage.setItem('ofe_lang','en')")
    page = ctx.new_page()
    try:
        release = ctx.request.get(SITE + "/api/health").json()["release_sha"]
        assert release in ctx.request.get(SITE).text()
        receipt["frontend_release"] = receipt["backend_release"] = release
        assert not EXPECTED or release == EXPECTED
        for kind, url, snippets in (
            ("program", HOST, ("2028 and beyond", "STEM", "3.0", "Three letters", "January 15th, 2027")),
            ("faq", FAQ, ("February 1st", "two-year college", "first year Boston University medical students", "issues with GPA")),
        ):
            resp = page.goto(url, wait_until="domcontentloaded")
            assert resp and resp.ok
            # BU uses accordions. Their content exists in the loaded page even
            # while a section is collapsed.
            body = " ".join((page.locator("body").text_content() or "").split())
            present = [s for s in snippets if s.casefold() in body.casefold()]
            receipt[kind] = {"url": page.url, "title": page.title(), "status": resp.status,
                             "source_terms_present": present, "missing": [s for s in snippets if s not in present]}
        for oid in ("bu-bbc659c6ac92", "sro-60f60fbd", "sro-bc33bc08", "sro-51c40e5b"):
            reply = ctx.request.get(SITE + "/api/opportunities/" + oid, params={"_release_scope": SCOPE})
            entry = receipt["records"][oid] = {"status": reply.status}
            if not reply.ok:
                assert oid == "sro-51c40e5b" and reply.status == 404
                continue
            data = reply.json()
            assert data["id"] == oid
            entry.update({k: data.get(k) for k in ("deadline", "audience", "eligibility", "application")})
            fields = data["detail_fields"]["fields"]
            for k in ("eligibility", "application_method", "timing"):
                entry[k + "_facts"] = fields[k]["explicit"]
                entry[k + "_citations"] = {f: q.get("source_url") for f, q in fields[k]["quotes"].items()}
            if oid == "sro-51c40e5b":
                assert not fields["eligibility"]["explicit"].get("degree_path")
                continue
            page.goto(SITE + "/opportunities/" + oid, wait_until="domcontentloaded")
            expect(page.get_by_role("heading", level=1)).to_have_text(data["title"], timeout=85000)
            facts = page.get_by_test_id("fact-field-eligibility")
            expect(facts).to_be_visible(timeout=60000)
            entry["rendered_eligibility"] = facts.inner_text()
            entry["rendered_materials"] = page.get_by_test_id("fact-field-application_method").inner_text()
            if PHASE == "baseline":
                assert entry["eligibility"]["min_gpa"] is None
                assert entry["application"].get("requires_recommendation") == "unknown"
                assert "degree_path" not in entry["eligibility_facts"]
            else:
                assert data["application"]["application_url"] == HOST
                cta = page.get_by_role("link", name=re.compile(r"^Apply\b", re.I)).first
                expect(cta).to_be_visible()
                expect(cta).to_have_attribute("href", HOST)
                entry["application_button"] = {"label":cta.inner_text(),"url":cta.get_attribute("href")}
                assert entry["deadline"] == "2027-01-15" and entry["audience"] == "open"
                assert entry["eligibility"]["min_gpa"] == 3 and entry["eligibility"]["majors"] == []
                assert entry["application"]["requires_recommendation"] == "yes"
                for facet, term, url in [
                    ("min_gpa","3",HOST), ("degree_path","2028",HOST), ("class_year","junior",HOST),
                    ("citizenship","permanent",HOST), ("research_background","optional",HOST),
                    ("gpa_context","explain",FAQ), ("transfer_students","admitted",FAQ), ("medical_students","first year",FAQ),
                ]:
                    item = page.get_by_test_id("fact-eligibility-" + facet)
                    expect(item).to_contain_text(term)
                    expect(item.get_by_role("link")).to_have_attribute("href",url)
                for facet, text, url in (("requirements","Three recommendation letters",HOST),("recommendation_deadline","February 1",FAQ)):
                    item = page.get_by_test_id("fact-application_method-" + facet)
                    expect(item).to_contain_text(text)
                    expect(item.get_by_role("link")).to_have_attribute("href",url)
            page.get_by_test_id("fact-field-eligibility").screenshot(path=out / (oid + ".png"), animations="disabled")
        assert not receipt["program"]["missing"] and not receipt["faq"]["missing"], (receipt["program"], receipt["faq"])
    finally:
        (out/"boston-stars-eligibility.json").write_text(json.dumps(receipt,indent=2)+"\n")
        print(json.dumps(receipt,ensure_ascii=False))
        browser.close()

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
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page();page.on("response",capture)
    try:
        release=ctx.request.get(site+"/api/health").json()["release_sha"]
        assert release == EXPECTED and f'data-release-sha="{release}"' in ctx.request.get(site).text()
        receipt["frontend_release"]=receipt["backend_release"]=release
        enter_results(page,"ucb",major="Integrative Biology",interests="biomedical research, medicine, biology and health")
        receipt["student"]={"school":"UC Berkeley","major":"Integrative Biology","year":"Junior"}
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
            if source != "uiuc_sro":
                assert "bu-bbc659c6ac92" in info, (source, list(info))
            page.screenshot(path=out/("stars-"+(source or "all")+".png"))
    finally:
        (out/"stars-source-matches.json").write_text(json.dumps(receipt,indent=2)+"\n")
        print(json.dumps(receipt))
        browser.close()
