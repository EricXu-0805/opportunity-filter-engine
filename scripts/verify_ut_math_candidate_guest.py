"""Read the two historical UT appointments and current Columbia appointment in an isolated candidate."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

CASES = [
    ('faculty-utexas-math-245fa784', 'The University of Texas at Austin', 'Lucas Mason-Brown',
     'https://math.utexas.edu/directory/lucas-mason-brown', False, 'Assistant Professor'),
    ('faculty-utexas-math-3483c4f5', 'The University of Texas at Austin', 'Uri Treisman',
     'https://math.utexas.edu/directory/uri-treisman', False, 'Professor Emeritus'),
    ('faculty-columbia-math-245fa784', 'Columbia University', 'Lucas Mason-Brown',
     'https://www.math.columbia.edu/people/faculty-by-rank/name/lucas-mason-brown/', True, 'Assistant Professor'),
]


def check(site, sha, scope, output):
    def read(path):
        with urlopen(site + path, timeout=50) as response:
            return json.load(response)
    before = read('/api/health')['release_sha']
    assert before == sha
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(locale='en-US')
        account = {'signup_http': None, 'profile_saved': False}
        def observe(response):
            path = urlsplit(response.url).path
            if path == '/auth/v1/signup':
                account['signup_http'] = response.status
            if path.endswith('/rpc/commit_profile_patch_cas') and response.ok:
                result = response.json()
                if isinstance(result, list):
                    result = result[0] if result else {}
                if result.get('status') == 'applied':
                    account['profile_saved'] = True
        context.on('response', observe)
        home = context.new_page()
        home.goto(site + '/', wait_until='domcontentloaded', timeout=60000)
        tour = home.get_by_test_id('onboarding-intro')
        tour.wait_for(timeout=40000)
        tour.get_by_test_id('onboarding-skip').click()
        tour.get_by_test_id('onboarding-school-ncsu').click()
        tour.get_by_test_id('onboarding-primary').click()
        tour.wait_for(state='hidden', timeout=45000)
        home.locator('#student_name').wait_for()
        home.get_by_test_id('hydration-note').wait_for(state='hidden', timeout=45000)
        home.get_by_test_id('profile-refresh-status').wait_for(state='hidden', timeout=45000)
        home.locator('#student_name').fill('Appointment review fixture')
        for selector in ('#college', '#major'):
            field = home.locator(selector)
            if field.evaluate('e => e.tagName') == 'SELECT':
                field.locator("option:not([value='']):not([disabled])").first.wait_for(state='attached')
                field.select_option(field.locator('option').evaluate_all('rows => rows.find(x => x.value && !x.disabled).value'))
            else:
                field.fill('Computer Science')
        home.locator('#grade').select_option(label='Junior')
        for _ in range(120):
            if account['signup_http'] == 200 and account['profile_saved']:
                break
            home.wait_for_timeout(250)
        assert account['signup_http'] == 200 and account['profile_saved'], account
        for oid, school, name, official, active, rank in CASES:
            api = read('/api/opportunities/' + oid + '?' + urlencode({'_release_scope': scope}))
            assert api['id'] == oid and api['pi_name'] == name and api['target_truth']['actionable'] is active
            page = context.new_page()
            response = page.goto(site + '/opportunities/' + oid, wait_until='domcontentloaded', timeout=60000)
            assert response and response.status == 200
            main = page.get_by_role('main')
            main.get_by_role('heading', name=name, exact=True, level=1).wait_for(timeout=45000)
            assert page.locator('html').get_attribute('data-release-sha') == sha
            main.get_by_role('link', name='Back to matches', exact=True).wait_for(timeout=45000)
            text = main.inner_text()
            assert school in text
            archive = 'This record is no longer active.' in text
            assert archive is (not active)
            profile = main.get_by_role('link', name='View faculty profile', exact=True)
            assert profile.is_visible() and profile.get_attribute('href') == official
            button = main.get_by_role('button', name='Draft email', exact=True)
            if active:
                button.wait_for(timeout=45000)
            draft = button.is_visible()
            assert draft is active
            role = api['detail_fields']['fields']['professor_or_lab']
            assert role['explicit']['faculty_rank'] == rank
            quote = role.get('quotes', {}).get('faculty_rank')
            if not active:
                assert api['contact_email_status'] == 'unavailable'
                assert 'Contact the professor directly to inquire' not in text
            if name == 'Uri Treisman':
                assert rank in text and quote == {'text': rank, 'source_url': official, 'observed_at': '2026-11-27'}
            records.append({'id': oid, 'campus': school, 'h1': name, 'saved_status': response.status,
                            'active': active, 'inactive_banner': archive, 'visible_person_link': official,
                            'draft_button_visible': draft, 'rank': rank, 'rank_quote': quote,
                            'last_seen_listed_at': api.get('last_seen_listed_at'), 'release': sha})
            page.close()
        browser.close()
    after = read('/api/health')['release_sha']
    assert before == after
    live_site = 'https://joinalab.com'
    def live(path):
        with urlopen(live_site+path,timeout=35) as r:
            return json.load(r)
    live_before=live('/api/health')['release_sha']
    public_rows=[]
    for oid, _, _, _, _, _ in CASES:
        d=live('/api/opportunities/'+oid+'?'+urlencode({'_release_scope':scope}))
        role=d['detail_fields']['fields']['professor_or_lab']
        public_rows.append({'id':d['id'],'rank':role['explicit'].get('faculty_rank'),'actionable':d['target_truth']['actionable']})
    assert live('/api/health')['release_sha']==live_before
    output.write_text(json.dumps({'public_api_comparison':{'backend_sha':live_before,'details':public_rows},'checked_at': datetime.now(timezone.utc).isoformat(), 'site': site, 'guest_account': account,
                                  'release': sha, 'rows': records}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for argument in ['site','sha','scope','out']:
        parser.add_argument('--'+argument, required=True)
    args = parser.parse_args()
    check(args.site, args.sha, args.scope, Path(args.out))
