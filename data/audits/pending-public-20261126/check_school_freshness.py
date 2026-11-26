"""Read the actual production picker and results in an isolated, ordinary guest session."""
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

SITE = 'https://joinalab.com'
EVIDENCE = Path('school-evidence')
EVIDENCE.mkdir(exist_ok=True)
receipt = {'site': SITE, 'observed_utc': datetime.now(UTC).isoformat(), 'picker': {}}
seen = {}

def capture(res):
    path = urlsplit(res.url).path
    if path.endswith('/auth/v1/signup'):
        seen['guest_signup'] = res.status
    if path.endswith('/rpc/commit_profile_patch_cas'):
        seen['profile_write'] = res.status
    if path == '/api/matches/view' and res.request.method == 'POST':
        seen['rule_matches'] = res.status
        assert parse_qs(urlsplit(res.url).query).get('llm') == ['false']

def restrict(route):
    req = route.request
    url = urlsplit(req.url)
    if req.method == 'POST' and url.hostname == 'joinalab.com' and url.path.startswith('/api/'):
        if url.path == '/api/matches/view' and parse_qs(url.query).get('llm') == ['false']:
            return route.continue_()
        if url.path not in ('/api/events', '/api/health'):
            return route.abort()
    return route.continue_()

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    ctx = browser.new_context(locale='en-US', timezone_id='UTC', viewport={'width': 390, 'height': 844})
    ctx.route('**/*', restrict)
    ctx.add_init_script("""if (location.hostname === 'joinalab.com') {
      localStorage.setItem('ofe_onboarding_seen','1');
      localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');
      localStorage.setItem('ofe_lang','en');
    }""")
    page = ctx.new_page()
    page.on('response', capture)
    page.set_default_timeout(35000)
    api = page.request.get(SITE + '/api/opportunities/freshness')
    assert api.ok
    schools = api.json()['schools']
    receipt['health_sha'] = page.request.get(SITE + '/api/health').json()['release_sha']
    page.goto(SITE, wait_until='domcontentloaded')
    page.locator('#student_name').wait_for()
    for attempt in range(80):
        page.wait_for_timeout(250)
        if seen.get('guest_signup') == 200 and not page.get_by_test_id('hydration-note').is_visible() and not page.get_by_test_id('profile-refresh-status').is_visible():
            break
    assert seen.get('guest_signup') == 200
    for slug in ('amherst', 'haverford', 'ucb'):
        campus = page.get_by_test_id('university-card-' + slug)
        if not campus.is_visible():
            toggle = page.get_by_role('button', name='Change', exact=True)
            toggle.click()
            page.wait_for_timeout(500)
            if not campus.is_visible():
                toggle.click()
        expect(campus).to_be_visible()
        campus.click()
        page.get_by_test_id('switcher-confirm').click()
        data = schools[slug]
        date = datetime.fromisoformat(data['last_checked_at']).strftime('%b %-d, %Y')
        note = page.get_by_test_id('school-freshness')
        expect(note).to_contain_text('Last successful check: ' + date)
        hint = {'partly_unchecked': 'Some pages lack a recent successful read.', 'stale': 'Professor pages: no recent successful read.', 'current': ''}[data['status']]
        if hint:
            expect(note).to_contain_text(hint)
        else:
            expect(note).to_have_text('Last successful check: ' + date)
        receipt['picker'][slug] = {'api': data, 'visible': note.inner_text()}
        print('Picker', slug, data['status'], note.inner_text(), flush=True)
        note.screenshot(path=EVIDENCE / (slug + '-picker.png'))
    page.locator('#student_name').fill('Sample Student')
    for selector, value in [('#college','College of Computing, Data Science, and Society'),('#major','Computer Science')]:
        field = page.locator(selector)
        if field.evaluate('e=>e.tagName') == 'SELECT':
            field.select_option(label=value)
        else:
            field.fill(value)
    page.locator('#grade').select_option(label='Junior')
    page.locator('#research_interests').fill('machine learning, health data')
    generate=page.get_by_test_id('generate-matches')
    expect(generate).to_be_enabled(timeout=45000)
    generate.click()
    for _ in range(25):
        page.wait_for_timeout(250)
        if urlsplit(page.url).path.startswith('/results'):
            break
    if urlsplit(page.url).path == '/' and generate.is_enabled():
        generate.click()
    page.wait_for_url(re.compile('/results'),timeout=55000)
    page.locator('[id^=match-card-]').first.wait_for(timeout=90000)
    result_note = page.get_by_test_id('results-school-freshness')
    expect(result_note).to_contain_text(date)
    expect(result_note).to_contain_text(hint)
    receipt['results'] = result_note.inner_text()
    result_note.screenshot(path=EVIDENCE / 'ucb-results.png')
    receipt['real_request_status'] = seen
    assert seen.get('rule_matches') == 200 and seen.get('profile_write') == 200
    page.goto(SITE + '/admin', wait_until='domcontentloaded')
    expect(page.get_by_placeholder('Admin token')).to_be_visible()
    receipt['admin'] = 'A fresh guest sees the admin token form. An administrator view is still required.'
    browser.close()
(EVIDENCE / 'browser.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(receipt, ensure_ascii=False))
