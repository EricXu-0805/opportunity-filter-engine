"""Exercise a long, editable free draft at genuine desktop Chrome page zoom."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright

SITE = "https://joinalab.com"
TARGET = "faculty-cs-321c7f13"
out = Path("evidence")
out.mkdir(exist_ok=True)
report = {"site": SITE, "target": TARGET, "started_utc": datetime.now(timezone.utc).isoformat(),
          "observations": [], "template_http": [], "guest_signup_http":None, "profile_commits":[], "cloud_profile_saved": False, "external_composer_opens": 0}
def capture(response):
    path = urlsplit(response.url).path
    if response.request.method == "POST":
        if path == "/auth/v1/signup":
            report["guest_signup_http"]=response.status
        elif path == "/api/cold-email/variants":
            report["template_http"].append(response.status)
        elif path.endswith("/rpc/commit_profile_patch_cas") and response.ok:
            data = response.json()
            result = (data[0] if data else {}) if isinstance(data, list) else data
            report["profile_commits"].append({"http":response.status,"outcome":result.get("status"),"fields":sorted(response.request.post_data_json.get("p_patch",{}))})
            if result.get("status") == "applied" and response.request.post_data_json.get("p_patch",{}).get("major") == "Electrical Engineering":
                report["cloud_profile_saved"] = True

def bounds(page, locator):
    return locator.evaluate("""el => {const r=el.getBoundingClientRect(); return {x:r.x, y:r.y, w:r.width,
      h:r.height, inside:r.x>=-1 && r.right<=innerWidth+1 && r.y>=-1 && r.bottom<=innerHeight+1,
      viewport:[innerWidth,innerHeight], dpr:devicePixelRatio};}""")

def check_actions(page, stage):
    copy = page.get_by_role("button", name="Copy", exact=True)
    composer = page.get_by_role("button", name="Open in Email", exact=True)
    states = [bounds(page,loc) for loc in (copy,composer)]
    report["observations"].append({"stage":stage,"copy":states[0],"composer":states[1],
                                   "composer_enabled":composer.is_enabled()})
    assert all(s["inside"] for s in states), stage

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome",headless=False,args=["--window-size=1280,900","--force-device-scale-factor=1"])
        context = browser.new_context(no_viewport=True,locale="en-US",permissions=["clipboard-read","clipboard-write"])
        context.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_lang','en');localStorage.setItem('ofe_onboarding_seen','1')}")
        page = context.new_page()
        page.on("response",capture)
        page.goto(SITE+"/", wait_until="domcontentloaded",timeout=70000)
        page.locator("#student_name").wait_for(timeout=50000)
        for _ in range(140):
            if report["guest_signup_http"]==200: break
            page.wait_for_timeout(250)
        assert report["guest_signup_http"]==200,"production guest signup"
        page.get_by_test_id("hydration-note").wait_for(state="hidden",timeout=45000)
        page.get_by_test_id("profile-refresh-status").wait_for(state="hidden",timeout=45000)
        page.add_locator_handler(page.get_by_test_id("switcher-confirm"),lambda:page.keyboard.press("Escape"))
        name = page.locator("#student_name")
        name.fill("Draft Layout Sample")
        college = page.locator("#college")
        if college.evaluate("el=>el.tagName") == "SELECT": college.select_option(label="Grainger College of Engineering")
        else: college.fill("Grainger College of Engineering")
        major = page.locator("#major")
        if major.evaluate("el=>el.tagName") == "SELECT": major.select_option(label="Electrical Engineering")
        else: major.fill("Electrical Engineering")
        page.locator("#grade").select_option(label="Junior")
        page.locator("#research_interests").fill("Robotics, adaptive control, engineering")
        page.locator("#research_interests").press("Tab")
        for _ in range(150):
            if report["cloud_profile_saved"]: break
            page.wait_for_timeout(200)
        assert report["cloud_profile_saved"], "guest profile save"
        report["backend_release"] = page.request.get(SITE+"/api/health").json()["release_sha"]
        page.goto(SITE+"/opportunities/"+TARGET,wait_until="domcontentloaded",timeout=65000)
        report["frontend_release"] = page.locator("html").get_attribute("data-release-sha")
        expect(page.get_by_role("heading",level=1)).to_have_text("Girish Chowdhary")
        page.get_by_role("button",name="Draft email",exact=True).click()
        editor = page.locator("#cold-email-body")
        expect(editor).to_be_visible(timeout=65000)
        assert report["template_http"] and report["template_http"][-1]==200
        original = editor.input_value()
        text = original+"\n\n"+("This is an editable layout sample for the draft screen. "*26)
        editor.fill(text)
        check_actions(page,"desktop 100%")
        base = page.evaluate("({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})")
        for _ in range(5): subprocess.run(["xdotool","key","--clearmodifiers","ctrl+plus"],check=True)
        page.wait_for_function("d => Math.abs(devicePixelRatio/d-2) < 0.02",arg=base["dpr"],timeout=10000)
        report["initial_viewport"]=base
        check_actions(page,"native page zoom 200%")
        editor.scroll_into_view_if_needed()
        editor.press("Control+End")
        editor.press("Enter")
        editor.press_sequentially("Draft zoom check.")
        expect(editor).to_have_value(text+"\nDraft zoom check.")
        check_actions(page,"typing at 200%")
        backup=page.get_by_test_id("copy-draft-only")
        backup.scroll_into_view_if_needed()
        backup.click()
        expect(backup).to_have_text("Draft copied")
        page.wait_for_function("async () => (await navigator.clipboard.readText()).includes('Draft zoom check.')",timeout=10000)
        report["copy_action"]="Copy draft only"
        check_actions(page,"after copy at 200%")
        recipient=page.locator("#cold-email-to")
        composer=page.get_by_role("button",name="Open in Email",exact=True)
        recipient.scroll_into_view_if_needed()
        report["initial_recipient_present"]=bool(recipient.input_value().strip())
        if not report["initial_recipient_present"]:
            recipient.fill("layout-test@example.org")
            recipient.press("Tab")
        report["composer_with_recipient_enabled"]=composer.is_enabled()
        report["visible_guidance"]=[t[:220] for t in page.get_by_role("dialog").locator("[role=status]:visible, [role=alert]:visible").all_inner_texts() if t.strip()][:6]
        check_actions(page,"with recipient at 200%")
        report["copied_long_draft_characters"]=len(editor.input_value())
        page.get_by_test_id("cold-email-footer").screenshot(path=str(out/"footer-200.png"))
        report["result"]="passed"
        browser.close()
finally:
    (out/"receipt.json").write_text(json.dumps(report,indent=2)+"\n")
