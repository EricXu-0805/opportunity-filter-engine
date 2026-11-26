"""Prepare normal production checks for the published calendar, grouping and later SRO refresh."""
from pathlib import Path
import subprocess,sys
p=Path('data/audits/verify_m23_manual_20261126.py')
sha,phase=sys.argv[1:]
assert len(sha)==40 and set(sha)<=set("0123456789abcdef")
assert phase in ('calendar','identity','refreshed')
base=subprocess.check_output(['git','show','7c059d9b7:'+str(p)],text=True)
s=base[:base.index('def check(')].replace('College of Computing, Data Science, and Society','College of Letters and Science').replace('"Computer Science"','"Integrative Biology"')
a=s.index('    interests = ');b=s.index('    page.locator("#research_interests")',a)
s=s[:a]+'    interests = "molecular biology, biosciences, undergraduate research, summer research, biology"\n'+s[b:]
s+='''host="wisc-86cba49b83d7"; primary="sro-595e912d"; alias="sro-3c378261"
phase="__PHASE__"
source_ids={host,primary,alias}
expected_by_source={"calendar":[source_ids,{host},{primary,alias}], "identity":[{host,alias},{host},{primary,alias}], "refreshed":[{host},{host},{primary}]}[phase]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page();page.on("response",capture)
    try:
        receipt["backend_release"]=page.request.get(site+"/api/health").json()["release_sha"]
        assert receipt["backend_release"]=="__DEPLOY__"
        assert 'data-release-sha="__DEPLOY__"' in ctx.request.get(site).text()
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
    finally:
        (out/"wisconsin-after.json").write_text(json.dumps(receipt,indent=2)+"\\n");print(json.dumps(receipt));browser.close()
'''
p.write_text(s.replace('__PHASE__',phase).replace('__DEPLOY__',sha))
