"""Normal public visitor flow for the project-owned PR fixture (no sent materials)."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

SITE = "https://joinalab.com"
REPO = "EricXu-0805/opportunity-filter-engine"
URL = f"https://github.com/{REPO}/pull/1298"
QA_TEXT = "QA sample: I reviewed the integration test fixture for this project."
checked = {"site": SITE, "source": URL, "started_utc": datetime.now(timezone.utc).isoformat()}
saved = []
saved_rows = {}


def capture(response):
    url = urlsplit(response.url)
    if url.hostname == "joinalab.com" and "/resume/github/" in url.path:
        checked.setdefault("lookups", []).append(response.status)
    if not url.hostname or not url.hostname.endswith(".supabase.co"):
        return
    if url.path == "/auth/v1/signup":
        checked["guest_signup_http"] = response.status
    if url.path.endswith("/rpc/commit_profile_patch_cas") and response.ok:
        patch = response.request.post_data_json or {}
        entries = (patch.get("p_patch") or {}).get("experience_entries", [])
        for row in entries or []:
            if row.get("id") == "github-pr:5504607756":
                result = response.json()
                if isinstance(result, list):
                    result = result[0] if result else {}
                if result.get("status") == "applied":
                    saved.append(row["status"])
                    saved_rows[row["status"]] = row


def wait_saved(page, status):
    for _ in range(100):
        page.wait_for_timeout(250)
        if status in saved:
            return
    raise RuntimeError(f"missing successful account write for {status}: {saved}")


def verify_free_draft(page, target, status):
    # Reuse this test guest's committed library row. The public free variants
    # API only drafts, and the response bodies are discarded after checking.
    row = saved_rows[status]
    payload = {"opportunity_id":target, "profile":{
        "name":"QA sample", "school":"UIUC", "year":"Junior", "major":"Computer Science",
        "hard_skills":[], "coursework":[]},
        "experience_evidence":{"version":1, "resume_text":"", "entries":[row]}, "engine":"template"}
    result=page.request.post(SITE+"/api/cold-email/variants",data=payload)
    assert result.ok, f"free draft returned HTTP {result.status}"
    variants=result.json()["variants"]
    assert variants
    selected=[]
    for variant in variants:
        usage=variant["experience_usage"]
        if status=="confirmed":
            assert usage["eligible_count"]==1
            used=any(item["id"]==row["id"] and item["revision"]==row["revision"]
                     and item["source"]["kind"]=="github" and item["source"]["repository"]==REPO
                     and item["source"]["number"]==1298 for item in usage["selected"])
            if used:
                assert QA_TEXT in variant["body"]
                selected.append(variant["id"])
        else:
            assert usage["eligible_count"]==0 and not usage["selected"]
            assert any(item["id"]==row["id"] and item["reason"]==status for item in usage["excluded"])
            assert row["text"] not in variant["body"]
    if status=="confirmed":
        assert selected, f"confirmed fact absent from all free variants for {target}"
    checked.setdefault("free_unsent_draft_checks",[]).append({
        "target":target,"status":status,"revision":row["revision"],"variants":len(variants),
        "variants_quoting_confirmed_with_source":selected,"http":result.status})


def handle_campus_prompt(page):
    # A fresh guest can be asked to confirm their default campus only after
    # the first profile save. Use the ordinary defer action whenever it opens.
    page.add_locator_handler(page.get_by_test_id("switcher-confirm"),
                             lambda: page.keyboard.press("Escape"))


def wait_ready(page):
    page.locator("#student_name").wait_for()
    page.get_by_test_id("hydration-note").wait_for(state="hidden",timeout=45000)
    page.get_by_test_id("profile-refresh-status").wait_for(state="hidden",timeout=45000)


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome")
    context = browser.new_context(locale="en-US")
    context.add_init_script("localStorage.setItem('ofe_lang','en');localStorage.setItem('ofe_onboarding_seen','1')")
    page = context.new_page()
    page.on("response", capture)
    handle_campus_prompt(page)
    health = page.request.get(SITE+"/api/health").json()
    checked["backend_release"] = health["release_sha"]
    deployment = json.loads(Path("data/audits/m14-production-verify.json").read_text())
    expected = deployment["production_merge"]
    assert len(expected)==40 and all(ch in "abcdef0123456789" for ch in expected)
    if checked["backend_release"] != expected:
        compare = page.request.get("https://api.github.com/repos/"+REPO+"/compare/"+expected+"..."+checked["backend_release"])
        assert compare.ok and compare.json()["status"] in ("ahead","identical"), "Backend is missing merged change"
    checked["included_merge"] = expected
    original = page.request.get("https://api.github.com/repos/"+REPO+"/pulls/1298")
    assert original.ok
    data = original.json()
    assert data["user"]["login"] == "EricXu-0805" and data["base"]["repo"]["full_name"] == REPO
    assert data["id"] == 5504607756
    checked["verified_official_pull_id"] = data["id"]
    sample_fork = page.request.get(SITE+"/api/resume/github/unoju/pull/octocat/Hello-World/1")
    assert sample_fork.ok, f"public fork HTTP {sample_fork.status}"
    fork = sample_fork.json()
    assert fork["id"] == "github-pr:140900"
    assert (fork["source"]["author"], fork["source"]["repository"], fork["source"]["head_repository"]) == (
        "unoju", "octocat/Hello-World", "unoju/Hello-World")
    checked["same_named_fork"] = {"author": "unoju", "base": "octocat/Hello-World", "head": "unoju/Hello-World", "id": fork["id"]}
    page.goto(SITE+"/",wait_until="domcontentloaded")
    wait_ready(page)
    checked["frontend_release"] = page.locator("html").get_attribute("data-release-sha")
    if checked["frontend_release"] != expected:
        compare = page.request.get("https://api.github.com/repos/"+REPO+"/compare/"+expected+"..."+checked["frontend_release"])
        assert compare.ok and compare.json()["status"] in ("ahead","identical"), "Frontend is missing merged change"
    for _ in range(100):
        if checked.get("guest_signup_http")==200:
            break
        page.wait_for_timeout(200)
    assert checked.get("guest_signup_http")==200, "Fresh anonymous site account was not observed"
    page.locator("#student_name").fill("QA GitHub contribution sample")
    for selector in ("#college", "#major"):
        field=page.locator(selector)
        if field.evaluate("e=>e.tagName") == "SELECT":
            field.locator("option:not([value='']):not([disabled])").first.wait_for(state="attached")
            value=field.locator("option").evaluate_all("rows => rows.find(x => x.value && !x.disabled)?.value")
            assert value
            field.select_option(value)
        else:
            field.fill("Computer Science")
    page.locator("#grade").select_option(label="Junior")
    page.locator("#github_url").fill("https://github.com/octocat")
    lib=page.locator("#experience-library")
    lib.get_by_text("Import a GitHub pull request",exact=True).click()
    lib.get_by_label("Public pull request URL").fill(URL)
    button=lib.get_by_role("button",name="Add for review",exact=True)
    button.click()
    expect(lib.get_by_role("alert")).to_contain_text("different author")
    page.locator("#github_url").fill("https://github.com/EricXu-0805")
    button.click()
    candidate=lib.locator("details").filter(has=page.locator(f'a[href="{URL}"]')).first
    expect(candidate.locator("summary").first).to_contain_text("Needs confirmation")
    wait_saved(page,"candidate")
    verify_free_draft(page,"faculty-ucb-eecs-d683bc2c","candidate")
    candidate.locator("summary").first.click()
    expect(candidate.get_by_role("link")).to_have_attribute("href",URL)
    expect(candidate).to_contain_text("Opened by EricXu-0805")
    candidate.get_by_role("textbox").fill(QA_TEXT)
    candidate.get_by_role("button",name="Confirm corrected facts",exact=True).click()
    wait_saved(page,"confirmed")
    # Retain the newly created visitor's own authentication only. Cold profile
    # reads below cannot use this tab's local profile data or outbox.
    fresh_state=context.storage_state()
    for origin in fresh_state["origins"]:
        origin["localStorage"]=[item for item in origin["localStorage"] if item["name"] in
                                ("ofe_auth","ofe_lang","ofe_onboarding_seen","ofe_school_confirmed")]
    assert any(item["name"] == "ofe_auth" for origin in fresh_state["origins"] for item in origin["localStorage"])
    cold=browser.new_context(storage_state=fresh_state, locale="en-US")
    read=cold.new_page()
    read.on("response",capture)
    handle_campus_prompt(read)
    read.goto(SITE+"/",wait_until="domcontentloaded")
    wait_ready(read)
    library=read.locator("#experience-library")
    row=library.locator("details").filter(has=read.locator(f'a[href="{URL}"]')).first
    expect(row.locator("summary").first).to_contain_text(QA_TEXT)
    expect(row.locator("summary").first).to_contain_text("Confirmed")
    row.locator("summary").first.click()
    expect(row.get_by_role("link")).to_contain_text(data["title"])
    for target in ("faculty-ucb-eecs-d683bc2c","faculty-cs-321c7f13"):
        verify_free_draft(read,target,"confirmed")
    row.get_by_role("button",name="Do not use",exact=True).click()
    wait_saved(read,"rejected")
    verify_free_draft(read,"faculty-cs-321c7f13","rejected")
    checked.update({"cold_read_corrected_text":True,"cold_read_source_and_title":True,
                    "observed_writes":saved,"finished_utc":datetime.now(timezone.utc).isoformat()})
    assert checked["guest_signup_http"] == 200 and 422 in checked["lookups"] and 200 in checked["lookups"]
    out=Path("evidence");out.mkdir(exist_ok=True)
    (out/"github-experience.json").write_text(json.dumps(checked,indent=2)+"\n")
    print("PUBLIC RECEIPT",json.dumps(checked))
    browser.close()
