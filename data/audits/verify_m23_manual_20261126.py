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
    college = "College of Letters and Science" if school == "ucb" else "Grainger College of Engineering"
    for selector, value in (("#college", college), ("#major", "Integrative Biology")):
        field = page.locator(selector)
        if field.evaluate("e=>e.tagName") == "SELECT":
            field.select_option(label=value)
        else:
            field.fill(value)
    page.locator("#grade").select_option(label="Sophomore" if student == "ucb-sophomore" else "Junior")
    interests = "molecular biology, biosciences, undergraduate research, summer research, biology"
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


host="wisc-86cba49b83d7"; primary="sro-595e912d"; alias="sro-3c378261"
phase="identity"
source_ids={host,primary,alias}
expected_by_source={"calendar":[source_ids,{host},{primary,alias}], "identity":[{host,alias},{host},{primary,alias}], "refreshed":[{host},{host},{primary}]}[phase]
def prepare_computing_profile(page):
    page.goto(site,wait_until="domcontentloaded")
    expect(page.locator("#student_name")).to_have_value("Sample Student",timeout=65000)
    school, student = "ucb", "ucb-sophomore"
    page.locator("#student_name").fill("Sample Student")
    college = "College of Computing, Data Science, and Society" if school == "ucb" else "Grainger College of Engineering"
    for selector, value in (("#college", college), ("#major", "Computer Science")):
        field = page.locator(selector)
        if field.evaluate("e=>e.tagName") == "SELECT":
            field.select_option(label=value)
        else:
            field.fill(value)
    page.locator("#grade").select_option(label="Sophomore" if student == "ucb-sophomore" else "Junior")
    interests = "database systems, computer science, summer research" if school == "uiuc" else "machine learning, artificial intelligence, healthcare"
    if student == "ucb-sophomore":
        interests = "machine learning, engineering, data science, undergraduate research, software engineering, creative technologies"
        for index, skill in enumerate(("Python", "machine learning", "C++", "Linux", "data science", "HPC", "software engineering")):
            box = page.get_by_placeholder("Add more…" if index else "Search or add a skill…", exact=True)
            box.fill(skill)
            box.press("Enter")
            chip = page.locator("span.min-w-0.break-all").filter(has_text=re.compile("^" + re.escape(skill) + "$", re.I))
            level = chip.locator("..").get_by_title("Click to change level (Beginner)", exact=True)
            level.click()
            expect(chip.locator("..").get_by_title("Click to change level (Experienced)", exact=True)).to_be_visible()
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




