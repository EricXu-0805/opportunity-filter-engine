"""Check the launch profile against five original undergraduate program records."""
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

CALIFORNIA = [('ucsd-d93b49abd299', 'https://ugresearch.ucsd.edu/programs/urh-summer/index.html', ('Each program has a cohort and a coordinator', 'McNair Program', 'Look through the programs')), ('ucsd-c6d547c9321a', 'https://ucsd-research.academicworks.com/opportunities/2368', ('11/20/2026', 'undergraduate students in all majors', 'October 29, 2026')), ('ucsb-45d0bef1a207', 'https://calbridge.org/undergraduate-program/', ('must be attending a California State University', 'in April', 'Graduate students are not eligible'))]

def california_details(page, context):
    for oid, host, qualifiers in CALIFORNIA:
        response = page.goto(host, wait_until="domcontentloaded")
        text = " ".join((page.locator("body").text_content() or "").lower().split())
        assert response.ok and all(phrase.lower() in text for phrase in qualifiers), oid
        detail = context.request.get(site + "/api/opportunities/" + oid, params={"_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
        assert detail.ok
        row = detail.json()
        assert row["id"] == oid and row["is_rolling"] is False
        page.goto(site + "/opportunities/" + oid, wait_until="domcontentloaded")
        expect(page.get_by_role("heading", level=1)).to_have_text(row["title"], timeout=60000)
        body = page.locator("main").inner_text()
        apply_url = (row.get("application") or {}).get("application_url")
        if oid == "ucsb-45d0bef1a207":
            assert row["target_truth"]["actionable"] and row["deadline"] is None
            assert row["organization"] == "Cal-Bridge" and apply_url == host
            assert "Community College students transferring" in body and "Santa Barbara" not in row["location"]
        elif oid == "ucsd-c6d547c9321a":
            assert not row["target_truth"]["actionable"] and not apply_url
            assert row["deadline"] == "2026-11-20" and "2026-11-20" in body
        else:
            assert row["target_truth"]["reference_only"] and not row["target_truth"]["actionable"]
            assert not apply_url and row["eligibility"]["international_friendly"] == "unknown"
        receipt[oid] = {"deadline": row["deadline"], "rolling": row["is_rolling"],
                        "actionable": row["target_truth"]["actionable"], "source": host, "apply": apply_url}
        page.screenshot(path=out/(oid+"-verified-detail.png"))

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox","--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page();page.on("response",capture)
    page.set_default_timeout(90000)
    page.on("pageerror",lambda exc: print("Browser error:",str(exc)[:400],flush=True))
    try:
        release=ctx.request.get(site+"/api/health").json()["release_sha"]
        assert release == "c1b0c3c21b3c806bbf9b7b6ff95ece078f98d541"
        homepage = ctx.request.get(site)
        assert homepage.ok and 'data-release-sha="c1b0c3c21b3c806bbf9b7b6ff95ece078f98d541"' in homepage.text()
        receipt["frontend_release"] = receipt["backend_release"] = release
        enter_results(page,"bu",major="Biology",interests="research, biological science, microbiology, medicine, history and linguistics")
        cases = [
            ("sro-7b7d80d3", "Computer Assisted Synthesis", None),
            ("sro-5725bf41", "Summer STAR", None),
            ("sro-e74d89e9", "Michigan Humanities Emerging Research Scholars", "2026-12-02"),
            ("stanford-1a20b2e045cf", "Stanford Summer Research Program", "2026-11-01"),
            ("sro-7f860ddc", "Microbiology Summer Undergraduate Research", "2026-12-01"),
        ]
        visible = []
        for oid, query, opening in cases:
            with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")==query,timeout=90000) as read:
                page.goto(site+"/results?tab=all&ai=0&q="+quote(query),wait_until="domcontentloaded")
            assert read.value.ok
            listing = read.value.json()
            assert not listing["has_more"]
            ids = [item["opportunity_id"] for item in listing["results"]]
            entry = {"ids": ids, "total": listing["filtered_total"]}
            assert len(ids) == entry["total"]
            if oid in ids:
                card = page.locator("#match-card-"+oid)
                expect(card).to_be_visible(timeout=60000)
                card.get_by_role("button",name="Show details",exact=True).click()
                item = next(item for item in listing["results"] if item["opportunity_id"] == oid)
                entry["ranking_gaps"] = item.get("reasons_gap", [])
                assert "Targets graduate / PhD students" not in card.inner_text()
                assert not any("Targets graduate" in gap for gap in entry["ranking_gaps"])
                visible.append(oid)
                card.screenshot(path=out/(oid+"-student-result.png"))
            detail = page.request.get(site+"/api/opportunities/"+oid,params={"_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
            assert detail.ok and detail.json()["id"] == oid
            page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
            expect(page.get_by_role("heading",level=1)).to_have_text(detail.json()["title"],timeout=90000)
            if opening:
                dt = detail.json()
                entry["deadline"],entry["opening"] = dt["deadline"],dt["application_opens"]["on"]
                assert entry["deadline"] == "2027-02-01" and entry["opening"] == opening
                timing = page.get_by_test_id("fact-field-timing")
                expect(timing).to_contain_text("2027-02-01")
                timing.screenshot(path=out/(oid+"-timing.png"))
            receipt[oid] = entry
            print("Checked original", oid, query, entry, flush=True)
        receipt["ordinary_biology_profile_found"] = visible
        assert set(visible) == {oid for oid, _, _ in cases if oid != "sro-e74d89e9"}
        history = page
        receipt["biology_guest_commit"] = receipt["profile_commit"]
        receipt["profile_commit"] = None
        enter_results(history,"bu",major="History",interests="humanities, history, literature, cultural studies and historical research")
        oid, q = "sro-e74d89e9", "Michigan Humanities Emerging Research Scholars"
        with history.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")==q,timeout=90000) as read:
            history.goto(site+"/results?tab=all&ai=0&q="+quote(q),wait_until="domcontentloaded")
        assert read.value.ok
        view = read.value.json()
        ids = [row["opportunity_id"] for row in view["results"]]
        assert ids == [oid] and view["filtered_total"] == 1
        card = history.locator("#match-card-" + oid)
        expect(card).to_be_visible(timeout=90000)
        card.get_by_role("button",name="Show details",exact=True).click()
        assert "Targets graduate / PhD students" not in card.inner_text()
        receipt["humanities_profile_found"] = ids
        print("History student sees", ids, "in", view["filtered_total"], "results",flush=True)
        card.screenshot(path=out/(oid+"-history-student-result.png"))
        five = {"deadline":"rolling","paid":"no","intl":"no","scope":"open","on_campus":"no"}
        def five_filter_view(resp):
            if not is_view(resp): return False
            view = (resp.request.post_data_json or {}).get("view",{})
            return all(view.get(key)==value for key,value in five.items())
        with page.expect_response(five_filter_view,timeout=90000) as combo:
            page.goto(site+"/results?tab=all&dl=rolling&paid=no&intl=no&scope=open&loc=no",wait_until="domcontentloaded")
        assert combo.value.ok
        selected = page.locator("select").evaluate_all("(sels) => sels.map(s => ({value:s.value, label:s.selectedOptions[0]?.textContent.trim()}))")
        labels = {x["label"].casefold() for x in selected if x["label"]}
        receipt["five_filter_url"]={"url":page.url,"status":combo.value.status, "labels":selected,"total":combo.value.json()["filtered_total"]}
        assert any("no deadline listed" in s for s in labels) and any("off campus" in s for s in labels), selected
        assert all("≤rollingd" not in label for label in labels)
        california_details(page,ctx)
    finally:
        (out/"undergraduate-results.json").write_text(json.dumps(receipt,indent=2)+"\n")
        print(json.dumps(receipt))
        browser.close()
