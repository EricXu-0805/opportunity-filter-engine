"""Read both normal saved details for the confirmed move. No contact action is performed."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

CASES = [
    ('faculty-pitt-cs-bb6c586d', 'University of Pittsburgh',
     'https://www.cs.pitt.edu/people/full-time-faculty/xiaowei-jia', False),
    ('faculty-rutgers-cs-bb6c586d', 'Rutgers University-New Brunswick',
     'https://www.cs.rutgers.edu/people/professors/details/xiaowei-jia', True),
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
        school_button = tour.get_by_test_id('onboarding-school-ncsu')
        school_button.click()
        assert school_button.get_attribute('aria-pressed') == 'true'
        account['school_confirmation'] = []
        for attempt in range(3):
            tour.get_by_test_id('onboarding-primary').click()
            try:
                tour.wait_for(state='hidden', timeout=15000)
                account['school_confirmation'].append('saved')
                break
            except PlaywrightTimeout:
                error = tour.get_by_test_id('onboarding-error')
                account['school_confirmation'].append('retry offered' if error.is_visible() else 'form still open')
                print('School confirmation', attempt + 1, account, flush=True)
                home.wait_for_timeout(5000)
        tour.wait_for(state='hidden', timeout=15000)
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
        for oid, school, official, active in CASES:
            api = read('/api/opportunities/' + oid + '?' + urlencode({'_release_scope': scope}))
            assert api['id'] == oid and api['pi_name'] == 'Xiaowei Jia' and api['target_truth']['actionable'] is active
            page = context.new_page()
            response = page.goto(site + '/opportunities/' + oid, wait_until='domcontentloaded', timeout=60000)
            assert response and response.status == 200
            main = page.get_by_role('main')
            main.get_by_role('heading', name='Xiaowei Jia', exact=True, level=1).wait_for(timeout=45000)
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
            generic_contact = 'Contact this faculty member to ask' in text
            assert generic_contact is active
            if not active:
                assert not draft and 'Recent publications' in text and api['contact_email_status'] == 'unavailable'
                papers = main.locator('a[href^="https://scholar.google.com/scholar"]').all_text_contents()
                assert len(papers) == 3 and set(papers) == {w['title'] for w in api['metadata']['recent_works']}
            else:
                papers = []
            records.append({'id': oid, 'campus': school, 'h1': api['pi_name'], 'saved_status': response.status,
                            'active': active, 'inactive_banner': archive, 'visible_person_link': official,
                            'draft_button_visible': draft, 'generic_invitation_visible': generic_contact,
                            'retained_archived_paper_titles': papers, 'release': sha})
            page.close()
        browser.close()
    after = read('/api/health')['release_sha']
    assert before == after
    output.write_text(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(), 'site': site, 'guest_account': account,
                                  'release': sha, 'rows': records}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for argument in ['site','sha','scope','out']:
        parser.add_argument('--'+argument, required=True)
    args = parser.parse_args()
    check(args.site, args.sha, args.scope, Path(args.out))