with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page();page.on("response",capture)
    try:
        receipt["backend_release"]=page.request.get(site+"/api/health").json()["release_sha"]
        assert receipt["backend_release"]=="daa5a43eb3b91974869c59dfb9a3c342b9082c6b"
        assert 'data-release-sha="daa5a43eb3b91974869c59dfb9a3c342b9082c6b"' in ctx.request.get(site).text()
        receipt["frontend_release"] = receipt["backend_release"]
        make_student(page,"ucb")
        q="Cellular and Molecular Biology of Stress"
        receipt["source_views"]={}
        for source,expected in zip(["","wisc_external_research","uiuc_sro"],expected_by_source):
            with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")==q and ((r.request.post_data_json or {}).get("view",{}).get("source") or "")==source,timeout=90000) as res:
                if not source:
                    page.goto(site+"/results?tab=all&ai=0&q="+quote(q),wait_until="domcontentloaded")
                else:
                    page.get_by_role("combobox",name="Source",exact=True).select_option(source)
            assert res.value.ok
            d=res.value.json();ids=[r["opportunity_id"] for r in d["results"]]
            receipt["source_views"][source or "all"]={"ids":ids,"total":d["filtered_total"],"url":page.url}
            assert set(ids)==expected and d["filtered_total"]==len(expected) and not d["has_more"]
            for oid in expected:expect(page.locator("#match-card-"+oid)).to_be_visible(timeout=90000)
            page.screenshot(path=out/("wisconsin-"+(source or "all")+".png"))
        for oid in source_ids:
            d=page.request.get(site+"/api/opportunities/"+oid,params={"_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"}).json()
            assert d["id"]==oid and d["deadline"]=="2027-02-10" and not d["deadline_is_estimate"] and not d["is_rolling"]
            assert d["application_opens"]["on"]=="2026-11-01" and d["application_opens"]["source_url"]=="https://wiscience.wisc.edu/research/summer_research_program/"
            assert d["target_truth"]["actionable"] is (phase!="refreshed" or oid!=alias)
            page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
            expect(page.get_by_role("heading",level=1)).to_have_text(d["title"],timeout=90000)
            receipt[oid]={"title":d["title"],"source":d["url"],"deadline":d["deadline"],"truth":d["target_truth"],"opening":d["application_opens"],"visible":page.locator("main").inner_text()}
            page.screenshot(path=out/(oid+"-published-window.png"))
        # Reopen the same authenticated guest's saved campus profile and apply
        # the computing interests used for the first published FoDOMMaT check.
        prepare_computing_profile(page)
        host, directory = "ext-uiuc-ncsa-reu", "sro-1532726e"
        for oid,url in [(host,"https://reu.ncsa.illinois.edu/"),(directory,"https://researchops.web.illinois.edu/opportunity/future-discovery-training-students-build-and-apply-open-source-machine-learning-models")]:
            official=ctx.new_page(); response=official.goto(url,wait_until="domcontentloaded"); assert response and response.ok
            official_text=" ".join(official.locator("body").inner_text().lower().split())
            if oid==host:
                assert "experience with python is required" in official_text and "february 15" in official_text
            else:
                assert "3/15/27" in official_text
                assert any("reu.ncsa.illinois.edu" in (l.get_attribute("href") or "") for l in official.locator("a[href]").all())
            official.close()
            response=page.request.get(site+"/api/opportunities/"+oid,params={"_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
            assert response.ok
            detail=response.json(); assert (detail["id"],detail["url"],detail["deadline"])==(oid,url,"2027-02-15")
            assert detail["deadline_is_estimate"] is False and detail["application_opens"]["on"]=="2026-12-15"
            assert "experience with Python is required" in str(detail["detail_fields"])
            page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
            expect(page.get_by_role("heading",level=1)).to_have_text(detail["title"],timeout=90000)
            main=page.locator("main")
            assert "2027-02-15" in main.inner_text() and "2027-03-15" not in main.inner_text()
            receipt[oid]={"original_url":url,"title":detail["title"],"deadline":detail["deadline"],"application_opens":detail["application_opens"],"skills":detail["eligibility"]["skills_required"]}
            page.screenshot(path=out/(oid+"-corrected-detail.png"))
        def request_for(source):
            return lambda r: is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")=="FoDOMMaT" and ((r.request.post_data_json or {}).get("view",{}).get("source") or "")==source
        for source,expect_oid in [("",host),("uiuc_sro",directory),("manual",host),("",host)]:
            with page.expect_response(request_for(source),timeout=90000) as res:
                if not receipt.get("combined"):
                    page.goto(site+"/results?tab=all&ai=0&q=FoDOMMaT",wait_until="domcontentloaded")
                else:
                    page.get_by_role("combobox",name="Source",exact=True).select_option(source)
            assert res.value.ok
            data=res.value.json(); ids=[r["opportunity_id"] for r in data["results"]]
            assert ids==[expect_oid] and data["filtered_total"]==data["view_counts"]["all"]==1 and not data["has_more"]
            expect(page.locator("#match-card-"+expect_oid)).to_be_visible(timeout=90000)
            expect(page.locator("#match-card-"+(host if expect_oid==directory else directory))).to_have_count(0)
            receipt[source or "combined"]={"ids":ids,"count":data["filtered_total"],"view":data["view_counts"],"url":page.url}
            page.screenshot(path=out/((source or "combined")+"-result.png"))
    finally:
        (out/"wisconsin-after.json").write_text(json.dumps(receipt,indent=2)+"\n");print(json.dumps(receipt));browser.close()
