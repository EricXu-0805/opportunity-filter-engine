"""Read the free English manual draft's target-conditioned final check using one synthetic guest."""
import datetime
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright
import verify_public_matching_experience as shared

FACULTY="faculty-caltech-phys-b6dd07e7"
LISTING="sro-629b15b1"
SUBJECT="Synthetic research inquiry"
A="I am writing about your advertised position."
B="I am writing about the position you posted."
Q="Is there an open position in your lab?"
SELF="I previously held a position as a peer tutor."
CASES={FACULTY:[("advertised",SUBJECT,A),("posted_subject","The position you posted",SELF),
                 ("inquiry",SUBJECT,Q),("own_position",SUBJECT,SELF)],
       LISTING:[("advertised_listing",SUBJECT,A),("posted_listing",SUBJECT,B)]}
report={"started_at":None,"reads":[],"paid_requests":0,"mail_composers":0,"deliveries":0}
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def release(probe):
    backend=probe.get(shared.site+"/api/health",timeout=40000).json()["release_sha"]
    front=re.search(r'data-release-sha="([a-f0-9]{40})"',probe.get(shared.site+"/about",timeout=40000).text()).group(1)
    assert backend==front
    return {"frontend":front,"backend":backend,"utc":now()}
def main():
    local=os.environ.get("M30_LOCAL_SITE")
    if local:
        assert local=="http://127.0.0.1:3000"
        shared.site=local
        shared.db="127.0.0.1"
        report["stage"]="isolated source frontend, backend, account and saved profile"
    report["started_at"]=now()
    with sync_playwright() as pw:
        probe=pw.request.new_context();report["release_start"]=release(probe)
        if local:assert report["release_start"]["backend"]==os.environ["M30_EXPECTED_SHA"]
        browser=pw.chromium.launch(channel="chrome",args=["--no-sandbox"])
        ctx=browser.new_context(locale="en-US",service_workers="block") if local else shared.cold(browser)
        if local:ctx.on("response",shared.record)
        ctx.grant_permissions(["clipboard-read","clipboard-write"],origin=shared.site)
        seen=set()
        def protect(route):
            req=route.request;p=urlsplit(req.url)
            if local:
                if p.hostname!="127.0.0.1" or p.port not in (3000,54321):
                    report["mail_composers"]+=int(req.is_navigation_request())
                    return route.abort()
                if req.method in ("GET","HEAD","OPTIONS"):return route.continue_()
                if p.port==54321 and req.method=="POST":
                    val=req.post_data_json or {}
                    if p.path=="/auth/v1/signup" and not shared.auth and not val.get("email"):return route.continue_()
                    if p.path=="/auth/v1/token":return route.continue_()
                    if p.path=="/rest/v1/rpc/commit_profile_patch_cas" and shared.auth and val.get("p_expected_device_id")==shared.auth[0]["user"]["id"]:return route.continue_()
                    return route.abort()
            if (p.hostname=="joinalab.com" or (local and p.port==3000)) and req.method=="POST":
                if p.path in ("/api/cold-email/variants","/api/cold-email/validate"):
                    data=req.post_data_json;assert data["opportunity_id"] in CASES
                    if p.path.endswith("variants"):assert data.get("engine","template")=="template"
                    return route.continue_()
                if p.path!="/api/matches/view":
                    report["paid_requests"]+=int(any(x in p.path for x in ("refine","tailor","billing","generate")))
                    return route.abort()
            if local:
                if req.method=="POST" and p.path=="/api/matches/view" and "llm=false" in p.query:return route.continue_()
                return route.abort()
            if p.hostname not in ("joinalab.com",shared.db):
                report["mail_composers"]+=int(req.is_navigation_request())
                return route.abort()
            return shared.guard(route)
        ctx.route("**/*",protect)
        if local:
            home=ctx.new_page();home.goto(local,wait_until="domcontentloaded")
            tour=home.get_by_test_id("onboarding-intro");tour.wait_for(timeout=60000)
            tour.get_by_test_id("onboarding-skip").click();tour.get_by_test_id("onboarding-school-uiuc").click()
            tour.get_by_test_id("onboarding-primary").click();tour.wait_for(state="hidden")
            home.locator("#student_name").wait_for(timeout=45000)
            home.get_by_test_id("hydration-note").wait_for(state="hidden",timeout=45000)
            home.get_by_test_id("profile-refresh-status").wait_for(state="hidden",timeout=45000)
        else:
            home=shared.home(ctx)
        home.locator("#student_name").fill(shared.student)
        home.locator("#college").select_option(label="Liberal Arts & Sciences (LAS)")
        home.locator("#major").select_option(label="Integrative Biology");home.locator("#grade").select_option(label="Sophomore")
        ed=home.get_by_test_id("resume-master-editor");ed.locator(":scope > summary").click()
        ed.get_by_label("Full name",exact=True).fill("Rowan Fictional Observer")
        ed.get_by_role("button",name="Confirm Full name",exact=True).click()
        with home.expect_response(lambda r:urlsplit(r.url).path=="/rest/v1/rpc/commit_profile_patch_cas" and r.ok,timeout=60000):
            ed.get_by_role("button",name="Apply changes").click()
        assert shared.auth and shared.auth[0]["user"]["is_anonymous"]
        report["purpose_created_guest_profile_saved"]=True;report["targets"]={}
        for oid,scenarios in CASES.items():
            scoped="mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
            api=probe.get(shared.site+"/api/opportunities/"+oid+"?_release_scope="+scoped).json()
            assert api["id"]==oid and api["target_truth"]["actionable"]
            report["targets"][oid]={"title":api["title"],"source":api["url"],"target_truth":{k:v for k,v in api["target_truth"].items() if isinstance(v,(str,bool))},"records":[]}
            page=ctx.new_page()
            page.on("popup",lambda popup:(report.update(mail_composers=report["mail_composers"]+1),popup.close()))
            def collect(r):
                if urlsplit(r.url).path=="/api/cold-email/variants" and r.request.post_data_json["opportunity_id"]==oid:
                    v=r.json()
                    detail=v.get("detail") or {}
                    report["targets"][oid].setdefault("variant_http",[]).append({"http":r.status,"code":detail.get("code") if isinstance(detail,dict) else None})
                    if r.ok:
                        report["targets"][oid]["free_variants"]=[x["id"] for x in v["variants"]];seen.add(oid)
            page.on("response",collect)
            page.goto(shared.site+"/opportunities/"+oid,wait_until="domcontentloaded")
            page.get_by_role("button",name="Draft email",exact=True).click(timeout=60000)
            for _ in range(170):
                if oid in seen:break
                regen=page.get_by_role("button",name="Regenerate from updated materials",exact=True)
                if regen.is_visible():regen.click()
                page.wait_for_timeout(250)
            if oid not in seen:
                # Keep only the notices and ordinary control labels for this synthetic guest.
                modal=page.get_by_role("dialog").last
                report["targets"][oid]["modal_status"]=re.sub(r"[\w.+-]+@[\w.-]+","[address]",modal.inner_text()[:2400]) if modal.count() else None
            assert oid in seen and len(set(report["targets"][oid]["free_variants"]))==3
            subject=page.locator("#cold-email-subject");body=page.locator("#cold-email-body")
            for label,s,b in scenarios:
                subject.fill(s);body.fill(b)
                expected="Subject: "+s+"\n\n"+b
                prev=page.evaluate("navigator.clipboard.readText()")
                with page.expect_response(lambda r:urlsplit(r.url).path=="/api/cold-email/validate" and r.request.post_data_json["body"]==b,timeout=45000) as event:
                    page.get_by_role("button",name="Copy",exact=True).click()
                resp=event.value;payload=resp.json();assert resp.status==200 and payload["opportunity_id"]==oid
                expected_mode=os.environ.get("M30_MODE","before")
                should_block=expected_mode=="after" and oid==FACULTY and label in ("advertised","posted_subject")
                row={"case":label,"subject":s,"body":b,"http":resp.status,"outcome":payload["outcome"],"issues":payload["issues"],"utc":now()}
                report["targets"][oid]["records"].append(row)
                expect(subject).to_have_value(s);expect(body).to_have_value(b)
                if should_block:
                    assert payload["outcome"]=="review_required" and "unsupported_opening_claim" in payload["issues"]
                    expect(page.get_by_text("This faculty profile does not confirm the opening named in your draft. You can ask whether one is available.",exact=True)).to_be_visible()
                    assert page.evaluate("navigator.clipboard.readText()")==prev
                    page.get_by_test_id("copy-draft-only").click();row["backup_available"]=True
                else:
                    assert payload["outcome"]=="ready" and not payload["issues"]
                    expect(page.get_by_role("button",name="Copied!",exact=True).or_(page.get_by_role("button",name="Copied",exact=True))).to_be_visible(timeout=8000)
                assert page.evaluate("navigator.clipboard.readText()")==expected
                row.update(ordinary_copy_succeeded=not should_block,exact_subject_and_body_kept=True,clipboard_sha256=hashlib.sha256(expected.encode()).hexdigest())
            page.close()
        assert report["paid_requests"]==report["mail_composers"]==0
        report["release_end"]=release(probe);assert report["release_end"]["backend"]==report["release_start"]["backend"]
        report["complete"]=True;browser.close()
if __name__=="__main__":
    try:main()
    finally:
        report["finished_at"]=now();Path(os.environ["M30_RESULT"]).write_text(json.dumps(report,indent=2)+"\n")
