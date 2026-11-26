"""Produce the post-deployment check for the same real visitor and sources as the baseline."""
from pathlib import Path
import subprocess,sys
sha=sys.argv[1]
assert len(sha)==40 and set(sha)<=set("0123456789abcdef")
p=Path("data/audits/verify_m23_manual_20261126.py")
base=subprocess.check_output(["git","show","7c059d9b7:"+str(p)],text=True)
s=base[:base.index("def check(")]
s += '''
host="ext-uiuc-ncsa-reu"; directory="sro-1532726e"
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page(); page.on("response",capture)
    try:
        health=page.request.get(site+"/api/health").json()
        assert health["release_sha"]=="__DEPLOY__"
        receipt["backend_release"]=health["release_sha"]
        assert 'data-release-sha="__DEPLOY__"' in ctx.request.get(site).text()
        receipt["frontend_release"] = health["release_sha"]
        make_student(page,"ucb-sophomore")
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
        (out/"paired-program.json").write_text(json.dumps(receipt,indent=2)+"\\n")
        print(json.dumps(receipt));browser.close()
'''
p.write_text(s.replace("__DEPLOY__",sha))
