"""Compare two sampled dates with real public results, their original details and university sites."""
import json, re
from urllib.parse import quote
from verify_berkeley_coverage_card import BerkeleyCoverageCard
from playwright.sync_api import expect,sync_playwright
from verify_m25_results_20261126 import capture,enter_results,is_view,out,receipt,site
etap="https://etap.nsf.gov/award/8314/opportunity/12305"
cases=[
    ("sro-44f176cd","Advancing Data Science in the Public Interest",["https://researchops.web.illinois.edu/opportunity/reu-advancing-data-science-public-interest",etap]),
    ("sro-3ec4ea4e","Cancer Research Internship Summer Program",["https://researchops.web.illinois.edu/opportunity/cancer-research-internship-summer-program-crisp",'https://cancer.iu.edu/education/summer/acs-cancer-research-internship.html']),
    ("nsf-reu-2447670","Advancing Data Science in the Public Interest",["https://www.nsf.gov/awardsearch/showAward?AWD_ID=2447670",'https://www.smu.edu/provost/saes/academic-enrichment/engaged-learning/research/research-experiences-undergraduates/data-science-reu']),
]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page();page.on("response",capture)
    try:
        receipt["backend_release"]=page.request.get(site+"/api/health").json()["release_sha"]
        assert receipt["backend_release"]=='91140c465b5cd546e129c04f5097064b91fddb57'
        assert 'data-release-sha="91140c465b5cd546e129c04f5097064b91fddb57"' in ctx.request.get(site).text()
        receipt["frontend_release"] = receipt["backend_release"]
        coverage = BerkeleyCoverageCard(page, receipt, out)
        enter_results(page, before_select=coverage.verify)
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
                assert ids==(["sro-3ec4ea4e"] if crisp else ["nsf-reu-2447670"])
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
        assert not errors,errors
    finally:
        (out/"two-verified-host-windows.json").write_text(json.dumps(receipt,indent=2)+"\n"); print(json.dumps(receipt)); browser.close()
