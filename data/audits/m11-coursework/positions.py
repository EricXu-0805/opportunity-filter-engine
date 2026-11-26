"""Validate only invented work history on a new anonymous student-owned production profile."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re

from check import SITE, confirm_school, expect, home, reads, sessions, sync_playwright, writes

company = 'Fictional Copper Studio'
original = 'Reviewed synthetic sample values at Fictional Copper Studio in 2024.'
combined = 'Fictional Copper Studio analyst, 2024 to 2025. Reviewed synthetic sample values and reported two examples.'
profile_link = 'https://www.linkedin.com/in/ofe-fictional-sample-1354'
csv = f'Company Name,Title,Started On,Finished On,Description,Results\n{company},Analyst,2024,2025,Reviewed synthetic values,Reported two examples'
fixed = os.environ['PDF_ACCEPTANCE_MODE'] == 'fixed'


def wait_for_write(page, before):
    for _ in range(100):
        page.wait_for_timeout(300)
        if writes and writes[-1] > before:
            return writes[-1]
    raise AssertionError(f'No confirmed production write after revision {before}')


def fresh(browser, predicate):
    count = len(reads)
    page = home(browser, sessions[0])
    for _ in range(100):
        page.wait_for_timeout(200)
        if len(reads) > count and any(predicate(row['profile_data']) for row in reads[count:]):
            break
    confirm_school(page)
    row = next(r for r in reversed(reads[count:]) if predicate(r['profile_data']))
    return page, row


def uploader(page):
    summary = page.get_by_text('Import LinkedIn experience', exact=True)
    if summary.locator('..').get_attribute('open') is None:
        summary.click()
    return summary.locator('..')


def field(panel, label):
    return panel.get_by_role('textbox', name=re.compile('^'+label))


def input_csv(panel):
    panel.get_by_label('Input method').select_option('file')
    panel.locator('input[type=file]').set_input_files({'name':'Positions.csv','mimeType':'text/csv','buffer':csv.encode()})
    panel.get_by_role('button',name='Preview experiences').click()
    expect(field(panel,'Company')).to_have_value(company)


def save(panel, action):
    panel.get_by_label('Choose what to save').select_option(action)
    panel.get_by_role('button',name='Confirm selected experiences').click()


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
    page = home(browser)
    for _ in range(100):
        page.wait_for_timeout(200)
        if sessions and not page.get_by_test_id('hydration-note').is_visible():
            break
    assert len(sessions) == 1
    confirm_school(page)
    page.locator('#student_name').fill('Synthetic Positions Example')
    page.locator('#college').select_option(label='Grainger College of Engineering')
    page.locator('#major').select_option(label='Computer Science')
    page.locator('#grade').select_option(label='Sophomore')
    page.locator('#linkedin_url').fill(profile_link)
    builder = browser.new_page()
    builder.set_content('<p>Experience</p><p>'+original+'</p>')
    pdf = builder.pdf()
    builder.close()
    page.locator('input[type=file][accept*="pdf"]').first.set_input_files({'name':'fictional-work.pdf','mimeType':'application/pdf','buffer':pdf})
    expect(page.get_by_role('button',name='Remove file')).to_be_visible(timeout=50000)
    page.wait_for_timeout(2500)
    prior, old = fresh(browser,lambda p: p.get('linkedin_url')==profile_link and original in (p.get('resume_text') or ''))
    assert not old['profile_data'].get('experience_entries')
    receipt={'site':SITE,'frontend_sha':prior.locator('html').get_attribute('data-release-sha'),
             'backend_sha':prior.request.get(SITE+'/api/health').json()['release_sha'],
             'before_revision':old['revision'],'only_link_saved_experiences':0,'mode':'fixed' if fixed else 'baseline'}
    gate=prior.get_by_text('Import LinkedIn experience',exact=True)
    if fixed:
        panel=uploader(prior)
        panel.get_by_label('Input method').select_option('paste')
        panel.get_by_label('Experience text').fill(profile_link)
        panel.get_by_role('button',name='Preview experiences').click()
        expect(panel.get_by_role('alert')).to_contain_text('profile link alone')
        input_csv(panel)
        for label, value in [('Role','Analyst'),('Start date','2024'),('End date','2025'),('Responsibilities','Reviewed synthetic values'),('Results','Reported two examples')]:
            expect(field(panel,label)).to_have_value(value)
        expect(panel.locator('p').filter(has_text=original).first).to_be_visible()
        panel.get_by_role('button',name='Confirm selected experiences').click()
        expect(panel.get_by_role('alert')).to_contain_text('Choose an action')
        panel.get_by_label('Choose what to save').select_option('combine')
        panel.get_by_role('textbox',name=re.compile('^Final wording to keep')).fill(combined)
        before=old['revision']
        prior.context.set_offline(True)
        panel.get_by_role('button',name='Confirm selected experiences').click()
        expect(panel.get_by_role('status')).to_contain_text('Confirmed experiences')
        prior.wait_for_timeout(1600)
        assert not writes or writes[-1]==before
        prior.context.set_offline(False)
        prior.reload(wait_until='domcontentloaded')
        wait_for_write(prior,before)
        restored,r1=fresh(browser,lambda p: any(e['text']==combined and e['status']=='confirmed' for e in p.get('experience_entries',[])))
        entries=r1['profile_data']['experience_entries']
        assert len(entries)==2, [(e['status'],e['text']) for e in entries]
        merged=next(e for e in entries if e['status']=='confirmed')
        quote=next(e for e in entries if e['status']=='withdrawn')
        assert quote['source']['kind']=='resume' and original in quote['source']['quote']
        assert merged['source']=={'kind':'manual'} and merged['id'].startswith('li:')
        panel=uploader(restored)
        input_csv(panel)
        save(panel,'new')
        expect(panel.get_by_role('alert')).to_contain_text('already imported')
        save(panel,'keep')
        expect(panel.get_by_role('status')).to_contain_text('No experiences changed')
        panel.get_by_label('Input method').select_option('paste')
        panel.get_by_label('Experience text').fill('Company: Fictional Blue Orchard\nRole: Assistant\nResponsibilities: Filed sample notes\nResults: Prepared one synthetic report')
        panel.get_by_role('button',name='Preview experiences').click()
        expect(field(panel,'Company')).to_have_value('Fictional Blue Orchard')
        save(panel,'new')
        wait_for_write(restored,r1['revision'])
        panel.get_by_label('Input method').select_option('manual')
        field(panel,'Company').fill('Fictional Amber Circle')
        field(panel,'Role').fill('Technician')
        field(panel,'Start date').fill('2023')
        field(panel,'End date').fill('2024')
        field(panel,'Responsibilities').fill('Measured synthetic samples.')
        field(panel,'Results').fill('Assembled three test summaries.')
        panel.get_by_role('button',name='Preview experiences').click()
        expect(field(panel,'Results')).to_have_value('Assembled three test summaries.')
        last=writes[-1]; save(panel,'new');wait_for_write(restored,last)
        final,r2=fresh(browser,lambda p: len(p.get('experience_entries',[]))==4)
        profile=r2['profile_data']
        assert profile['resume_text']==old['profile_data']['resume_text'] and profile['linkedin_url']==profile_link
        confirmed=[e['text'] for e in profile['experience_entries'] if e['status']=='confirmed']
        assert len(confirmed)==3 and combined in confirmed
        assert any('Fictional Blue Orchard' in t and 'one synthetic report' in t for t in confirmed)
        assert any('Fictional Amber Circle' in t and 'From 2023 · To 2024' in t and 'three test summaries' in t for t in confirmed)
        expect(final.locator('#student_name')).to_have_value('Synthetic Positions Example')
        library=final.locator('#experience-library')
        for phrase in ['Fictional Copper Studio','Fictional Blue Orchard','Fictional Amber Circle']:
            expect(library.locator('summary').filter(has_text=phrase).first).to_be_visible()
        receipt.update({'reviewed_fields':['company','position','start','end','responsibilities','results'],
                        'after_offline_reload_revision':r1['revision'],'repeat_kept_existing':True,
                        'final_revision':r2['revision'],'confirmed':confirmed,'original_quote_withdrawn':quote['source']['quote'],
                        'old_resume_and_saved_link_preserved':True,'profiles_read_from_first_party':True})
    else:
        expect(gate).to_have_count(0)
        receipt['old_experience_library_present']=prior.locator('#experience-library').count()==1
    out=Path('m11-results')
    out.mkdir(exist_ok=True)
    receipt['time']=datetime.now(timezone.utc).isoformat()
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False))
    print(json.dumps(receipt,indent=2,ensure_ascii=False))
    browser.close()
