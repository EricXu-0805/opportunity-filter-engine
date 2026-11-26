"""Exercise public match and unsent template flows in clean production guest contexts."""
import base64
import hashlib
import json
import os
import re
import zlib
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

SITE = "https://joinalab.com"
ARCHIVE = "eJztmE13qjAQhv9SwNZ7XLZUa3JKvMin7PhobRCo51Ir4ddfwEXLLHrOu2c3Y2bi4+C8YfKqhcmLj/bFEkVqtk0c5mXvq/1CvCfhfR1H/OiYqyZ9DurYffyK1eMmrfJzWgVlVpWXWPOGV8Z7Uq30kNfHfmbbgA15vinPcXhfxO4Qk+tDuB/3duvgkoR9vLqq/jtYavFlXG2azPT7uPKSPwc6jiTLNF/yWnwdqhVLQtnx7WzP9mzP9mzP9mzP9mzP9mzP9g/7r/V2Xn4cvfXG3wcr4ZX7jX8KvMDqZ5Ba/kvCthnminDRqFT180V5+4w/rVU/AzXDfBJH79c4ErfZJXTUm9v+4dWd2inhJWbZpNbDOLsMcwuvgrusn1eSMLgczODEa9a8anEZ9vHNz3P6fD3a44x0HfLL1+3jMDeVaSXL2BKrly3lcBAOA+GQCuHIEI47hGPnIhzrK1RrD3qOrQ3VZN1hLNCzbCVWFxNjgZ5nu7MglnuIpXiAes2G6sKx3ixsiEVCdeFQf9rFAWOBdIVDPWoXJ4Sls6G62C3E0ncdxALVxWYYiw+xYJprLzCWI8SC6a4D6a7Ezk+G6a4D6a7EzlCG6a4D6a7EzlGG6a4D6a70IN01MN31Id2VHqS7Bqa7PvZe5EG6a2C660O6Kz1Id83fdDdyryozg7KPHe7pl6EWw716eYhEkVgiH+/8F4HuYzpenFN+kl95JLrYfRj12TFXRlbLsj87BqanW6x/e5/9jmXTWH8SO+rfd+xiGnucxI769INh/G0/fbquiD/laiXJlySfsLWS5O9IPuHThE/bdF0Rf7q/Jnya8GnCpwmfJnya8HWEr7PpuiL+dP+O8HWEryN8HeHrCF9H+BjhYzZdV8Qn/zvCxwgfI3yM8DHCxwifQfgMm64r4k/3NwifQfgMwmcQPoPwGYSv732Rvzn/AavMjhs="
AMHERST_ID = "amherst-8b2e68d735f0"
PHRASE = "Our listing suggests junior, senior students — not confirmed on the program page"
MODE = os.environ["CHECK_CASE"]
evidence = {"case": MODE, "signed_up": False, "committed": False, "paid_or_send_requests_blocked": 0}
stage = "start"

def record(name, **values):
    global stage
    stage = name
    evidence.update(values)
    print(json.dumps({"stage": name, **values}), flush=True)

def restrict(route):
    req = route.request
    url = urlsplit(req.url)
    path = url.path
    if req.method == "POST" and url.hostname in ("joinalab.com", "www.joinalab.com", "opportunity-filter-engine-api.onrender.com") and path.startswith("/api/"):
        if path == "/api/matches/view" and "llm=false" in url.query:
            return route.continue_()
        if path == "/api/cold-email/variants":
            return route.continue_()
        if path in ("/api/health", "/api/events"):
            return route.continue_()
        evidence["paid_or_send_requests_blocked"] += 1
        return route.abort()
    return route.continue_()

