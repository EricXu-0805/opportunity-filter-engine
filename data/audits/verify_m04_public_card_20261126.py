"""Verify one free, unsent professor inquiry from the real public match card."""
import base64
import json
import os
import re
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright, expect

SITE = "https://joinalab.com"
OID = "faculty-cs-321c7f13"
NAME = "Girish Chowdhary"
OUT = Path(os.environ.get("RECEIPT_DIRECTORY", "evidence"))
OUT.mkdir(parents=True, exist_ok=True)
guest = {"signup_http": None, "profile_commit_http": None, "match_http": None}
draft = {}
receipt = {"production_site": SITE, "target_id": OID, "guest": guest, "draft_api": draft,
           "blocked_app_posts": [], "started_at": datetime.now(timezone.utc).isoformat()}
allowed_app_posts = {"/api/events", "/api/health"}

def restrict(route):
    req = route.request
    url = urlsplit(req.url)
    if url.scheme in ("mailto", "ms-outlook") or url.hostname in ("mail.google.com", "outlook.live.com", "outlook.office.com"):
        return route.abort()
    if req.method == "POST" and url.hostname in ("joinalab.com", "www.joinalab.com", "opportunity-filter-engine-api.onrender.com") and url.path.startswith("/api/"):
        if url.path in allowed_app_posts or url.path == "/api/matches/view" and parse_qs(url.query).get("llm") == ["false"]:
            return route.continue_()
        if url.path == "/api/cold-email/variants" and req.post_data_json.get("opportunity_id") == OID:
            return route.continue_()
        receipt["blocked_app_posts"].append(url.path)
        return route.abort()
    return route.continue_()

def capture(res):
    req = res.request
    url = urlsplit(res.url)
    if req.method != "POST":
        return
    if url.hostname and url.hostname.endswith(".supabase.co"):
        if url.path.endswith("/auth/v1/signup"):
            guest["signup_http"] = res.status
        elif url.path.endswith("/rpc/commit_profile_patch_cas"):
            guest["profile_commit_http"] = res.status
    if url.path == "/api/matches/view":
        guest["match_http"] = res.status
        guest["rules_only"] = parse_qs(url.query).get("llm") == ["false"]
        if res.ok:
            guest["ai_refined"] = res.json().get("ai_refined")
    if url.path == "/api/cold-email/variants" and res.ok:
        answer=res.json()
        vs=answer["variants"]
        draft.update({"opportunity_id":req.post_data_json.get("opportunity_id"),"http":res.status,
                      "variant_ids":[v.get("id") for v in vs], "recipient_status":answer.get("recipient_status"),
                      "pipeline_version":answer.get("pipeline_version"),"variants":vs})

def run(page):
    # An ordinary archived, entirely synthetic QA share makes this same person reproducibly appear.
    archived_script=Path(os.environ.get("ARCHIVED_GUEST_SCRIPT","data/audits/verify_public_guest_20261126.py")).read_text()
    archive=re.search(r'^ARCHIVE = "([^"]+)"',archived_script,re.M).group(1)
    payload=zlib.decompress(base64.b64decode(archive)).decode()
    source="https://siebelschool.illinois.edu/about/people/faculty/girishc"
    official=page.request.get(source,timeout=30000)
    assert official.ok and NAME in official.text() and 'mailto:girishc@illinois.edu' in official.text().lower()
    receipt["official_contact"]={"url":source,"http":official.status,"display_name":NAME,"published_professional_email_verified":True}
    page.goto(SITE+"/?share="+payload,wait_until="domcontentloaded",timeout=90000)
    page.locator("#student_name").wait_for(timeout=50000)
    for _ in range(100):
        page.wait_for_timeout(250)
        if guest["signup_http"] == 200 and not page.get_by_test_id("hydration-note").is_visible() and not page.get_by_test_id("profile-refresh-status").is_visible():
            break
    assert guest["signup_http"] == 200, "The site's real anonymous account service did not confirm a fresh guest"
    campus=page.get_by_test_id("university-card-uiuc")
    if campus.is_visible():
        campus.click()
        page.get_by_test_id("switcher-confirm").click()
    expect(page.locator("#research_interests")).to_have_value(re.compile("LATE_INTEREST"),timeout=30000)
    page.locator("#student_name").fill("Sample Student")
    generate=page.get_by_test_id("generate-matches")
    expect(generate).to_be_enabled(timeout=45000)
    generate.click()
    for _ in range(25):
        page.wait_for_timeout(250)
        if urlsplit(page.url).path.startswith("/results"):
            break
    if urlsplit(page.url).path=="/" and generate.is_enabled():
        generate.click()
    page.wait_for_url(re.compile("/results"),timeout=55000)
    card=page.locator("#match-card-"+OID)
    expect(card).to_be_visible(timeout=90000)
    if page.get_by_test_id("switcher-confirm").is_visible():
        page.keyboard.press("Escape")
    title=card.get_by_role("heading",level=3)
    assert title.inner_text().strip() == NAME
    receipt["card"]={"id":card.get_attribute("id"),"name":title.inner_text(),"href":title.get_by_role("link").get_attribute("href")}
    card.get_by_role("button",name="Show details",exact=True).click()
    why=card.get_by_role("heading",name="Why it fits",exact=True)
    expect(why).to_be_visible()
    reasons=why.locator("..").locator("li").all_inner_texts()
    assert any(s.strip() for s in reasons)
    receipt["card"]["displayed_fit_reasons"]=reasons
    gaps=card.get_by_role("heading",name="Potential concerns",exact=True)
    receipt["card"]["displayed_concerns"]=gaps.locator("..").locator("li").all_inner_texts() if gaps.count() else []
    card.screenshot(path=str(OUT/"card.png"),animations="disabled")
    draft_button=card.get_by_role("button",name="Draft email",exact=True)
    expect(draft_button).to_be_enabled()
    draft_button.click()
    body=page.locator("#cold-email-body")
    expect(body).to_be_visible(timeout=70000)
    subject=page.locator("#cold-email-subject").input_value().strip()
    body_text=body.input_value().strip()
    assert subject and body_text and "Chowdhary" in body_text, "The unsent editor does not identify its target"
    variants=draft.pop("variants")
    assert any(v.get("subject","").strip()==subject and v.get("body","").strip()==body_text for v in variants), "Wrong variant in the editor"
    assert draft["opportunity_id"]==OID and set(draft["variant_ids"])=={"balanced","skills","concise"}
    assert guest["rules_only"] and guest["ai_refined"] is False
    assert guest["profile_commit_http"] == 200
    receipt["editor"]={"subject":subject,"body":body_text,
                       "recipient_input_populated":bool(page.locator("#cold-email-to").input_value().strip()),
                       "selected_template_matches_response":True}
    page.locator("#cold-email-subject").screenshot(path=str(OUT/"subject.png"))
    body.screenshot(path=str(OUT/"body.png"))
    receipt["completed_at"]=datetime.now(timezone.utc).isoformat()
    (OUT/"receipt.json").write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps(receipt,ensure_ascii=False),flush=True)

with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"),args=["--no-sandbox","--disable-dev-shm-usage"])
    ctx=browser.new_context(locale="en-US",service_workers="block",viewport={"width":1250,"height":950})
    ctx.route("**/*",restrict)
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page=ctx.new_page()
    page.on("response",capture)
    page.set_default_timeout(25000)
    try:
        run(page)
    except Exception as error:
        print("verification failed",type(error).__name__,str(error).split("Call log:")[0][:400],json.dumps(guest),flush=True)
        raise SystemExit(1) from None
    finally:
        browser.close()
