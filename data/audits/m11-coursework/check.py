"""Use the public PDF picker, then read the same anonymous profile through a clean browser."""
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

SITE = 'https://joinalab.com'
DATABASE = 'mjpirkyduibkakvlbdko.supabase.co'
FIXTURE = Path(__file__).with_name('resume-zh-courses.pdf')
EXPECTED = sorted(['统计', '数据结构', '线性代数', '算法', '機器學習', 'CS 225 Data Structures'])
REQUIRED = 'baseline-or-fixed'
sessions, reads, writes = [], [], []


def capture(response):
    url = urlsplit(response.url)
    if url.hostname != DATABASE or response.status != 200:
        return
    if url.path == '/auth/v1/signup':
        session = response.json()
        assert session['user']['is_anonymous']
        sessions.append(session)
    if url.path == '/rest/v1/rpc/commit_profile_patch_cas':
        result = response.json()
        if result.get('status') == 'applied':
            writes.append(result['revision'])
    if url.path == '/rest/v1/profiles' and response.request.method == 'GET':
        result = response.json()
        row = result[0] if isinstance(result, list) and result else result
        if isinstance(row, dict) and row.get('profile_data'):
            reads.append(row)


def restrict(route):
    request = route.request
    url = urlsplit(request.url)
    if url.hostname not in (DATABASE, 'joinalab.com'):
        return route.abort()
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return route.continue_()
    if url.hostname == DATABASE:
        if url.path == '/auth/v1/signup':
            assert not sessions and not (request.post_data_json or {}).get('email')
            return route.continue_()
        if url.path == '/auth/v1/token':
            return route.continue_()
        if url.path == '/rest/v1/rpc/commit_profile_patch_cas':
            assert sessions and request.post_data_json['p_expected_device_id'] == sessions[0]['user']['id']
            return route.continue_()
    if url.hostname == 'joinalab.com' and url.path == '/api/events':
        return route.continue_()
    return route.abort()


def home(browser, session=None):
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, locale='en-US', service_workers='block')
    ctx.route('**/*', restrict)
    ctx.on('response', capture)
    settings = {'ofe_lang': 'en', 'ofe_onboarding_seen': '1'}
    if session:
        settings['ofe_auth'] = json.dumps(session)
    ctx.add_init_script("if(location.origin==='https://joinalab.com'&&!localStorage.getItem('m11_init')){"
                        "for(const [k,v] of Object.entries(" + json.dumps(settings) + "))localStorage.setItem(k,v);"
                        "localStorage.setItem('m11_init','1')}")
    page = ctx.new_page()
    page.goto(SITE, wait_until='domcontentloaded', timeout=70000)
    page.locator('#student_name').wait_for(timeout=55000)
    return page


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    page = home(browser)
    for _ in range(80):
        page.wait_for_timeout(200)
        if sessions and not page.get_by_test_id('hydration-note').is_visible():
            break
    assert len(sessions) == 1
    uiuc = page.get_by_test_id('university-card-uiuc')
    if uiuc.is_visible():
        uiuc.click()
        page.get_by_test_id('switcher-confirm').click()
    page.locator('#student_name').fill('Synthetic coursework test')
    page.locator('#college').select_option(label='Grainger College of Engineering')
    page.locator('#major').select_option(label='Computer Science')
    page.locator('#grade').select_option(label='Sophomore')
    page.locator('input[type=file][accept*="pdf"]').first.set_input_files(str(FIXTURE))
    expect(page.get_by_role('button', name='Remove file', exact=True)).to_be_visible(timeout=55000)
    page.get_by_text('CS 225', exact=False).first.wait_for(timeout=20000)
    for _ in range(60):
        page.wait_for_timeout(300)
        if writes:
            break
    assert writes
    fresh = home(browser, sessions[0])
    expect(fresh.get_by_role('button', name='Remove file', exact=True)).to_be_visible(timeout=55000)
    row = next(x for x in reversed(reads) if '主修课程' in (x['profile_data'].get('resume_text') or ''))
    courses = sorted(row['profile_data']['coursework'])
    assert courses in (EXPECTED, ['CS 225']), courses
    if REQUIRED == 'fixed':
        assert courses == EXPECTED, courses
    for name in courses:
        expect(fresh.get_by_text(name, exact=True).first).to_be_visible()
    out = Path('m11-results')
    out.mkdir(exist_ok=True)
    fresh.get_by_text(courses[0], exact=True).first.locator('xpath=../..').screenshot(path=str(out / 'courses.png'))
    receipt = {
        'time':datetime.now(timezone.utc).isoformat(), 'url':SITE,
        'release':fresh.request.get(SITE+'/api/health').json()['release_sha'],
        'anonymous_accounts':len(sessions), 'save_revisions':writes, 'read_revision':row['revision'],
        'first_party_profile_read':True, 'stored_source_text_contains_course_list':True,
        'courses_displayed_after_reopen':courses, 'expected_after_fix':EXPECTED,
        'result':'fixed' if courses == EXPECTED else 'reproduced',
    }
    (out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    browser.close()
