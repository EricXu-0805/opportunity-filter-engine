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
REQUIRED = 'baseline'
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


def confirm_school(page):
    picker = page.get_by_test_id('university-card-uiuc')
    if picker.is_visible():
        picker.click()
        page.get_by_test_id('switcher-confirm').click()
    expect(page.get_by_role('dialog', name='Choose your university')).to_have_count(0)


if __name__ == '__main__' and (pw := sync_playwright().start()):
    browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    page = home(browser)
    for _ in range(80):
        page.wait_for_timeout(200)
        if sessions and not page.get_by_test_id('hydration-note').is_visible():
            break
    assert len(sessions) == 1
    confirm_school(page)
    page.locator('#student_name').fill('Synthetic coursework test')
    page.locator('#college').select_option(label='Grainger College of Engineering')
    page.locator('#major').select_option(label='Computer Science')
    page.locator('#grade').select_option(label='Sophomore')
    picker = page.locator('input[type=file][accept*="pdf"]').first
    doc = browser.new_page()
    doc.set_content('<p>Coursework: Discrete Mathematics; Computer Vision</p>')
    seed = doc.pdf()
    doc.close()
    picker.set_input_files({'name': 'earlier-synthetic.pdf', 'mimeType': 'application/pdf', 'buffer': seed})
    expect(page.get_by_text('Discrete Mathematics', exact=True)).to_be_visible(timeout=55000)
    page.wait_for_timeout(2500)
    old = home(browser, sessions[0])
    expect(old.get_by_text('Computer Vision', exact=True)).to_be_visible(timeout=45000)
    old_row = next(x for x in reversed(reads) if 'Computer Vision' in (x['profile_data'].get('coursework') or []))
    confirm_school(old)
    old_picker = old.locator('input[type=file][accept*="pdf"]').first
    old_picker.set_input_files({'name': 'damaged-synthetic.pdf', 'mimeType': 'application/pdf', 'buffer': b'Not a PDF file. Synthetic test.'})
    retry = old.get_by_role('button', name='Try again', exact=True)
    expect(retry).to_be_visible(timeout=15000)
    error = retry.locator('..').locator('p').first
    expect(error).to_have_text('Invalid PDF structure.')
    error_text = error.inner_text()
    announced = error.get_attribute('role') == 'alert'

    expect(old.get_by_text('Computer Vision', exact=True)).to_be_visible()
    check = home(browser, sessions[0])
    expect(check.get_by_text('Computer Vision', exact=True)).to_be_visible()
    confirm_school(check)
    preserved = next(x for x in reversed(reads) if 'Computer Vision' in (x['profile_data'].get('coursework') or []))
    assert preserved['profile_data']['resume_text'] == old_row['profile_data']['resume_text']
    check.context.close()
    retry.click()
    old_picker.set_input_files(str(FIXTURE))
    expected = EXPECTED if REQUIRED == 'fixed' else ['CS 225']
    expect(old.get_by_text(expected[0], exact=True)).to_be_visible(timeout=55000)
    for _ in range(60):
        old.wait_for_timeout(300)
        if writes and writes[-1] > old_row['revision']:
            break
    assert writes[-1] > old_row['revision']
    fresh = home(browser, sessions[0])
    expect(fresh.get_by_role('button', name='Remove file', exact=True)).to_be_visible(timeout=55000)
    confirm_school(fresh)
    row = next(x for x in reversed(reads) if '主修课程' in (x['profile_data'].get('resume_text') or ''))
    courses = sorted(row['profile_data']['coursework'])
    assert courses == expected, courses
    for name in courses:
        course = fresh.get_by_text(name, exact=True).first
        expect(course).to_be_visible()
        entry = course.locator('xpath=ancestor::li[1]')
        expect(entry.locator('select')).to_have_value('unknown')
        expect(entry.locator('summary')).to_contain_text(name)
    expect(fresh.get_by_text('Computer Vision', exact=True)).to_have_count(0)
    expect(fresh.locator('#student_name')).to_have_value('Synthetic coursework test')
    out = Path('m11-results')
    out.mkdir(exist_ok=True)
    fresh.get_by_text(courses[0], exact=True).first.locator('xpath=../..').screenshot(path=str(out / 'courses.png'))
    receipt = {
        'time':datetime.now(timezone.utc).isoformat(), 'url':SITE,
        'release':fresh.request.get(SITE+'/api/health').json()['release_sha'],
        'frontend_sha':fresh.locator('html').get_attribute('data-release-sha'),
        'upload_error_text':error_text, 'upload_error_role_alert':announced,
        'earlier_revision':old_row['revision'], 'preserved_after_invalid_upload_revision':preserved['revision'],
        'old_pdf_preserved_after_error':True, 'retry_completed_after_reopen':True,
        'visible_source_lines':len(courses), 'unknown_course_statuses':len(courses), 'previous_courses_cleared':True,
        'anonymous_accounts':len(sessions), 'save_revisions':writes, 'read_revision':row['revision'],
        'first_party_profile_read':True, 'stored_source_text_contains_course_list':True,
        'courses_displayed_after_reopen':courses, 'expected_after_fix':EXPECTED,
        'result':'fixed' if courses == EXPECTED else 'reproduced',
    }
    (out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    browser.close()
