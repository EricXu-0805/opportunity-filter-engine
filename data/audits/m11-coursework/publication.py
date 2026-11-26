"""Open the actual uploaded résumé and request unconfirmed candidates in the production editor."""
from datetime import datetime, timezone
from pathlib import Path
import json
from check import confirm_school, expect, home, reads, sessions, sync_playwright, writes

title = 'Tidal Records in a Synthetic Library'
authors = 'A. Example; B. Example'
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    page = home(browser)
    for _ in range(80):
        page.wait_for_timeout(200)
        if sessions and not page.get_by_test_id('hydration-note').is_visible(): break
    assert len(sessions)==1
    confirm_school(page)
    page.locator('#student_name').fill('Synthetic Scholar')
    page.locator('#college').select_option(label='Grainger College of Engineering')
    page.locator('#major').select_option(label='Computer Science')
    page.locator('#grade').select_option(label='Sophomore')
    doc=browser.new_page()
    lines=['Synthetic Scholar', 'scholar@example.com', 'Education', 'School: Example University',
           'Degree: B.S.', 'Major: Computer Science', 'Start: 2024', 'End: 2028',
           'Coursework: Discrete Mathematics; Computer Vision', 'Experience', 'Title: Student Researcher',
           'Organization: Mock Lab', 'Start: 2024', 'End: 2025', 'Projects', 'Title: Synthetic Atlas',
           'Publications', 'Title: '+title, 'Authors: '+authors,
           'Venue: Synthetic Proceedings', 'Date: 2025', 'Skills', 'Python, SQL']
    doc.set_content('<style>p{font:11pt Arial; margin:0 0 4pt}</style>'+''.join('<p>'+l+'</p>' for l in lines))
    pdf=doc.pdf()
    doc.close()
    page.locator('input[type=file][accept*="pdf"]').first.set_input_files({'name':'synthetic-publication.pdf','mimeType':'application/pdf','buffer':pdf})
    expect(page.get_by_role('button',name='Remove file')).to_be_visible(timeout=55000)
    master=page.locator('#resume-master')
    master.get_by_text('View complete current résumé source',exact=True).click()
    source=master.locator('pre').first
    expect(source).to_contain_text('Title: '+title)
    expect(source).to_contain_text('Authors: '+authors)
    master.get_by_text('Open full résumé editor',exact=True).click()
    master.get_by_role('button',name='Add candidates from my résumé').click()
    expect(master.get_by_role('status').filter(has_text='candidates quoted from your résumé')).to_be_visible(timeout=20000)
    section=master.get_by_text('Publications',exact=True).filter(visible=True).first.locator('..')
    expect(section.get_by_role('button',name='Add publication')).to_be_visible()
    candidates=section.locator('fieldset').count()
    assert candidates == 0, candidates
    for course in ['Discrete Mathematics','Computer Vision']:
        expect(page.get_by_text(course, exact=True).first).to_be_visible()
    supplied = ['Synthetic Scholar','scholar@example.com','Example University','B.S.','Computer Science',
                '2024','2028','Student Researcher','Mock Lab','2025','Synthetic Atlas','Python','SQL']
    editor = page.get_by_test_id('resume-master-editor')
    controls = editor.locator('textarea').evaluate_all('(elements) => elements.map(x => x.value)')
    assert not (set(supplied)-set(controls)), set(supplied)-set(controls)
    preview = master.get_by_role('heading', name='Confirmed content preview').locator('..')
    expect(preview.get_by_text('No confirmed content to preview yet.',exact=True)).to_be_visible()
    master.get_by_role('button',name='Apply changes',exact=True).click()
    page.wait_for_timeout(2300)
    reopened=home(browser,sessions[0])
    expect(reopened.get_by_role('button',name='Remove file')).to_be_visible(timeout=55000)
    confirm_school(reopened)
    reopened.get_by_text('Open full résumé editor',exact=True).click()
    editor2 = reopened.get_by_test_id('resume-master-editor')
    saved_controls=editor2.locator('textarea').evaluate_all('(elements) => elements.map(x => x.value)')
    assert set(supplied).issubset(set(saved_controls)), set(supplied)-set(saved_controls)
    stored=next(r for r in reversed(reads) if r.get('profile_data',{}).get('resume_master'))
    assert len(stored['profile_data']['resume_master']['publications'])==0
    receipt={'site':'https://joinalab.com','time':datetime.now(timezone.utc).isoformat(),
             'frontend_sha':page.locator('html').get_attribute('data-release-sha'),
             'pdf_title_in_complete_source':True,'pdf_authors_in_complete_source':True,
             'editor_generated_candidates':master.get_by_role('status').filter(has_text='candidates quoted from your résumé').inner_text(),
             'publication_records_after_generation':candidates, 'publication_title':title,
             'source_backed_contact_education_role_project_dates_skills':supplied,
             'saved_and_read_again_from_real_profile_revision':stored['revision'],
             'original_courses_visible':['Discrete Mathematics','Computer Vision'],'unconfirmed_preview_empty':True}
    out=Path('m11-results')
    out.mkdir(exist_ok=True)
    section.screenshot(path=str(out/'publication-section.png'))
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt,indent=2))
    browser.close()
