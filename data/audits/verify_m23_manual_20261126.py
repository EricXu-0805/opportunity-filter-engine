"""Read both scopes of the published B19 university-program release in isolated guest sessions."""
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys

if len(sys.argv)==1:
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs=list(pool.map(lambda task: subprocess.run([sys.executable,__file__,task],check=False).returncode,
                           ["wisconsin","academic"]))
    raise SystemExit(max(runs))

if sys.argv[1]=="wisconsin":
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
        school = student
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
        college = "College of Letters and Science" if school == "ucb" else "College of Letters & Science"
        for selector, value in (("#college", college), ("#major", "Integrative Biology" if school == "ucb" else "Molecular and Cell Biology")):
            field = page.locator(selector)
            if field.evaluate("e=>e.tagName") == "SELECT":
                field.select_option(label=value)
            else:
                field.fill(value)
        page.locator("#grade").select_option(label="Freshman")
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
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
        ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
        page=ctx.new_page();page.on("response",capture)
        try:
            receipt["backend_release"]=page.request.get(site+"/api/health").json()["release_sha"]
            assert receipt["backend_release"]=="b129ed3336f1203ae6097a50af9e7e4f8950ac40"
            assert 'data-release-sha="b129ed3336f1203ae6097a50af9e7e4f8950ac40"' in ctx.request.get(site).text()
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
            receipt["confirmed_paid_for_students"] = {}
            for campus in ("ucb", "wisc"):
                if campus == "wisc":
                    make_student(page, campus)
                def requested(response):
                    if not is_view(response):
                        return False
                    post = response.request.post_data_json or {}
                    view, profile = post.get("view", {}), post.get("profile", {})
                    return (view.get("paid") == "yes" and view.get("search_query") == q
                            and profile.get("home_school") == campus and profile.get("year", "").lower() == "freshman")
                with page.expect_response(requested, timeout=90000) as res:
                    page.goto(site + "/results?tab=all&ai=0&paid=yes&q=" + quote(q), wait_until="domcontentloaded")
                d=res.value.json()
                ids=[r["opportunity_id"] for r in d["results"]]
                assert res.value.ok and set(ids)==expected_by_source[0] and len(ids)==d["filtered_total"]
                expect(page.get_by_role("combobox",name="Pay",exact=True)).to_have_value("yes")
                card=page.locator("#match-card-"+host);expect(card).to_be_visible(timeout=60000)
                text=card.inner_text(); assert "$7,000" in text and "Pay not confirmed" not in text
                receipt["confirmed_paid_for_students"][campus]={"ids":ids,"count":d["filtered_total"],"host_card":text}
                card.screenshot(path=out/("confirmed-paid-"+campus+".png"))
            for oid in source_ids:
                d=page.request.get(site+"/api/opportunities/"+oid,params={"_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"}).json()
                assert d["id"]==oid and d["deadline"]=="2027-02-10" and not d["deadline_is_estimate"] and not d["is_rolling"]
                assert d["application_opens"]["on"]=="2026-11-01" and d["application_opens"]["source_url"]=="https://wiscience.wisc.edu/research/summer_research_program/"
                assert d["target_truth"]["actionable"] is (phase!="refreshed" or oid!=alias)
                page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
                expect(page.get_by_role("heading",level=1)).to_have_text(d["title"],timeout=90000)
                receipt[oid]={"title":d["title"],"source":d["url"],"deadline":d["deadline"],"truth":d["target_truth"],"opening":d["application_opens"],"visible":page.locator("main").inner_text()}
                if phase != "refreshed" or oid != alias:
                    assert d["paid"]=="yes" and not d.get("paid_attribution") and not d.get("compensation_attribution")
                    visible = receipt[oid]["visible"]
                    for claim in ("UW–Madison students may apply", "$7,000", "10 weeks", "funding"):
                        assert claim in visible
                    assert "excluded by funding rules" not in visible and "Pay not confirmed" not in visible
                original=d.get("description_raw") or ""
                if oid in {primary, alias}:
                    assert original.strip() and " ".join(original.split()) in " ".join(receipt[oid]["visible"].split())
                receipt[oid]["historic_source_text_retained"]=bool(original)
                page.screenshot(path=out/(oid+"-published-window.png"))
        finally:
            (out/"wisconsin-after.json").write_text(json.dumps(receipt,indent=2)+"\n");print(json.dumps(receipt));browser.close()

