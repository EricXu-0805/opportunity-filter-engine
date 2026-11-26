"""Read two original opportunity IDs in the live bilingual public site and follow official sources."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
from playwright.sync_api import TimeoutError, sync_playwright

SITE = "https://joinalab.com"
RELEASE = "77603b9e0afac651bcd82428e6c59494aaa5b1ce"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
FACULTY_ID = "faculty-ucb-stat-5558a1b1"
PROGRAM_ID = "ext-usc-ict"
PROFILE = "https://statistics.berkeley.edu/people/rasmus-nielsen"
LAB = "https://nielsen-lab.github.io/"
TEAM = LAB + "team/"
RESEARCH = LAB + "research/"
OUT = Path("evidence")
OUT.mkdir(exist_ok=True)
report = {
    "observed_utc": datetime.now(timezone.utc).isoformat(),
    "action_run": "https://github.com/" + os.environ["GITHUB_REPOSITORY"] + "/actions/runs/" + os.environ["GITHUB_RUN_ID"],
    "release": RELEASE, "cases": {}
}


def original_detail(context, page, record_id, case):
    resp = page.goto(f"{SITE}/opportunities/{record_id}", wait_until="domcontentloaded")
    assert resp and resp.status == 200
    assert page.locator("html").get_attribute("data-release-sha") == RELEASE
    response = context.request.get(
        f"{SITE}/api/opportunities/{record_id}", params={"_release_scope": SCOPE}
    )
    assert response.ok
    data = response.json()
    assert data["id"] == record_id
    case.update(original_id=record_id, url=page.url, detail_http=resp.status,
                api_http=response.status, title=data["title"], source=data["source"],
                source_url=data["source_url"])
    return data


def onboarding(page):
    dialog = page.get_by_role("dialog", name="Welcome to JoinALab")
    try:
        dialog.wait_for(state="visible", timeout=6500)
    except TimeoutError:
        return
    dialog.get_by_role("button", name="Skip tour", exact=True).click()
    school = dialog.get_by_test_id("onboarding-school-ucb")
    school.click()
    assert school.get_attribute("aria-pressed") == "true"
    dialog.get_by_test_id("onboarding-primary").click()
    dialog.wait_for(state="hidden", timeout=30000)


def sources_panel(context, case):
    page = context.new_page()
    # Carry the visitor from the actual detail into their own profile after signup settles.
    signup = []
    context.on('response', lambda r: signup.append(r.status) if '/auth/v1/signup' in r.url and r.request.method == 'POST' else None)
    assert page.goto(SITE + '/opportunities/' + FACULTY_ID, wait_until='domcontentloaded').ok
    for _ in range(160):
        if signup: break
        page.wait_for_timeout(250)
    assert signup and signup[-1]==200, 'Fresh guest signup did not finish'
    case['guest_signup_http']=signup[-1]
    onboarding(page)
    assert page.goto(SITE + '/', wait_until='domcontentloaded').ok
    page.get_by_test_id('hydration-note').wait_for(state='hidden', timeout=45000)
    page.get_by_test_id('profile-refresh-status').wait_for(state='hidden', timeout=45000)
    name = page.locator('#student_name')
    saved = []
    def watch_save(r):
        if '/rest/v1/rpc/' in r.url and 'profile' in r.url and r.request.method == 'POST':
            if r.ok and 'QA Source Review' in (r.request.post_data or ''):
                saved.append(r.status)
    context.on('response', watch_save)
    name.fill('QA Source Review')
    name.blur()
    for _ in range(140):
        if saved:
            break
        page.wait_for_timeout(250)
    assert saved, 'Synthetic guest profile name was not saved through normal UI'
    case['synthetic_profile_write_http'] = saved[-1]
    data = original_detail(context, page, FACULTY_ID, case)
    case['lab_status'] = data['lab_context']['status']
    assert case['lab_status'] == 'available'
    free_responses = []
    paid_paths = []
    def observe(request):
        from urllib.parse import urlsplit
        path = urlsplit(request.url).path
        if request.method == 'POST' and path.startswith('/api/') and ('/ai/' in path or 'generate-ai' in path or ('cold-email' in path and ('generate' in path or 'refine' in path))):
            paid_paths.append(path)
    context.on('request', observe)
    context.on('response', lambda r: free_responses.append(r.status) if '/api/cold-email/variants' in r.url and r.request.method == 'POST' else None)
    page.get_by_role('button',name='Draft email',exact=True).click()
    panel = page.get_by_test_id('email-contact-context-panel')
    panel.locator(':scope > summary').click(timeout=60000)
    sources = panel.get_by_role('region', name='Faculty and lab website sources')
    sources.get_by_text('View source verification',exact=True).click()
    source_links = sources.get_by_role('list',name='Source pages').get_by_role('link')
    urls = [source_links.nth(i).get_attribute('href') for i in range(source_links.count())]
    assert urls == [PROFILE,LAB,TEAM,RESEARCH]
    name_on_team = sources.get_by_text('Rasmus Nielsen',exact=True).filter(visible=True)
    assert name_on_team.count() >= 1
    case.update(visible_attribution=urls, identity_on_team_page='Rasmus Nielsen',
                free_templates_http=free_responses, paid_api_requests=paid_paths)
    assert free_responses and free_responses[-1] == 200 and not paid_paths
    sources.get_by_text('View source verification',exact=True).scroll_into_view_if_needed()
    sources.screenshot(path=str(OUT/'b7-berkeley-lab-source-panel.png'),timeout=15000)
    # Inspect lengths only. Never store lab material or the visitor draft.
    counts = {}
    for prefix, expected_count in [('Faculty profile: ',3),('Full lab research: ',10)]:
        import re
        row = sources.locator('summary').filter(has_text=re.compile('^'+prefix)).locator('..')
        assert row.count()==1
        row.locator('summary').click()
        link = row.get_by_role('link',name='Open source page',exact=True)
        assert link.is_visible()
        rows = row.locator('div[class*="excerpt"] p:visible')
        assert rows.count()==expected_count, str((prefix,rows.count()))
        counts[link.get_attribute('href')]=rows.count()
        row.locator('summary').click()
    case['visible_section_counts']=counts


def more_manual(context,case):
    page=context.new_page()
    for record_id in ('ext-umbc-bigdata','ext-utexas-tacc'):
        row = case.setdefault(record_id,{})
        data = original_detail(context,page,record_id,row)
        onboarding(page)
        assert data['source']=='manual'
        row['host_source']=data['source_url']
        for language,label in [('en','Manually curated'),('zh','人工整理')]:
            if language=='zh':
                page.locator('button[aria-label="切换到中文"]:visible').first.click()
            box=page.get_by_text(label,exact=False).first
            box.wait_for(state='visible')
            row[language]=box.inner_text()
            assert label in row[language] and 'UIUC' not in row[language]
        page.locator('button[aria-label="Switch to English"]:visible').first.click()
        page.get_by_text('Manually curated',exact=False).first.wait_for(state='visible')


with sync_playwright() as engine:
    browser = engine.chromium.launch(channel="chrome")
    for name, scenario in [("berkeley_sources_reader", sources_panel), ("additional_national_programs", more_manual)]:
        case = report["cases"][name] = {}
        context = browser.new_context(locale="en-US",viewport={"width":1280,"height":920})
        context.set_default_timeout(18000)
        try:
            version = context.request.get(SITE + "/api/health").json()["release_sha"]
            origin = context.request.get("https://opportunity-filter-engine-api.onrender.com/api/health").json()["release_sha"]
            case.update(site_backend_sha=version,render_origin_sha=origin)
            assert version == RELEASE == origin
            scenario(context, case)
            case["passed"] = True
        except Exception as exc:
            case.update(passed=False,error=type(exc).__name__ + ": " + str(exc)[:1000])
            print(name, case["error"])
            for i,p in enumerate(context.pages):
                if p.url.startswith(SITE):
                    try:
                        p.screenshot(path=str(OUT/f"{name}-failure-{i}.png"),timeout=5000)
                        (OUT/f"{name}-failure-{i}.txt").write_text(p.locator("body").inner_text(timeout=5000))
                    except Exception:
                        pass
        finally:
            context.close()
            (OUT/"b7-visible-lab-other-programs.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    browser.close()
assert all(c["passed"] for c in report["cases"].values()), str({k:v["passed"] for k,v in report["cases"].items()})
