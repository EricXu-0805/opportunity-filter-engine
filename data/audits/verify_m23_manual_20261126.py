"""Compare two sampled dates with real public results, their original details and university sites."""
import json, re
from urllib.parse import quote
from playwright.sync_api import expect,sync_playwright
from verify_m25_results_20261126 import capture,enter_results,is_view,out,receipt,site
cases=[
    ("sro-3ec4ea4e","Cancer Research Internship Summer Program",["https://researchops.web.illinois.edu/opportunity/cancer-research-internship-summer-program-crisp",'https://cancer.iu.edu/education/summer/acs-cancer-research-internship.html']),
    ("nsf-reu-2447670","Advancing Data Science in the Public Interest",["https://www.nsf.gov/awardsearch/showAward?AWD_ID=2447670",'https://www.smu.edu/provost/saes/academic-enrichment/engaged-learning/research/research-experiences-undergraduates']),
]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page();page.on("response",capture)
    try:
        receipt["backend_release"]=page.request.get(site+"/api/health").json()["release_sha"]
        assert receipt["backend_release"]=='743e6fa6e6b8d56c39e5c2eb29a92a4fcdc16d7f'
        enter_results(page)
        errors={}
        for oid,q,sources in cases:
            result=receipt[oid]={}
            try:
                for url in sources:
                    tab=ctx.new_page()
                    try:
                        response=tab.goto(url,wait_until="domcontentloaded",timeout=45000)
                        result[url]={"http":response.status if response else None,"landed":tab.url,"title":tab.title()}
                        body=tab.locator("body").inner_text(timeout=30000)
                        result[url]["date_lines"]=[x.strip()[:600] for x in body.splitlines() if re.search(r"deadline|applications? |apply by|anticipated|202[5678]|internship|SMU|sophomore",x,re.I)][:65]
                    except Exception as exc:
                        result[url]={"source_visit":str(exc)[:300]}
                    finally:tab.close()
                response=page.request.get(site+"/api/opportunities/"+oid,params={"_release_scope":"mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
                assert response.ok,(oid,response.status)
                d=response.json()
                result["detail"]={k:d.get(k) for k in ("id","title","url","deadline","deadline_is_estimate","is_rolling","target_truth","application_opens")}
                assert d["id"]==oid
                page.goto(site+"/opportunities/"+oid,wait_until="domcontentloaded")
                expect(page.get_by_role("heading",level=1)).to_have_text(d["title"],timeout=90000)
                body=page.locator("main").inner_text()
                result["detail_text"]=[x for x in body.splitlines() if re.search(r"deadline|estimated|unknown|202[5678]|rolling|application|closed",x,re.I)]
                page.screenshot(path=out/(oid+"-date-detail.png"))
                with page.expect_response(lambda r:is_view(r) and (r.request.post_data_json or {}).get("view",{}).get("search_query")==q,timeout=90000) as res:
                    page.goto(site+"/results?tab=all&ai=0&q="+quote(q),wait_until="domcontentloaded")
                assert res.value.ok
                data=res.value.json();ids=[r["opportunity_id"] for r in data["results"]]
                assert not data["has_more"]
                result["search"]={"ids":ids,"total":data["filtered_total"],"present":oid in ids}
                if oid in ids:
                    card=page.locator("#match-card-"+oid);expect(card).to_be_visible(timeout=90000)
                    result["card"]=card.inner_text();card.screenshot(path=out/(oid+"-date-card.png"))
                else:
                    expect(page.get_by_role("tablist")).to_be_visible(timeout=90000)
                    expect(page.locator("#match-card-"+oid)).to_have_count(0)
            except Exception as exc:errors[oid]=str(exc)[:800]
        assert not errors,errors
    finally:
        (out/"two-sampled-dates.json").write_text(json.dumps(receipt,indent=2)+"\n"); print(json.dumps(receipt)); browser.close()
