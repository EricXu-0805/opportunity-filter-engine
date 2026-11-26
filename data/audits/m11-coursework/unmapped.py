"""Check a synthetic unlabelled citation and actual manual recovery in the released résumé master."""
from datetime import datetime, timezone
import base64
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from check import DATABASE, SITE, confirm_school, expect, home, reads, sessions, sync_playwright

marker='An invented archive note, Fictional Journal (2024).'
title='An invented archive note'
adjacent='Prepared synthetic field diagrams.'
guidance='Review source text without a matching field'
fixed=os.environ['PDF_ACCEPTANCE_MODE']=='fixed'

def read_before_confirmation(browser):
    """Reopen the owner's real profile and inspect the fresh first-party read."""
    reader = home(browser, sessions[0])
    try:
        def profile_read(response):
            address = urlsplit(response.url)
            query = parse_qs(address.query)
            expected_owner = sessions[0]['user']['id']
            return (address.hostname == DATABASE and address.path == '/rest/v1/profiles'
                    and query.get('id') == ['eq.' + expected_owner]
                    and {'profile_data', 'revision'} <= set(query.get('select', [''])[0].split(','))
                    and response.request.method == 'GET' and response.status == 200)

        with reader.expect_response(profile_read, timeout=40000) as received:
            reader.reload(wait_until='domcontentloaded')
        response = received.value
        authorization = response.request.all_headers().get('authorization', '')
        assert authorization.startswith('Bearer '), 'The profile read was unauthenticated'
        token_payload = authorization.split('.', 2)[1]
        claims = json.loads(base64.urlsafe_b64decode(token_payload + '=' * (-len(token_payload) % 4)))
        assert claims.get('sub') == sessions[0]['user']['id'], 'A different visitor made the read'
        payload = response.json()
        assert not isinstance(payload, list) or len(payload) <= 1
        if isinstance(payload, list):
            row = payload[0] if payload else None
        else:
            row = payload
        if row is None:
            return {'http': response.status, 'owner_verified': True, 'profile_row': 'absent',
                    'revision': 0, 'uploaded_source_saved': False, 'publication_field': 'absent', 'publication_count': 0}
        assert isinstance(row, dict) and 'profile_data' in row and isinstance(row.get('revision'), int)
        profile = row['profile_data'] or {}
        assert isinstance(profile, dict)
        master = profile.get('resume_master') or {}
        publications = master.get('publications')
        assert publications is None or publications == [], 'A publication was saved before the student confirmed the title'
        saved_source = marker in (profile.get('resume_text') or '')
        return {'http': response.status, 'owner_verified': True, 'profile_row': 'present',
                'revision': row['revision'], 'uploaded_source_saved': saved_source,
                'publication_field': 'absent' if publications is None else 'saved_empty_list',
                'publication_count': 0}
    finally:
        reader.context.close()

with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
    page=home(browser)
    for _ in range(100):
        page.wait_for_timeout(200)
        if sessions and not page.get_by_test_id('hydration-note').is_visible(): break
    assert len(sessions)==1
    confirm_school(page)
    page.locator('#student_name').fill('Synthetic Unmapped Example')
    page.locator('#college').select_option(label='Grainger College of Engineering')
    page.locator('#major').select_option(label='Computer Science')
    page.locator('#grade').select_option(label='Sophomore')
    doc=browser.new_page()
    doc.set_content(''.join('<p>'+s+'</p>' for s in ['Synthetic Unmapped Example','scholar@example.com | '+adjacent,'Publications',marker]))
    pdf=doc.pdf();doc.close()
    page.locator('input[type=file][accept*="pdf"]').first.set_input_files({'name':'fictional-citation.pdf','mimeType':'application/pdf','buffer':pdf})
    expect(page.get_by_role('button',name='Remove file')).to_be_visible(timeout=55000)
    master=page.locator('#resume-master')
    master.get_by_text('View complete current résumé source',exact=True).click()
    expect(master.locator('pre').first).to_contain_text(marker)
    expect(master.locator('pre').first).to_contain_text('scholar@example.com | '+adjacent)
    master.get_by_text('Open full résumé editor',exact=True).click()
    master.get_by_role('button',name='Add candidates from my résumé').click()
    status=master.get_by_role('status').filter(has_text='quoted from your résumé')
    expect(status).to_be_visible(timeout=20000)
    section=master.get_by_text('Publications',exact=True).filter(visible=True).first.locator('..')
    expect(section.get_by_role('button',name='Remove publication')).to_have_count(0)
    prompt=master.get_by_text(guidance,exact=True)
    if fixed:
        expect(prompt).to_be_visible()
        prompt.click()
        expect(prompt.locator('..')).to_contain_text(marker)
        expect(prompt.locator('..')).to_contain_text(adjacent)
        expect(prompt.locator('..')).not_to_contain_text('scholar@example.com')
        expect(prompt.locator('..')).to_contain_text('Add any missing details in their section')
    else:
        expect(prompt).to_have_count(0)
        assert 'missing' not in status.inner_text().lower()
    checks = {}
    if fixed:
        checks['after_scanning_before_entry'] = read_before_confirmation(browser)
    section.get_by_role('button',name='Add publication').click()
    section.locator('label').filter(has_text='Publication title').locator('textarea').fill(title)
    if fixed:
        checks['after_typing_before_confirmation'] = read_before_confirmation(browser)
    section.get_by_role('button',name='Confirm Publication title',exact=True).click()
    master.get_by_role('button',name='Apply changes',exact=True).click()
    page.wait_for_timeout(2500)
    fresh=home(browser,sessions[0])
    expect(fresh.get_by_role('button',name='Remove file')).to_be_visible(timeout=55000)
    confirm_school(fresh)
    stored=next(row for row in reversed(reads) if (row.get('profile_data',{}).get('resume_master') or {}).get('publications'))
    pub=stored['profile_data']['resume_master']['publications'][0]
    assert pub['title']['value']==title and pub['title']['status']=='confirmed' and pub['title']['source']=={'kind':'manual'}
    assert marker in stored['profile_data']['resume_text']
    receipt={'site':SITE,'time':datetime.now(timezone.utc).isoformat(),'frontend_sha':fresh.locator('html').get_attribute('data-release-sha'),
             'backend_sha':fresh.request.get(SITE+'/api/health').json()['release_sha'],'unlabelled_line':marker,'unmatched_text_next_to_extracted_email':adjacent,
             'automatic_publication_record_count':0,'independent_reads_before_manual_confirmation':checks,'notice_identifies_missing_line':fixed,'review_status_before_manual_add':status.inner_text(),
             'manual_title_survived_first_party_read':pub['title']['value'],'first_party_read_revision':stored['revision']}
    out=Path('m11-results');out.mkdir(exist_ok=True);(out/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt,indent=2));browser.close()
