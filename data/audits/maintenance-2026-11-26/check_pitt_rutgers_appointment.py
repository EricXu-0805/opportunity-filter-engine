"""Read both normal saved details for the confirmed move. No contact action is performed."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

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
            draft = main.get_by_role('button', name='Draft email', exact=True).is_visible()
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
    output.write_text(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(), 'site': site,
                                  'release': sha, 'rows': records}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for argument in ['site','sha','scope','out']:
        parser.add_argument('--'+argument, required=True)
    args = parser.parse_args()
    check(args.site, args.sha, args.scope, Path(args.out))
