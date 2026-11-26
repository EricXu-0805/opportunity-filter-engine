"""Check a synthetic unlabelled citation and actual manual recovery in the released résumé master."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from check import SITE, confirm_school, expect, home, reads, sessions, sync_playwright

marker='An invented archive note, Fictional Journal (2024).'
title='An invented archive note'
guidance='Review source lines without a matching field'
fixed=os.environ['PDF_ACCEPTANCE_MODE']=='fixed'
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
    doc.set_content(''.join('<p>'+s+'</p>' for s in ['Synthetic Unmapped Example','scholar@example.com','Publications',marker]))
    pdf=doc.pdf();doc.close()
    page.locator('input[type=file][accept*="pdf"]').first.set_input_files({'name':'fictional-citation.pdf','mimeType':'application/pdf','buffer':pdf})
    expect(page.get_by_role('button',name='Remove file')).to_be_visible(timeout=55000)
    master=page.locator('#resume-master')
    master.get_by_text('View complete current résumé source',exact=True).click()
    expect(master.locator('pre').first).to_contain_text(marker)
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
        expect(prompt.locator('..')).to_contain_text('Add any missing details in their section')
    else:
        expect(prompt).to_have_count(0)
        assert 'missing' not in status.inner_text().lower()
    section.get_by_role('button',name='Add publication').click()
    section.locator('label').filter(has_text='Publication title').locator('textarea').fill(title)
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
             'backend_sha':fresh.request.get(SITE+'/api/health').json()['release_sha'],'unlabelled_line':marker,
             'automatic_publication_record_count':0,'notice_identifies_missing_line':fixed,'review_status_before_manual_add':status.inner_text(),
             'manual_title_survived_first_party_read':pub['title']['value'],'first_party_read_revision':stored['revision']}
    out=Path('m11-results');out.mkdir(exist_ok=True);(out/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt,indent=2));browser.close()