def responses(res):
    req, url = res.request, urlsplit(res.url)
    if url.hostname and url.hostname.endswith(".supabase.co"):
        endpoint=url.path.rsplit("/",1)[-1]
        evidence.setdefault("real_account_requests",[]).append([req.method,endpoint,res.status])
    if url.hostname and url.hostname.endswith(".supabase.co") and req.method=="POST":
        if url.path=="/auth/v1/signup" and res.status==200:
            evidence["signed_up"] = True
        if url.path.endswith("/rpc/commit_profile_patch_cas") and res.status in (200,201,204):
            evidence["committed"] = True
    if req.method!="POST" or url.path not in ("/api/matches/view","/api/cold-email/variants"): return
    if res.status!=200:
        print(json.dumps({"path":url.path,"status":res.status}),flush=True)
        return
    try:
        data=res.json()
        if url.path=="/api/matches/view":
            profile=req.post_data_json.get("profile",{})
            skills=profile.get("hard_skills",[])
            evidence["match_status"]=res.status
            evidence["shared_skill_count"]=sum(s.get("source")=="shared" for s in skills)
            evidence["confirmed_count"]=sum(bool(s.get("confirmed")) for s in skills)
            evidence["match_year"]=profile.get("year")
            evidence["match_home"]=profile.get("home_school")
            evidence["ai_refined"]=data.get("ai_refined")
        else:
            vs=data.get("variants",[])
            evidence['free_variants']=len(vs)
            evidence['variant_methods']=sorted(set(v.get('method') or '' for v in vs))
            evidence['inherited_names_in_templates']=sum(bool(re.search(r"\bSkill (?:[1-9]|[1-5][0-9]|60)\b",v.get('body') or '',re.I)) for v in vs)
            evidence['skill_one_in_templates']=sum(bool(re.search(r"\bSkill 1\b",v.get('body') or '',re.I)) for v in vs)
    except Exception:
        return

def choose_campus(page, slug):
    card=page.get_by_test_id("university-card-"+slug)
    if not card.is_visible():
        record("open school selector")
        page.get_by_role("button",name="Change",exact=True).click()
        if not card.is_visible(timeout=2500):
            page.wait_for_timeout(1000)
            if not card.is_visible():
                page.get_by_role("button",name="Change",exact=True).click()
    record("select campus "+slug)
    card.click()
    record("confirm campus "+slug)
    page.get_by_test_id("switcher-confirm").click()
    expect(page.get_by_test_id("switcher-confirm")).not_to_be_visible(timeout=15000)

def locate_results(page):
    generate=page.get_by_test_id("generate-matches")
    expect(generate).to_be_enabled(timeout=45000)
    generate.click()
    for _ in range(25):
        page.wait_for_timeout(250)
        if urlsplit(page.url).path.startswith("/results"):
            break
    if urlsplit(page.url).path=="/" and generate.is_enabled():
        record("retry enabled Generate once",profile_status=page.locator("#profile-save-status").inner_text())
        generate.click()
    page.wait_for_url(re.compile(r"/results"),timeout=45000)
    page.locator('[id^=match-card-]').first.wait_for(timeout=85000)

