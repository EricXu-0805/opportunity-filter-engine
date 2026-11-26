"""Exercise #1203 from real public details using a fresh synthetic visitor."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

SITE = "https://joinalab.com"
GRAINGER = "Grainger College of Engineering"
MAJOR = "Electrical Engineering"
OWN_EMPTY = ("faculty-cs-283f2c60","Jiawei Han")
OWN_TWO = ("faculty-cs-321c7f13","Girish Chowdhary")
AWAY = ("faculty-ucb-eecs-d683bc2c","Ahmed Alaa")
UNRELATED = "I counted the books returned to a library desk during a practice exercise."
RELATED = ("I compared adaptive control and reinforcement learning in a simulated robot.",
           "I trained a machine vision model to detect obstacles in a simulated robotics course.")
ALLOWED_IDS = {OWN_EMPTY[0], OWN_TWO[0], AWAY[0]}
LABELS = {"balanced":"Balanced","skills":"Skills Focus","concise":"Concise"}
report = {"site":SITE,"feature_merge":"dcbedf7307fdca66093067f0c9f9e9a8d485c55f",
          "started_utc":datetime.now(timezone.utc).isoformat(), "drafts":[], "blocked_requests":[]}
state = {"confirmed":set(),"profile":False,"signup":None}
answers = {}


def restrict(route):
    req=route.request
    link=urlsplit(req.url)
    if link.scheme in ("mailto","ms-outlook") or link.hostname in ("mail.google.com","outlook.office.com","outlook.live.com"):
        return route.abort()
    if req.method=="POST" and link.hostname in ("joinalab.com","www.joinalab.com","opportunity-filter-engine-api.onrender.com") and link.path.startswith("/api/"):
        if link.path in ("/api/events","/api/health"):
            return route.continue_()
        if link.path=="/api/cold-email/variants" and req.post_data_json.get("opportunity_id") in ALLOWED_IDS:
            return route.continue_()
        report["blocked_requests"].append(link.path)
        return route.abort()
    return route.continue_()


def capture(res):
    req=res.request
    u=urlsplit(res.url)
    if req.method!="POST": return
    if u.hostname and u.hostname.endswith(".supabase.co"):
        if u.path=="/auth/v1/signup":
            state["signup"]=res.status
        if u.path.endswith("/rpc/commit_profile_patch_cas") and res.ok:
            result=res.json()
            if isinstance(result,list): result=result[0] if result else {}
            if result.get("status")!="applied": return
            p=(req.post_data_json or {}).get("p_patch",{})
            if p.get("major")==MAJOR: state["profile"]=True
            for entry in p.get("experience_entries") or []:
                if entry["status"]=="confirmed" and entry["text"] in (UNRELATED,*RELATED):
                    state["confirmed"].add(entry["text"])
    if u.path=="/api/cold-email/variants":
        assert res.ok, f"Template API HTTP {res.status}"
        payload=req.post_data_json
        answers[payload["opportunity_id"]]=(payload,res.json(),res.status)


def wait_for(page, test, label):
    for _ in range(150):
        if test(): return
        page.wait_for_timeout(200)
    raise RuntimeError(label)


def home(page):
    page.goto(SITE+"/",wait_until="domcontentloaded")
    page.locator("#student_name").wait_for()
    page.get_by_test_id("hydration-note").wait_for(state="hidden",timeout=45000)
    page.get_by_test_id("profile-refresh-status").wait_for(state="hidden",timeout=45000)


def setup(page):
    home(page)
    wait_for(page,lambda:state["signup"]==200,"Anonymous account was not created")
    page.locator("#student_name").fill("QA Template Sample")
    for selector,value in (("#college",GRAINGER),("#major",MAJOR)):
        field=page.locator(selector)
        if field.evaluate("e=>e.tagName")=="SELECT": field.select_option(label=value)
        else: field.fill(value)
    page.locator("#grade").select_option(label="Junior")
    page.locator("#research_interests").fill("machine vision, robotics, adaptive control")
    wait_for(page,lambda:state["profile"],"Initial synthetic academic profile was not saved")
    report["guest_signup_http"]=state["signup"]
    print("production guest and profile ready",flush=True)


def add_facts(page):
    home(page)
    library=page.locator("#experience-library")
    manual=library.locator("details").filter(has=page.get_by_text("Add an experience",exact=True))
    manual.locator("summary").click()
    for text in (UNRELATED,*RELATED):
        manual.get_by_label("Describe your contribution, methods and results").fill(text)
        manual.get_by_role("button",name="Add for review",exact=True).click()
        row=library.locator("details").filter(has=page.get_by_text(text,exact=True)).first
        expect(row.locator("summary")).to_contain_text("Needs confirmation")
        row.locator("summary").click()
        row.get_by_role("button",name="Confirm facts",exact=True).click()
        expect(row.locator("summary")).to_contain_text("Confirmed")
    wait_for(page,lambda:len(state["confirmed"])==3,"Three explicit confirmations were not committed to the real account")
    report["confirmed_synthetic_experiences"]=list((UNRELATED,*RELATED))
    print("three explicit confirmations persisted",flush=True)


def check_draft(page, target, mode):
    oid,name=target
    page.goto(SITE+"/opportunities/"+oid,wait_until="domcontentloaded")
    expect(page.get_by_role("heading",level=1)).to_have_text(name)
    button=page.get_by_role("button",name="Draft email",exact=True)
    expect(button).to_be_enabled(timeout=45000)
    button.click()
    editor=page.locator("#cold-email-body")
    expect(editor).to_be_visible(timeout=65000)
    wait_for(page,lambda:oid in answers,"No free variants response for "+oid)
    request,response,code=answers[oid]
    student=request["profile"]
    assert student["home_school"]=="uiuc" and student["major"]==MAJOR and student["year"]=="junior"
    assert student["school"],"Outgoing request is missing the student's institution"
    variants={v["id"]:v for v in response["variants"]}
    assert set(variants)==set(LABELS)
    out={"target":oid,"display_name":name,"case":mode,"http":code,"entry":"Public opportunity detail > Draft email",
         "home_school":student["home_school"],"school_label":student["school"],"verified_variants":[]}
    for key,label in LABELS.items():
        v=variants[key]
        page.get_by_role("button",name=label,exact=True).click()
        expect(editor).to_have_value(v["body"])
        expect(page.locator("#cold-email-subject")).to_have_value(v["subject"])
        body=editor.input_value()
        intro=next(s for s in body.split("\n\n") if MAJOR in s)
        assert "junior" in intro.lower()
        school_displayed=(" at "+student["school"]) in intro
        assert school_displayed==(mode=="other_campus"), f"Wrong school in {mode} {key}: {intro}"
        if mode!="other_campus": assert student["school"].lower() not in intro.lower()
        usage=v["experience_usage"]
        chosen=[x["excerpt"] for x in usage["selected"]]
        if mode=="empty":
            assert not chosen and usage["eligible_count"]==0
            assert "what you would suggest I learn or do first to prepare for research" in body
            assert "May I contact you again once I have done that?" in body and "research openings" not in body
        else:
            assert usage["eligible_count"]==3 and len(chosen)==2 and all(x in (UNRELATED,*RELATED) for x in chosen)
            assert all(body.count(x)==1 for x in chosen)
            assert "current or upcoming research openings" in body
            if mode=="own_campus":
                assert set(chosen)==set(RELATED) and UNRELATED not in body, f"Chosen wrong experiences: {chosen}"
        ask=next(s for s in body.split("\n\n") if "May I contact you again" in s or "research openings" in s)
        out["verified_variants"].append({"id":key,"intro":intro,"closing_request":ask,
              "quoted_experiences":chosen,"request_matches_editor":True})
    report["drafts"].append(out)
    print(mode,oid,"3/3 variants verified in editor",flush=True)


with sync_playwright() as pw:
    b=pw.chromium.launch(channel="chrome")
    ctx=b.new_context(locale="en-US",service_workers="block")
    ctx.route("**/*",restrict)
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_lang','en');localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0')}")
    page=ctx.new_page()
    page.on("response",capture)
    page.add_locator_handler(page.get_by_test_id("switcher-confirm"),lambda:page.keyboard.press("Escape"))
    report["backend_release"]=page.request.get(SITE+"/api/health").json()["release_sha"]
    setup(page)
    report["frontend_release"]=page.locator("html").get_attribute("data-release-sha")
    check_draft(page,OWN_EMPTY,"empty")
    add_facts(page)
    check_draft(page,OWN_TWO,"own_campus")
    check_draft(page,AWAY,"other_campus")
    assert not report["blocked_requests"],report["blocked_requests"]
    report["ended_utc"]=datetime.now(timezone.utc).isoformat()
    dest=Path("evidence");dest.mkdir(exist_ok=True)
    (dest/"template-rules.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    b.close()
