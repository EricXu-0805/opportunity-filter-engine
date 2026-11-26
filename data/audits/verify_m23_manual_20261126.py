"""Follow the two historical UCSD links and the current Cal-Bridge application in production."""
import json
from pathlib import Path
import re
from playwright.sync_api import expect, sync_playwright

site = "https://joinalab.com"
version = "c1b0c3c21b3c806bbf9b7b6ff95ece078f98d541"
scope = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
cases = [('ucsd-d93b49abd299', 'https://ugresearch.ucsd.edu/programs/urh-summer/index.html', ('Each program has a cohort and a coordinator', 'McNair Program', 'Look through the programs')), ('ucsd-c6d547c9321a', 'https://ucsd-research.academicworks.com/opportunities/2368', ('11/20/2026', 'undergraduate students in all majors', 'October 29, 2026')), ('ucsb-45d0bef1a207', 'https://calbridge.org/undergraduate-program/', ('must be attending a California State University', 'in April', 'Graduate students are not eligible'))]
out = Path("evidence")
out.mkdir(exist_ok=True)
receipt = {"release":version,"results_and_profile_run":"45892876598","records":{}}
errors = {}
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
    context = browser.new_context(locale="en-US",service_workers="block")
    context.add_init_script("if(location.hostname==='joinalab.com')localStorage.setItem('ofe_lang','en')")
    page = context.new_page()
    try:
        assert context.request.get(site+"/api/health").json()["release_sha"]==version
        assert f'data-release-sha="{version}"' in context.request.get(site).text()
        for oid,host,qualifiers in cases:
            record=receipt["records"][oid]={}
            try:
                result=context.request.get(site+"/api/opportunities/"+oid,params={"_release_scope":scope})
                assert result.ok
                data=result.json()
                assert data["id"]==oid and data["is_rolling"] is False
                opening=page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
                assert opening and opening.ok
                expect(page.get_by_role("heading",level=1)).to_have_text(data["title"],timeout=60000)
                application=(data.get("application") or {}).get("application_url")
                truth=data["target_truth"]
                record.update({"title":data["title"],"status":opening.status,"deadline":data["deadline"],
                               "truth":truth,"application":application})
                current=oid=="ucsb-45d0bef1a207"
                button=page.get_by_role("link",name=re.compile("^Apply now$") if current else "View source",exact=True).first
                expect(button).to_be_visible(timeout=45000)
                expect(button).to_have_attribute("href",host)
                if oid==cases[0][0]:
                    tour=page.get_by_test_id("onboarding-skip")
                    expect(tour).to_be_visible(timeout=15000)
                    tour.click()
                    expect(page.get_by_test_id("onboarding-intro")).not_to_be_visible()
                body=page.locator("main").inner_text()
                if current:
                    assert application==host and truth["actionable"] and data["deadline"] is None
                    assert "community college students transferring" in body.lower() and "Santa Barbara" not in data["location"]
                else:
                    assert not truth["actionable"] and not application
                    assert page.get_by_role("link",name=re.compile("^Apply",re.I)).count()==0
                    if oid=="ucsd-c6d547c9321a":
                        assert data["deadline"]=="2026-11-20" and truth["listing_state"]=="closed"
                        assert "no longer accepting applications" in body.lower()
                    else:
                        assert truth["reference_only"] and data["eligibility"]["international_friendly"]=="unknown"
                record["detail_text"]=body
                record["button"]=button.inner_text()
                page.screenshot(path=out/(oid+"-detail.png"))
                with page.expect_popup(timeout=45000) as pop:
                    button.click()
                origin=pop.value
                origin.wait_for_load_state("domcontentloaded",timeout=60000)
                text=" ".join((origin.locator("body").text_content() or "").lower().split())
                missing=[term for term in qualifiers if term.casefold() not in text]
                record.update({"host_url":origin.url,"host_terms_found":[term for term in qualifiers if term not in missing],"missing":missing})
                assert not missing,missing
                origin.screenshot(path=out/(oid+"-host.png"));origin.close()
            except Exception as exc:
                errors[oid]=str(exc)[:550] or type(exc).__name__
        profile={"name":"Sample Student","home_school":"ucsd","school":"UC San Diego","year":"junior",
                 "major":"Biology","international_student":False,"gpa":3.7,
                 "research_interests_text":"undergraduate research opportunities, biology, mentoring",
                 "seeking_type":["research","summer_program"],"preferences":{"min_match_threshold":0}}
        hidden={cases[0][0],cases[1][0]}
        queries=receipt["historical_rank_and_saved_reads"]={}
        for key, query, tab in (("current","McNair","all"),("starred","McNair","starred"),
                                ("directory","UC San Diego Summer Research Programs","all")):
            post={"profile":profile,"view":{"tab":tab,"today":"2026-11-26","search_query":query},"page_size":50}
            if tab=="starred":post["view"]["favorite_ids"]=sorted(hidden)
            resp=context.request.post(site+"/api/matches/view?llm=false",data=post,timeout=90000)
            assert resp.ok
            listing=resp.json();ids=[r["opportunity_id"] for r in listing["results"]]
            assert not set(ids)&hidden and not listing["has_more"]
            queries[key]={"ids":ids,"count":listing["filtered_total"]}
        assert not errors,errors
    finally:
        receipt["errors"]=errors
        (out/"california-original-links.json").write_text(json.dumps(receipt,indent=2)+"\n")
        print("Checked",[(k,v.get("button"),v.get("missing")) for k,v in receipt["records"].items()],"errors",errors)
        browser.close()