def test(page):
    target=SITE+"/"
    if MODE=="shared":
        payload=zlib.decompress(base64.b64decode(ARCHIVE)).decode()
        assert hashlib.sha256(payload.encode()).hexdigest()=="9cb06e26a2aa3fc4d02fb73a11c9963c83ce9b8a278f66786aba4f3e422424f0"
        target+="?share="+payload
    record("open synthetic visitor form")
    response=page.goto(target,wait_until="domcontentloaded",timeout=60000)
    record("load form",status=response.status)
    page.locator("#student_name").wait_for(timeout=40000)
    for _ in range(80):
        page.wait_for_timeout(250)
        if evidence["signed_up"] and not page.get_by_test_id("hydration-note").is_visible() and not page.get_by_test_id("profile-refresh-status").is_visible():
            break
    record("guest form ready",signed_up=evidence["signed_up"],readiness=page.locator("#profile-save-status").inner_text())
    if MODE=="amherst":
        choose_campus(page,"amherst")
        record("fill Amherst freshman form")
        page.locator("#student_name").fill("Sample Student")
        for selector,value in (("#college","Division of Humanities"),("#major","English")):
            field=page.locator(selector)
            if field.evaluate("e=>e.tagName")== "SELECT":
                field.select_option(label=value)
            else:
                field.fill(value)
        page.locator("#grade").select_option(label="Freshman")
        page.locator("#research_interests").fill("summer research, senior thesis, faculty-advised research, research award")
        if not page.get_by_test_id("generate-matches").is_enabled():
            print(json.dumps({"form_state":[s for s in (page.locator('main').inner_text().splitlines()) if re.search(r'select|check|required|choose',s,re.I)][-12:]}),flush=True)
        record("generate from form")
        locate_results(page)
        record("search for public Amherst record")
        page.locator("#results-search-input").fill("Gregory")
        card=page.locator("#match-card-"+AMHERST_ID)
        card.wait_for(timeout=60000)
        card.get_by_role("button",name="Show details",exact=True).click()
        expect(card.get_by_text(PHRASE,exact=True)).to_be_visible(timeout=20000)
        record("Amherst card verified",id=AMHERST_ID,displayed_reason=PHRASE)
    else:
        campus=page.get_by_test_id("university-card-uiuc")
        if campus.is_visible():
            campus.click();page.get_by_test_id("switcher-confirm").click()
        expect(page.locator("#research_interests")).to_have_value(re.compile("LATE_INTEREST"),timeout=30000)
        page.locator("#student_name").fill("Sample Student")
        record("generate from archived October v1 link")
        locate_results(page)
        assert evidence.get("shared_skill_count")==60 and evidence.get("confirmed_count")==0
        record("old share reached real matches",shared_skill_count=evidence["shared_skill_count"])
        first=page.locator('[id^=match-card-]').filter(has=page.get_by_role("button",name="Draft email",exact=True)).first
        oid=first.get_attribute('id').removeprefix("match-card-")
        button=first.get_by_role("button",name="Draft email",exact=True)
        expect(button).to_be_enabled(timeout=40000)
        button.click()
        editor=page.locator("#cold-email-body")
        expect(editor).to_be_visible(timeout=60000)
        assert editor.input_value().strip() and evidence.get('free_variants',0)>0 and evidence.get('inherited_names_in_templates')==0
        record("unconfirmed template editor verified",opportunity_id=oid,visible_editor=True)
        page.goto(SITE+"/",wait_until="domcontentloaded")
        confirm=page.get_by_role("button",name=re.compile(r"Keep this level for Skill 1 \("))
        expect(confirm).to_be_visible(timeout=30000)
        confirm.click()
        record("one archived skill confirmed by guest")
        locate_results(page)
        assert evidence.get("confirmed_count")==1
        another=page.locator('[id^=match-card-]').filter(has=page.get_by_role("button",name="Draft email",exact=True)).nth(1)
        another.get_by_role("button",name="Draft email",exact=True).click()
        expect(page.locator("#cold-email-body")).to_be_visible(timeout=60000)
        assert evidence.get("free_variants",0)>0
        record("confirmed profile reached template editor",confirmed_count=1)
    assert evidence['signed_up'] and evidence.get('match_status')==200 and evidence.get('ai_refined') is False

with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox","--disable-dev-shm-usage"])
    context=browser.new_context(locale="en-US",service_workers="block")
    context.route("**/*",restrict)
    context.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=context.new_page();page.on("response",responses);page.set_default_timeout(25000)
    try: test(page)
    except Exception as ex:
        print(json.dumps({"failed_stage":stage,"error_class":type(ex).__name__,"error":re.sub(r'https?://\S+','[URL]',str(ex))[:400],"flow_status":page.get_by_role("status").all_inner_texts()[:6],"validation":page.locator("#match-validation").all_inner_texts(),"page_path":urlsplit(page.url).path,"headings":page.get_by_role("heading").all_text_contents()[:9],"statuses":page.get_by_role("alert").all_text_contents()[:2],"buttons":page.get_by_role("button").all_text_contents()[:18]}),flush=True)
        raise SystemExit(1) from None
    finally:
        print("PUBLIC RECEIPT",json.dumps(evidence),flush=True);browser.close()
