"""Check the released program periods, skills, directory and archived IDs through production."""
import json
import re
from urllib.parse import quote, urlsplit

from playwright.sync_api import expect, sync_playwright
from verify_m25_results_20261126 import capture, enter_results, is_view, out, receipt, site


cases = [
    ("ext-cmu-reuse", "Carnegie Mellon REUSE", "https://www.cmu.edu/scs/s3d/reuse/", "criteria", "2027-01-28", [], True),
    ("ext-umn-reu", "Computing for Social Good", "https://reu.cs.umn.edu/apply", "programming", None, ["Basic programming"], False),
    ("ext-usc-ict", "Institute for Creative Technologies REU", "https://ict.usc.edu/reu/", "january 27, 2027", "2027-01-27", [], True),
    ("ext-uiuc-ncsa-reu", "FoDOMMaT", "https://reu.ncsa.illinois.edu/", "python", "2027-02-15", ["Python", "machine learning"], True),
    ("ext-utexas-tacc", "TACC REU", "https://tacc.utexas.edu/education/undergraduates-graduates/reu/", "april 1, 2027", "2027-04-01", [], True),
    ("ext-umbc-bigdata", "UMBC Big Data REU", "https://bigdatareu.umbc.edu/2026-program-and-application/", "march 03, 2026", "2026-03-03", [], False),
    ("sro-1532726e", "FoDOMMaT", "https://researchops.web.illinois.edu/opportunity/future-discovery-training-students-build-and-apply-open-source-machine-learning-models", "3/15/27", "2027-03-15", [], True),
    ("uiuc-sro-database", "Summer Research Opportunities Database", "https://researchops.web.illinois.edu/", "how to use", None, [], False),
]


def make_student(page, student):
    school = "uiuc" if student == "uiuc" else "ucb"
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
    college = "College of Computing, Data Science, and Society" if school == "ucb" else "Grainger College of Engineering"
    for selector, value in (("#college", college), ("#major", "Computer Science")):
        field = page.locator(selector)
        if field.evaluate("e=>e.tagName") == "SELECT":
            field.select_option(label=value)
        else:
            field.fill(value)
    page.locator("#grade").select_option(label="Sophomore" if student == "ucb-sophomore" else "Junior")
    interests = "data science, undergraduate research, paid"
    page.locator("#research_interests").fill(interests)
    for label in ("Research", "Summer program", "Internship"):
        target = page.locator('fieldset[aria-describedby="seeking-types-help"]').get_by_role("button", name=label, exact=True)
        wanted = student != "ucb-sophomore" or label == "Summer program"
        if (target.get_attribute("aria-pressed") == "true") != wanted:
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




programs = {
    "sro-595e912d": ("2027-02-15", True, False),
    "sro-3c378261": ("2027-02-10", False, False),
    "wisc-86cba49b83d7": (None, None, True),
}
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page();page.on("response",capture)
    try:
        receipt["backend_release"]=page.request.get(site+"/api/health").json()["release_sha"]
        assert receipt["backend_release"]=="50d4aca1e4db82610e2c1483a4aa24b50f75b439"
        enter_results(page)
        query="Cellular and Molecular Biology of Stress"
        with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")==query,timeout=90000) as res:
            page.goto(site+"/results?tab=all&ai=0&q="+quote(query),wait_until="domcontentloaded")
        assert res.value.ok
        data=res.value.json()
        receipt["ids"]=[r["opportunity_id"] for r in data["results"]]
        assert set(receipt["ids"])==set(programs) and data["filtered_total"]==3
        for oid,(date,estimated,rolling) in programs.items():
            card=page.locator("#match-card-"+oid);expect(card).to_be_visible(timeout=90000)
            receipt[oid]={"card":card.inner_text()}
        page.screenshot(path=out/"wisconsin-three-cards.png")
        for oid,(day,estimated,rolling) in programs.items():
            d=page.request.get(site+"/api/opportunities/"+oid,params={"_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"}).json()
            assert d["id"]==oid and d["deadline"]==day and d["is_rolling"] is rolling
            if day: assert d["deadline_is_estimate"] is estimated
            page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
            expect(page.get_by_role("heading",level=1)).to_have_text(d["title"],timeout=90000)
            body=page.locator("main").inner_text()
            receipt[oid].update(title=d["title"],source=d["url"],program_url=d["application"].get("application_url"),deadline=day,estimated=d.get("deadline_is_estimate"),rolling=rolling,body=body)
            if estimated: assert "estimated" in body.lower()
            if rolling: assert "rolling" in body.lower()
            page.screenshot(path=out/(oid+"-detail.png"))
        for url in ["https://researchops.web.illinois.edu/opportunity/cellular-and-molecular-biology-stress-summer-research-program-0","https://wiscience.wisc.edu/IBS-SRP"]:
            src=ctx.new_page();resp=src.goto(url,wait_until="domcontentloaded");assert resp and resp.ok
            body=" ".join(src.locator("body").inner_text().lower().split())
            if url.endswith("-0"):
                assert "2/15/27" in body and "anticipated deadline" in body
            else:
                assert "apply by february 10, 2027" in body and "previously called cellular and molecular biology of stress" in body
            receipt[url]={"original":url,"landed":src.url,"title":src.title()};src.close()
    finally:
        (out/"wisconsin.json").write_text(json.dumps(receipt,indent=2)+"\n");print(json.dumps(receipt));browser.close()
