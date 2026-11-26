"""Prepare normal production checks for the published calendar, grouping and later SRO refresh."""
from pathlib import Path
import subprocess,sys
p=Path('data/audits/verify_m23_manual_20261126.py')
sha,phase=sys.argv[1:3]
student_terms = sys.argv[3:] == ['student-terms']
assert student_terms or len(sys.argv) == 3
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
if student_terms:
    s=s.replace('school = "uiuc" if student == "uiuc" else "ucb"', 'school = student')
    s=s.replace('college = "College of Letters and Science" if school == "ucb" else "Grainger College of Engineering"',
                'college = "College of Letters and Science" if school == "ucb" else "College of Letters & Science"')
    s=s.replace('("#major", "Integrative Biology")',
                '("#major", "Integrative Biology" if school == "ucb" else "Molecular and Cell Biology")')
    s=s.replace('label="Sophomore" if student == "ucb-sophomore" else "Junior"', 'label="Freshman"')
    marker = '        for oid in source_ids:'
    assert s.count(marker) == 1
    s=s.replace(marker, '''        receipt["confirmed_paid_for_students"] = {}
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
        for oid in source_ids:''')
    s=s.replace('            page.screenshot(path=out/(oid+"-published-window.png"))', '''            if phase != "refreshed" or oid != alias:
                assert d["paid"]=="yes" and not d.get("paid_attribution") and not d.get("compensation_attribution")
                visible = receipt[oid]["visible"]
                for claim in ("UW–Madison students may apply", "$7,000", "10 weeks", "funding"):
                    assert claim in visible
                assert "excluded by funding rules" not in visible and "Pay not confirmed" not in visible
            page.screenshot(path=out/(oid+"-published-window.png"))''')
p.write_text(s.replace('__PHASE__',phase).replace('__DEPLOY__',sha))