else:
    """Compare two sampled dates with real public results, their original details and university sites."""
    import json, re
    from urllib.parse import quote,urlsplit
    from verify_berkeley_coverage_card import BerkeleyCoverageCard
    from playwright.sync_api import expect,sync_playwright
    from verify_m25_results_20261126 import capture,enter_results,is_view,out,receipt,site
    etap="https://etap.nsf.gov/award/8314/opportunity/12305"
    cases=[
        ("sro-44f176cd","Advancing Data Science in the Public Interest",["https://researchops.web.illinois.edu/opportunity/reu-advancing-data-science-public-interest",etap]),
        ("sro-3ec4ea4e","Cancer Research Internship Summer Program",["https://researchops.web.illinois.edu/opportunity/cancer-research-internship-summer-program-crisp",'https://cancer.iu.edu/education/summer/acs-cancer-research-internship.html']),
        ("nsf-reu-2447670","Advancing Data Science in the Public Interest",["https://www.nsf.gov/awardsearch/showAward?AWD_ID=2447670",'https://www.smu.edu/provost/saes/academic-enrichment/engaged-learning/research/research-experiences-undergraduates/data-science-reu']),
    ]
    def set_academic_route(page, major, college, year, interests):
        school="ucb"
        receipt["profile_commit"] = None
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
        for selector, value in (("#college", college), ("#major", major)):
            field = page.locator(selector)
            if field.evaluate("e=>e.tagName") == "SELECT":
                field.select_option(label=value)
            else:
                field.fill(value)
        page.locator("#grade").select_option(label=year)
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
        browser=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
        ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
        page=ctx.new_page();page.on("response",capture)
        try:
            receipt["backend_release"]=page.request.get(site+"/api/health").json()["release_sha"]
            assert receipt["backend_release"]=='b129ed3336f1203ae6097a50af9e7e4f8950ac40'
            assert 'data-release-sha="b129ed3336f1203ae6097a50af9e7e4f8950ac40"' in ctx.request.get(site).text()
            receipt["frontend_release"] = receipt["backend_release"]
            enter_results(page)
            errors={}
            for oid,q,sources in cases:
                result=receipt[oid]={}
                try:
                    for url in sources:
                        tab=ctx.new_page()
                        try:
                            response=tab.goto(url,wait_until="domcontentloaded",timeout=45000)
                            if url==etap:
                                tab.get_by_text("Application Window",exact=True).wait_for(timeout=45000)
                                expect(tab.get_by_text("2447670",exact=True)).to_be_visible()
                                body=tab.locator("body").inner_text()
                                assert "02/22/2027" in body and "11:59 PM ET" in body
                                tab.screenshot(path=out/"smu-etap-2027.png",full_page=True)
                            result[url]={"http":response.status if response else None,"landed":tab.url,"title":tab.title()}
                            body=tab.locator("body").inner_text(timeout=30000)
                            if "acs-cancer-research-internship.html" in url:
                                assert response.ok and "Jan. 31, 2027" in body and "3.2" in body
                            if "data-science-reu" in url:
                                assert response.ok and "$5600 stipend" in body and "U.S. citizen or permanent resident" in body
                                assert "social science" in body.lower() and "2447670" in body
                            result[url]["date_lines"]=[x.strip()[:600] for x in body.splitlines() if re.search(r"deadline|applications? |apply by|anticipated|11:59 PM ET|2447670|202[5678]|internship|SMU|sophomore",x,re.I)][:65]
                        except Exception as exc:
                            result[url]={"source_visit":str(exc)[:300]}
                            if url == etap or "data-science-reu" in url or "acs-cancer-research-internship.html" in url:
                                errors[url] = str(exc)[:500]
                        finally:tab.close()
                    response=page.request.get(site+"/api/opportunities/"+oid,params={"_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
                    assert response.ok,(oid,response.status)
                    d=response.json()
                    result["detail"]={k:d.get(k) for k in ("id","title","url","deadline","deadline_is_estimate","is_rolling","target_truth","application_opens")}
                    assert d["id"]==oid
                    crisp = oid == "sro-3ec4ea4e"
                    expected = "2027-01-31" if crisp else "2027-02-22"
                    opens = "2026-11-15" if crisp else "2026-11-19"
                    page_url = "https://cancer.iu.edu/education/summer/acs-cancer-research-internship.html" if crisp else etap
                    assert (d["deadline"],d["deadline_is_estimate"],d["is_rolling"])==(expected,False,False)
                    assert d["application_opens"]["on"]==opens and d["application_opens"]["source_url"]==page_url
                    fields=d["detail_fields"]["fields"]
                    assert fields["timing"]["quotes"]["deadline"]["source_url"]==page_url
                    if crisp:
                        assert d["eligibility"]["min_gpa"]==3.2 and d["paid"]=="yes"
                        assert d["location"]=="Indianapolis, IN" and d["remote_option"]=="no"
                    else:
                        assert d["eligibility"]["skills_required"]==[] and d["eligibility"]["preferred_year"]==["sophomore","junior"]
                        assert fields["eligibility"]["explicit"]["work_authorization_notes"]=="U.S. citizen or permanent resident"
                        assert d["compensation_details"]=="$5,600 stipend" and d["duration"]=="8 weeks"
                        if oid.startswith("nsf-reu-"):
                            assert not d.get("start_date") and d["application"]["application_url"]==etap
                    result["terms"]={"stipend":d["compensation_details"],"paid":d["paid"],"eligibility":d["eligibility"],"duration":d["duration"],"application":d["application"]}
                    page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
                    expect(page.get_by_role("heading",level=1)).to_have_text(d["title"],timeout=90000)
                    body=page.locator("main").inner_text()
                    result["detail_text"]=[x for x in body.splitlines() if re.search(r"deadline|estimated|unknown|202[5678]|rolling|application|closed",x,re.I)]
                    e = fields["eligibility"]
                    majors = (["Biomedical science","Behavioral science"] if crisp else
                              ["Mathematics","Statistics","Computer Science","Social science"])
                    assert d["eligibility"]["majors"] == e["explicit"]["majors"] == majors
                    assert "majors_attribution" not in d
                    assert e["quotes"]["majors"]["source_url"].startswith(
                        "https://cancer.iu.edu/" if crisp else "https://www.smu.edu/")
                    phrase = "incoming first-year students" if crisp else "two academic routes"
                    assert phrase in body and all(major in body for major in majors)
                    result["academic_routes"] = {"majors":majors, "source":e["quotes"]["majors"]["source_url"],
                                                 "student_summary":d["description_clean"].split("\n", 1)[0]}
                    original=d.get("description_raw") or ""
                    if original.strip():
                        assert " ".join(original.split()) in " ".join(body.split())
                    result["original_text_retained"]=bool(original)
                    assert expected in body
                    if crisp:
                        assert "Indianapolis, IN" in body and "Bloomington, IN" not in body
                    else:
                        assert "U.S. citizen or permanent resident" in body
                        assert "$5,600" in body and "$4,800" not in body and "$6,000-$7,000" not in body
                    page.screenshot(path=out/(oid+"-date-detail.png"))
                    with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")==q,timeout=90000) as res:
                        page.goto(site+"/results?tab=all&ai=0&q="+quote(q),wait_until="domcontentloaded")
                    assert res.value.ok
                    data=res.value.json();ids=[r["opportunity_id"] for r in data["results"]]
                    assert not data["has_more"]
                    result["search"]={"ids":ids,"total":data["filtered_total"],"present":oid in ids}
                    matched_profile=(res.value.request.post_data_json or {})["profile"]
                    assert matched_profile["major"]=="Computer Science" and matched_profile["year"].casefold()=="junior"
                    # Computer science is one SMU route. Indiana instead specifies
                    # biomedical or behavioral science. A psychology freshman is checked below.
                    result["search"]["major"]=matched_profile["major"]
                    result["search"]["year"]=matched_profile["year"]
                    assert ids==([] if crisp else ["nsf-reu-2447670"]), (oid,matched_profile["major"],ids)
                    assert data["filtered_total"]==len(ids)
                    if oid in ids:
                        card=page.locator("#match-card-"+oid);expect(card).to_be_visible(timeout=90000)
                        result["card"]=card.inner_text();card.screenshot(path=out/(oid+"-date-card.png"))
                    else:
                        expect(page.get_by_role("tablist")).to_be_visible(timeout=90000)
                        expect(page.locator("#match-card-"+oid)).to_have_count(0)
                    if oid=="sro-44f176cd":
                        for key, want in [("uiuc_sro","sro-44f176cd"),("nsf_reu","nsf-reu-2447670"),("","nsf-reu-2447670")]:
                            with page.expect_response(lambda r:is_view(r) and ((r.request.post_data_json or {}).get("view",{}).get("source") or "")==key, timeout=60000) as src:
                                page.get_by_role("combobox",name="Source",exact=True).select_option(key)
                            info=src.value.json()
                            assert src.value.ok and [r["opportunity_id"] for r in info["results"]]==[want]
                            assert info["filtered_total"]==1 and not info["has_more"]
                            current=page.locator("#match-card-"+want);expect(current).to_be_visible(timeout=60000)
                            ct=current.inner_text();assert "$5,600" in ct and "2027-02-22" in ct
                            result["source_"+(key or "combined")]={"id":want,"count":1,"card":ct};current.screenshot(path=out/("smu-"+(key or "combined")+".png"))
                except Exception as exc:errors[oid]=str(exc)[:800]
            receipt["student_academic_queries"] = {}
            for route,major,college,year,interests,q,oid in [
                ("quantitative","Statistics","College of Computing, Data Science, and Society","Junior","statistics, social research and data science","Advancing Data Science in the Public Interest","nsf-reu-2447670"),
                ("social_science","Sociology","College of Letters and Science","Sophomore","data science, sociology, cities and policy","Advancing Data Science in the Public Interest","nsf-reu-2447670"),
                ("behavioral_science","Psychology","College of Letters and Science","Freshman","cancer research, behavioral science and health psychology","Cancer Research Internship Summer Program","sro-3ec4ea4e"),
            ]:
                try:
                    set_academic_route(page, major, college, year, interests)
                    with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")==q,timeout=90000) as lookup:
                        page.goto(site+"/results?tab=all&ai=0&q="+quote(q),wait_until="domcontentloaded")
                    data=lookup.value.json()
                    chosen=(lookup.value.request.post_data_json or {})["profile"]
                    assert chosen["major"]==major and chosen["year"].casefold()==year.casefold()
                    ids=[row["opportunity_id"] for row in data["results"]]
                    receipt["student_academic_queries"][route]={"major":major,"year":year,"request_status":lookup.value.status,"profile_commit":receipt["profile_commit"],"ids":ids,"total":data["filtered_total"]}
                    assert lookup.value.ok and ids==[oid] and data["filtered_total"]==1, (major,ids)
                    expect(page.locator("#match-card-"+oid)).to_be_visible(timeout=60000)
                    page.screenshot(path=out/("academic-profile-"+route+".png"))
                except Exception as exc:
                    errors[route]=str(exc)[:800] or type(exc).__name__
            receipt["errors"]=errors
            assert not errors,errors
        finally:
            (out/"two-verified-host-windows.json").write_text(json.dumps(receipt,indent=2)+"\n"); print(json.dumps(receipt)); browser.close()
